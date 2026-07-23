#!/usr/bin/env python3
"""Provision, launch, monitor, stop, and summarize EdgeBench campaigns."""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bench_runtime_paths import configure_temp_environment, ensure_temp_root  # noqa: E402


EDGE_ROOT = ROOT / "third_party" / "edgebench"
GOAL_PLUS_ROOT = ROOT / "third_party" / "goal-plus"
TASKS_DIR = EDGE_ROOT / "tasks"
PROFILE_DIR = ROOT / "experiments" / "edgebench" / "profiles"
RUNS_ROOT = ROOT / "runs" / "edgebench"
UPSTREAM_MANIFEST = ROOT / "environment" / "upstreams.json"
VENV = ROOT / ".bench-env" / "venv"
VENV_BIN = VENV / ("Scripts" if sys.platform == "win32" else "bin")
VENV_PYTHON = VENV_BIN / ("python.exe" if sys.platform == "win32" else "python")
SFORGE = VENV_BIN / ("sforge.exe" if sys.platform == "win32" else "sforge")

METHODS = {
    "plain-codex": {
        "agent": "codex",
        "outer_replicas": "concurrency",
        "inner_search": False,
    },
    "goal-plus-codex": {
        "agent": "codex-goal-plus",
        "outer_replicas": 1,
        "inner_search": True,
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def campaign_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def git_head(path: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def git_branch(path: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(path), "symbolic-ref", "--short", "-q", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def git_dirty(path: Path) -> bool | None:
    completed = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(completed.stdout.strip()) if completed.returncode == 0 else None


def upstream_entry(name: str) -> dict[str, Any]:
    manifest = read_json(UPSTREAM_MANIFEST)
    return dict(manifest["upstreams"][name])


def load_profile(value: str | Path) -> tuple[Path, dict[str, Any]]:
    candidate = Path(value)
    if not candidate.suffix:
        candidate = PROFILE_DIR / f"{candidate.name}.json"
    elif not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(f"EdgeBench profile not found: {candidate}")
    profile = read_json(candidate)
    if profile.get("schema_version") != 1:
        raise ValueError("unsupported EdgeBench profile schema")
    for key in (
        "id",
        "dataset_repository",
        "dataset_revision",
        "task_ids",
        "methods",
        "model",
        "wall_time_seconds",
        "concurrency",
    ):
        if key not in profile:
            raise ValueError(f"EdgeBench profile is missing {key!r}")
    unknown = set(profile["methods"]) - set(METHODS)
    if unknown:
        raise ValueError("unknown EdgeBench method(s): " + ", ".join(sorted(unknown)))
    if int(profile["wall_time_seconds"]) < 1 or int(profile["concurrency"]) < 1:
        raise ValueError("wall_time_seconds and concurrency must be positive")
    return candidate, profile


def campaign_dir(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        direct = (ROOT / candidate).resolve()
        candidate = direct if direct.is_dir() else (RUNS_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()
    try:
        candidate.relative_to(RUNS_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"campaign must be under {RUNS_ROOT}") from exc
    if not (candidate / "campaign.json").is_file():
        raise FileNotFoundError(f"campaign.json not found in {candidate}")
    return candidate


def portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return resolved.name


def portable_command(command: Iterable[str]) -> list[str]:
    replacements = (
        (str(ROOT.resolve()), "<bench-goal-plus>"),
        (str(Path.home().resolve()), "<home>"),
    )
    result: list[str] = []
    for argument in command:
        clean = str(argument)
        for source, replacement in replacements:
            clean = clean.replace(source, replacement)
        result.append(clean)
    return result


def run_capture(command: list[str], *, env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return {"returncode": 127, "stdout": "", "stderr": str(exc)}
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def task_config(task_id: str) -> dict[str, Any]:
    path = TASKS_DIR / f"{task_id}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"task definition missing: {path}; run provision first"
        )
    return read_json(path)


def task_images(task_id: str) -> tuple[str, str]:
    config = task_config(task_id)
    return (
        f"edgebench.work.{task_id}:{config['work']['image_tag']}",
        f"edgebench.judge.{task_id}:{config['judge']['image_tag']}",
    )


def dataset_revision(task_id: str) -> str | None:
    metadata = TASKS_DIR / ".cache" / "huggingface" / "download" / f"{task_id}.json.metadata"
    if not metadata.is_file():
        return None
    lines = metadata.read_text(encoding="utf-8").splitlines()
    return lines[0].strip() if lines else None


def ensure_local_task_exclude() -> None:
    """Keep fetched task data out of managed-source dirty-state checks."""

    exclude = EDGE_ROOT / ".git" / "info" / "exclude"
    if not exclude.is_file():
        return
    lines = exclude.read_text(encoding="utf-8").splitlines()
    if "tasks/" not in lines:
        exclude.write_text(
            "\n".join([*lines, "tasks/"]).rstrip() + "\n",
            encoding="utf-8",
        )


def provision(profile: dict[str, Any]) -> int:
    if not SFORGE.is_file():
        raise FileNotFoundError("SForge is not installed; run repro_env.py bootstrap --only edgebench")
    ensure_local_task_exclude()
    env = dict(os.environ)
    configure_temp_environment(env)
    fetch = [
        str(SFORGE),
        "--tasks-dir",
        str(TASKS_DIR),
        "fetch-tasks",
        "--repo",
        str(profile["dataset_repository"]),
        "--revision",
        str(profile["dataset_revision"]),
    ]
    completed = subprocess.run(fetch, cwd=ROOT, env=env, check=False)
    if completed.returncode != 0:
        return completed.returncode
    pull = [
        str(SFORGE),
        "--tasks-dir",
        str(TASKS_DIR),
        "pull",
        "--task",
        *[str(task) for task in profile["task_ids"]],
        "--registry",
        str(profile["registry"]),
    ]
    return subprocess.run(pull, cwd=ROOT, env=env, check=False).returncode


def doctor_payload(profile: dict[str, Any]) -> dict[str, Any]:
    expected_edge = upstream_entry("edgebench")["tracking_branch"]
    expected_goal = upstream_entry("goal_plus")["tracking_branch"]
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, **details: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), **details})

    add(
        "checkout:edgebench",
        git_branch(EDGE_ROOT) == expected_edge and git_dirty(EDGE_ROOT) is False,
        expected_branch=expected_edge,
        actual_branch=git_branch(EDGE_ROOT),
        actual_commit=git_head(EDGE_ROOT),
        dirty=git_dirty(EDGE_ROOT),
    )
    add(
        "checkout:goal-plus",
        git_branch(GOAL_PLUS_ROOT) == expected_goal
        and git_dirty(GOAL_PLUS_ROOT) is False,
        expected_branch=expected_goal,
        actual_branch=git_branch(GOAL_PLUS_ROOT),
        actual_commit=git_head(GOAL_PLUS_ROOT),
        dirty=git_dirty(GOAL_PLUS_ROOT),
    )
    add("entrypoint:sforge", SFORGE.is_file(), path=" .bench-env/venv/bin/sforge".strip())
    imports = run_capture(
        [str(VENV_PYTHON), "-c", "import fastapi, sforge"]
    ) if VENV_PYTHON.is_file() else {"returncode": 127, "stderr": "venv missing"}
    add(
        "runtime:sforge-server-dependencies",
        imports["returncode"] == 0,
        stderr=imports["stderr"][-400:] or None,
    )
    add("runtime:repository-local-temp", ensure_temp_root().is_dir(), path=".tmp")

    auth_override = os.environ.get("SFORGE_CODEX_AUTH_FILE")
    auth = Path(auth_override).expanduser() if auth_override else Path.home() / ".codex" / "auth.json"
    add(
        "auth:codex",
        auth.is_file(),
        policy="SFORGE_CODEX_AUTH_FILE or ~/.codex/auth.json",
    )

    docker_info = run_capture(
        ["docker", "info", "--format", "{{.Architecture}}"]
    )
    architecture = docker_info["stdout"].strip().lower()
    add(
        "docker:engine",
        docker_info["returncode"] == 0,
        architecture=architecture or None,
        stderr=docker_info["stderr"][-400:] or None,
    )
    add(
        "docker:linux-amd64",
        architecture in {"amd64", "x86_64"},
        required="linux/amd64",
        actual=architecture or None,
    )

    for task_id in profile["task_ids"]:
        task_path = TASKS_DIR / f"{task_id}.json"
        add(f"task:{task_id}", task_path.is_file(), path=portable_path(task_path))
        actual_revision = dataset_revision(task_id)
        add(
            f"dataset-revision:{task_id}",
            actual_revision == profile["dataset_revision"],
            expected=profile["dataset_revision"],
            actual=actual_revision,
        )
        if not task_path.is_file():
            continue
        for image in task_images(task_id):
            inspected = run_capture(["docker", "image", "inspect", image])
            add(
                f"image:{image}",
                inspected["returncode"] == 0,
                image=image,
            )

    return {
        "schema_version": 1,
        "checked_at": utc_now(),
        "profile": profile["id"],
        "ok": all(check["passed"] for check in checks),
        "checks": checks,
    }


def doctor(profile: dict[str, Any], *, output: Path | None = None) -> int:
    payload = doctor_payload(profile)
    if output:
        write_json(output, payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["ok"] else 1


def sanitize_id(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    if not clean:
        raise ValueError("campaign id must contain a letter or digit")
    return clean


def prepare(args: argparse.Namespace, profile: dict[str, Any]) -> Path:
    methods = args.method or list(profile["methods"])
    unknown = set(methods) - set(METHODS)
    if unknown:
        raise ValueError("unknown EdgeBench method(s): " + ", ".join(sorted(unknown)))
    wall_time = int(args.wall_time_seconds or profile["wall_time_seconds"])
    concurrency = int(args.concurrency or profile["concurrency"])
    model = args.model or profile["model"]
    reasoning = args.reasoning_effort or profile.get("reasoning_effort", "high")
    if wall_time < 1 or concurrency < 1:
        raise ValueError("wall time and concurrency must be positive")

    campaign_id = sanitize_id(
        args.campaign_id or f"{profile['id']}-{campaign_stamp()}"
    )
    destination = RUNS_ROOT / campaign_id
    if destination.exists():
        raise FileExistsError(
            f"campaign already exists and will not be overwritten: {destination}"
        )
    destination.mkdir(parents=True)

    cells: list[dict[str, Any]] = []
    for task_id in profile["task_ids"]:
        config = task_config(task_id)
        prompt = str(config["work"]["agent_query"])
        for method in methods:
            method_config = METHODS[method]
            cell_id = sanitize_id(f"{task_id}--{method}")
            outer_replicas = (
                concurrency
                if method_config["outer_replicas"] == "concurrency"
                else int(method_config["outer_replicas"])
            )
            cell = {
                "schema_version": 1,
                "cell_id": cell_id,
                "task_id": task_id,
                "method": method,
                "sforge_agent": method_config["agent"],
                "model": model,
                "reasoning_effort": reasoning,
                "wall_time_seconds": wall_time,
                "live_search_concurrency": concurrency,
                "outer_replicas": outer_replicas,
                "outer_replica_concurrency": concurrency if outer_replicas > 1 else 1,
                "inner_search_concurrency": concurrency
                if method_config["inner_search"]
                else 0,
                "worker_runtime_seconds": min(
                    wall_time,
                    int(profile.get("worker_runtime_seconds", wall_time)),
                ),
                "eval_interval_seconds": int(
                    profile.get("eval_interval_seconds", 300)
                ),
                "judge_concurrency": int(profile.get("judge_concurrency", 1)),
                "judge_port": int(profile.get("judge_port", 8080)),
                "work_cpu_limit": profile.get("work_cpu_limit"),
                "judge_cpu_limit": profile.get("judge_cpu_limit"),
                "internet": bool(profile.get("internet", True)),
                "prompt_sha256": sha256_text(prompt),
                "metric_direction": config["judge"].get("score_direction", "maximize"),
                "sforge_run_id": sanitize_id(
                    f"{campaign_id}-{task_id}-{method}"
                ),
                "state": "prepared",
                "created_at": utc_now(),
            }
            cell_path = destination / "cells" / cell_id
            cell_path.mkdir(parents=True)
            write_json(cell_path / "cell.json", cell)
            cells.append(
                {
                    "cell_id": cell_id,
                    "task_id": task_id,
                    "method": method,
                    "state": "prepared",
                }
            )

    snapshot = {
        **profile,
        "methods": methods,
        "model": model,
        "reasoning_effort": reasoning,
        "wall_time_seconds": wall_time,
        "concurrency": concurrency,
    }
    write_json(destination / "profile.json", snapshot)
    write_json(
        destination / "campaign.json",
        {
            "schema_version": 1,
            "campaign_id": campaign_id,
            "profile": profile["id"],
            "state": "prepared",
            "created_at": utc_now(),
            "edgebench_tracking_branch": upstream_entry("edgebench")[
                "tracking_branch"
            ],
            "edgebench_branch": git_branch(EDGE_ROOT),
            "edgebench_commit": git_head(EDGE_ROOT),
            "goal_plus_tracking_branch": upstream_entry("goal_plus")[
                "tracking_branch"
            ],
            "goal_plus_branch": git_branch(GOAL_PLUS_ROOT),
            "goal_plus_commit": git_head(GOAL_PLUS_ROOT),
            "dataset_revision": profile["dataset_revision"],
            "task_ids": list(profile["task_ids"]),
            "methods": methods,
            "model": model,
            "reasoning_effort": reasoning,
            "wall_time_seconds": wall_time,
            "concurrency": concurrency,
            "cells": cells,
        },
    )
    write_json(
        destination / "controller.json",
        {
            "schema_version": 1,
            "state": "prepared",
            "created_at": utc_now(),
            "pid": None,
            "pgid": None,
        },
    )
    print(portable_path(destination))
    return destination


def build_sforge_command(destination: Path, cell: dict[str, Any]) -> list[str]:
    cell_path = destination / "cells" / cell["cell_id"]
    command = [
        str(SFORGE),
        "--log-dir",
        str(cell_path / "sforge"),
        "--tasks-dir",
        str(TASKS_DIR),
        "run",
        "--task",
        str(cell["task_id"]),
        "--agent",
        str(cell["sforge_agent"]),
        "--model",
        str(cell["model"]),
        "--timeout",
        str(cell["wall_time_seconds"]),
        "--eval-interval",
        str(cell["eval_interval_seconds"]),
        "--run-id",
        str(cell["sforge_run_id"]),
        "--replicas",
        str(cell["outer_replicas"]),
        "--replica-concurrency",
        str(cell["outer_replica_concurrency"]),
        "--judge-concurrency",
        str(cell["judge_concurrency"]),
        "--judge-url",
        str(
            cell.get("judge_url")
            or f"http://host.docker.internal:{cell.get('judge_port', 8080)}"
        ),
    ]
    if cell.get("work_cpu_limit"):
        command.extend(["--work-cpu-limit", str(cell["work_cpu_limit"])])
    if cell.get("judge_cpu_limit"):
        command.extend(["--judge-cpu-limit", str(cell["judge_cpu_limit"])])
    command.append("--enable-internet" if cell.get("internet", True) else "--disable-internet")
    return command


def cell_environment(cell: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    configure_temp_environment(env)
    for sforge_key, candidates in (
        ("SFORGE_HTTP_PROXY", ("SFORGE_HTTP_PROXY", "HTTP_PROXY", "http_proxy")),
        ("SFORGE_HTTPS_PROXY", ("SFORGE_HTTPS_PROXY", "HTTPS_PROXY", "https_proxy")),
    ):
        value = next((env[key] for key in candidates if env.get(key)), None)
        if value:
            env[sforge_key] = value.replace(
                "127.0.0.1", "host.docker.internal"
            ).replace("localhost", "host.docker.internal")
    env.setdefault("SFORGE_NODEJS_MIRROR_URL", "https://npmmirror.com/mirrors/node")
    env.setdefault("SFORGE_NPM_REGISTRY_URL", "https://registry.npmmirror.com")
    env["SFORGE_CODEX_REASONING_EFFORT"] = str(cell["reasoning_effort"])
    if cell["method"] == "goal-plus-codex":
        env["SFORGE_GOAL_PLUS_SOURCE_DIR"] = str(GOAL_PLUS_ROOT)
        env["SFORGE_AGENT_EXTRA_ENV"] = ",".join(
            [
                f"SFORGE_GOAL_PLUS_MAX_PARALLEL={cell['inner_search_concurrency']}",
                "SFORGE_GOAL_PLUS_WORKER_RUNTIME_SECONDS="
                f"{cell['worker_runtime_seconds']}",
            ]
        )
    return env


def process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def judge_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/openapi.json",
            timeout=1.0,
        ) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def start_or_reuse_judge(
    destination: Path,
    port: int,
    controller: dict[str, Any],
) -> tuple[subprocess.Popen[str] | None, Any]:
    controller_path = destination / "controller.json"
    if judge_ready(port):
        controller.update(
            {
                "judge_owned": False,
                "judge_pid": None,
                "judge_host_url": f"http://127.0.0.1:{port}",
                "judge_container_url": f"http://host.docker.internal:{port}",
            }
        )
        write_json(controller_path, controller)
        return None, lambda: None

    command = [
        str(SFORGE),
        "--log-dir",
        str(destination / "judge"),
        "--tasks-dir",
        str(TASKS_DIR),
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    log = (destination / "judge.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=dict(configure_temp_environment(dict(os.environ))),
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log.close()
    controller.update(
        {
            "judge_owned": True,
            "judge_pid": process.pid,
            "judge_command": portable_command(command),
            "judge_host_url": f"http://127.0.0.1:{port}",
            "judge_container_url": f"http://host.docker.internal:{port}",
        }
    )
    write_json(controller_path, controller)

    def close_judge() -> None:
        if process.poll() is not None:
            return
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            controller["judge_closeout_incomplete"] = True
            write_json(controller_path, controller)

    atexit.register(close_judge)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if judge_ready(port):
            return process, close_judge
        if process.poll() is not None:
            break
        time.sleep(0.25)
    close_judge()
    raise RuntimeError(
        f"SForge judge did not become ready; inspect {portable_path(destination / 'judge.log')}"
    )


def cell_has_scored_results(destination: Path, cell: dict[str, Any]) -> bool:
    cell_path = destination / "cells" / cell["cell_id"]
    task_runs = sorted(
        (cell_path / "sforge" / "runs").glob(f"*/{cell['task_id']}")
    )
    if len(task_runs) < int(cell["outer_replicas"]):
        return False
    for task_run in task_runs:
        final_path = task_run / "final_result.json"
        if not final_path.is_file():
            return False
        final = read_json(final_path)
        scored_reports = list((task_run / "submissions").glob("*/report.json"))
        if final.get("best_score") is None and not scored_reports:
            return False
    return True


def update_campaign_cell(
    destination: Path,
    cell_id: str,
    state: str,
) -> None:
    campaign = read_json(destination / "campaign.json")
    for item in campaign["cells"]:
        if item["cell_id"] == cell_id:
            item["state"] = state
            break
    campaign["updated_at"] = utc_now()
    write_json(destination / "campaign.json", campaign)


def execute_campaign(destination: Path) -> int:
    controller_path = destination / "controller.json"
    controller = read_json(controller_path)
    controller.update(
        {
            "state": "running",
            "started_at": utc_now(),
            "pid": os.getpid(),
            "pgid": os.getpgrp(),
        }
    )
    write_json(controller_path, controller)
    campaign = read_json(destination / "campaign.json")
    campaign["state"] = "running"
    campaign["started_at"] = utc_now()
    write_json(destination / "campaign.json", campaign)

    stop_requested = False
    active_child: subprocess.Popen[str] | None = None

    def handle_stop(signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True
        controller["stop_requested_at"] = utc_now()
        controller["stop_signal"] = signal.Signals(signum).name
        write_json(controller_path, controller)

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    judge_port = int(read_json(destination / "profile.json").get("judge_port", 8080))
    try:
        judge_process, close_judge = start_or_reuse_judge(
            destination,
            judge_port,
            controller,
        )
    except Exception as exc:
        campaign = read_json(destination / "campaign.json")
        campaign.update(
            {
                "state": "failed",
                "finished_at": utc_now(),
                "controller_error": str(exc),
            }
        )
        write_json(destination / "campaign.json", campaign)
        controller.update(
            {
                "state": "failed",
                "finished_at": utc_now(),
                "returncode": 1,
                "error": str(exc),
            }
        )
        write_json(controller_path, controller)
        return 1
    overall_returncode = 0
    for cell_summary in list(campaign["cells"]):
        if stop_requested:
            break
        cell_id = cell_summary["cell_id"]
        cell_path = destination / "cells" / cell_id
        cell_file = cell_path / "cell.json"
        cell = read_json(cell_file)
        cell["judge_url"] = f"http://host.docker.internal:{judge_port}"
        if cell.get("state") == "completed":
            continue
        command = build_sforge_command(destination, cell)
        write_json(
            cell_path / "command.json",
            {
                "command": portable_command(command),
                "environment_policy": {
                    "credentials": "host Codex auth only; values are never persisted",
                    "temp": ".tmp",
                    "goal_plus_source": "third_party/goal-plus"
                    if cell["method"] == "goal-plus-codex"
                    else None,
                },
            },
        )
        cell.update({"state": "running", "started_at": utc_now()})
        write_json(cell_file, cell)
        update_campaign_cell(destination, cell_id, "running")
        with (cell_path / "controller.log").open("a", encoding="utf-8") as log:
            active_child = subprocess.Popen(
                command,
                cwd=ROOT,
                env=cell_environment(cell),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            cell["pid"] = active_child.pid
            write_json(cell_file, cell)
            returncode = active_child.wait()
        active_child = None
        scored = cell_has_scored_results(destination, cell)
        if returncode == 0 and not stop_requested and not scored:
            returncode = 1
            cell["result_validation_error"] = (
                "SForge exited without the expected scored final result"
            )
        cell.update(
            {
                "state": "interrupted"
                if stop_requested
                else "completed"
                if returncode == 0
                else "failed",
                "returncode": returncode,
                "finished_at": utc_now(),
            }
        )
        write_json(cell_file, cell)
        update_campaign_cell(destination, cell_id, cell["state"])
        if returncode != 0:
            overall_returncode = returncode

    campaign = read_json(destination / "campaign.json")
    states = {cell["state"] for cell in campaign["cells"]}
    if stop_requested:
        final_state = "interrupted"
        overall_returncode = overall_returncode or 130
    elif states == {"completed"}:
        final_state = "completed"
    elif "failed" in states:
        final_state = "failed"
        overall_returncode = overall_returncode or 1
    else:
        final_state = "partial"
    campaign.update({"state": final_state, "finished_at": utc_now()})
    write_json(destination / "campaign.json", campaign)
    if judge_process is not None:
        close_judge()
    controller.update(
        {
            "state": final_state,
            "finished_at": utc_now(),
            "returncode": overall_returncode,
            "active_child_pid": active_child.pid if active_child else None,
            "judge_alive_after_closeout": process_alive(
                judge_process.pid if judge_process is not None else None
            ),
        }
    )
    write_json(controller_path, controller)
    finalize_campaign(destination)
    return overall_returncode


def launch(destination: Path, *, detach: bool) -> int:
    controller = read_json(destination / "controller.json")
    if process_alive(controller.get("pid")):
        raise RuntimeError(f"campaign controller is already running: {controller['pid']}")
    if not detach:
        return execute_campaign(destination)

    command = [
        str(VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)),
        str(Path(__file__).resolve()),
        "_execute",
        "--campaign",
        portable_path(destination),
    ]
    log = (destination / "controller.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=dict(configure_temp_environment(dict(os.environ))),
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    log.close()
    controller = read_json(destination / "controller.json")
    controller.update(
        {
            "schema_version": 1,
            "launched_at": controller.get("launched_at") or utc_now(),
            "pid": process.pid,
            "pgid": process.pid,
            "command": portable_command(command),
        }
    )
    if controller.get("state") in {"prepared", "launching"}:
        controller["state"] = "launching"
    write_json(destination / "controller.json", controller)
    print(json.dumps({"pid": process.pid, "campaign": portable_path(destination)}))
    return 0


def status_payload(destination: Path) -> dict[str, Any]:
    campaign = read_json(destination / "campaign.json")
    controller = read_json(destination / "controller.json")
    cells: list[dict[str, Any]] = []
    for item in campaign["cells"]:
        cell_path = destination / "cells" / item["cell_id"]
        cell = read_json(cell_path / "cell.json")
        task_runs = sorted(
            (cell_path / "sforge" / "runs").glob(f"*/{cell['task_id']}")
        )
        final_results = [
            run / "final_result.json" for run in task_runs if (run / "final_result.json").is_file()
        ]
        cells.append(
            {
                "cell_id": item["cell_id"],
                "task_id": item["task_id"],
                "method": item["method"],
                "state": cell["state"],
                "pid": cell.get("pid"),
                "pid_alive": process_alive(cell.get("pid")),
                "completed_trajectories": len(final_results),
                "expected_trajectories": cell["outer_replicas"],
                "summary": portable_path(cell_path / "summary.json")
                if (cell_path / "summary.json").is_file()
                else None,
            }
        )
    return {
        "campaign": campaign["campaign_id"],
        "state": campaign["state"],
        "controller": {
            "state": controller["state"],
            "pid": controller.get("pid"),
            "pgid": controller.get("pgid"),
            "alive": process_alive(controller.get("pid")),
            "judge_owned": controller.get("judge_owned"),
            "judge_pid": controller.get("judge_pid"),
            "judge_alive": process_alive(controller.get("judge_pid")),
        },
        "cells": cells,
    }


def print_status(destination: Path, *, as_json: bool) -> int:
    payload = status_payload(destination)
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(
        f"{payload['campaign']}: {payload['state']} "
        f"(controller alive={payload['controller']['alive']})"
    )
    for cell in payload["cells"]:
        print(
            f"- {cell['cell_id']}: {cell['state']}; "
            f"{cell['completed_trajectories']}/{cell['expected_trajectories']} trajectories"
        )
    return 0


def stop_campaign(destination: Path, *, wait_seconds: int) -> int:
    controller_path = destination / "controller.json"
    controller = read_json(controller_path)
    pid = controller.get("pid")
    pgid = controller.get("pgid")
    if not process_alive(pid):
        print("controller is not running; no signal sent")
        return 0
    if not pgid:
        raise RuntimeError("running controller has no recorded process group")
    os.killpg(int(pgid), signal.SIGINT)
    controller["state"] = "stopping"
    controller["stop_requested_at"] = utc_now()
    write_json(controller_path, controller)
    deadline = time.monotonic() + max(0, wait_seconds)
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.25)
    payload = {
        "signal": "SIGINT",
        "pid": pid,
        "pgid": pgid,
        "alive_after_wait": process_alive(pid),
        "artifacts_preserved": True,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not payload["alive_after_wait"] else 2


def iter_json_lines(text: str) -> Iterable[dict[str, Any]]:
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            yield item


def add_usage(total: dict[str, int], event: dict[str, Any]) -> None:
    if event.get("type") != "turn.completed":
        return
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return
    for key, value in usage.items():
        if isinstance(value, int) and not isinstance(value, bool):
            total[key] += value


def codex_usage(task_run: Path) -> dict[str, Any]:
    totals: dict[str, int] = defaultdict(int)
    session_ids: set[str] = set()
    archive_path = task_run / "codex-sessions.tar"
    coverage = "agent_output_only"
    if archive_path.is_file():
        coverage = "all_collected_codex_sessions"
        try:
            with tarfile.open(archive_path) as archive:
                for member in archive:
                    if not member.isfile() or not member.name.endswith(".jsonl"):
                        continue
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        continue
                    text = extracted.read().decode("utf-8", errors="replace")
                    rollout_total: dict[str, int] = {}
                    for event in iter_json_lines(text):
                        if event.get("type") == "thread.started" and event.get("thread_id"):
                            session_ids.add(str(event["thread_id"]))
                        if event.get("type") == "session_meta":
                            payload = event.get("payload", {})
                            if isinstance(payload, dict):
                                session_id = payload.get("id") or payload.get("session_id")
                                if session_id:
                                    session_ids.add(str(session_id))
                        if event.get("type") == "event_msg":
                            payload = event.get("payload", {})
                            if (
                                isinstance(payload, dict)
                                and payload.get("type") == "token_count"
                            ):
                                info = payload.get("info", {})
                                usage = (
                                    info.get("total_token_usage", {})
                                    if isinstance(info, dict)
                                    else {}
                                )
                                if isinstance(usage, dict):
                                    rollout_total = {
                                        key: value
                                        for key, value in usage.items()
                                        if isinstance(value, int)
                                        and not isinstance(value, bool)
                                    }
                        add_usage(totals, event)
                    for key, value in rollout_total.items():
                        totals[key] += value
        except tarfile.TarError:
            coverage = "invalid_codex_sessions_archive"
    else:
        output = task_run / "agent_output.txt"
        if output.is_file():
            for event in iter_json_lines(output.read_text(encoding="utf-8", errors="replace")):
                if event.get("type") == "thread.started" and event.get("thread_id"):
                    session_ids.add(str(event["thread_id"]))
                add_usage(totals, event)
    return {
        "coverage": coverage,
        "session_count": len(session_ids),
        "tokens": dict(sorted(totals.items())),
    }


def goal_plus_stats(task_run: Path) -> dict[str, Any] | None:
    archive_path = task_run / "goal-plus-state.tar"
    if not archive_path.is_file():
        return None
    candidates: set[tuple[str, str]] = set()
    sessions = 0
    verifier_runs = 0
    search_runs: set[str] = set()
    search_run_states: dict[str, int] = defaultdict(int)
    try:
        with tarfile.open(archive_path) as archive:
            for member in archive:
                run_match = re.search(r"/runs/([^/]+)/run\.json$", member.name)
                if run_match:
                    search_runs.add(run_match.group(1))
                    extracted = archive.extractfile(member)
                    if extracted:
                        try:
                            payload = json.loads(
                                extracted.read().decode("utf-8", errors="replace")
                            )
                            state = payload.get("state")
                            if state:
                                search_run_states[str(state)] += 1
                        except (json.JSONDecodeError, TypeError):
                            pass
                match = re.search(r"/runs/([^/]+)/candidates/([^/]+)/candidate\.json$", member.name)
                if match:
                    search_runs.add(match.group(1))
                    candidates.add((match.group(1), match.group(2)))
                if "/agent_sessions/" in member.name and member.name.endswith(".json"):
                    sessions += 1
                    extracted = archive.extractfile(member)
                    if extracted:
                        try:
                            payload = json.loads(
                                extracted.read().decode("utf-8", errors="replace")
                            )
                            verifier_runs += int(
                                payload.get("counters", {}).get("verifier_runs", 0)
                            )
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
    except tarfile.TarError:
        return {"archive": "invalid"}
    return {
        "search_runs": len(search_runs),
        "candidates": len(candidates),
        "agent_sessions": sessions,
        "worker_verifier_runs": verifier_runs,
        "search_run_states": dict(sorted(search_run_states.items())),
    }


def score_task_run(task_run: Path, cell: dict[str, Any]) -> dict[str, Any]:
    reporter = EDGE_ROOT / "scripts" / "report_edgebench_scores.py"
    command = [
        str(VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)),
        str(reporter),
        "--run-dir",
        str(task_run),
        "--model",
        str(cell["model"]),
        "--budget-seconds",
        str(cell["wall_time_seconds"]),
        "--json",
    ]
    scored = run_capture(command, env=dict(configure_temp_environment(dict(os.environ))))
    if scored["returncode"] != 0:
        return {
            "task_run": portable_path(task_run),
            "error": scored["stderr"] or scored["stdout"],
        }
    observation = json.loads(scored["stdout"])
    observation["source"] = portable_path(Path(observation["source"]))
    observation["task_run"] = portable_path(task_run)
    final = read_json(task_run / "final_result.json")
    observation["runtime_seconds"] = final.get("runtime_seconds")
    observation["total_rounds"] = final.get("total_rounds")
    observation["agent_submissions"] = final.get("agent_submissions")
    observation["auto_submissions"] = final.get("auto_submissions")
    observation["resume_count"] = final.get("resume_count")
    observation["timed_out"] = final.get("timed_out")
    history = read_json(task_run / "run_history.json")
    entries = history.get("entries", [])
    evaluator_calls = (
        sum(
            1
            for entry in entries
            if isinstance(entry, dict) and entry.get("type") == "submission"
        )
        if isinstance(entries, list)
        else 0
    )
    if not evaluator_calls:
        evaluator_calls = len(list((task_run / "submissions").glob("*/report.json")))
    observation["evaluator_calls"] = evaluator_calls
    observation["codex_usage"] = codex_usage(task_run)
    observation["goal_plus"] = goal_plus_stats(task_run)
    return observation


def summarize_cell(destination: Path, cell: dict[str, Any]) -> dict[str, Any]:
    cell_path = destination / "cells" / cell["cell_id"]
    task_runs = sorted(
        (cell_path / "sforge" / "runs").glob(f"*/{cell['task_id']}")
    )
    observations = [
        score_task_run(task_run, cell)
        for task_run in task_runs
        if (task_run / "final_result.json").is_file()
    ]
    valid = [item for item in observations if "edgebench_score" in item]
    best = max(valid, key=lambda item: float(item["edgebench_score"])) if valid else None
    summary = {
        "schema_version": 1,
        "cell_id": cell["cell_id"],
        "task_id": cell["task_id"],
        "method": cell["method"],
        "model": cell["model"],
        "reasoning_effort": cell["reasoning_effort"],
        "wall_time_seconds": cell["wall_time_seconds"],
        "live_search_concurrency": cell["live_search_concurrency"],
        "outer_replicas": cell["outer_replicas"],
        "inner_search_concurrency": cell["inner_search_concurrency"],
        "expected_trajectories": cell["outer_replicas"],
        "completed_trajectories": len(observations),
        "valid_trajectories": len(valid),
        "observations": observations,
        "best": best,
        "finalized_at": utc_now(),
    }
    write_json(cell_path / "summary.json", summary)
    return summary


def render_comparison(payload: dict[str, Any]) -> str:
    lines = [
        f"# EdgeBench campaign: {payload['campaign_id']}",
        "",
        (
            f"Matched protocol: `{payload['matched_protocol']}`. "
            "Plain Codex uses K independent outer trajectories; Goal Plus uses "
            "one outer trajectory with K internal search workers."
        ),
        "",
        "| Task | Method | T | K | Outer trajectories | Valid | Best raw | EdgeBench 0-100 | Evaluator calls | Runtime | Tokens | Usage coverage |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for cell in payload["cells"]:
        best = cell.get("best") or {}
        observations = cell.get("observations", [])
        evaluator_calls = sum(int(item.get("evaluator_calls") or 0) for item in observations)
        runtime = sum(float(item.get("runtime_seconds") or 0) for item in observations)
        input_tokens = 0
        output_tokens = 0
        coverage: set[str] = set()
        for item in observations:
            usage = item.get("codex_usage") or {}
            tokens = usage.get("tokens") or {}
            input_tokens += int(tokens.get("input_tokens") or 0)
            output_tokens += int(tokens.get("output_tokens") or 0)
            if usage.get("coverage"):
                coverage.add(str(usage["coverage"]))
        raw = best.get("raw_score", "-")
        normalized = best.get("edgebench_score", "-")
        lines.append(
            "| {task} | {method} | {time} | {concurrency} | {outer} | {valid} | "
            "{raw} | {normalized} | {calls} | {runtime:.1f}s | {tokens} | {coverage} |".format(
                task=cell["task_id"],
                method=cell["method"],
                time=cell["wall_time_seconds"],
                concurrency=cell["live_search_concurrency"],
                outer=cell["completed_trajectories"],
                valid=cell["valid_trajectories"],
                raw=raw,
                normalized=normalized,
                calls=evaluator_calls,
                runtime=runtime,
                tokens=f"{input_tokens}/{output_tokens}",
                coverage=", ".join(sorted(coverage)) or "unavailable",
            )
        )
    lines.extend(
        [
            "",
            "Token column is `input/output`. A zero value with non-complete coverage "
            "means unavailable telemetry, not free model usage.",
            "",
        ]
    )
    return "\n".join(lines)


def finalize_campaign(destination: Path) -> dict[str, Any]:
    campaign = read_json(destination / "campaign.json")
    summaries: list[dict[str, Any]] = []
    for item in campaign["cells"]:
        cell_path = destination / "cells" / item["cell_id"]
        cell = read_json(cell_path / "cell.json")
        summaries.append(summarize_cell(destination, cell))
    protocol_fields = {
        (
            summary["task_id"],
            summary["model"],
            summary["reasoning_effort"],
            summary["wall_time_seconds"],
            summary["live_search_concurrency"],
        )
        for summary in summaries
    }
    payload = {
        "schema_version": 1,
        "campaign_id": campaign["campaign_id"],
        "matched_protocol": len(protocol_fields) == len(set(campaign["task_ids"])),
        "edgebench_commit": campaign.get("edgebench_commit"),
        "goal_plus_commit": campaign.get("goal_plus_commit"),
        "dataset_revision": campaign.get("dataset_revision"),
        "cells": summaries,
        "finalized_at": utc_now(),
    }
    write_json(destination / "comparison.json", payload)
    (destination / "comparison.md").write_text(
        render_comparison(payload), encoding="utf-8"
    )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("provision", "doctor"):
        child = subparsers.add_parser(name)
        child.add_argument("--profile", default="vliw-smoke")
        if name == "doctor":
            child.add_argument("--output", type=Path)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--profile", default="vliw-smoke")
    prepare_parser.add_argument("--campaign-id")
    prepare_parser.add_argument("--method", action="append", choices=sorted(METHODS))
    prepare_parser.add_argument("--model")
    prepare_parser.add_argument("--reasoning-effort")
    prepare_parser.add_argument("--wall-time-seconds", type=int)
    prepare_parser.add_argument("--concurrency", type=int)

    for name in ("run", "status", "stop", "finalize", "_execute"):
        child = subparsers.add_parser(name)
        child.add_argument("--campaign", required=True)
        if name == "run":
            child.add_argument("--detach", action="store_true")
        elif name == "status":
            child.add_argument("--json", action="store_true")
        elif name == "stop":
            child.add_argument("--wait-seconds", type=int, default=10)
    return parser


def main() -> int:
    configure_temp_environment()
    args = build_parser().parse_args()
    if args.command in {"provision", "doctor", "prepare"}:
        _, profile = load_profile(args.profile)
        if args.command == "provision":
            return provision(profile)
        if args.command == "doctor":
            return doctor(profile, output=args.output)
        prepare(args, profile)
        return 0

    destination = campaign_dir(args.campaign)
    if args.command == "run":
        return launch(destination, detach=args.detach)
    if args.command == "_execute":
        return execute_campaign(destination)
    if args.command == "status":
        return print_status(destination, as_json=args.json)
    if args.command == "stop":
        return stop_campaign(destination, wait_seconds=args.wait_seconds)
    if args.command == "finalize":
        payload = finalize_campaign(destination)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
