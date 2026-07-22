#!/usr/bin/env python3
"""Materialize and evaluate AutoLab's CPU-only toy ISA optimization task."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adapters.portable import (
    append_history,
    candidate_changed_paths,
    claim_evaluator_call,
    git_commit,
    init_git,
    render_evaluate_wrapper,
    render_goal_plus_verifier,
    sha256_file,
    utc_now,
    write_json,
)


CONTROLLER_PATH = Path(__file__).resolve()
UPSTREAM_KEY = "autolab"
BENCHMARK_NAME = "AutoLab"
TASK_ID = "toy_isa_opt"
ARTIFACT_NAME = "program.s"
PRIMARY_METRIC = "cycles"
DIRECTION = "minimize"
CODEX_SANDBOX = "workspace-write"
CASE_SET_DESCRIPTION = "toy_isa_opt seeds 0, 42, 137, 999"
BASELINE_CYCLES = 9220
BEST_KNOWN_CYCLES = 1545
INVALID_CYCLES = 1_000_000_000
RUN_SEEDS = (0, 42, 137, 999)
BUILD_TIMEOUT_SECONDS = 30
RUN_TIMEOUT_SECONDS = 10
VERIFIER_TIMEOUT_SECONDS = 30


def task_source(upstream_root: Path) -> Path:
    return upstream_root / "tasks/toy_isa_opt"


def task_text(instruction: str) -> str:
    return f"""# Objective

Improve `{ARTIFACT_NAME}` for AutoLab's CPU-only Toy ISA Optimization task. The
program must compute the 512-element integer dot product for every verifier seed
and minimize the official simulated cycle count.

{instruction.strip()}

# Evaluation

- Run `python3 evaluate.py` for official-compatible public feedback.
- Primary metric: `{PRIMARY_METRIC}`; lower is better.
- Correctness is checked on seeds {', '.join(str(seed) for seed in RUN_SEEDS)}.

# Hard constraints

- Only edit `{ARTIFACT_NAME}`.
- Do not edit `evaluate.py`, `.goal-plus-verifiers/`, `task.json`, `TASK.md`,
  `AGENTS.md`, or Git configuration.
- Do not inspect parent directories, controller runtime files, credentials, or
  network resources.
- Do not hardcode outputs for the visible seeds; implement the general dot
  product for arbitrary valid input values.
