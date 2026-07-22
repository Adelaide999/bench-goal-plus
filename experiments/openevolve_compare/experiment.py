#!/usr/bin/env python3
"""Prepare and run the same OpenEvolve example with native OE or Codex hosts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adapters.openevolve_examples.adapter import (  # noqa: E402
    describe_task,
    evaluate_workspace,
    git_commit,
    materialize_workspace,
    resolve_task,
    run_worker,
)


DEFAULT_ENV_MANIFEST = ROOT / "environment/upstreams.json"
DEFAULT_VENV = ROOT / ".bench-env/venv"
DEFAULT_RUNS = ROOT / "runs/openevolve-compare"
METHODS = ("openevolve", "plain-codex", "goal-plus")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def default_run_dir(task_id: str, method: str, seed: int) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_RUNS / f"{timestamp}-{task_id}-{method}-seed{seed}"


def runtime_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def runtime_bin(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def copy_goal_plus_assets(goal_plus_root: Path, workspace: Path) -> None:
    source = goal_plus_root / ".codex"
    required = (
        source / "agents",
        source / "skills",
        source / "hooks.json",
        source / "config.example.toml",
    )
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)

    target = workspace / ".codex"
    target.mkdir()
    shutil.copytree(source / "agents", target / "agents")
    shutil.copytree(source / "skills", target / "skills")
    shutil.copy2(source / "hooks.json", target / "hooks.json")
    shutil.copy2(source / "config.example.toml", target / "config.toml")


def append_unique_lines(path: Path, lines: list[str]) -> None:
    existing = path.read_text().splitlines() if path.is_file() else []
    for line in lines:
        if line not in existing:
            existing.append(line)
    path.write_text("\n".join(existing) + "\n")


def commit_workspace(workspace: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(workspace), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-m", message],
        check=True,
        capture_output=True,
    )
    return git_commit(workspace)


def render_goal(
    task_text: str,
    wall_seconds: int,
    closeout_seconds: int,
    concurrency: int,
) -> str:
    exploration_seconds = max(1, wall_seconds - closeout_seconds)
    return (
        "/goal-plus mode=autonomous\n\n"
        "Run this measurable optimization task with Goal Plus Search while preserving Goal Plus's "
        "native fixed parallel-loop design.\n\n"
        f"{task_text.strip()}\n\n"
        "# System-level experiment budget\n\n"
        f"- Total outer wall-clock budget: {wall_seconds} seconds.\n"
        f"- Stop new exploration after about {exploration_seconds} seconds and reserve "
        f"{closeout_seconds} seconds for final verification, selection, promotion, and shutdown.\n"
        f"- Freeze exactly {concurrency} candidates with `max_candidates={concurrency}` and "
        f"`max_parallel={concurrency}`. Keep those same autonomous lineages alive.\n"
        "- Public evaluator calls are not hard-capped. The outer controller will report the actual "
        "calls, tokens, cost coverage, and wall time after the run.\n"
        "- Treat `GOAL_PLUS_OUTER_DEADLINE_AT` as authoritative. Finish and drain every "
        "worker before it.\n"
        "- Use only `python3 evaluate.py` for task feedback and leave the selected, promoted best "
        "candidate in the task artifact.\n"
    )


def write_openevolve_config(
    source: Path,
    target: Path,
    *,
    concurrency: int,
    iterations_ceiling: int,
    seed: int,
) -> None:
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError("PyYAML is missing; run scripts/repro_env.py bootstrap") from error

    payload = yaml.safe_load(source.read_text())
    payload["max_iterations"] = iterations_ceiling
    payload["random_seed"] = seed
    payload.setdefault("database", {})["random_seed"] = seed
    payload.setdefault("evaluator", {})["parallel_evaluations"] = concurrency
    llm = payload.setdefault("llm", {})
    llm.pop("api_key", None)
    llm["secondary_model_weight"] = 0.0
    target.write_text(yaml.safe_dump(payload, sort_keys=False))


def prepare(args: argparse.Namespace) -> int:
    if args.wall_time_seconds <= args.soft_closeout_seconds:
        raise ValueError("wall time must be greater than the soft closeout reserve")
    if args.concurrency < 1:
        raise ValueError("concurrency must be positive")
    if args.method == "plain-codex" and args.concurrency != 1:
        raise ValueError("plain-codex is a single-lane baseline; use --concurrency 1")
    if args.hard_kill_grace_seconds < 1:
        raise ValueError("hard-kill grace must be positive")
    if args.iterations_ceiling < 1:
        raise ValueError("iterations ceiling must be positive")

    environment = load_json(args.environment_manifest)
    checkout_root = args.checkout_root.expanduser().absolute()
    upstreams = environment["upstreams"]
    openevolve_root = checkout_root / upstreams["openevolve"]["checkout_dir"]
    goal_plus_root = checkout_root / upstreams["goal_plus"]["checkout_dir"]
    python = runtime_python(args.venv.expanduser().absolute())
    if not python.is_file():
        raise FileNotFoundError(f"reproducible runtime is missing: {python}")

    task = resolve_task(args.task_id, openevolve_root)
    run_dir = (
        args.run_dir or default_run_dir(args.task_id, args.method, args.seed)
    ).absolute()
    run_dir.mkdir(parents=True, exist_ok=False)
    run_config = run_dir / "openevolve-config.yaml"
    write_openevolve_config(
        task.config,
        run_config,
        concurrency=args.concurrency,
        iterations_ceiling=args.iterations_ceiling,
        seed=args.seed,
    )
    run_task = replace(task, config=run_config)
    description = describe_task(run_task, python)
    workspace: Path | None = None
    workspace_commit: str | None = None

    if args.method in {"plain-codex", "goal-plus"}:
        workspace = run_dir / "workspace"
        materialized = materialize_workspace(
            run_task,
            workspace,
            python,
            max_evaluator_calls=None,
            reserved_final_calls=1,
            description=description,
        )
        workspace_commit = materialized["workspace_commit"]
        if args.method == "goal-plus":
            copy_goal_plus_assets(goal_plus_root, workspace)
            append_unique_lines(workspace / ".gitignore", [".gp/", ".codex-log/"])
            goal = render_goal(
                (workspace / "TASK.md").read_text(),
                args.wall_time_seconds,
                args.soft_closeout_seconds,
                args.concurrency,
            )
            (workspace / "GOAL.md").write_text(goal)
            workspace_commit = commit_workspace(workspace, "install pinned Goal Plus host assets")
    manifest = {
        "schema_version": 1,
        "status": "prepared",
        "prepared_at": utc_now(),
        "method": args.method,
        "task_id": args.task_id,
        "seed": args.seed,
        "budget": {
            "wall_time_seconds": args.wall_time_seconds,
            "concurrency": args.concurrency,
            "soft_closeout_seconds": args.soft_closeout_seconds,
            "hard_kill_grace_seconds": args.hard_kill_grace_seconds,
            "iterations_ceiling": args.iterations_ceiling,
            "evaluator_call_cap": None,
        },
        "task": {
            "artifact_name": task.artifact_name,
            "primary_metric": description["evaluation"]["primary_metric"],
            "direction": description["evaluation"]["direction"],
            "upstream_commit": task.upstream_commit,
            "initial_program": str(task.initial_program),
            "evaluator": str(task.evaluator),
            "config": str(run_config),
            "upstream_config": str(task.config),
            "initial_program_sha256": sha256_file(task.initial_program),
            "evaluator_sha256": sha256_file(task.evaluator),
        },
        "environment": {
            "manifest": str(args.environment_manifest.absolute()),
            "runtime_python": str(python),
            "openevolve_root": str(openevolve_root),
            "openevolve_commit": git_commit(openevolve_root),
            "goal_plus_root": str(goal_plus_root),
            "goal_plus_commit": git_commit(goal_plus_root),
        },
        "workspace": str(workspace) if workspace else None,
        "workspace_commit": workspace_commit,
        "secret_policy": (
            "credentials are inherited from the process environment and never serialized"
        ),
    }
    write_json(run_dir / "experiment.json", manifest)
    print(run_dir)
    return 0


def send_soft_stop(process: subprocess.Popen[str]) -> None:
    try:
        process.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        pass


def send_hard_stop(process: subprocess.Popen[str]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass


def parse_codex_events(path: Path) -> dict[str, Any]:
    thread_id = None
    usage = None
    terminal_event = None
    event_count = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        event_count += 1
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
        if event_type in {"turn.completed", "turn.failed"}:
            terminal_event = event_type
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
    return {
        "thread_id": thread_id,
        "terminal_event": terminal_event,
        "top_level_usage": usage,
        "event_count": event_count,
        "coverage": (
            "top-level Codex usage only; Goal Plus worker observability remains in workspace/.gp"
        ),
    }


def run_controlled(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    stdin_text: str | None,
    stdout_path: Path,
    stderr_path: Path,
    wall_time_seconds: int,
    hard_kill_grace_seconds: int,
) -> dict[str, Any]:
    started_at = utc_now()
    started = time.monotonic()
    soft_stopped = False
    hard_killed = False
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            text=True,
            start_new_session=True,
        )
        if stdin_text is not None and process.stdin is not None:
            process.stdin.write(stdin_text)
            process.stdin.close()
        try:
            process.wait(timeout=wall_time_seconds)
        except subprocess.TimeoutExpired:
            soft_stopped = True
            send_soft_stop(process)
            try:
                process.wait(timeout=hard_kill_grace_seconds)
            except subprocess.TimeoutExpired:
                hard_killed = True
                send_hard_stop(process)
                process.wait()

    return {
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_seconds": time.monotonic() - started,
        "returncode": process.returncode,
        "deadline_reached": soft_stopped,
        "soft_stop_signal": "SIGTERM" if soft_stopped else None,
        "hard_killed": hard_killed,
        "hard_kill_grace_seconds": hard_kill_grace_seconds,
        "command": command,
    }


def evaluate_native(
    task: Any,
    python: Path,
    artifact: Path,
    config: Path,
) -> dict[str, Any]:
    return run_worker(
        python,
        "evaluate",
        [
            "--upstream-root",
            str(task.upstream_root),
            "--config",
            str(config),
            "--evaluator",
            str(task.evaluator),
            "--artifact",
            str(artifact),
        ],
    )


def execute(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().absolute()
    manifest_path = run_dir / "experiment.json"
    manifest = load_json(manifest_path)
    if manifest["status"] != "prepared":
        raise RuntimeError(f"run is not prepared: status={manifest['status']}")

    method = manifest["method"]
    if not args.model:
        raise ValueError("--model is required so every comparable run has explicit identity")
    budget = manifest["budget"]
    python = Path(manifest["environment"]["runtime_python"])
    task = resolve_task(
        manifest["task_id"],
        Path(manifest["environment"]["openevolve_root"]),
    )
    run_config = Path(manifest["task"]["config"])
    environment = os.environ.copy()
    bin_dir = runtime_bin(args.venv.expanduser().absolute())
    environment["PATH"] = str(bin_dir) + os.pathsep + environment.get("PATH", "")

    if method == "openevolve":
        if not args.api_base:
            raise ValueError("native OpenEvolve requires --model and --api-base")
        if not environment.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for native OpenEvolve")

    manifest["status"] = "running"
    manifest["execution_started_at"] = utc_now()
    write_json(manifest_path, manifest)

    if method == "openevolve":
        baseline = evaluate_native(task, python, task.initial_program, run_config)
        write_json(run_dir / "seed-eval.json", baseline)
        output = run_dir / "native-output"
        command = [
            str(bin_dir / "openevolve-run"),
            str(task.initial_program),
            str(task.evaluator),
            "--config",
            str(run_dir / "openevolve-config.yaml"),
            "--output",
            str(output),
            "--iterations",
            str(budget["iterations_ceiling"]),
            "--api-base",
            args.api_base,
            "--primary-model",
            args.model,
            "--secondary-model",
            args.model,
            "--log-level",
            "INFO",
        ]
        control = run_controlled(
            command,
            cwd=task.source_dir,
            environment=environment,
            stdin_text=None,
            stdout_path=run_dir / "stdout.log",
            stderr_path=run_dir / "stderr.log",
            wall_time_seconds=budget["wall_time_seconds"],
            hard_kill_grace_seconds=budget["hard_kill_grace_seconds"],
        )
        best = output / "best" / f"best_program{task.initial_program.suffix}"
        if best.is_file():
            shutil.copy2(best, run_dir / "final-candidate.py")
            write_json(
                run_dir / "final-eval.json",
                evaluate_native(task, python, best, run_config),
            )
            info = output / "best" / "best_program_info.json"
            if info.is_file():
                control["native_best"] = load_json(info)
        else:
            control["result_incomplete_reason"] = "native best program was not saved"
        control["telemetry_coverage"] = {
            "evaluator_calls": "missing: native upstream does not expose an exact completed-call ledger",
            "tokens": "missing: native upstream OpenAI-compatible client does not persist usage",
            "iterations": "best_program_info iteration is available when graceful shutdown saves a best",
        }
    else:
        workspace = Path(manifest["workspace"])
        write_json(run_dir / "seed-eval.json", evaluate_workspace(workspace, "public"))
        prompt_path = workspace / ("GOAL.md" if method == "goal-plus" else "TASK.md")
        command = [
            args.codex_bin,
            "exec",
            "--json",
            "--sandbox",
            "workspace-write",
            "--cd",
            str(workspace),
            "--output-last-message",
            str(run_dir / "final-message.txt"),
            "--ignore-user-config",
            "--color",
            "never",
        ]
        if method == "goal-plus":
            command.append("--dangerously-bypass-hook-trust")
            deadline = datetime.now(timezone.utc) + timedelta(
                seconds=budget["wall_time_seconds"]
            )
            environment["GOAL_PLUS_OUTER_DEADLINE_AT"] = deadline.isoformat()
        else:
            command.append("--ephemeral")
        if args.model:
            command.extend(["--model", args.model])
        command.append("-")
        control = run_controlled(
            command,
            cwd=workspace,
            environment=environment,
            stdin_text=prompt_path.read_text(),
            stdout_path=run_dir / "events.jsonl",
            stderr_path=run_dir / "stderr.log",
            wall_time_seconds=budget["wall_time_seconds"],
            hard_kill_grace_seconds=budget["hard_kill_grace_seconds"],
        )
        final = evaluate_workspace(workspace, "final")
        write_json(run_dir / "final-eval.json", final)
        shutil.copy2(workspace / task.artifact_name, run_dir / "final-candidate.py")
        control["codex"] = parse_codex_events(run_dir / "events.jsonl")
        control["evaluator_calls"] = final["budget"]
        if control["hard_killed"]:
            control["result_incomplete_reason"] = "Codex process group exceeded the shutdown grace"

    if control["returncode"] != 0 and not control.get("result_incomplete_reason"):
        control["result_incomplete_reason"] = (
            f"controlled process exited nonzero ({control['returncode']})"
        )

    manifest["status"] = (
        "finished" if not control.get("result_incomplete_reason") else "incomplete"
    )
    manifest["model"] = args.model
    manifest["api_base"] = args.api_base if method == "openevolve" else None
    version_command = (
        [
            str(python),
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('openevolve'))",
        ]
        if method == "openevolve"
        else [args.codex_bin, "--version"]
    )
    version = subprocess.run(version_command, capture_output=True, text=True, check=False)
    manifest["runner_version"] = (version.stdout or version.stderr).strip() or None
    manifest["execution"] = control
    write_json(manifest_path, manifest)
    print(json.dumps(control, indent=2))
    return 0 if manifest["status"] == "finished" else 2


def seed_smoke(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().absolute()
    manifest = load_json(run_dir / "experiment.json")
    python = Path(manifest["environment"]["runtime_python"])
    task = resolve_task(
        manifest["task_id"],
        Path(manifest["environment"]["openevolve_root"]),
    )
    payload = evaluate_native(
        task,
        python,
        task.initial_program,
        Path(manifest["task"]["config"]),
    )
    write_json(run_dir / "seed-eval.json", payload)
    print(json.dumps(payload, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--method", choices=METHODS, required=True)
    prepare_parser.add_argument("--task-id", default="function_minimization")
    prepare_parser.add_argument("--seed", type=int, default=1)
    prepare_parser.add_argument("--wall-time-seconds", type=int, default=600)
    prepare_parser.add_argument("--concurrency", type=int, default=3)
    prepare_parser.add_argument("--soft-closeout-seconds", type=int, default=60)
    prepare_parser.add_argument("--hard-kill-grace-seconds", type=int, default=120)
    prepare_parser.add_argument("--iterations-ceiling", type=int, default=1_000_000)
    prepare_parser.add_argument("--run-dir", type=Path)
    prepare_parser.add_argument(
        "--environment-manifest", type=Path, default=DEFAULT_ENV_MANIFEST
    )
    prepare_parser.add_argument("--checkout-root", type=Path, default=ROOT.parent)
    prepare_parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--run-dir", type=Path, required=True)
    run_parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)
    run_parser.add_argument("--codex-bin", default="codex")
    run_parser.add_argument("--model")
    run_parser.add_argument("--api-base")

    smoke_parser = subparsers.add_parser("seed-smoke")
    smoke_parser.add_argument("--run-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "prepare":
        return prepare(args)
    if args.command == "seed-smoke":
        return seed_smoke(args)
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
