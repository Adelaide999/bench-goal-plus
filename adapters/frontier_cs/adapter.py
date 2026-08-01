#!/usr/bin/env python3
"""Materialize and evaluate Frontier-CS algorithmic problem 0."""

from __future__ import annotations

import argparse
import json
import re
import shlex
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
from bench_runtime_paths import make_preserved_temp_directory
from bench_goal_plus.docker_inventory import inspect_exact_images


CONTROLLER_PATH = Path(__file__).resolve()
UPSTREAM_KEY = "frontier_cs"
BENCHMARK_NAME = "Frontier-CS Algorithmic"
TASK_ID = "problem-0"
ARTIFACT_NAME = "solution.cpp"
PRIMARY_METRIC = "checker_score_percent"
DIRECTION = "maximize"
CODEX_SANDBOX = "danger-full-access"
CASE_SET_DESCRIPTION = "algorithmic/problem-0 official public case"
IMAGE = "bench-goal-plus/frontier-cs-judge:07500f9"
CONTAINER_NAME = "bench-goal-plus-frontier-cs-direct-07500f9"
ASSET_PROFILE = "problem-0"
EXPECTED_UPSTREAM_COMMIT = "07500f9e5751ddf86ef2760e0d35ff93e6a96a29"
INVALID_SCORE = 0.0
VERIFIER_TIMEOUT_SECONDS = 60
RATIO_PATTERN = re.compile(r"Ratio:\s*([0-9]+(?:\.[0-9]+)?)")


def problem_root(upstream_root: Path) -> Path:
    return upstream_root / "algorithmic/problems/0"


def task_text(statement: str) -> str:
    return f"""# Objective

Improve `{ARTIFACT_NAME}` for Frontier-CS Algorithmic problem 0. Produce a
valid placement for the official instance and maximize the official checker
ratio, reported here as a percentage.

{statement.strip()}

# Evaluation

- Run `python3 evaluate.py` for official checker feedback.
- Primary metric: `{PRIMARY_METRIC}`; higher is better.
- The controller compiles and runs the program in the pinned Frontier-CS judge
  image, then invokes the unmodified problem checker on the official case.

# Hard constraints

- Only edit `{ARTIFACT_NAME}`.
- Do not edit `evaluate.py`, `.goal-plus-verifiers/`, `task.json`, `TASK.md`,
  `AGENTS.md`, or Git configuration.
- Do not inspect parent directories, controller runtime files, credentials, or
  network resources.
- Do not hardcode checker internals or read answer files. Implement a general
  solver that consumes the instance on standard input.
- Leave the best evaluator-verified C++17 program in `{ARTIFACT_NAME}`.
"""


def materialize_workspace(upstream_root: Path, workspace: Path) -> dict[str, Any]:
    upstream_root = upstream_root.expanduser().absolute()
    workspace = workspace.expanduser().absolute()
    problem = problem_root(upstream_root)
    required = {
        "statement": problem / "statement.txt",
        "seed": problem / "examples/reference.cpp",
        "checker": problem / "chk.cc",
        "input": problem / "testdata/1.in",
        "answer": problem / "testdata/1.ans",
        "testlib": upstream_root / "algorithmic/judge/include/testlib.h",
    }
    for path in required.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    if workspace.exists():
        raise FileExistsError(workspace)

    workspace.mkdir(parents=True)
    (workspace / ARTIFACT_NAME).write_bytes(required["seed"].read_bytes())
    statement = required["statement"].read_text()
    (workspace / "TASK.md").write_text(task_text(statement))
    (workspace / "AGENTS.md").write_text(
        "# Frontier-CS problem-0 task rules\n\n"
        f"- Only edit `{ARTIFACT_NAME}`.\n"
        "- Run `python3 evaluate.py` for official checker feedback.\n"
        "- Keep a general stdin/stdout solver; do not inspect parent paths.\n"
        "- Do not use the network or modify controller-owned files.\n"
    )
    (workspace / "evaluate.py").write_text(
        render_evaluate_wrapper(CONTROLLER_PATH, upstream_root)
    )
    verifier_dir = workspace / ".goal-plus-verifiers"
    verifier_dir.mkdir()
    (verifier_dir / "primary_metric.py").write_text(
        render_goal_plus_verifier(CONTROLLER_PATH, upstream_root, PRIMARY_METRIC)
    )
    (workspace / ".gitignore").write_text(
        ".bench-runtime/\n.gp/\n.codex-log/\n__pycache__/\n*.pyc\n"
    )
    metadata = {
        "schema_version": 1,
        "adapter": "frontier-cs-problem-0",
        "task_id": TASK_ID,
        "artifact_name": ARTIFACT_NAME,
        "upstream_root": str(upstream_root),
        "upstream_commit": git_commit(upstream_root),
        "source_sha256": {
            name: sha256_file(path) for name, path in required.items()
        },
        "primary_metric": PRIMARY_METRIC,
        "direction": DIRECTION,
        "docker_image": IMAGE,
        "docker_container": CONTAINER_NAME,
    }
    write_json(workspace / "task.json", metadata)
    workspace_commit = init_git(workspace, "materialize Frontier-CS problem 0")
    return {
        **metadata,
        "workspace": str(workspace),
        "workspace_commit": workspace_commit,
    }


def run(command: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def local_asset_inventory(
    upstream_root: Path, profile: str | None
) -> dict[str, Any]:
    """Inspect the exact judge image and preserved container without mutation."""
    if profile != ASSET_PROFILE:
        raise ValueError(
            f"Frontier-CS inventory profile must be {ASSET_PROFILE!r}"
        )
    upstream_root = upstream_root.expanduser().resolve()
    try:
        source_commit = git_commit(upstream_root)
    except subprocess.CalledProcessError:
        source_commit = None
    inspected = inspect_exact_images(
        [
            {
                "role": "judge",
                "reference": IMAGE,
                "required": True,
                "expected_container": CONTAINER_NAME,
            }
        ]
    )
    image = inspected["images"][0]
    image["architecture_matches"] = image.get("architecture") == "amd64"
    source_files = {
        "dockerfile": upstream_root / "algorithmic/Dockerfile",
        "problem": problem_root(upstream_root),
    }
    source_ready = all(path.exists() for path in source_files.values())
    ready = bool(
        source_commit == EXPECTED_UPSTREAM_COMMIT
        and source_ready
        and image["present"]
        and image["architecture_matches"]
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
            "files": {
                name: {"path": str(path), "present": path.exists()}
                for name, path in source_files.items()
            },
        },
        "images": inspected["images"],
        "container_check": inspected["container_check"],
        "docker_commands": inspected["docker_commands"],
    }


def ensure_compile_container() -> None:
    image = run(["docker", "image", "inspect", IMAGE])
    if image.returncode != 0:
        raise RuntimeError(
            f"missing Docker image {IMAGE}; build it with `docker build -t {IMAGE} "
            "third_party/frontier-cs/algorithmic` from the bench-goal-plus root"
        )
    inspected = run(
        ["docker", "inspect", CONTAINER_NAME, "--format", "{{json .}}"]
    )
    if inspected.returncode != 0:
        created = run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                CONTAINER_NAME,
                "--network",
                "none",
                "--cpus",
                "2",
                "--memory",
                "2g",
                "--entrypoint",
                "sleep",
                "-v",
                f"{ROOT}:/bench",
                IMAGE,
                "infinity",
            ],
            timeout=60,
        )
        if created.returncode != 0:
            raise RuntimeError(created.stderr.strip() or "failed to create judge container")
        return
    payload = json.loads(inspected.stdout)
    mounts = payload.get("Mounts") or []
    expected_source = str(ROOT.resolve())
    if not any(
        item.get("Destination") == "/bench"
        and str(Path(item.get("Source", "")).resolve()) == expected_source
        for item in mounts
    ):
        raise RuntimeError(
            f"preserved container {CONTAINER_NAME} is bound to another checkout; "
            "rename it before retrying"
        )
    if not payload.get("State", {}).get("Running"):
        started = run(["docker", "start", CONTAINER_NAME])
        if started.returncode != 0:
            raise RuntimeError(started.stderr.strip() or "failed to start judge container")