- Leave the best evaluator-verified assembly program in `{ARTIFACT_NAME}`.
"""


def materialize_workspace(upstream_root: Path, workspace: Path) -> dict[str, Any]:
    upstream_root = upstream_root.expanduser().absolute()
    workspace = workspace.expanduser().absolute()
    source = task_source(upstream_root)
    required = {
        "main.c": source / "environment/main.c",
        "Makefile": source / "environment/Makefile",
        ARTIFACT_NAME: source / "environment/program.s",
        "instruction.md": source / "instruction.md",
    }
    for path in required.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    if workspace.exists():
        raise FileExistsError(workspace)

    workspace.mkdir(parents=True)
    shutil.copy2(required[ARTIFACT_NAME], workspace / ARTIFACT_NAME)
    instruction = required["instruction.md"].read_text()
    (workspace / "TASK.md").write_text(task_text(instruction))
    (workspace / "AGENTS.md").write_text(
        "# AutoLab toy ISA task rules\n\n"
        f"- Only edit `{ARTIFACT_NAME}`.\n"
        "- Run `python3 evaluate.py` for official-compatible feedback.\n"
        "- Do not inspect parent directories or use the network.\n"
        "- Preserve correctness for arbitrary verifier seeds.\n"
    )
    (workspace / "evaluate.py").write_text(
        render_evaluate_wrapper(CONTROLLER_PATH, upstream_root)
    )
    verifier_dir = workspace / ".goal-plus-verifiers"
    verifier_dir.mkdir()
    (verifier_dir / "primary_metric.py").write_text(
        render_goal_plus_verifier(
            CONTROLLER_PATH, upstream_root, PRIMARY_METRIC
        )
    )
    (workspace / ".gitignore").write_text(
        ".bench-runtime/\n.gp/\n.codex-log/\n__pycache__/\n*.pyc\n"
    )
    metadata = {
        "schema_version": 1,
        "adapter": "autolab-toy-isa",
        "task_id": TASK_ID,
        "artifact_name": ARTIFACT_NAME,
        "upstream_root": str(upstream_root),
        "upstream_commit": git_commit(upstream_root),
        "source_sha256": {
            name: sha256_file(path) for name, path in required.items()
        },
        "primary_metric": PRIMARY_METRIC,
        "direction": DIRECTION,
        "run_seeds": list(RUN_SEEDS),
        "baseline_cycles": BASELINE_CYCLES,
        "best_known_cycles": BEST_KNOWN_CYCLES,
    }
    write_json(workspace / "task.json", metadata)
    workspace_commit = init_git(workspace, "materialize AutoLab toy ISA task")
    return {
        **metadata,
        "workspace": str(workspace),
        "workspace_commit": workspace_commit,
        "seed_sha256": sha256_file(workspace / ARTIFACT_NAME),
    }


def parse_result(output: str) -> tuple[int | None, bool]:
    cycles_match = re.search(r"cycles=(\d+)", output)
    verify_match = re.search(r"verify=([^\s]+)", output)
    cycles = int(cycles_match.group(1)) if cycles_match else None
    return cycles, bool(verify_match and verify_match.group(1) == "ok")


def evaluate_candidate(
    workspace: Path,
    upstream_root: Path,
    metadata: dict[str, Any],
) -> tuple[bool, int, float, list[dict[str, Any]], dict[str, Any]]:
    source = task_source(upstream_root)
    source_files = {
        "main.c": source / "environment/main.c",
        "Makefile": source / "environment/Makefile",
        "instruction.md": source / "instruction.md",
    }
    for name, path in source_files.items():
        if sha256_file(path) != metadata["source_sha256"][name]:
            raise RuntimeError(f"pinned AutoLab source changed: {name}")

    diagnostics: dict[str, Any] = {}
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="autolab-toy-isa-") as temporary:
        build = Path(temporary)
        shutil.copy2(source_files["main.c"], build / "main.c")
        shutil.copy2(source_files["Makefile"], build / "Makefile")
        shutil.copy2(workspace / ARTIFACT_NAME, build / ARTIFACT_NAME)
        compiled = subprocess.run(
            ["make"],
            cwd=build,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT_SECONDS,
        )
        diagnostics["make_returncode"] = compiled.returncode
        diagnostics["make_stdout"] = compiled.stdout[-4000:]
        diagnostics["make_stderr"] = compiled.stderr[-4000:]
        if compiled.returncode != 0:
            return False, INVALID_CYCLES, 0.0, results, diagnostics
        for seed in metadata["run_seeds"]:
            completed = subprocess.run(
                [str(build / "solve"), str(seed)],
                cwd=build,
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT_SECONDS,
            )
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            cycles, correct = parse_result(output)
            results.append(
                {
                    "seed": seed,
                    "returncode": completed.returncode,
                    "correct": correct,
                    "cycles": cycles,
                    "output": output.strip()[-2000:],
                }
            )

    valid = bool(results) and all(item["correct"] for item in results)
    cycles = int(results[0]["cycles"]) if valid else INVALID_CYCLES
    if cycles >= BASELINE_CYCLES:
        reward = 0.0
    elif cycles <= BEST_KNOWN_CYCLES:
        reward = 1.0
    else:
        reward = round(
            (BASELINE_CYCLES - cycles)
            / (BASELINE_CYCLES - BEST_KNOWN_CYCLES),
            4,
        )
    return valid, cycles, reward, results, diagnostics


def evaluate_workspace(workspace: Path, upstream_root: Path, mode: str) -> dict[str, Any]:
    started = time.monotonic()
    workspace = workspace.expanduser().absolute()
    upstream_root = upstream_root.expanduser().absolute()
    destination, budget = claim_evaluator_call(workspace, mode)
    metadata = json.loads((workspace / "task.json").read_text())
    changes = candidate_changed_paths(workspace)
    unauthorized = sorted(changes - {ARTIFACT_NAME})
    if unauthorized or not (workspace / ARTIFACT_NAME).is_file():
        valid, cycles, reward, cases, diagnostics = (
            False,
            INVALID_CYCLES,
            0.0,
            [],
            {"unauthorized_paths": unauthorized},
        )
    else:
        try:
            valid, cycles, reward, cases, diagnostics = evaluate_candidate(
                workspace, upstream_root, metadata
            )
        except (subprocess.TimeoutExpired, OSError) as error:
            valid, cycles, reward, cases, diagnostics = (
                False,
                INVALID_CYCLES,
                0.0,
                [],
                {"error": f"{type(error).__name__}: {error}"},
            )
    report = {
        "schema_version": 1,
        "benchmark": "autolab-cpu",
        "task_id": TASK_ID,
        "mode": mode,
        "valid": valid,
        "primary_metric": {
            "name": PRIMARY_METRIC,
            "value": cycles,
            "direction": DIRECTION,
        },
        PRIMARY_METRIC: cycles,
        "reward": reward,
        "cases": cases,
        "diagnostics": diagnostics,
        "artifact_sha256": (
            sha256_file(workspace / ARTIFACT_NAME)
            if (workspace / ARTIFACT_NAME).is_file()
            else None
        ),
        "duration_seconds": time.monotonic() - started,
        "budget": budget,
        "evaluated_at": utc_now(),
    }
    append_history(destination, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--upstream-root", type=Path, required=True)
    materialize.add_argument("--workspace", type=Path, required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--workspace", type=Path, required=True)
    evaluate.add_argument("--upstream-root", type=Path, required=True)
    evaluate.add_argument("--mode", choices=("public", "final"), default="public")
    evaluate.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "materialize":
        print(json.dumps(materialize_workspace(args.upstream_root, args.workspace), indent=2))
        return 0
    report = evaluate_workspace(args.workspace, args.upstream_root, args.mode)
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
