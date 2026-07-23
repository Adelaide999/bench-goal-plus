#!/usr/bin/env python3
"""Materialize and evaluate the HeuriGym operator-scheduling smoke task."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bench_runtime_paths import temporary_directory  # noqa: E402


CONTROLLER_PATH = Path(__file__).resolve()
UPSTREAM_KEY = "heurigym"
BENCHMARK_NAME = "HeuriGym"
ARTIFACT_NAME = "solver.py"
TASK_ID = "operator_scheduling_demo"
CASE_SET_DESCRIPTION = "operator_scheduling/demo (5 public cases)"
CODEX_SANDBOX = "workspace-write"
VERIFIER_TIMEOUT_SECONDS = 60
DATASET_REPOSITORY = "heurigen/heurigen-data"
DATASET_REVISION = "c11ab2db2824068e523ac4656a20a6f2581961b8"
CASE_NAMES = ("demo.json", "ewf.json", "hal.json", "horner.json", "motion.json")
EXPECTED_CASE_SHA256 = {
    "demo.json": "93ca4b9c63ab3b446f77c71da75897b06b702b563d5aacbbb61c49348f5556a7",
    "ewf.json": "324243ae5d7b8900fe2366c696f396c1beffcdff3713670c870f7d42dc5be1f0",
    "hal.json": "95c67695c5d69d658d8c905e758c55c0ae5154ff995d52366d210d9d54d81514",
    "horner.json": "2291f6c14a278bf31cbdab30f2c626ed2ba7996fb10993afe681b6d772f53238",
    "motion.json": "3aa8c5bc5c83248ac08c56962ae8cf382e5a3d68def52ae0c4a2fb4d2e2e0132",
}
PRIMARY_METRIC = "total_cost"
DIRECTION = "minimize"
INVALID_COST = 1_000_000_000
CASE_TIMEOUT_SECONDS = 10


SEED_SOLVER = '''"""Valid but deliberately sequential operator scheduler."""

import json


def solve(input_file, output_file):
    with open(input_file) as source:
        problem = json.load(source)

    delays = problem["delay"]
    resource_by_node = {node_id: resource for node_id, resource in problem["nodes"]}
    successors = {node_id: [] for node_id in resource_by_node}
    indegree = {node_id: 0 for node_id in resource_by_node}
    for source, target, _ in problem["edges"]:
        successors[source].append(target)
        indegree[target] += 1

    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    order = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for target in successors[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)

    if len(order) != len(resource_by_node):
        raise ValueError("input graph is not a DAG")

    current_cycle = 0
    schedule = {}
    for node_id in order:
        schedule[node_id] = current_cycle
        current_cycle += delays[resource_by_node[node_id]]

    with open(output_file, "w") as destination:
        for node_id, _ in problem["nodes"]:
            destination.write(f"{node_id}:{schedule[node_id]}\\n")
'''


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit(path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def init_git(workspace: Path) -> str:
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "config", "user.name", "Benchmark Controller"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "config",
            "user.email",
            "benchmark-controller@example.invalid",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(workspace), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-q", "-m", "materialize HeuriGym task"],
        check=True,
    )
    return git_commit(workspace)


def render_evaluate_wrapper(upstream_root: Path) -> str:
    return (
        "#!/usr/bin/env python3\n"
        '"""Controller-owned public evaluator wrapper; do not edit."""\n'
        "import subprocess\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        f"CONTROLLER = Path({str(CONTROLLER_PATH)!r})\n"
        f"UPSTREAM = Path({str(upstream_root)!r})\n"
        "raise SystemExit(subprocess.call([sys.executable, str(CONTROLLER), "
        "'evaluate', '--workspace', str(Path(__file__).resolve().parent), "
        "'--upstream-root', str(UPSTREAM), '--mode', 'public']))\n"
    )


def render_goal_plus_verifier(upstream_root: Path) -> str:
    return (
        "#!/usr/bin/env python3\n"
        '"""Controller-owned Goal Plus verifier; do not edit."""\n'
        "import json\n"
        "import subprocess\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        f"CONTROLLER = Path({str(CONTROLLER_PATH)!r})\n"
        f"UPSTREAM = Path({str(upstream_root)!r})\n"
        "completed = subprocess.run(\n"
        "    [sys.executable, str(CONTROLLER), 'evaluate', '--workspace', str(Path.cwd()),\n"
        "     '--upstream-root', str(UPSTREAM), '--mode', 'public'],\n"
        "    capture_output=True, text=True,\n"
        ")\n"
        "if completed.returncode != 0:\n"
        "    sys.stderr.write(completed.stderr)\n"
        "    raise SystemExit(completed.returncode)\n"
        "report = json.loads(completed.stdout)\n"
        "metric = report.get('primary_metric') or {}\n"
        "value = metric.get('value')\n"
        "if report.get('valid') is not True or not isinstance(value, (int, float)):\n"
        "    raise SystemExit('official evaluator rejected the candidate')\n"
        f"print(json.dumps({{{PRIMARY_METRIC!r}: float(value), 'valid': True}}))\n"
    )


def task_text(case_names: tuple[str, ...]) -> str:
    cases = ", ".join(f"`cases/{name}`" for name in case_names)
    return f"""# Objective