def doctor_environment(upstream_root: Path) -> dict[str, Any]:
    """Check the preserved judge without changing image or container state."""
    docker = run(["docker", "info"])
    if docker.returncode != 0:
        raise RuntimeError(docker.stderr.strip() or "Docker daemon is unavailable")
    image = run(["docker", "image", "inspect", IMAGE])
    if image.returncode != 0:
        raise RuntimeError(f"missing Docker image {IMAGE}")
    inspected = run(["docker", "inspect", CONTAINER_NAME, "--format", "{{json .}}"])
    if inspected.returncode != 0:
        raise RuntimeError(f"missing Docker container {CONTAINER_NAME}")
    payload = json.loads(inspected.stdout)
    expected_source = str(ROOT.resolve())
    mounts = payload.get("Mounts") or []
    if not any(
        item.get("Destination") == "/bench"
        and str(Path(item.get("Source", "")).resolve()) == expected_source
        for item in mounts
    ):
        raise RuntimeError(
            f"preserved container {CONTAINER_NAME} is bound to another checkout"
        )
    if not payload.get("State", {}).get("Running"):
        raise RuntimeError(f"Docker container {CONTAINER_NAME} is not running")
    dockerfile = upstream_root.expanduser().resolve() / "algorithmic/Dockerfile"
    if not dockerfile.is_file():
        raise RuntimeError(f"Frontier-CS Dockerfile is missing: {dockerfile}")
    return {
        "image": IMAGE,
        "container": CONTAINER_NAME,
        "container_running": True,
        "dockerfile": str(dockerfile),
    }


def provision_environment(upstream_root: Path) -> dict[str, Any]:
    """Build the pinned image when absent and create/start its evaluator container."""
    upstream_root = upstream_root.expanduser().resolve()
    dockerfile = upstream_root / "algorithmic/Dockerfile"
    if not dockerfile.is_file():
        raise RuntimeError(f"Frontier-CS Dockerfile is missing: {dockerfile}")
    docker = run(["docker", "info"])
    if docker.returncode != 0:
        raise RuntimeError(docker.stderr.strip() or "Docker daemon is unavailable")
    image = run(["docker", "image", "inspect", IMAGE])
    built = image.returncode != 0
    if built:
        completed = subprocess.run(
            ["docker", "build", "-t", IMAGE, str(dockerfile.parent)],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "failed to build judge image")
    ensure_compile_container()
    return {**doctor_environment(upstream_root), "image_built": built}


def container_path(host_path: Path) -> str:
    relative = host_path.resolve().relative_to(ROOT.resolve())
    return "/bench/" + relative.as_posix()


def parse_checker_ratio(output: str) -> float | None:
    match = RATIO_PATTERN.search(output)
    return float(match.group(1)) if match else None


