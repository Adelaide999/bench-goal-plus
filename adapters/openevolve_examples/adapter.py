"""Materialize and evaluate OpenEvolve example tasks without using its search controller."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bench_runtime_paths import temporary_directory  # noqa: E402


TASKS_PATH = Path(__file__).with_name("tasks.json")
WORKER_PATH = Path(__file__).with_name("worker.py")
CONTROLLER_PATH = ROOT / "scripts/openevolve_task.py"
START_MARKER = "# EVOLVE-BLOCK-START"
END_MARKER = "# EVOLVE-BLOCK-END"


class BudgetExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedTask:
    task_id: str
    upstream_root: Path
    upstream_commit: str
    source_dir: Path
    initial_program: Path
    evaluator: Path
    config: Path
    requirements: Path | None
    artifact_name: str
    profile: dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_catalog() -> dict[str, Any]:
    return json.loads(TASKS_PATH.read_text())


def list_catalog_tasks(task_set: str | None = None) -> list[dict[str, Any]]:
    catalog = load_catalog()
    tasks = catalog.get("tasks") or {}
    if task_set is None:
        task_ids = sorted(tasks)
    else:
        try:
            task_ids = list(catalog["task_sets"][task_set])
        except KeyError as error:
            raise KeyError(f"unknown OpenEvolve task set: {task_set}") from error
    missing = [task_id for task_id in task_ids if task_id not in tasks]
    if missing:
        raise RuntimeError(
            f"OpenEvolve task set {task_set!r} references unknown tasks: {missing}"
        )
    return [
        {
            "task_id": task_id,
            "source_dir": tasks[task_id]["source_dir"],
            "artifact_name": tasks[task_id]["artifact_name"],
            "profile": dict(tasks[task_id].get("profile") or {}),
        }
        for task_id in task_ids
    ]


def git_commit(repository: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"not a Git checkout: {repository}")
    return result.stdout.strip()


def git_branch(repository: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "symbolic-ref", "--short", "-q", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"OpenEvolve checkout must be on its managed branch: {repository}"
        )
    return result.stdout.strip()


def resolve_task(task_id: str, upstream_root: Path) -> ResolvedTask:
    catalog = load_catalog()
    if catalog.get("schema_version") != 2:
        raise RuntimeError("unsupported OpenEvolve task catalog schema")
    try:
        entry = catalog["tasks"][task_id]
    except KeyError as error:
        raise KeyError(f"unknown OpenEvolve example task: {task_id}") from error

    upstream_root = upstream_root.resolve()
    expected_branch = catalog["upstream"]["tracking_branch"]
    actual_branch = git_branch(upstream_root)
    actual_commit = git_commit(upstream_root)
    if actual_branch != expected_branch:
        raise RuntimeError(
            f"OpenEvolve branch mismatch: expected {expected_branch}, got {actual_branch}"
        )

    source_dir = upstream_root / entry["source_dir"]
    requirements_name = entry.get("requirements")
    requirements = (
        source_dir / requirements_name
        if isinstance(requirements_name, str) and requirements_name
        else None
    )
    profile = dict(entry.get("profile") or {})
    if profile.get("class") == "cpu_portable":
        unsupported_profile_keys = {
            key
            for key in ("gpu", "npu", "network", "external_software", "dataset")
            if profile.get(key)
        }
        if unsupported_profile_keys:
            raise RuntimeError(
                f"cpu_portable task {task_id} declares unsupported resources: "
                f"{sorted(unsupported_profile_keys)}"
            )
    task = ResolvedTask(
        task_id=task_id,
        upstream_root=upstream_root,
        upstream_commit=actual_commit,
        source_dir=source_dir,
        initial_program=source_dir / entry["initial_program"],
        evaluator=source_dir / entry["evaluator"],
        config=source_dir / entry["config"],
        requirements=requirements,
        artifact_name=entry["artifact_name"],
        profile=profile,
    )
    for required_path in (
        task.initial_program,
        task.evaluator,
        task.config,
    ):
        if not required_path.is_file():
            raise FileNotFoundError(required_path)
    if task.requirements is not None and not task.requirements.is_file():
        raise FileNotFoundError(task.requirements)
    return task


def split_evolve_block(code: str) -> tuple[str, str, str]:
    if code.count(START_MARKER) != 1 or code.count(END_MARKER) != 1:
        raise ValueError("candidate must contain exactly one EVOLVE-BLOCK")
    start = code.index(START_MARKER)
    block_start = code.index("\n", start) + 1
    end = code.index(END_MARKER, block_start)
    return code[:block_start], code[block_start:end], code[end:]


def run_worker(
    runtime_python: Path,
    command: str,
    arguments: list[str],
) -> dict[str, Any]:
    with temporary_directory(
        prefix="bench-openevolve-worker-",
        namespace="openevolve-worker",
    ) as temp_dir:
        output = temp_dir / "result.json"
        result = subprocess.run(
            [
                str(runtime_python),
                str(WORKER_PATH),
                command,
                *arguments,
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not output.is_file():
            raise RuntimeError(
                "OpenEvolve worker failed: "
                f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
            )
        payload = json.loads(output.read_text())
        if result.stdout:
            payload["worker_stdout"] = result.stdout
        if result.stderr:
            payload["worker_stderr"] = result.stderr
        return payload


def describe_task(task: ResolvedTask, runtime_python: Path) -> dict[str, Any]:
    return run_worker(
        runtime_python,
        "describe",
        [
            "--upstream-root",
            str(task.upstream_root),
            "--config",
            str(task.config),
        ],
    )


def init_git(workspace: Path) -> str:
    subprocess.run(
        ["git", "init", "-b", "main", str(workspace)], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "config",
            "user.email",
            "bench-goal-plus@example.invalid",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(workspace), "config", "user.name", "bench-goal-plus"],
        check=True,
    )
    subprocess.run(["git", "-C", str(workspace), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-m", "materialize OpenEvolve example"],
        check=True,
        capture_output=True,
    )
    return git_commit(workspace)


def render_evaluate_wrapper() -> str:
    return (
        "#!/usr/bin/env python3\n"
        "import subprocess\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        f"CONTROLLER = Path({json.dumps(str(CONTROLLER_PATH))})\n"
        "raise SystemExit(subprocess.call([sys.executable, str(CONTROLLER), "
        "'evaluate', '--workspace', str(Path(__file__).resolve().parent), '--mode', 'public']))\n"
    )


def render_goal_plus_verifier(primary_metric: str) -> str:
    return (
        "#!/usr/bin/env python3\n"
        '"""Controller-owned Goal Plus ranking wrapper; do not edit."""\n'
        "import json\n"
        "import math\n"
        "import subprocess\n"
        "import sys\n\n"
        "completed = subprocess.run(\n"
        "    [sys.executable, 'evaluate.py'], capture_output=True, text=True\n"
        ")\n"
        "if completed.returncode != 0:\n"
        "    sys.stderr.write(completed.stderr)\n"
        "    raise SystemExit(completed.returncode)\n"
        "report = json.loads(completed.stdout)\n"
        "metric = report.get('primary_metric') or {}\n"
        "value = metric.get('value')\n"
        "if report.get('valid') is not True or not isinstance(value, (int, float)):\n"
        "    raise SystemExit('official evaluator returned no valid numeric primary metric')\n"
        "value = float(value)\n"
        "if not math.isfinite(value):\n"
        "    raise SystemExit('official evaluator returned a non-finite primary metric')\n"
        f"print(json.dumps({{{primary_metric!r}: value, 'valid': True}}))\n"
    )


def materialize_workspace(
    task: ResolvedTask,
    workspace: Path,
    runtime_python: Path,
    max_evaluator_calls: int | None,
    reserved_final_calls: int,
    description: dict[str, Any] | None = None,
    controller_runtime_dir: Path | None = None,
) -> dict[str, Any]:
    if reserved_final_calls < 1:
        raise ValueError("at least one final evaluator call must be reserved")
    if max_evaluator_calls is not None and max_evaluator_calls <= reserved_final_calls:
        raise ValueError(
            "max evaluator calls must leave at least one public and one final call"
        )
    # Keep the venv launcher path intact. Path.resolve() follows its symlink to the
    # base interpreter and silently drops the venv's site-packages.
    runtime_python = runtime_python.expanduser().absolute()
    if not runtime_python.is_file():
        raise FileNotFoundError(runtime_python)
    description = description or describe_task(task, runtime_python)
    seed = task.initial_program.read_text()
    prefix, _, suffix = split_evolve_block(seed)
    system_message = description["prompt"]["system_message"]
    evaluation = description["evaluation"]
    profile_modules = list(task.profile.get("python_modules") or [])
    portable_constraint = ""
    if task.profile.get("class") == "cpu_portable":
        allowed = ", ".join(profile_modules) if profile_modules else "the Python standard library"
        portable_constraint = (
            "- This is a portable CPU-only task. Do not use GPU/NPU APIs, network access, "
            "external executables, downloaded datasets, or undeclared Python packages. "
            f"The available task dependencies are: {allowed}.\n"
        )
    if max_evaluator_calls is None:
        evaluation_budget = (
            "Run `python3 evaluate.py` for public feedback. Public evaluator calls are not "
            "hard-capped; work within the experiment controller's wall-clock deadline. "
            f"The controller reserves {reserved_final_calls} final evaluator call."
        )
    else:
        evaluation_budget = (
            "Run `python3 evaluate.py` for public feedback. At most "
            f"{max_evaluator_calls - reserved_final_calls} public evaluator calls are available; "
            f"{reserved_final_calls} call is reserved for the controller's final evaluation."
        )

    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    runtime_dir = (
        controller_runtime_dir.expanduser().absolute()
        if controller_runtime_dir is not None
        else workspace / ".bench-runtime"
    )
    runtime_dir.mkdir(parents=True, exist_ok=False)
    (workspace / task.artifact_name).write_text(seed)
    (workspace / "TASK.md").write_text(
        "# Objective\n\n"
        f"{system_message.strip()}\n\n"
        "# Success criterion\n\n"
        f"Maximize `{evaluation['primary_metric']}` using the controller-owned OpenEvolve evaluator. "
        "Preserve correctness and make a concrete improvement over the seed.\n\n"
        "# Hard constraints\n\n"
        f"- Only edit `{task.artifact_name}`, and only inside its single `EVOLVE-BLOCK`.\n"
        "- Do not modify the evaluator helper, Goal Plus verifier wrapper, task metadata, Git configuration, or files outside this workspace.\n"
        "- Do not use the network.\n"
        f"{portable_constraint}"
        f"- {evaluation_budget}\n"
        "- Stop with the best verified candidate left in the artifact file.\n"
    )
    (workspace / "AGENTS.md").write_text(
        "# OpenEvolve example task rules\n\n"
        f"- Only edit `{task.artifact_name}` inside `EVOLVE-BLOCK-START/END`.\n"
        "- Run `python3 evaluate.py` to obtain official public feedback.\n"
        "- Do not edit `evaluate.py`, `.goal-plus-verifiers/`, `task.json`, `TASK.md`, `AGENTS.md`, or `.gitignore`.\n"
        "- Do not inspect parent directories, evaluator source, credentials, or network resources.\n"
        f"{portable_constraint}"
        "- Leave the best verified candidate in the artifact file.\n"
    )
    (workspace / "evaluate.py").write_text(render_evaluate_wrapper())
    verifier_dir = workspace / ".goal-plus-verifiers"
    verifier_dir.mkdir()
    verifier_path = verifier_dir / "primary_metric.py"
    verifier_path.write_text(render_goal_plus_verifier(evaluation["primary_metric"]))
    (workspace / ".gitignore").write_text(".bench-runtime/\n__pycache__/\n")

    task_metadata = {
        "schema_version": 1,
        "adapter": "openevolve-example",
        "task_id": task.task_id,
        "artifact_name": task.artifact_name,
        "upstream_root": str(task.upstream_root),
        "upstream_commit": task.upstream_commit,
        "config_path": str(task.config),
        "evaluator_path": str(task.evaluator),
        "requirements_path": (
            str(task.requirements) if task.requirements is not None else None
        ),
        "execution_profile": task.profile,
        "runtime_python": str(runtime_python),
        # Candidate Git worktrees do not contain ignored runtime state. Keep every
        # lineage on one controller-owned ledger in the materialized source workspace.
        "controller_runtime_dir": str(runtime_dir),
        "primary_metric": evaluation["primary_metric"],
        "direction": evaluation["direction"],
        "timeout_seconds": evaluation["timeout_seconds"],
        "cascade_evaluation": evaluation["cascade_evaluation"],
        "parallel_evaluations": evaluation["parallel_evaluations"],
        "goal_plus_verifier": str(verifier_path.relative_to(workspace)),
        "prompt_sha256": sha256_text(system_message),
        "fixed_prefix_sha256": sha256_text(prefix),
        "fixed_suffix_sha256": sha256_text(suffix),
        "max_evaluator_calls": max_evaluator_calls,
        "reserved_final_calls": reserved_final_calls,
    }
    (workspace / "task.json").write_text(json.dumps(task_metadata, indent=2) + "\n")

    budget = {
        "schema_version": 1,
        "max_evaluator_calls": max_evaluator_calls,
        "reserved_final_calls": reserved_final_calls,
        "total_claimed": 0,
        "public_claimed": 0,
        "final_claimed": 0,
    }
    (runtime_dir / "budget.json").write_text(json.dumps(budget, indent=2) + "\n")
    (runtime_dir / "budget.lock").touch()
    workspace_commit = init_git(workspace)
    return {
        "workspace": str(workspace),
        "workspace_commit": workspace_commit,
        **task_metadata,
    }


def claim_ticket(runtime_dir: Path, mode: str) -> tuple[int, dict[str, Any]]:
    budget_path = runtime_dir / "budget.json"
    lock_path = runtime_dir / "budget.lock"
    with lock_path.open("r+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        budget = json.loads(budget_path.read_text())
        if mode == "public":
            maximum = budget["max_evaluator_calls"]
            public_limit = (
                maximum - budget["reserved_final_calls"]
                if maximum is not None
                else None
            )
            if public_limit is not None and budget["public_claimed"] >= public_limit:
                raise BudgetExhausted("public evaluator budget exhausted")
            budget["public_claimed"] += 1
        elif mode == "final":
            if budget["final_claimed"] >= budget["reserved_final_calls"]:
                raise BudgetExhausted("reserved final evaluator budget exhausted")
            budget["final_claimed"] += 1
        else:
            raise ValueError(f"unsupported evaluation mode: {mode}")
        budget["total_claimed"] += 1
        call_index = budget["total_claimed"]
        budget_path.write_text(json.dumps(budget, indent=2) + "\n")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return call_index, budget


def validate_candidate(candidate: str, metadata: dict[str, Any]) -> str | None:
    try:
        prefix, _, suffix = split_evolve_block(candidate)
    except ValueError as error:
        return str(error)
    if sha256_text(prefix) != metadata["fixed_prefix_sha256"]:
        return "content before EVOLVE-BLOCK changed"
    if sha256_text(suffix) != metadata["fixed_suffix_sha256"]:
        return "content after EVOLVE-BLOCK changed"
    return None


def append_history(runtime_dir: Path, payload: dict[str, Any]) -> None:
    lock_path = runtime_dir / "budget.lock"
    with lock_path.open("r+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        with (runtime_dir / "history.jsonl").open("a") as history:
            history.write(json.dumps(payload) + "\n")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def evaluate_workspace(workspace: Path, mode: str) -> dict[str, Any]:
    workspace = workspace.resolve()
    metadata = json.loads((workspace / "task.json").read_text())
    runtime_dir = Path(
        metadata.get("controller_runtime_dir", workspace / ".bench-runtime")
    )
    call_index, budget = claim_ticket(runtime_dir, mode)
    artifact = workspace / metadata["artifact_name"]
    candidate = artifact.read_text()
    candidate_sha256 = sha256_text(candidate)
    validation_error = validate_candidate(candidate, metadata)
    started = time.monotonic()

    if validation_error:
        result: dict[str, Any] = {
            "schema_version": 1,
            "valid": False,
            "primary_metric": {
                "name": metadata["primary_metric"],
                "value": None,
                "direction": metadata["direction"],
            },
            "raw_metrics": {"error": validation_error},
            "artifacts": {"failure_stage": "editable_region_validation"},
            "elapsed_seconds": time.monotonic() - started,
        }
    else:
        result = run_worker(
            Path(metadata["runtime_python"]),
            "evaluate",
            [
                "--upstream-root",
                metadata["upstream_root"],
                "--config",
                metadata["config_path"],
                "--evaluator",
                metadata["evaluator_path"],
                "--artifact",
                str(artifact),
            ],
        )

    primary_value = result["primary_metric"].get("value")
    if (
        isinstance(primary_value, bool)
        or not isinstance(primary_value, (int, float))
        or not math.isfinite(primary_value)
    ):
        primary_value = -1e300 if metadata["direction"] == "maximize" else 1e300
    payload = {
        "schema_version": 1,
        "benchmark": "openevolve-examples",
        "task_id": metadata["task_id"],
        "mode": mode,
        "call_index": call_index,
        "budget": budget,
        "candidate_sha256": candidate_sha256,
        "upstream_commit": metadata["upstream_commit"],
        "evaluated_at": utc_now(),
        **result,
        # Goal Plus ranking verifiers require a finite top-level metric in the
        # final JSON object; raw/native metrics remain preserved above.
        metadata["primary_metric"]: primary_value,
    }
    append_history(runtime_dir, payload)
    return payload


def sanitize_evidence_text(text: str) -> str:
    home = str(Path.home())
    return text.replace(home, "<USER_HOME>")


def archive_workspace(workspace: Path, run_dir: Path) -> dict[str, Any]:
    workspace = workspace.resolve()
    run_dir = run_dir.resolve()
    metadata = json.loads((workspace / "task.json").read_text())
    history_path = (
        Path(metadata.get("controller_runtime_dir", workspace / ".bench-runtime"))
        / "history.jsonl"
    )
    history = [
        json.loads(line) for line in history_path.read_text().splitlines() if line
    ]
    if not history:
        raise RuntimeError(
            "cannot archive an OpenEvolve task without evaluator history"
        )
    final_results = [item for item in history if item["mode"] == "final"]
    if len(final_results) != 1:
        raise RuntimeError("archive requires exactly one controller final evaluation")
    final_result = final_results[0]
    candidate = (workspace / metadata["artifact_name"]).read_text()
    if sha256_text(candidate) != final_result["candidate_sha256"]:
        raise RuntimeError("final candidate hash differs from controller evaluation")

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "candidate.py").write_text(candidate)
    sanitized_history = "\n".join(
        sanitize_evidence_text(json.dumps(item)) for item in history
    )
    (run_dir / "evaluation-history.jsonl").write_text(sanitized_history + "\n")

    for filename in (
        "events.jsonl",
        "stderr.log",
        "final-message.txt",
        "run-manifest.json",
        "final-eval.json",
    ):
        path = run_dir / filename
        if path.is_file():
            path.write_text(sanitize_evidence_text(path.read_text()))

    manifest_path = run_dir / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    initial_result = history[0]
    public_results = [item for item in history if item["mode"] == "public"]
    numeric_public_scores = [
        item["primary_metric"]["value"]
        for item in public_results
        if isinstance(item["primary_metric"].get("value"), (int, float))
    ]
    initial_score = initial_result["primary_metric"]["value"]
    final_score = final_result["primary_metric"]["value"]
    score_gain = (
        final_score - initial_score
        if isinstance(initial_score, (int, float))
        and isinstance(final_score, (int, float))
        else None
    )
    runtime_version = subprocess.run(
        [metadata["runtime_python"], "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    summary = {
        "schema_version": 1,
        "benchmark": "openevolve-examples",
        "task_id": metadata["task_id"],
        "method": "plain-codex",
        "upstream_commit": metadata["upstream_commit"],
        "workspace_initial_commit": manifest.get("workspace_commit"),
        "prompt_sha256": metadata["prompt_sha256"],
        "primary_metric": metadata["primary_metric"],
        "direction": metadata["direction"],
        "seed_score": initial_score,
        "best_public_score": (
            max(numeric_public_scores) if numeric_public_scores else None
        ),
        "final_score": final_score,
        "absolute_gain": score_gain,
        "relative_gain": (
            score_gain / abs(initial_score)
            if score_gain is not None and initial_score
            else None
        ),
        "valid": final_result["valid"],
        "candidate_sha256": final_result["candidate_sha256"],
        "evaluator_calls": final_result["budget"],
        "codex": {
            "version": manifest.get("codex_version"),
            "model": manifest.get("model"),
            "model_identity_coverage": (
                "missing" if manifest.get("model") is None else "explicit"
            ),
            "duration_seconds": manifest.get("duration_seconds"),
            "usage": manifest.get("usage"),
        },
        "environment": {
            "runtime_python": (
                runtime_version.stdout or runtime_version.stderr
            ).strip(),
        },
        "evidence": {
            "candidate": "candidate.py",
            "evaluation_history": "evaluation-history.jsonl",
            "final_evaluation": "final-eval.json",
            "codex_manifest": "run-manifest.json",
            "codex_events": "events.jsonl",
            "codex_final_message": "final-message.txt",
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary
