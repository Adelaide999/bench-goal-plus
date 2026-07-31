#!/usr/bin/env python3
"""Materialize and evaluate the host-only VLIW optimization local example."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adapters.portable import (  # noqa: E402
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
from bench_runtime_paths import temporary_directory  # noqa: E402


CONTROLLER_PATH = Path(__file__).resolve()
LOCAL_SOURCE_RELATIVE = "local_examples/vliw_kernel_optimization"
UPSTREAM_KEY = "local_examples"
BENCHMARK_NAME = "Local VLIW Kernel Optimization"
TASK_ID = "vliw_kernel_optimization"
ARTIFACT_NAME = "solution.py"
PRIMARY_METRIC = "cycles"
DIRECTION = "minimize"
CODEX_SANDBOX = "workspace-write"
CASE_SET_DESCRIPTION = (
    "public local VLIW cases plus controller-owned held-out local cases"
)
OFFICIAL_BENCHMARK_COMPARABLE = False
BASELINE_CYCLES = 147_734
INVALID_CYCLES = 1_000_000_000
VERIFIER_TIMEOUT_SECONDS = 60
FINAL_EVALUATOR_TIMEOUT_SECONDS = 180

SOURCE_FILES = {
    "task/problem.py": "task/problem.py",
    "task/runner.py": "task/runner.py",
    "task/verifier.py": "task/verifier.py",
    "task/problem.md": "task/problem.md",
    "task/starter_solution.py": "task/starter_solution.py",
    "task/public_cases.json": "task/test_cases/public_cases.json",
    "controller/problem.py": "controller/problem.py",
    "controller/runner.py": "controller/runner.py",
    "controller/verifier.py": "controller/verifier.py",
    "controller/frozen_problem.py": "controller/tests/frozen_problem.py",
    "controller/hidden_cases.json": "controller/test_cases/hidden_cases.json",
}


def source_paths(source_root: Path) -> dict[str, Path]:
    return {
        logical_name: source_root / relative
        for logical_name, relative in SOURCE_FILES.items()
    }


def task_text(problem_text: str) -> str:
    return f"""# Objective

Optimize `{ARTIFACT_NAME}` for the local VLIW/SIMD kernel-generation task.
Preserve correctness and minimize the simulated `{PRIMARY_METRIC}` value.

{problem_text.strip()}

# Evaluation

- Run `python3 evaluate.py` for public local feedback.
- The controller runs a separate held-out local case set only during final
  evaluation.
- The starter implementation takes `{BASELINE_CYCLES}` cycles on the main case;
  lower is better.

# Hard constraints

- Only edit `{ARTIFACT_NAME}`.
- Do not edit `problem.py`, `runner.py`, `verifier.py`, `evaluate.py`,
  `.goal-plus-verifiers/`, `test_cases/`, `task.json`, `TASK.md`, `AGENTS.md`,
  or Git configuration.
- Do not inspect parent or sibling directories, controller files, credentials,
  or network resources.
- Do not hardcode outputs for visible seeds; generate a correct kernel for
  arbitrary valid task parameters.
- Leave the best evaluator-verified implementation in `{ARTIFACT_NAME}`.

# Result classification

This is a host-only local replica extracted from the EdgeBench VLIW task
images. It is suitable for controlled method comparisons, but its score is not
an official EdgeBench result.
"""


def materialize_workspace(source_root: Path, workspace: Path) -> dict[str, Any]:
    source_root = source_root.expanduser().absolute()
    workspace = workspace.expanduser().absolute()
    required = source_paths(source_root)
    for path in required.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    if workspace.exists():
        raise FileExistsError(workspace)

    workspace.mkdir(parents=True)
    shutil.copy2(required["task/problem.py"], workspace / "problem.py")
    shutil.copy2(required["task/runner.py"], workspace / "runner.py")
    shutil.copy2(required["task/verifier.py"], workspace / "verifier.py")
    shutil.copy2(required["task/starter_solution.py"], workspace / ARTIFACT_NAME)
    cases_dir = workspace / "test_cases"
    cases_dir.mkdir()
    shutil.copy2(required["task/public_cases.json"], cases_dir / "public_cases.json")
    (workspace / "TASK.md").write_text(
        task_text(required["task/problem.md"].read_text())
    )
    (workspace / "AGENTS.md").write_text(
        "# Local VLIW task rules\n\n"
        f"- Only edit `{ARTIFACT_NAME}`.\n"
        "- Run `python3 evaluate.py` for public local feedback.\n"
        "- Do not inspect parent/sibling directories or use the network.\n"
        "- Do not edit task, evaluator, metadata, instruction, or Git files.\n"
        "- This local replica does not produce an official EdgeBench score.\n"
    )
    (workspace / "evaluate.py").write_text(
        render_evaluate_wrapper(CONTROLLER_PATH, source_root)
    )
    verifier_dir = workspace / ".goal-plus-verifiers"
    verifier_dir.mkdir()
    (verifier_dir / "primary_metric.py").write_text(
        render_goal_plus_verifier(
            CONTROLLER_PATH,
            source_root,
            PRIMARY_METRIC,
        )
    )
    (workspace / ".gitignore").write_text(
        ".bench-runtime/\n.gp/\n.codex-log/\n__pycache__/\n*.pyc\n"
    )
    metadata = {
        "schema_version": 1,
        "adapter": "local-vliw",
        "task_id": TASK_ID,
        "artifact_name": ARTIFACT_NAME,
        "upstream_root": str(source_root),
        "source_commit": git_commit(source_root),
        "source_sha256": {
            name: sha256_file(path) for name, path in required.items()
        },
        "primary_metric": PRIMARY_METRIC,
        "direction": DIRECTION,
        "baseline_cycles": BASELINE_CYCLES,
        "classification": "local_example",
        "official_edgebench_comparable": False,
    }
    write_json(workspace / "task.json", metadata)
    workspace_commit = init_git(workspace, "materialize local VLIW task")
    return {
        **metadata,
        "workspace": str(workspace),
        "workspace_commit": workspace_commit,
        "seed_sha256": sha256_file(workspace / ARTIFACT_NAME),
    }


def run_source_evaluator(
    source_root: Path,
    solution: Path,
    mode: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if mode not in {"public", "final"}:
        raise ValueError(f"unsupported evaluation mode: {mode}")
    runtime_root = source_root / ("task" if mode == "public" else "controller")
    cases = runtime_root / "test_cases" / (
        "public_cases.json" if mode == "public" else "hidden_cases.json"
    )
    with temporary_directory(
        prefix=f"local-vliw-{mode}-",
        namespace="local-vliw",
    ) as call_dir:
        report_path = call_dir / "report.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(runtime_root / "runner.py"),
                "--solution",
                str(solution),
                "--cases",
                str(cases),
                "--output",
                str(report_path),
            ],
            cwd=runtime_root,
            capture_output=True,
            text=True,
            timeout=(
                FINAL_EVALUATOR_TIMEOUT_SECONDS
                if mode == "final"
                else VERIFIER_TIMEOUT_SECONDS
            ),
        )
        raw = json.loads(report_path.read_text()) if report_path.is_file() else {}
    diagnostics = {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }
    return raw, diagnostics


def validate_source(source_root: Path, metadata: dict[str, Any]) -> None:
    required = source_paths(source_root)
    for name, expected in metadata["source_sha256"].items():
        path = required[name]
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"pinned local VLIW source changed: {name}")


def evaluate_workspace(
    workspace: Path,
    upstream_root: Path,
    mode: str,
) -> dict[str, Any]:
    started = time.monotonic()
    workspace = workspace.expanduser().absolute()
    source_root = upstream_root.expanduser().absolute()
    destination, budget = claim_evaluator_call(workspace, mode)
    metadata = json.loads((workspace / "task.json").read_text())
    changes = candidate_changed_paths(workspace)
    unauthorized = sorted(changes - {ARTIFACT_NAME})
    diagnostics: dict[str, Any] = {}
    raw: dict[str, Any] = {}

    if unauthorized or not (workspace / ARTIFACT_NAME).is_file():
        diagnostics["unauthorized_paths"] = unauthorized
    else:
        try:
            validate_source(source_root, metadata)
            raw, diagnostics = run_source_evaluator(
                source_root,
                workspace / ARTIFACT_NAME,
                mode,
            )
        except (subprocess.TimeoutExpired, OSError, RuntimeError, ValueError) as error:
            diagnostics = {"error": f"{type(error).__name__}: {error}"}

    score = raw.get("score_cycles")
    valid = bool(raw.get("all_correct")) and isinstance(score, (int, float))
    cycles = int(score) if valid else INVALID_CYCLES
    report = {
        "schema_version": 1,
        "benchmark": "local-vliw-replica",
        "task_id": TASK_ID,
        "mode": mode,
        "valid": valid,
        "primary_metric": {
            "name": PRIMARY_METRIC,
            "value": cycles,
            "direction": DIRECTION,
        },
        PRIMARY_METRIC: cycles,
        "speedup_over_baseline": (
            BASELINE_CYCLES / cycles if valid and cycles > 0 else 0.0
        ),
        "raw_report": raw,
        "diagnostics": diagnostics,
        "artifact_sha256": (
            sha256_file(workspace / ARTIFACT_NAME)
            if (workspace / ARTIFACT_NAME).is_file()
            else None
        ),
        "duration_seconds": time.monotonic() - started,
        "budget": budget,
        "classification": "local_example",
        "official_edgebench_comparable": False,
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
        print(
            json.dumps(
                materialize_workspace(args.upstream_root, args.workspace),
                indent=2,
            )
        )
        return 0
    report = evaluate_workspace(args.workspace, args.upstream_root, args.mode)
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