Improve the Python operator scheduler in `{ARTIFACT_NAME}`. It must emit a valid schedule for every public HeuriGym case and minimize aggregate latency.

# Task interface

- Implement `solve(input_file, output_file)` in `{ARTIFACT_NAME}`.
- Each JSON input defines operation nodes, precedence edges, resource delays, and available resource counts.
- Write one `node_id:start_cycle` line for every node.
- Public cases: {cases}.
- Run `python3 evaluate.py` for official feedback. The primary metric is `{PRIMARY_METRIC}` and lower is better.

# Success criterion

Keep every case valid and improve `{PRIMARY_METRIC}` over the deliberately sequential seed scheduler.

# Hard constraints

- Only edit `{ARTIFACT_NAME}`.
- Do not modify `evaluate.py`, `.goal-plus-verifiers/`, `cases/`, `task.json`, `TASK.md`, `AGENTS.md`, or Git configuration.
- Do not inspect parent directories, controller runtime files, credentials, or network resources.
- Do not hardcode schedules for the visible cases; implement a general scheduler for arbitrary valid DAG inputs.
- Use only the Python standard library.
- Leave the best evaluator-verified implementation in `{ARTIFACT_NAME}`.
"""


def ensure_demo_cases(upstream_root: Path) -> Path:
    source_cases = upstream_root / "_datasets/operator_scheduling/demo"
    missing = [name for name in CASE_NAMES if not (source_cases / name).is_file()]
    if not missing:
        return source_cases
    try:
        from huggingface_hub import snapshot_download
    except ImportError as error:
        raise RuntimeError(
            "HeuriGym public data is missing; run scripts/repro_env.py bootstrap "
            "to install huggingface-hub"
        ) from error
    snapshot_download(
        repo_id=DATASET_REPOSITORY,
        repo_type="dataset",
        revision=DATASET_REVISION,
        allow_patterns="operator_scheduling/demo/*.json",
        local_dir=str(upstream_root / "_datasets"),
        token=os.getenv("HUGGINGFACE_TOKEN"),
    )
    missing = [name for name in CASE_NAMES if not (source_cases / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "HeuriGym dataset download did not materialize: " + ", ".join(missing)
        )
    return source_cases


def materialize_workspace(
    upstream_root: Path,
    workspace: Path,
) -> dict[str, Any]:
    upstream_root = upstream_root.expanduser().absolute()
    workspace = workspace.expanduser().absolute()
    source_cases = ensure_demo_cases(upstream_root)
    program_dir = upstream_root / "operator_scheduling/program"
    required = [
        upstream_root / ".git",
        program_dir / "verifier.py",
        program_dir / "evaluator.py",
        program_dir / "utils.py",
        *(source_cases / name for name in CASE_NAMES),
    ]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)
    if workspace.exists():
        raise FileExistsError(workspace)

    workspace.mkdir(parents=True)
    visible_cases = workspace / "cases"
    visible_cases.mkdir()
    for name in CASE_NAMES:
        shutil.copy2(source_cases / name, visible_cases / name)
        actual_sha256 = sha256_file(visible_cases / name)
        if actual_sha256 != EXPECTED_CASE_SHA256[name]:
            raise RuntimeError(
                f"pinned HeuriGym case hash mismatch for {name}: {actual_sha256}"
            )

    (workspace / ARTIFACT_NAME).write_text(SEED_SOLVER)
    (workspace / "TASK.md").write_text(task_text(CASE_NAMES))
    (workspace / "AGENTS.md").write_text(
        "# HeuriGym operator-scheduling task rules\n\n"
        f"- Only edit `{ARTIFACT_NAME}`.\n"
        "- Run `python3 evaluate.py` for official public feedback.\n"
        "- Do not edit evaluator, verifier, cases, metadata, instructions, or Git files.\n"
        "- Do not inspect parent directories or use the network.\n"
        "- Leave the best verified general scheduler in the editable artifact.\n"
    )
    (workspace / "evaluate.py").write_text(render_evaluate_wrapper(upstream_root))
    verifier_dir = workspace / ".goal-plus-verifiers"
    verifier_dir.mkdir()
    (verifier_dir / "primary_metric.py").write_text(
        render_goal_plus_verifier(upstream_root)
    )
    (workspace / ".gitignore").write_text(
        ".bench-runtime/\n.gp/\n.codex-log/\n__pycache__/\n*.pyc\n"
    )

    upstream_commit = git_commit(upstream_root)
    metadata = {
        "schema_version": 1,
        "adapter": "heurigym-operator-scheduling",
        "task_id": TASK_ID,
        "artifact_name": ARTIFACT_NAME,
        "upstream_root": str(upstream_root),
        "upstream_commit": upstream_commit,
        "program_dir": str(program_dir),
        "case_names": list(CASE_NAMES),
        "dataset_repository": DATASET_REPOSITORY,
        "dataset_revision": DATASET_REVISION,
        "case_sha256": EXPECTED_CASE_SHA256,
        "primary_metric": PRIMARY_METRIC,
        "direction": DIRECTION,
        "case_timeout_seconds": CASE_TIMEOUT_SECONDS,
        "controller_runtime_dir": ".bench-runtime",
    }
    write_json(workspace / "task.json", metadata)
    workspace_commit = init_git(workspace)
    return {
        **metadata,
        "workspace": str(workspace),
        "workspace_commit": workspace_commit,
        "seed_sha256": sha256_file(workspace / ARTIFACT_NAME),
    }


def claim_evaluator_call(runtime_dir: Path, mode: str) -> dict[str, Any]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    lock_path = runtime_dir / "budget.lock"
    budget_path = runtime_dir / "budget.json"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        budget = (
            json.loads(budget_path.read_text())
            if budget_path.is_file()
            else {
                "schema_version": 1,
                "total_claimed": 0,
                "public_claimed": 0,
                "final_claimed": 0,
            }
        )
        budget["total_claimed"] += 1
        budget[f"{mode}_claimed"] += 1
        write_json(budget_path, budget)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return budget


def load_solver(workspace: Path):
    path = workspace / ARTIFACT_NAME
    spec = importlib.util.spec_from_file_location("heurigym_candidate_solver", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    solve = getattr(module, "solve", None)
    if not callable(solve):
        raise RuntimeError("solver.py must define callable solve(input_file, output_file)")
    return solve


def changed_workspace_paths(workspace: Path) -> set[str]:
    tracked = subprocess.run(
        ["git", "-C", str(workspace), "diff", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    untracked = subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "ls-files",
            "--others",
            "--exclude-standard",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return {
        line
        for line in (*tracked.stdout.splitlines(), *untracked.stdout.splitlines())
        if line
    }


def evaluate_one_case(
    workspace: Path,
    program_dir: Path,
    case_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    sys.path.insert(0, str(program_dir))
    try:
        from evaluator import evaluate as official_evaluate
        from verifier import verify as official_verify

        solve = load_solver(workspace)
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(
            captured_stderr
        ):
            solve(str(case_path), str(output_path))
        valid, message = official_verify(str(case_path), str(output_path))
        cost = official_evaluate(str(case_path), str(output_path)) if valid else None
        return {
            "case": case_path.name,
            "valid": bool(valid),
            "cost": cost,
            "message": message,
            "candidate_stdout": captured_stdout.getvalue()[-2000:],
            "candidate_stderr": captured_stderr.getvalue()[-2000:],
        }
    finally:
        try:
            sys.path.remove(str(program_dir))
        except ValueError:
            pass


def run_case_subprocess(
    workspace: Path,
    upstream_root: Path,
    name: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    with temporary_directory(
        prefix="heurigym-eval-",
        namespace="heurigym",
    ) as temporary:
        output_path = temporary / f"{Path(name).stem}.output"
        completed = subprocess.run(
            [
                sys.executable,
                str(CONTROLLER_PATH),
                "_case",
                "--workspace",
                str(workspace),
                "--upstream-root",
                str(upstream_root),
                "--case-name",
                name,
                "--output",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=workspace,
        )
    if completed.returncode != 0:
        return {
            "case": name,
            "valid": False,
            "cost": None,
            "message": (completed.stderr or completed.stdout).strip()[-4000:],
        }
    return json.loads(completed.stdout)


def evaluate_workspace(workspace: Path, upstream_root: Path, mode: str) -> dict[str, Any]:
    started = time.monotonic()
    workspace = workspace.expanduser().absolute()
    upstream_root = upstream_root.expanduser().absolute()
    metadata = json.loads((workspace / "task.json").read_text())
    verifier_tmpdir = os.getenv("GOAL_PLUS_VERIFIER_TMPDIR")
    runtime_dir = (
        Path(verifier_tmpdir) / "heurigym-runtime"
        if verifier_tmpdir
        else workspace / ".bench-runtime"
    )
    budget = claim_evaluator_call(runtime_dir, mode)
    changed_paths = changed_workspace_paths(workspace)
    unauthorized_paths = sorted(
        path
        for path in changed_paths - {ARTIFACT_NAME}
        if not path.startswith(".bench-runtime/")
        and path not in {".tmp/handoff.json", "results.tsv"}
    )
    if unauthorized_paths or not (workspace / ARTIFACT_NAME).is_file():
        report = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "mode": mode,
            "valid": False,
            "primary_metric": {
                "name": PRIMARY_METRIC,
                "value": INVALID_COST,
                "direction": DIRECTION,
            },
            PRIMARY_METRIC: INVALID_COST,
            "raw_total_cost": 0,
            "cases": [],
            "message": (
                "candidate changed files outside solver.py: "
                + ", ".join(unauthorized_paths)
                if unauthorized_paths
                else "candidate removed solver.py"
            ),
            "artifact_sha256": (
                sha256_file(workspace / ARTIFACT_NAME)
                if (workspace / ARTIFACT_NAME).is_file()
                else None
            ),
            "duration_seconds": time.monotonic() - started,
            "budget": budget,
            "evaluated_at": utc_now(),
        }
        with (runtime_dir / "history.jsonl").open("a") as history:
            history.write(json.dumps(report, sort_keys=True) + "\n")
        return report
    case_results = []
    if tuple(metadata["case_names"]) != CASE_NAMES:
        raise RuntimeError("task case list differs from the pinned adapter contract")
    for name in CASE_NAMES:
        frozen_case = workspace / "cases" / name
        if sha256_file(frozen_case) != EXPECTED_CASE_SHA256[name]:
            raise RuntimeError(f"pinned task case changed: {name}")
        try:
            result = run_case_subprocess(
                workspace,
                upstream_root,
                name,
                int(metadata["case_timeout_seconds"]),
            )
        except subprocess.TimeoutExpired:
            result = {
                "case": name,
                "valid": False,
                "cost": None,
                "message": f"candidate exceeded {metadata['case_timeout_seconds']} seconds",
            }
        case_results.append(result)

    valid = all(item["valid"] for item in case_results)
    raw_total = sum(int(item["cost"]) for item in case_results if item["cost"] is not None)
    metric_value = raw_total if valid else INVALID_COST + raw_total
    report = {
        "schema_version": 1,
        "task_id": metadata["task_id"],
        "mode": mode,
        "valid": valid,
        "primary_metric": {
            "name": metadata["primary_metric"],
            "value": metric_value,
            "direction": metadata["direction"],
        },
        metadata["primary_metric"]: metric_value,
        "raw_total_cost": raw_total,
        "cases": case_results,
        "artifact_sha256": sha256_file(workspace / metadata["artifact_name"]),
        "duration_seconds": time.monotonic() - started,
        "budget": budget,
        "evaluated_at": utc_now(),
    }
    with (runtime_dir / "history.jsonl").open("a") as history:
        history.write(json.dumps(report, sort_keys=True) + "\n")
    return report


def case_command(args: argparse.Namespace) -> int:
    workspace = args.workspace.expanduser().absolute()
    upstream_root = args.upstream_root.expanduser().absolute()
    if args.case_name not in CASE_NAMES:
        raise ValueError(f"unknown case: {args.case_name}")
    report = evaluate_one_case(
        workspace,
        upstream_root / "operator_scheduling/program",
        workspace / "cases" / args.case_name,
        args.output,
    )
    print(json.dumps(report))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("--upstream-root", type=Path, required=True)
    materialize_parser.add_argument("--workspace", type=Path, required=True)

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--workspace", type=Path, required=True)
    evaluate_parser.add_argument("--upstream-root", type=Path, required=True)
    evaluate_parser.add_argument("--mode", choices=("public", "final"), default="public")
    evaluate_parser.add_argument("--output", type=Path)

    case_parser = subparsers.add_parser("_case")
    case_parser.add_argument("--workspace", type=Path, required=True)
    case_parser.add_argument("--upstream-root", type=Path, required=True)
    case_parser.add_argument("--case-name", required=True)
    case_parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "materialize":
        print(
            json.dumps(
                materialize_workspace(
                    args.upstream_root, args.workspace
                ),
                indent=2,
            )
        )
        return 0
    if args.command == "_case":
        return case_command(args)
    report = evaluate_workspace(args.workspace, args.upstream_root, args.mode)
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
