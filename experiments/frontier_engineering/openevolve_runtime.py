"""Paper-protocol OpenEvolve execution for Frontier-Engineering cells."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from bench_artifacts import utc_now
from bench_runtime_paths import configure_temp_environment

from . import task_adapter
from .config import UPSTREAM_ROOT, V1_LITE_TASKS, write_json


PAPER_BATCH_CONFIG = UPSTREAM_ROOT / "frontier_eval/conf/batch/v1_lite.yaml"
ALGORITHM_CONFIG = UPSTREAM_ROOT / "frontier_eval/conf/algorithm/openevolve.yaml"
LLM_CONFIG = UPSTREAM_ROOT / "frontier_eval/conf/llm/openai_compatible.yaml"
DRIVER_PYTHON = UPSTREAM_ROOT / ".venvs/frontier-eval-driver/bin/python"
PAPER_ITERATIONS = 100
PAPER_RANDOM_SEED = 42
PAPER_TEMPERATURE = 0.7
PAPER_MAX_TOKENS = 32768
PAPER_LLM_TIMEOUT_SECONDS = 60
PAPER_LLM_RETRIES = 3
PAPER_LLM_RETRY_DELAY_SECONDS = 5
PAPER_PARALLEL_EVALUATIONS = 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _combined_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(UPSTREAM_ROOT)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(UPSTREAM_ROOT), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def protocol_contract(profile: dict[str, Any]) -> dict[str, Any]:
    iterations = int(profile["iterations"])
    protocol_kind = str(profile["openevolve_protocol"])
    if protocol_kind == "paper" and iterations != PAPER_ITERATIONS:
        raise ValueError(
            f"paper protocol requires {PAPER_ITERATIONS} iterations, got {iterations}"
        )
    if protocol_kind not in {"paper", "smoke"}:
        raise ValueError(f"unsupported OpenEvolve protocol: {protocol_kind}")
    config_paths = [PAPER_BATCH_CONFIG, ALGORITHM_CONFIG, LLM_CONFIG]
    for path in config_paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    return {
        "name": f"frontier-engineering-v1-openevolve-{protocol_kind}-{iterations}",
        "kind": protocol_kind,
        "publication_scope": (
            "Experiment 1 search protocol; model identity is the campaign model, "
            "not a claim that this model appeared in the paper"
            if protocol_kind == "paper"
            else "Diagnostic short-budget run using the paper protocol defaults; not a paper result"
        ),
        "iterations": iterations,
        "initial_program_evaluations": 1,
        "random_seed": PAPER_RANDOM_SEED,
        "temperature": PAPER_TEMPERATURE,
        "max_tokens": PAPER_MAX_TOKENS,
        "llm_timeout_seconds": PAPER_LLM_TIMEOUT_SECONDS,
        "llm_retries": PAPER_LLM_RETRIES,
        "llm_retry_delay_seconds": PAPER_LLM_RETRY_DELAY_SECONDS,
        "parallel_evaluations": PAPER_PARALLEL_EVALUATIONS,
        "batch_task_parallelism": 4,
        "task_parallelism_for_this_campaign": 1,
        "selection": (
            f"best feasible combined_score within {iterations} evolution iterations"
        ),
        "config_files": [str(path) for path in config_paths],
        "config_sha256": _combined_sha256(config_paths),
    }


def build_command(
    profile: dict[str, Any], *, task_id: str, output_dir: Path
) -> list[str]:
    task = V1_LITE_TASKS[task_id]
    contract = protocol_contract(profile)
    command = [
        str(DRIVER_PYTHON),
        "-m",
        "frontier_eval",
        "task=unified",
        f"task.benchmark={task_id}",
        "algorithm=openevolve",
        f"algorithm.iterations={contract['iterations']}",
        "algorithm.checkpoint_interval=25",
        "algorithm.max_code_length=20000",
        f"algorithm.oe.evaluator.timeout={task.evaluator_timeout_seconds}",
        "+algorithm.oe.evaluator.parallel_evaluations=1",
        "+algorithm.oe.random_seed=42",
        "llm=openai_compatible",
        f"llm.model={profile['model']}",
        "llm.temperature=0.7",
        "llm.max_tokens=32768",
        "llm.timeout=60",
        "llm.retries=3",
        "llm.retry_delay=5",
        f"+algorithm.oe.llm.reasoning_effort={profile['reasoning_effort']}",
        f"run.output_dir={output_dir}",
    ]
    if task.runtime_python_env:
        command.append(f"task.runtime.python_path=uv-env:{task.runtime_python_env}")
    elif task.runtime_env != "frontier-eval-driver":
        command.append(f"task.runtime.env_name={task.runtime_env}")
    return command


def prepare_cell(
    run_dir: Path,
    *,
    task_id: str,
    seed: int,
    profile: dict[str, Any],
) -> None:
    if run_dir.exists():
        raise FileExistsError(run_dir)
    run_dir.mkdir(parents=True)
    task_adapter.configure_task(task_id)
    materialized = task_adapter.materialize_workspace(
        UPSTREAM_ROOT, run_dir / "workspace"
    )
    contract = protocol_contract(profile)
    output_dir = run_dir / "native-output"
    manifest = {
        "schema_version": 1,
        "status": "prepared",
        "prepared_at": utc_now(),
        "method": "openevolve",
        "model": profile["model"],
        "reasoning_effort": profile["reasoning_effort"],
        "task_id": task_id,
        "seed": seed,
        "budget": {
            "budget_kind": "fixed_openevolve_iterations",
            "iterations_ceiling": contract["iterations"],
            "wall_time_seconds": profile["wall_time_seconds"],
            "wall_time_role": "operational hard ceiling; iterations are authoritative",
            "concurrency": 1,
            "soft_closeout_seconds": profile["soft_closeout_seconds"],
            "hard_kill_grace_seconds": profile["hard_kill_grace_seconds"],
            "evaluator_call_cap": None,
        },
        "task": {
            "artifact_name": materialized["artifact_name"],
            "primary_metric": materialized["primary_metric"],
            "direction": materialized["direction"],
            "upstream_tracking_branch": "main",
            "upstream_commit": materialized["upstream_commit"],
            "initial_program": str(
                UPSTREAM_ROOT
                / "benchmarks"
                / task_id
                / materialized["artifact_source_relative"]
            ),
            "initial_program_sha256": materialized["seed_sha256"],
            "evaluator": materialized["evaluator"],
            "evaluator_sha256": materialized["evaluator_sha256"],
            "execution_profile": "frontier-engineering-upstream-openevolve",
        },
        "environment": {
            "frontier_engineering_root": str(UPSTREAM_ROOT),
            "frontier_engineering_branch": _git_value(
                "symbolic-ref", "--short", "HEAD"
            ),
            "frontier_engineering_commit": _git_value("rev-parse", "HEAD"),
            "runtime_python": str(DRIVER_PYTHON),
            "openevolve_version": "0.2.26",
            "api_base_env": "OPENAI_BASE_URL",
            "api_key_env": "OPENAI_API_KEY",
            "wire_api": "openai-completions",
        },
        "protocol": contract,
        "workspace": str(run_dir / "workspace"),
        "workspaces": [str(run_dir / "workspace")],
        "workspace_commit": materialized["workspace_commit"],
        "output_dir": str(output_dir),
        "command": build_command(profile, task_id=task_id, output_dir=output_dir),
        "secret_policy": "provider endpoint and credential values are inherited only",
    }
    write_json(run_dir / "experiment.json", manifest)


def _history_entries(output_dir: Path) -> list[dict[str, Any]]:
    index_path = output_dir / "openevolve/history/index.jsonl"
    if not index_path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def _history_metrics(output_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    iteration = int(entry.get("iteration_found") or 0)
    program_id = str(entry["id"])
    path = (
        output_dir
        / "openevolve/history"
        / f"iter_{iteration:06d}__{program_id}"
        / "metrics.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _evaluation_from_history(
    metrics: dict[str, Any], *, task_id: str, seed_sha256: str
) -> dict[str, Any]:
    value = metrics.get("combined_score")
    valid = bool(
        metrics.get("valid") in {True, 1, 1.0}
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    )
    return {
        "schema_version": 1,
        "benchmark": "frontier-engineering",
        "suite": "v1-lite",
        "task_id": task_id,
        "mode": "seed",
        "valid": valid,
        "primary_metric": {
            "name": "combined_score",
            "value": float(value) if valid else -1e18,
            "direction": "maximize",
        },
        "combined_score": float(value) if valid else -1e18,
        "raw_metrics": metrics,
        "artifact_sha256": seed_sha256,
        "source": "upstream OpenEvolve initial-program evaluation inside the run",
    }


def iteration_progress(run_dir: Path) -> dict[str, int] | None:
    manifest_path = run_dir / "experiment.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("method") != "openevolve":
        return None
    entries = _history_entries(Path(manifest["output_dir"]))
    initial = sum(1 for entry in entries if not entry.get("parent_id"))
    return {
        "requested": int(manifest["budget"]["iterations_ceiling"]),
        "completed_candidates": max(0, len(entries) - initial),
        "initial_programs": initial,
    }


def _run_upstream(
    command: list[str],
    *,
    run_dir: Path,
    wall_time_seconds: int,
    hard_kill_grace_seconds: int,
) -> dict[str, Any]:
    environment = configure_temp_environment(os.environ.copy())
    api_base = environment.get("OPENAI_BASE_URL")
    if not api_base or not environment.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OpenEvolve requires OPENAI_BASE_URL and OPENAI_API_KEY"
        )
    environment["OPENAI_API_BASE"] = api_base
    environment["FRONTIER_ENGINEERING_ROOT"] = str(UPSTREAM_ROOT)
    environment["PYTHONNOUSERSITE"] = "1"
    started_at = utc_now()
    started = time.monotonic()
    deadline_reached = False
    hard_killed = False
    with (
        (run_dir / "stdout.log").open("w") as stdout,
        (run_dir / "stderr.log").open("w") as stderr,
    ):
        process = subprocess.Popen(
            command,
            cwd=UPSTREAM_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            text=True,
        )
        try:
            process.wait(timeout=wall_time_seconds)
        except subprocess.TimeoutExpired:
            deadline_reached = True
            process.terminate()
            try:
                process.wait(timeout=hard_kill_grace_seconds)
            except subprocess.TimeoutExpired:
                hard_killed = True
                process.kill()
                process.wait()
    return {
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_seconds": time.monotonic() - started,
        "returncode": process.returncode,
        "deadline_reached": deadline_reached,
        "hard_killed": hard_killed,
        "hard_kill_grace_seconds": hard_kill_grace_seconds,
        "command": command,
    }


def execute_cell(run_dir: Path) -> int:
    manifest_path = run_dir / "experiment.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "prepared":
        raise RuntimeError(f"run is not prepared: {manifest.get('status')}")
    if _git_value("rev-parse", "HEAD") != manifest["task"]["upstream_commit"]:
        raise RuntimeError("pinned Frontier-Engineering checkout changed")
    manifest["status"] = "running"
    manifest["execution_started_at"] = utc_now()
    write_json(manifest_path, manifest)

    run_started = time.monotonic()
    control = _run_upstream(
        list(manifest["command"]),
        run_dir=run_dir,
        wall_time_seconds=int(manifest["budget"]["wall_time_seconds"]),
        hard_kill_grace_seconds=int(
            manifest["budget"]["hard_kill_grace_seconds"]
        ),
    )
    output_dir = Path(manifest["output_dir"])
    entries = _history_entries(output_dir)
    initial_entries = [entry for entry in entries if not entry.get("parent_id")]
    evolved_entries = [entry for entry in entries if entry.get("parent_id")]
    if len(initial_entries) == 1:
        seed_evaluation = _evaluation_from_history(
            _history_metrics(output_dir, initial_entries[0]),
            task_id=manifest["task_id"],
            seed_sha256=manifest["task"]["initial_program_sha256"],
        )
        write_json(run_dir / "seed-eval.json", seed_evaluation)

    best_dir = output_dir / "openevolve/best"
    artifact_name = str(manifest["task"]["artifact_name"])
    best_program = best_dir / f"best_program{Path(artifact_name).suffix}"
    best_info_path = best_dir / "best_program_info.json"
    best_info = (
        json.loads(best_info_path.read_text(encoding="utf-8"))
        if best_info_path.is_file()
        else {}
    )
    final: dict[str, Any] = {}
    if best_program.is_file():
        workspace = Path(manifest["workspace"])
        shutil.copy2(best_program, workspace / artifact_name)
        shutil.copy2(best_program, run_dir / artifact_name)
        task_adapter.configure_task(manifest["task_id"])
        final = task_adapter.evaluate_workspace(workspace, UPSTREAM_ROOT, "final")
        write_json(run_dir / "final-eval.json", final)

    requested = int(manifest["budget"]["iterations_ceiling"])
    exact_iterations = len(evolved_entries) == requested and len(initial_entries) == 1
    final_claims = int((final.get("budget") or {}).get("total_claimed") or 0)
    control.update(
        {
            "total_duration_seconds": time.monotonic() - run_started,
            "native_best": best_info,
            "iterations": {
                "requested": requested,
                "completed_candidates": len(evolved_entries),
                "initial_programs": len(initial_entries),
                "exact_match": exact_iterations,
            },
            "evaluator_calls": {
                "successful_upstream_evaluations": len(entries),
                "upstream_initial": len(initial_entries),
                "upstream_evolved_candidates": len(evolved_entries),
                "controller_final_claimed": final_claims,
                "successful_evaluation_lower_bound": len(entries) + final_claims,
                "coverage": (
                    "successful upstream history programs plus controller final; "
                    "internal evaluator retries are not exposed"
                ),
            },
            "usage": {"coverage": "missing: upstream OpenEvolve does not persist token usage"},
            "telemetry_coverage": {
                "iterations": "exact successful candidates audited from upstream history",
                "evaluator_calls": "successful lower bound; internal retries unavailable",
                "tokens": "missing: upstream client does not persist usage",
            },
        }
    )
    incomplete: list[str] = []
    if control["returncode"] != 0:
        incomplete.append(f"upstream OpenEvolve exited {control['returncode']}")
    if control["deadline_reached"]:
        incomplete.append("operational wall-clock ceiling was reached")
    if not exact_iterations:
        incomplete.append(
            f"expected 1 initial + {requested} evolved candidates, observed "
            f"{len(initial_entries)} + {len(evolved_entries)}"
        )
    if not best_program.is_file():
        incomplete.append("upstream best program was not saved")
    if final.get("valid") is not True:
        incomplete.append("controller final evaluator did not return a valid score")
    if incomplete:
        control["result_incomplete_reason"] = "; ".join(incomplete)
        manifest["status"] = "incomplete"
    else:
        manifest["status"] = "finished"
    manifest["execution"] = control
    manifest["execution_finished_at"] = utc_now()
    write_json(manifest_path, manifest)
    return 0 if manifest["status"] == "finished" else 2
