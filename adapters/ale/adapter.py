#!/usr/bin/env python3
"""Materialize and evaluate the ALE-Bench Lite AHC027 task."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib
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
from bench_goal_plus.docker_inventory import inspect_exact_images  # noqa: E402


CONTROLLER_PATH = Path(__file__).resolve()
UPSTREAM_KEY = "ale_bench"
BENCHMARK_NAME = "ALE-Bench Lite"
TASK_ID = "ahc027"
ARTIFACT_NAME = "solution.cpp"
PRIMARY_METRIC = "overall_absolute_score"
DIRECTION = "minimize"
CODEX_SANDBOX = "danger-full-access"
CASE_SET_DESCRIPTION = "AHC027 public-lite (5 cases)"
INVALID_SCORE = 10**18
NUM_WORKERS = 4
VERIFIER_TIMEOUT_SECONDS = 180
TOOL_CACHE = ROOT / ".bench-env/cache/ale-bench/ahc027-lite/tools"
DEFAULT_STARTER = (
    ROOT / "evidence/runs/2026-07-21-ale-ahc027-plain-codex/solution.cpp"
)
ASSET_PROFILE = "ahc027-cpp20-202301"
EXPECTED_UPSTREAM_COMMIT = "f7d927906dc1dcd860ee086e4560d576438b1354"
CPP_IMAGE = "ale-bench:cpp20-202301"
RUST_TOOL_IMAGE = "rust:1.79.0-buster"
OPTIONAL_RUST_CANDIDATE_IMAGE = "ale-bench:rust-202301"


def load_ale_bench(upstream_root: Path):
    source_root = str(upstream_root / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    import ale_bench

    install_tool_cache(ale_bench)
    return ale_bench


def install_tool_cache(ale_bench: Any) -> None:
    """Reuse built official Rust tools without changing evaluator semantics."""
    start_module = importlib.import_module("ale_bench.start")
    if getattr(start_module, "_bench_goal_plus_tool_cache", False):
        return
    original_build = start_module.build_rust_tools

    def cached_build(tool_dir: Path) -> None:
        required = [
            name
            for name in ("gen", "tester", "vis")
            if (tool_dir / "src/bin" / f"{name}.rs").is_file()
        ]
        release = tool_dir / "target/release"
        TOOL_CACHE.mkdir(parents=True, exist_ok=True)
        lock_path = TOOL_CACHE / "build.lock"
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            if not all((TOOL_CACHE / name).is_file() for name in required):
                original_build(tool_dir)
                for name in required:
                    shutil.copy2(release / name, TOOL_CACHE / name)
            else:
                release.mkdir(parents=True, exist_ok=True)
                for name in required:
                    shutil.copy2(TOOL_CACHE / name, release / name)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    start_module.build_rust_tools = cached_build
    start_module._bench_goal_plus_tool_cache = True


def local_asset_inventory(
    upstream_root: Path, profile: str | None
) -> dict[str, Any]:
    """Inspect the fixed AHC027 C++ evaluator assets without building them."""
    if profile != ASSET_PROFILE:
        raise ValueError(f"ALE inventory profile must be {ASSET_PROFILE!r}")
    upstream_root = upstream_root.expanduser().resolve()
    try:
        source_commit = git_commit(upstream_root)
    except subprocess.CalledProcessError:
        source_commit = None
    expected_images = [
        {"role": "candidate-cpp20", "reference": CPP_IMAGE, "required": True},
        {"role": "rust-tool-builder", "reference": RUST_TOOL_IMAGE, "required": True},
        {
            "role": "optional-rust-candidate",
            "reference": OPTIONAL_RUST_CANDIDATE_IMAGE,
            "required": False,
        },
    ]
    inspected = inspect_exact_images(expected_images)
    for image in inspected["images"]:
        image["architecture_matches"] = (
            not image["present"] or image.get("architecture") == "amd64"
        )
    required_images = [
        image for image in inspected["images"] if image["required"]
    ]
    cache = {
        name: {
            "path": str(TOOL_CACHE / name),
            "present": (TOOL_CACHE / name).is_file(),
        }
        for name in ("gen", "tester", "vis")
    }
    ready = bool(
        source_commit == EXPECTED_UPSTREAM_COMMIT
        and DEFAULT_STARTER.is_file()
        and all(image["present"] for image in required_images)
        and all(image["architecture_matches"] for image in required_images)
        and inspected["container_check"]["returncode"] == 0
        and not inspected["container_check"]["parse_errors"]
    )
    return {
        "schema_version": 1,
        "action": "local-asset-inventory",
        "profile": profile,
        "read_only": True,
        "acquisition_attempted": False,
        "ready": ready,
        "source": {
            "path": str(upstream_root),
            "expected_commit": EXPECTED_UPSTREAM_COMMIT,
            "actual_commit": source_commit,
            "commit_matches": source_commit == EXPECTED_UPSTREAM_COMMIT,
            "starter": str(DEFAULT_STARTER),
            "starter_present": DEFAULT_STARTER.is_file(),
        },
        "tool_cache": cache,
        "images": inspected["images"],
        "container_check": inspected["container_check"],
        "docker_commands": inspected["docker_commands"],
    }


def task_text(statement: str) -> str:
    return f"""# Objective

Improve `{ARTIFACT_NAME}` for ALE-Bench Lite AHC027. The program must remain
accepted on every public-lite case and minimize the official aggregate absolute
score.

# Official problem statement

{statement.strip()}

# Evaluation

- Run `python3 evaluate.py` for official ALE-Bench public-lite feedback.
- Primary metric: `{PRIMARY_METRIC}`; lower is better.
- The controller evaluates five public-lite seeds in the official C++20 Docker
  judge and records every call.

# Hard constraints

- Only edit `{ARTIFACT_NAME}`.
- Do not edit `evaluate.py`, `.goal-plus-verifiers/`, `task.json`, `TASK.md`,
  `AGENTS.md`, or Git configuration.
- Do not inspect parent directories, hidden/private benchmark data, controller
  runtime files, credentials, or network resources.
- Do not hardcode public cases. Implement a general solver for valid AHC027
  instances and respect the official time limit.
- Leave the best evaluator-verified C++20 implementation in `{ARTIFACT_NAME}`.
"""


def materialize_workspace(upstream_root: Path, workspace: Path) -> dict[str, Any]:
    upstream_root = upstream_root.expanduser().absolute()
    workspace = workspace.expanduser().absolute()
    if not DEFAULT_STARTER.is_file():
        raise FileNotFoundError(DEFAULT_STARTER)
    if workspace.exists():
        raise FileExistsError(workspace)
    ale_bench = load_ale_bench(upstream_root)
    problem, seeds, _, _, data_root = ale_bench.data.load_problem(
        problem_id=TASK_ID, lite_version=True
    )
    try:
        statement = problem.statement
        public_case_count = len(seeds.public)
    finally:
        # The official loader owns an extracted temporary data root. Session
        # evaluation loads its own copy, so this materialization copy is unused.
        import shutil

        shutil.rmtree(data_root, ignore_errors=True)
    if public_case_count != 5:
        raise RuntimeError(
            f"unexpected ALE-Bench Lite public case count: {public_case_count}"
        )

    workspace.mkdir(parents=True)
    (workspace / ARTIFACT_NAME).write_bytes(DEFAULT_STARTER.read_bytes())
    (workspace / "PROBLEM.md").write_text(statement.rstrip() + "\n")
    (workspace / "TASK.md").write_text(task_text(statement))
    (workspace / "AGENTS.md").write_text(
        "# ALE-Bench Lite task rules\n\n"
        f"- Only edit `{ARTIFACT_NAME}`.\n"
        "- Run `python3 evaluate.py` for official public-lite feedback.\n"
        "- Do not inspect private data, parent directories, or the network.\n"
        "- Keep the solver general, deterministic, terminating, and C++20-compatible.\n"
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
        "adapter": "ale-bench-lite-ahc027",
        "task_id": TASK_ID,
        "artifact_name": ARTIFACT_NAME,
        "upstream_root": str(upstream_root),
        "upstream_commit": git_commit(upstream_root),
        "starter_sha256": sha256_file(DEFAULT_STARTER),
        "primary_metric": PRIMARY_METRIC,
        "direction": DIRECTION,
        "lite_version": True,
        "public_case_count": public_case_count,
        "code_language": "cpp20",
        "judge_version": "202301",
    }
    write_json(workspace / "task.json", metadata)
    workspace_commit = init_git(workspace, "materialize ALE-Bench Lite AHC027")
    return {
        **metadata,
        "workspace": str(workspace),
        "workspace_commit": workspace_commit,
    }


def evaluate_workspace(workspace: Path, upstream_root: Path, mode: str) -> dict[str, Any]:
    started = time.monotonic()
    workspace = workspace.expanduser().absolute()
    upstream_root = upstream_root.expanduser().absolute()
    destination, budget = claim_evaluator_call(workspace, mode)
    metadata = json.loads((workspace / "task.json").read_text())
    changes = candidate_changed_paths(workspace)
    unauthorized = sorted(changes - {ARTIFACT_NAME})
    code_path = workspace / ARTIFACT_NAME
    cases: list[dict[str, Any]] = []
    overall_judge_result = "INVALID_EDIT_SURFACE"
    absolute_score: int | float = INVALID_SCORE
    relative_score: int | float | None = None
    error: str | None = None
    if unauthorized or not code_path.is_file():
        error = (
            "candidate changed files outside solution.cpp: "
            + ", ".join(unauthorized)
            if unauthorized
            else "candidate removed solution.cpp"
        )
    else:
        ale_bench = load_ale_bench(upstream_root)
        session = ale_bench.start(
            problem_id=metadata["task_id"],
            lite_version=True,
            maximum_num_call_public_eval=1,
            num_workers=NUM_WORKERS,
        )
        try:
            result = session.public_eval(
                code_path.read_text(),
                code_language=metadata["code_language"],
                judge_version=metadata["judge_version"],
            )
            overall_judge_result = result.overall_judge_result.value
            if result.overall_absolute_score is not None:
                absolute_score = result.overall_absolute_score
            relative_score = result.overall_relative_score
            cases = [
                {
                    "judge_result": case.judge_result.value,
                    "absolute_score": case.absolute_score,
                    "relative_score": case.relative_score,
                    "execution_time": case.execution_time,
                    "memory_usage": case.memory_usage,
                    "message": case.message,
                }
                for case in result.case_results
            ]
        except Exception as exception:
            error = f"{type(exception).__name__}: {exception}"
        finally:
            session.close()

    valid = bool(
        overall_judge_result == "ACCEPTED"
        and len(cases) == metadata["public_case_count"]
        and all(case["judge_result"] == "ACCEPTED" for case in cases)
    )
    score = absolute_score if valid else INVALID_SCORE
    report = {
        "schema_version": 1,
        "benchmark": "ale-bench-lite",
        "task_id": TASK_ID,
        "mode": mode,
        "valid": valid,
        "primary_metric": {
            "name": PRIMARY_METRIC,
            "value": score,
            "direction": DIRECTION,
        },
        PRIMARY_METRIC: score,
        "overall_judge_result": overall_judge_result,
        "overall_relative_score": relative_score,
        "cases": cases,
        "error": error,
        "artifact_sha256": (
            hashlib.sha256(code_path.read_bytes()).hexdigest()
            if code_path.is_file()
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
