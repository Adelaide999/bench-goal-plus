#!/usr/bin/env python3
"""Run one non-interactive Codex turn and persist reproducibility evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def codex_version(codex_bin: str) -> str | None:
    result = subprocess.run(
        [codex_bin, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or result.stderr.strip() or None


def ensure_git_workspace(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"workspace is not a Git repository with a commit: {workspace}")
    return result.stdout.strip()


def parse_events(events_path: Path) -> tuple[str | None, dict | None, str | None]:
    thread_id: str | None = None
    usage: dict | None = None
    terminal_event: str | None = None
    for line_number, line in enumerate(events_path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"invalid Codex JSONL at line {line_number}: {error}") from error
        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
        if event_type in {"turn.completed", "turn.failed"}:
            terminal_event = event_type
            if isinstance(event.get("usage"), dict):
                usage = event["usage"]
    return thread_id, usage, terminal_event


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--model")
    parser.add_argument(
        "--sandbox",
        choices=["read-only", "workspace-write", "danger-full-access"],
        default="workspace-write",
    )
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--ephemeral", action="store_true")
    parser.add_argument(
        "--load-user-config",
        action="store_true",
        help="load personal config.toml; disabled by default for benchmark reproducibility",
    )
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    prompt_path = args.prompt_file.resolve()
    run_dir = args.run_dir.resolve()
    if args.sandbox == "danger-full-access":
        raise RuntimeError("danger-full-access is not allowed by the shared runner")
    if not prompt_path.is_file():
        raise FileNotFoundError(prompt_path)
    workspace_commit = ensure_git_workspace(workspace)
    prompt = prompt_path.read_text()
    run_dir.mkdir(parents=True, exist_ok=False)

    events_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    final_message_path = run_dir / "final-message.txt"
    manifest_path = run_dir / "run-manifest.json"

    command = [
        args.codex_bin,
        "exec",
        "--json",
        "--sandbox",
        args.sandbox,
        "--cd",
        str(workspace),
        "--output-last-message",
        str(final_message_path),
    ]
    if not args.load_user_config:
        command.append("--ignore-user-config")
    if args.ephemeral:
        command.append("--ephemeral")
    if args.model:
        command.extend(["--model", args.model])
    command.append("-")

    started_at = utc_now()
    started_monotonic = time.monotonic()
    exit_code: int
    timed_out = False
    with events_path.open("w") as events_file, stderr_path.open("w") as stderr_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=events_file,
            stderr=stderr_file,
            text=True,
        )
        try:
            process.communicate(prompt, timeout=args.timeout_seconds)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.communicate()
            exit_code = 124

    duration_seconds = time.monotonic() - started_monotonic
    thread_id, usage, terminal_event = parse_events(events_path)
    manifest = {
        "schema_version": 1,
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_seconds": duration_seconds,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "terminal_event": terminal_event,
        "thread_id": thread_id,
        "usage": usage,
        "codex_version": codex_version(args.codex_bin),
        "model": args.model,
        "sandbox": args.sandbox,
        "load_user_config": args.load_user_config,
        "ephemeral": args.ephemeral,
        "workspace": str(workspace),
        "workspace_commit": workspace_commit,
        "prompt_file": str(prompt_path),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "evidence": {
            "events": events_path.name,
            "stderr": stderr_path.name,
            "final_message": final_message_path.name,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(json.dumps(manifest, indent=2))
    if exit_code != 0:
        print(f"Codex run failed with exit code {exit_code}; see {stderr_path}", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

