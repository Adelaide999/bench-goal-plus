#!/usr/bin/env python3
"""Materialize and evaluate Frontier-Engineering MallocLab."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
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
from bench_runtime_paths import temporary_directory


CONTROLLER_PATH = Path(__file__).resolve()
UPSTREAM_KEY = "frontier_engineering"
BENCHMARK_NAME = "Frontier-Engineering v1-lite"
TASK_ID = "malloclab"
ARTIFACT_NAME = "mm.c"
PRIMARY_METRIC = "combined_score"
DIRECTION = "maximize"
CODEX_SANDBOX = "workspace-write"
CASE_SET_DESCRIPTION = "ComputerSystems/MallocLab official mdriver traces"
INVALID_SCORE = 0.0
VERIFIER_TIMEOUT_SECONDS = 60


def benchmark_root(upstream_root: Path) -> Path:
    return upstream_root / "benchmarks/ComputerSystems/MallocLab"


def evaluator_path(upstream_root: Path) -> Path:
    return upstream_root / "frontier_eval/tasks/malloclab/evaluator/python.py"


def task_text(specification: str) -> str:
    return f"""# Objective

Improve `{ARTIFACT_NAME}` for Frontier-Engineering MallocLab. Preserve allocator
correctness and maximize the official raw score out of 100, which combines heap
utilization and throughput.

{specification.strip()}

# Evaluation

- Run `python3 evaluate.py` for official Frontier-Engineering feedback.
- Primary metric: `{PRIMARY_METRIC}` (the guarded raw score from 0 to 100);
  higher is better.

# Hard constraints

- Only edit `{ARTIFACT_NAME}`.
- Preserve `mm_init`, `mm_malloc`, `mm_free`, and `mm_realloc` signatures.
- Do not edit `evaluate.py`, `.goal-plus-verifiers/`, `task.json`, `TASK.md`,
  `AGENTS.md`, or Git configuration.
- Do not inspect parent directories, controller runtime files, credentials, or
  network resources.
- Do not bypass or special-case the trace set. Implement a general allocator.
- Leave the best evaluator-verified allocator in `{ARTIFACT_NAME}`.
"""


def materialize_workspace(upstream_root: Path, workspace: Path) -> dict[str, Any]:
    upstream_root = upstream_root.expanduser().absolute()
    workspace = workspace.expanduser().absolute()
    benchmark = benchmark_root(upstream_root)
    seed = benchmark / "malloclab-handout/mm.c"
    specification = benchmark / "Task_zh-CN.md"
    evaluator = evaluator_path(upstream_root)
    for path in (seed, specification, evaluator, benchmark / "malloclab-handout/Makefile"):
        if not path.is_file():
            raise FileNotFoundError(path)
    if workspace.exists():
        raise FileExistsError(workspace)

    workspace.mkdir(parents=True)
    (workspace / ARTIFACT_NAME).write_bytes(seed.read_bytes())
    (workspace / "TASK.md").write_text(task_text(specification.read_text()))
    (workspace / "AGENTS.md").write_text(
        "# Frontier-Engineering MallocLab task rules\n\n"
        f"- Only edit `{ARTIFACT_NAME}`.\n"
        "- Run `python3 evaluate.py` for official feedback.\n"
        "- Preserve allocator correctness and all required interfaces.\n"
        "- Do not inspect parent directories or use the network.\n"
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
        "adapter": "frontier-engineering-malloclab",
        "task_id": TASK_ID,
        "artifact_name": ARTIFACT_NAME,
        "upstream_root": str(upstream_root),
        "upstream_commit": git_commit(upstream_root),
        "seed_sha256": sha256_file(seed),
        "specification_sha256": sha256_file(specification),
        "evaluator_sha256": sha256_file(evaluator),
        "primary_metric": PRIMARY_METRIC,
        "direction": DIRECTION,
    }
    write_json(workspace / "task.json", metadata)
    workspace_commit = init_git(
        workspace, "materialize Frontier-Engineering MallocLab"
    )
    return {
        **metadata,
        "workspace": str(workspace),
        "workspace_commit": workspace_commit,
    }


def load_official_evaluator(upstream_root: Path):
    path = evaluator_path(upstream_root)
    spec = importlib.util.spec_from_file_location(
        "frontier_engineering_malloclab_evaluator", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Frontier-Engineering evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.evaluate


def prepare_portable_repo(upstream_root: Path, destination: Path) -> Path:
    """Copy MallocLab sources without upstream's checked-in Linux binaries."""
    source = benchmark_root(upstream_root)
    portable_benchmark = destination / "benchmarks/ComputerSystems/MallocLab"
    portable_benchmark.parent.mkdir(parents=True)
    shutil.copytree(
        source,
        portable_benchmark,
        ignore=shutil.ignore_patterns("*.o", "mdriver"),
    )
    return destination


def unwrap_result(result: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(result, dict):
        return dict(result), {}
    metrics = getattr(result, "metrics", None)
    artifacts = getattr(result, "artifacts", None)
    if not isinstance(metrics, dict):
        raise TypeError(f"unsupported evaluator result: {type(result).__name__}")
    return dict(metrics), dict(artifacts or {})


def evaluate_workspace(workspace: Path, upstream_root: Path, mode: str) -> dict[str, Any]:
    started = time.monotonic()
    workspace = workspace.expanduser().absolute()
    upstream_root = upstream_root.expanduser().absolute()
    destination, budget = claim_evaluator_call(workspace, mode)
    metadata = json.loads((workspace / "task.json").read_text())
    changes = candidate_changed_paths(workspace)
    unauthorized = sorted(changes - {ARTIFACT_NAME})
    metrics: dict[str, Any] = {}
    artifacts: dict[str, Any] = {}
    error: str | None = None
    if unauthorized or not (workspace / ARTIFACT_NAME).is_file():
        error = (
            "candidate changed files outside mm.c: " + ", ".join(unauthorized)
            if unauthorized
            else "candidate removed mm.c"
        )
    elif sha256_file(evaluator_path(upstream_root)) != metadata["evaluator_sha256"]:
        raise RuntimeError("pinned Frontier-Engineering evaluator changed")
    else:
        try:
            previous_timeout = os.environ.get("FRONTIER_EVAL_EVALUATOR_TIMEOUT_S")
            os.environ["FRONTIER_EVAL_EVALUATOR_TIMEOUT_S"] = "120"
            try:
                with temporary_directory(
                    prefix="frontier-malloc-portable-",
                    namespace="frontier-engineering",
                ) as temporary:
                    portable_root = prepare_portable_repo(
                        upstream_root, temporary
                    )
                    raw = load_official_evaluator(upstream_root)(
                        str(workspace / ARTIFACT_NAME), repo_root=portable_root
                    )
            finally:
                if previous_timeout is None:
                    os.environ.pop("FRONTIER_EVAL_EVALUATOR_TIMEOUT_S", None)
                else:
                    os.environ["FRONTIER_EVAL_EVALUATOR_TIMEOUT_S"] = previous_timeout
            metrics, artifacts = unwrap_result(raw)
        except Exception as exception:  # Preserve official evaluator diagnostics.
            error = f"{type(exception).__name__}: {exception}"

    value = metrics.get(PRIMARY_METRIC)
    valid = bool(
        metrics.get("valid") == 1.0
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    )
    score = float(value) if valid else INVALID_SCORE
    report = {
        "schema_version": 1,
        "benchmark": "frontier-engineering-lite",
        "task_id": TASK_ID,
        "mode": mode,
        "valid": valid,
        "primary_metric": {
            "name": PRIMARY_METRIC,
            "value": score,
            "direction": DIRECTION,
        },
        PRIMARY_METRIC: score,
        "raw_metrics": metrics,
        "artifacts": artifacts,
        "error": error,
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