def evaluate_candidate(
    candidate_source: Path,
    upstream_root: Path,
    call_dir: Path,
) -> tuple[bool, float, dict[str, Any]]:
    ensure_compile_container()
    problem = problem_root(upstream_root)
    solution = call_dir / "solution"
    checker = call_dir / "checker"
    output = call_dir / "solution.out"
    compile_solution = run(
        [
            "docker",
            "exec",
            CONTAINER_NAME,
            "g++",
            "-std=c++17",
            "-O2",
            "-pipe",
            container_path(candidate_source),
            "-o",
            container_path(solution),
        ],
        timeout=45,
    )
    diagnostics: dict[str, Any] = {
        "compile_solution_returncode": compile_solution.returncode,
        "compile_solution_stdout": compile_solution.stdout[-4000:],
        "compile_solution_stderr": compile_solution.stderr[-4000:],
    }
    if compile_solution.returncode != 0:
        return False, INVALID_SCORE, diagnostics
    compile_checker = run(
        [
            "docker",
            "exec",
            CONTAINER_NAME,
            "g++",
            "-std=c++17",
            "-O2",
            "-I",
            container_path(upstream_root / "algorithmic/judge/include"),
            container_path(problem / "chk.cc"),
            "-o",
            container_path(checker),
        ],
        timeout=45,
    )
    diagnostics.update(
        {
            "compile_checker_returncode": compile_checker.returncode,
            "compile_checker_stdout": compile_checker.stdout[-4000:],
            "compile_checker_stderr": compile_checker.stderr[-4000:],
        }
    )
    if compile_checker.returncode != 0:
        return False, INVALID_SCORE, diagnostics

    command = (
        "timeout 3s "
        + shlex.quote(container_path(solution))
        + " < "
        + shlex.quote(container_path(problem / "testdata/1.in"))
        + " > "
        + shlex.quote(container_path(output))
    )
    executed = run(
        ["docker", "exec", CONTAINER_NAME, "bash", "-lc", command],
        timeout=10,
    )
    diagnostics.update(
        {
            "solution_returncode": executed.returncode,
            "solution_stdout": executed.stdout[-4000:],
            "solution_stderr": executed.stderr[-4000:],
        }
    )
    if executed.returncode != 0:
        return False, INVALID_SCORE, diagnostics
    checked = run(
        [
            "docker",
            "exec",
            CONTAINER_NAME,
            container_path(checker),
            container_path(problem / "testdata/1.in"),
            container_path(output),
            container_path(problem / "testdata/1.ans"),
        ],
        timeout=15,
    )
    checker_text = (checked.stdout or "") + "\n" + (checked.stderr or "")
    ratio = parse_checker_ratio(checker_text)
    diagnostics.update(
        {
            "checker_returncode": checked.returncode,
            "checker_output": checker_text.strip()[-4000:],
            "checker_ratio": ratio,
        }
    )
    return ratio is not None, (ratio or 0.0) * 100.0, diagnostics


def evaluate_workspace(workspace: Path, upstream_root: Path, mode: str) -> dict[str, Any]:
    started = time.monotonic()
    workspace = workspace.expanduser().absolute()
    upstream_root = upstream_root.expanduser().absolute()
    destination, budget = claim_evaluator_call(workspace, mode)
    metadata = json.loads((workspace / "task.json").read_text())
    changes = candidate_changed_paths(workspace)
    unauthorized = sorted(changes - {ARTIFACT_NAME})
    call_dir = make_preserved_temp_directory(
        prefix="call-",
        namespace="frontier-cs-calls",
    )
    diagnostics: dict[str, Any]
    error: str | None = None
    if unauthorized or not (workspace / ARTIFACT_NAME).is_file():
        valid = False
        score = INVALID_SCORE
        diagnostics = {"unauthorized_paths": unauthorized}
    else:
        expected = metadata["source_sha256"]
        current = {
            "checker": sha256_file(problem_root(upstream_root) / "chk.cc"),
            "input": sha256_file(problem_root(upstream_root) / "testdata/1.in"),
            "answer": sha256_file(problem_root(upstream_root) / "testdata/1.ans"),
            "testlib": sha256_file(
                upstream_root / "algorithmic/judge/include/testlib.h"
            ),
        }
        if any(current[name] != expected[name] for name in current):
            raise RuntimeError("pinned Frontier-CS checker inputs changed")
        try:
            candidate_source = call_dir / ARTIFACT_NAME
            shutil.copy2(workspace / ARTIFACT_NAME, candidate_source)
            valid, score, diagnostics = evaluate_candidate(
                candidate_source, upstream_root, call_dir
            )
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exception:
            valid = False
            score = INVALID_SCORE
            diagnostics = {}
            error = f"{type(exception).__name__}: {exception}"
    report = {
        "schema_version": 1,
        "benchmark": "frontier-cs",
        "task_id": TASK_ID,
        "mode": mode,
        "valid": valid,
        "primary_metric": {
            "name": PRIMARY_METRIC,
            "value": score,
            "direction": DIRECTION,
        },
        PRIMARY_METRIC: score,
        "checker_ratio": diagnostics.get("checker_ratio"),
        "diagnostics": diagnostics,
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
        print(
            json.dumps(
                materialize_workspace(args.upstream_root, args.workspace), indent=2
            )
        )
        return 0
    report = evaluate_workspace(args.workspace, args.upstream_root, args.mode)
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
