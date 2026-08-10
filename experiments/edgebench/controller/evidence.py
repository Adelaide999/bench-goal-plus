"""Collect EdgeBench, Codex, Goal Plus, and completion evidence."""

from __future__ import annotations

import json
import os
import re
import sys
import tarfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from bench_goal_plus.agent_events import parse_codex_event_file
from bench_runtime_paths import configure_temp_environment

from . import io
from .context import current_paths
from .profiles import GOAL_PLUS_METHODS, LEGACY_PAPER_PROTOCOL_ISSUES


def iter_json_lines(text: str) -> Iterable[dict[str, Any]]:
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            yield item


def add_usage(total: dict[str, int | float], event: dict[str, Any]) -> None:
    if event.get("type") != "turn.completed":
        return
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return
    for key, value in usage.items():
        if isinstance(value, int) and not isinstance(value, bool):
            total[key] += value


def add_pi_usage(total: dict[str, int | float], event: dict[str, Any]) -> bool:
    if event.get("type") != "message_end":
        return False
    usage = event.get("usage")
    if not isinstance(usage, dict):
        message = event.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return False
    values: dict[str, int] = {}
    for source, target in (
        ("input", "input_tokens"),
        ("cacheRead", "cached_input_tokens"),
        ("cacheWrite", "cache_write_tokens"),
        ("output", "output_tokens"),
        ("reasoning", "reasoning_output_tokens"),
    ):
        value = usage.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values[target] = int(value)
            total[target] += int(value)
    total["total_tokens"] += values.get("input_tokens", 0) + values.get(
        "output_tokens", 0
    )
    total["processed_tokens"] += sum(
        values.get(key, 0)
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "output_tokens",
        )
    )
    cost = usage.get("cost")
    if isinstance(cost, dict) and isinstance(cost.get("total"), (int, float)):
        total["cost_usd"] += float(cost["total"])
    total["assistant_messages"] += 1
    return True


def codex_usage(task_run: Path) -> dict[str, Any]:
    totals: dict[str, int | float] = defaultdict(int)
    session_ids: set[str] = set()
    pi_messages = 0
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
                    rollout_total: dict[str, int] = {}
                    for event in iter_json_lines(
                        extracted.read().decode("utf-8", errors="replace")
                    ):
                        if event.get("type") == "thread.started" and event.get(
                            "thread_id"
                        ):
                            session_ids.add(str(event["thread_id"]))
                        if event.get("type") == "session_meta":
                            payload = event.get("payload", {})
                            if isinstance(payload, dict):
                                session_id = payload.get("id") or payload.get(
                                    "session_id"
                                )
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
            for event in iter_json_lines(
                output.read_text(encoding="utf-8", errors="replace")
            ):
                if event.get("type") == "thread.started" and event.get("thread_id"):
                    session_ids.add(str(event["thread_id"]))
                if event.get("type") == "session" and event.get("id"):
                    session_ids.add(str(event["id"]))
                add_usage(totals, event)
                if add_pi_usage(totals, event):
                    pi_messages += 1
            if pi_messages:
                coverage = "pi_agent_output"
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
    worker_sessions: list[dict[str, Any]] = []
    bound_worker_handles: list[dict[str, Any]] = []
    verifier_runs = 0
    verifier_candidates: set[str] = set()
    search_runs: set[str] = set()
    search_run_states: dict[str, int] = defaultdict(int)
    selected_candidate_ids: set[str] = set()
    promoted_candidate_ids: set[str] = set()
    goal_statuses: list[dict[str, Any]] = []
    annotation_usage: dict[str, int | float] = {}
    annotation_tasks = 0
    annotation_attempts = 0
    annotation_states: dict[str, int] = defaultdict(int)
    worker_usage: dict[str, int | float] = defaultdict(int)
    worker_logs = 0
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
                            selected_candidate_id = payload.get(
                                "selected_candidate_id"
                            )
                            if (
                                isinstance(selected_candidate_id, str)
                                and selected_candidate_id
                            ):
                                selected_candidate_ids.add(selected_candidate_id)
                                if state == "promoted":
                                    promoted_candidate_ids.add(
                                        selected_candidate_id
                                    )
                        except (json.JSONDecodeError, TypeError):
                            pass
                match = re.search(
                    r"/runs/([^/]+)/candidates/([^/]+)/candidate\.json$",
                    member.name,
                )
                if match:
                    search_runs.add(match.group(1))
                    candidates.add((match.group(1), match.group(2)))
                if "/goal-plus/" in member.name and member.name.endswith(
                    "/goal.json"
                ):
                    extracted = archive.extractfile(member)
                    if extracted:
                        try:
                            payload = json.loads(
                                extracted.read().decode("utf-8", errors="replace")
                            )
                            goal_statuses.append(
                                {
                                    key: payload.get(key)
                                    for key in (
                                        "goal_plus_id",
                                        "status",
                                        "phase",
                                        "updated_at",
                                    )
                                    if payload.get(key) is not None
                                }
                            )
                        except (json.JSONDecodeError, TypeError):
                            pass
                if "/agent_sessions/" in member.name and member.name.endswith(".json"):
                    sessions += 1
                    extracted = archive.extractfile(member)
                    if extracted:
                        try:
                            payload = json.loads(
                                extracted.read().decode("utf-8", errors="replace")
                            )
                            session_verifier_runs = int(
                                payload.get("counters", {}).get("verifier_runs", 0)
                            )
                            verifier_runs += session_verifier_runs
                            session_id = payload.get("agent_session_id")
                            candidate_id = payload.get("candidate_id")
                            worker_sessions.append(
                                {
                                    key: value
                                    for key, value in {
                                        "agent_session_id": session_id,
                                        "run_id": payload.get("run_id"),
                                        "candidate_id": candidate_id,
                                        "host": payload.get("host"),
                                        "verifier_runs": session_verifier_runs,
                                        "updated_at": payload.get("updated_at"),
                                    }.items()
                                    if value is not None
                                }
                            )
                            handle = payload.get("host_handle")
                            if isinstance(handle, dict) and session_id:
                                compact_handle = {
                                    key: handle.get(key)
                                    for key in (
                                        "host",
                                        "task_name",
                                        "external_id",
                                    )
                                    if handle.get(key) is not None
                                }
                                if compact_handle:
                                    bound_worker_handles.append(
                                        {
                                            "agent_session_id": session_id,
                                            **compact_handle,
                                        }
                                    )
                            if (
                                session_verifier_runs > 0
                                and isinstance(candidate_id, str)
                                and candidate_id
                            ):
                                verifier_candidates.add(candidate_id)
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
                if "/evidence-annotations/" in member.name and member.name.endswith(
                    ".json"
                ):
                    extracted = archive.extractfile(member)
                    if extracted:
                        try:
                            payload = json.loads(
                                extracted.read().decode("utf-8", errors="replace")
                            )
                            annotation_tasks += 1
                            annotation_attempts += int(payload.get("attempts") or 0)
                            annotation_states[
                                str(payload.get("state") or "unknown")
                            ] += 1
                            task_usage = payload.get("usage")
                            if not isinstance(task_usage, dict):
                                task_usage = {}
                            for key, value in task_usage.items():
                                if isinstance(value, (int, float)) and not isinstance(
                                    value, bool
                                ):
                                    annotation_usage[key] = (
                                        annotation_usage.get(key, 0) + value
                                    )
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
                if (
                    "/host-logs/pi-rpc-" in member.name
                    and member.name.endswith(".jsonl")
                ):
                    extracted = archive.extractfile(member)
                    if extracted:
                        worker_logs += 1
                        text = extracted.read().decode("utf-8", errors="replace")
                        for event in iter_json_lines(text):
                            add_pi_usage(worker_usage, event)
    except tarfile.TarError:
        return {"archive": "invalid"}
    return {
        "search_runs": len(search_runs),
        "candidates": len(candidates),
        "candidate_ids": sorted({candidate_id for _, candidate_id in candidates}),
        "agent_sessions": sessions,
        "worker_sessions": worker_sessions,
        "bound_worker_handles": bound_worker_handles,
        "worker_verifier_runs": verifier_runs,
        "verifier_candidate_ids": sorted(verifier_candidates),
        "verifier_candidate_count": len(verifier_candidates),
        "search_run_states": dict(sorted(search_run_states.items())),
        "selected_candidate_ids": sorted(selected_candidate_ids),
        "promoted_candidate_ids": sorted(promoted_candidate_ids),
        "goal_statuses": goal_statuses,
        "worker_usage": {
            **dict(sorted(worker_usage.items())),
            "sessions": worker_logs,
            "coverage": "persisted Pi worker message usage",
        },
        "evidence_annotator_usage": {
            **annotation_usage,
            "tasks": annotation_tasks,
            "attempts": annotation_attempts,
            "states": dict(sorted(annotation_states.items())),
            "coverage": "persisted Goal Plus Evidence annotator turns",
        },
    }


def goal_plus_live_snapshot(task_run: Path) -> dict[str, Any] | None:
    """Read the compact snapshot emitted by a live SForge Goal Plus agent."""

    path = task_run / "goal-plus-live-status.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _merge_keyed_records(
    older: list[dict[str, Any]],
    newer: list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for item in [*older, *newer]:
        if not isinstance(item, dict):
            continue
        value = item.get(key)
        if isinstance(value, str) and value:
            merged[value] = {**merged.get(value, {}), **item}
        else:
            unkeyed.append(item)
    return [merged[value] for value in sorted(merged)] + unkeyed


def latest_judge_report(
    destination: Path,
    cell: dict[str, Any],
    task_run: Path | None,
) -> dict[str, Any] | None:
    paths: set[Path] = set()
    if task_run is not None:
        paths.update((task_run / "submissions").glob("*/report.json"))
    paths.update(
        (
            destination
            / "judge"
            / "runs"
            / str(cell["sforge_run_id"])
            / str(cell["task_id"])
            / "submissions"
        ).glob("*/report.json")
    )
    reports: list[tuple[float, Path, dict[str, Any]]] = []
    for path in paths:
        try:
            payload = io.read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        submitted_at = payload.get("submitted_at")
        order = (
            float(submitted_at)
            if isinstance(submitted_at, (int, float))
            else path.stat().st_mtime
        )
        reports.append((order, path, payload))
    if not reports:
        return None
    _, path, payload = max(reports, key=lambda item: item[0])
    return {
        key: payload.get(key)
        for key in (
            "submission_id",
            "score",
            "score_0_100",
            "valid",
            "submitted_at",
            "passed",
        )
        if payload.get(key) is not None
    } | {"path": io.portable_path(path)}


def remaining_time(cell: dict[str, Any]) -> dict[str, int | None]:
    started_at = cell.get("started_at")
    if not isinstance(started_at, str):
        return {"exploration_seconds": None, "finalization_seconds": None}
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        return {"exploration_seconds": None, "finalization_seconds": None}
    elapsed = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
    exploration = int(cell["wall_time_seconds"])
    grace = int(cell.get("goal_plus_finalization_grace_seconds", 300))
    if cell.get("state") in {"completed", "failed", "interrupted", "partial"}:
        return {"exploration_seconds": 0, "finalization_seconds": 0}
    return {
        "exploration_seconds": max(0, exploration - elapsed),
        "finalization_seconds": max(0, exploration + grace - elapsed),
    }


def live_goal_plus_status(
    destination: Path,
    cell: dict[str, Any],
    task_run: Path | None,
) -> dict[str, Any]:
    events = (
        parse_codex_event_file(task_run / "agent_output.txt")
        if task_run is not None
        else parse_codex_event_file(Path(""))
    )
    event_goal_plus = events["goal_plus"]
    live = goal_plus_live_snapshot(task_run) if task_run is not None else None
    archived = goal_plus_stats(task_run) if task_run is not None else None
    live_candidate_ids = (live or {}).get("candidate_ids") or []
    archived_candidate_ids = (archived or {}).get("candidate_ids") or []
    candidate_ids = sorted(
        {
            *event_goal_plus["candidate_ids"],
            *map(str, live_candidate_ids),
            *map(str, archived_candidate_ids),
        }
    )
    live_sessions = (live or {}).get("worker_sessions") or []
    worker_sessions = _merge_keyed_records(
        event_goal_plus["worker_sessions"], live_sessions, "agent_session_id"
    )
    worker_sessions = _merge_keyed_records(
        worker_sessions,
        (archived or {}).get("worker_sessions") or [],
        "agent_session_id",
    )
    live_handles = (live or {}).get("bound_worker_handles") or []
    bound_worker_handles = _merge_keyed_records(
        event_goal_plus["bound_worker_handles"],
        live_handles,
        "agent_session_id",
    )
    bound_worker_handles = _merge_keyed_records(
        bound_worker_handles,
        (archived or {}).get("bound_worker_handles") or [],
        "agent_session_id",
    )
    live_ledger = (live or {}).get("verifier_ledger") or []
    verifier_ledger = max(
        (event_goal_plus["verifier_ledger"], live_ledger),
        key=len,
    )
    goal_statuses = _merge_keyed_records(
        event_goal_plus["goal_statuses"],
        (live or {}).get("goal_statuses") or [],
        "goal_plus_id",
    )
    goal_statuses = _merge_keyed_records(
        goal_statuses,
        (archived or {}).get("goal_statuses") or [],
        "goal_plus_id",
    )
    evidence_annotations = (live or {}).get("evidence_annotations")
    if not isinstance(evidence_annotations, dict):
        archived_usage = (archived or {}).get("evidence_annotator_usage")
        evidence_annotations = (
            {
                "tasks": archived_usage.get("tasks"),
                "attempts": archived_usage.get("attempts"),
                "views_published": archived_usage.get("states", {}).get(
                    "completed", 0
                ),
                "states": archived_usage.get("states") or {},
                "active_attempts": [],
                "recent_attempts": [],
                "monitor_files": 0,
            }
            if isinstance(archived_usage, dict)
            else None
        )
    state_sources = []
    if live is not None:
        state_sources.append("goal-plus-live-status.json")
    if archived is not None:
        state_sources.append("goal-plus-state.tar")
    if any(
        (
            event_goal_plus["candidate_ids"],
            event_goal_plus["agent_session_ids"],
            event_goal_plus["verifier_ledger"],
            event_goal_plus["goal_statuses"],
        )
    ):
        state_sources.append("codex-event-stream")
    return {
        "candidate_ids": candidate_ids,
        "candidate_count": max(
            len(candidate_ids),
            int((live or {}).get("candidate_count") or 0),
            int((archived or {}).get("candidates") or 0),
        ),
        "worker_sessions": worker_sessions,
        "agent_session_count": max(
            len(event_goal_plus["agent_session_ids"]),
            len(worker_sessions),
            int((live or {}).get("agent_session_count") or 0),
            int((archived or {}).get("agent_sessions") or 0),
        ),
        "spawned_worker_thread_ids": events["spawned_agent_thread_ids"],
        "spawn_agent_completed_count": events["spawn_agent_completed_count"],
        "bound_worker_handles": bound_worker_handles,
        "actual_worker_launch_count": max(
            int(events["spawned_agent_thread_count"]),
            int(event_goal_plus["bound_worker_handle_count"]),
            int((live or {}).get("actual_worker_launch_count") or 0),
            int((archived or {}).get("agent_sessions") or 0),
        ),
        "verifier_ledger": verifier_ledger,
        "worker_verifier_runs": max(
            len(verifier_ledger),
            int((live or {}).get("worker_verifier_runs") or 0),
            int((archived or {}).get("worker_verifier_runs") or 0),
        ),
        "verifier_candidate_ids": sorted(
            {
                *(
                    str(item["candidate_id"])
                    for item in event_goal_plus["verifier_ledger"]
                    if isinstance(item, dict) and item.get("candidate_id")
                ),
                *((live or {}).get("verifier_candidate_ids") or []),
                *((archived or {}).get("verifier_candidate_ids") or []),
            }
        ),
        "selected_candidate_ids": sorted(
            {
                *event_goal_plus["selected_candidate_ids"],
                *((live or {}).get("selected_candidate_ids") or []),
                *((archived or {}).get("selected_candidate_ids") or []),
            }
        ),
        "promoted_candidate_ids": sorted(
            {
                *event_goal_plus["promoted_candidate_ids"],
                *((live or {}).get("promoted_candidate_ids") or []),
                *((archived or {}).get("promoted_candidate_ids") or []),
            }
        ),
        "evidence_annotations": evidence_annotations,
        "goal_statuses": goal_statuses,
        "terminal_ready": (live or {}).get("terminal_ready"),
        "snapshot_at": (live or {}).get("captured_at"),
        "state_sources": state_sources,
        "remaining": remaining_time(cell),
        "latest_judge_submission": latest_judge_report(destination, cell, task_run),
    }


def score_task_run(task_run: Path, cell: dict[str, Any]) -> dict[str, Any]:
    paths = current_paths()
    reporter = paths.edge_root / "scripts" / "report_edgebench_scores.py"
    command = [
        str(paths.venv_python if paths.venv_python.is_file() else Path(sys.executable)),
        str(reporter),
        "--run-dir",
        str(task_run),
        "--model",
        str(cell["model"]),
        "--budget-seconds",
        str(cell["wall_time_seconds"]),
        "--json",
    ]
    scored = io.run_capture(
        command, env=dict(configure_temp_environment(dict(os.environ)))
    )
    if scored["returncode"] != 0:
        return {
            "task_run": io.portable_path(task_run),
            "error": scored["stderr"] or scored["stdout"],
        }
    observation = json.loads(scored["stdout"])
    observation["source"] = io.portable_path(Path(observation["source"]))
    observation["task_run"] = io.portable_path(task_run)
    final = io.read_json(task_run / "final_result.json")
    for key in (
        "runtime_seconds",
        "total_rounds",
        "agent_submissions",
        "auto_submissions",
        "resume_count",
        "timed_out",
    ):
        observation[key] = final.get(key)
    evaluator_calls = 0
    for history_name, entry_type in (
        ("run_history.json", "submission"),
        ("game_history.json", "game"),
    ):
        history_path = task_run / history_name
        if not history_path.is_file():
            continue
        entries = io.read_json(history_path).get("entries", [])
        if isinstance(entries, list):
            evaluator_calls += sum(
                1
                for entry in entries
                if isinstance(entry, dict) and entry.get("type") == entry_type
            )
    if not evaluator_calls:
        evaluator_calls = len(list((task_run / "submissions").glob("*/report.json")))
    observation["evaluator_calls"] = evaluator_calls
    observation["codex_usage"] = codex_usage(task_run)
    observation["goal_plus"] = goal_plus_stats(task_run)
    observation["agent_events"] = parse_codex_event_file(
        task_run / "agent_output.txt"
    )
    return observation


def goal_plus_completion_evidence(
    cell: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    valid_trajectories: int,
) -> dict[str, Any]:
    if cell["method"] not in GOAL_PLUS_METHODS:
        return {
            "required": False,
            "passed": valid_trajectories == int(cell["outer_replicas"]),
            "checks": {
                "valid_trajectories": {
                    "expected": int(cell["outer_replicas"]),
                    "actual": valid_trajectories,
                }
            },
        }
    expected_workers = int(cell["inner_search_concurrency"])
    candidates = 0
    agent_sessions = 0
    verifier_candidates: set[str] = set()
    verifier_runs = 0
    spawned_worker_threads = 0
    bound_worker_handles = 0
    selected: set[str] = set()
    promoted: set[str] = set()
    for observation in observations:
        archived = observation.get("goal_plus") or {}
        events = observation.get("agent_events") or {}
        event_goal_plus = events.get("goal_plus") or {}
        candidates = max(
            candidates,
            int(archived.get("candidates") or 0),
            len(event_goal_plus.get("candidate_ids") or []),
        )
        agent_sessions = max(
            agent_sessions,
            int(archived.get("agent_sessions") or 0),
            len(event_goal_plus.get("agent_session_ids") or []),
        )
        spawned_worker_threads = max(
            spawned_worker_threads,
            int(events.get("spawned_agent_thread_count") or 0),
        )
        bound_worker_handles = max(
            bound_worker_handles,
            int(event_goal_plus.get("bound_worker_handle_count") or 0),
        )
        ledger = event_goal_plus.get("verifier_ledger") or []
        verifier_runs = max(
            verifier_runs,
            int(archived.get("worker_verifier_runs") or 0),
            len(ledger),
        )
        verifier_candidates.update(
            str(candidate_id)
            for candidate_id in archived.get("verifier_candidate_ids") or []
            if candidate_id
        )
        verifier_candidates.update(
            str(item["candidate_id"])
            for item in ledger
            if isinstance(item, dict) and item.get("candidate_id")
        )
        selected.update(archived.get("selected_candidate_ids") or [])
        selected.update(event_goal_plus.get("selected_candidate_ids") or [])
        promoted.update(archived.get("promoted_candidate_ids") or [])
        promoted.update(event_goal_plus.get("promoted_candidate_ids") or [])

    checks: dict[str, dict[str, Any]] = {
        "valid_trajectory": {"expected": 1, "actual": valid_trajectories},
        "candidates": {"expected": expected_workers, "actual": candidates},
        "agent_sessions": {"expected": expected_workers, "actual": agent_sessions},
        "worker_verifier_runs": {"expected": expected_workers, "actual": verifier_runs},
        "promotion": {"expected": 1, "actual": max(len(selected), len(promoted))},
    }
    if cell["method"] == "goal-plus-codex":
        checks["actual_worker_launches"] = {
            "expected": expected_workers,
            "actual": max(spawned_worker_threads, bound_worker_handles),
        }
        checks["spawn_agent_event_coverage"] = {
            "expected": 0,
            "actual": spawned_worker_threads,
        }
    checks["verifier_candidate_coverage"] = {
        "expected": expected_workers,
        "actual": len(verifier_candidates),
    }
    required_evidence_present = all(
        int(check["actual"]) >= int(check["expected"]) for check in checks.values()
    )
    actual_subagent_check = (
        checks["actual_worker_launches"]
        if cell["method"] == "goal-plus-codex"
        else checks["agent_sessions"]
    )
    actual_subagent_count_matches_k = (
        int(actual_subagent_check["actual"]) == expected_workers
    )
    passed = required_evidence_present and actual_subagent_count_matches_k
    return {
        "required": True,
        "passed": passed,
        "checks": checks,
        "reason": (
            None
            if passed
            else "Goal Plus method did not persist exactly K actual subagents plus "
            "the required verifier, promotion, and official trajectory evidence"
        ),
    }


def paper_protocol_issue(cell: dict[str, Any]) -> str | None:
    task_id = str(cell["task_id"])
    if task_id == "borden_source_inversion":
        if cell.get("submission_cooldown") != 120:
            return LEGACY_PAPER_PROTOCOL_ISSUES[task_id]
    elif task_id == "exchange_core_throughput":
        resources = (
            cell.get("work_cpu_limit"),
            cell.get("work_mem_limit"),
            cell.get("judge_cpu_limit"),
            cell.get("judge_mem_limit"),
        )
        if cell.get("internet") is not False or any(
            value is None for value in resources
        ):
            return LEGACY_PAPER_PROTOCOL_ISSUES[task_id]
    elif task_id.startswith("schemathesis_"):
        if cell.get("internet") is not False or cell.get(
            "submission_cooldown"
        ) != 216:
            return LEGACY_PAPER_PROTOCOL_ISSUES.get(task_id)
    return None


def summarize_cell(destination: Path, cell: dict[str, Any]) -> dict[str, Any]:
    cell_path = destination / "cells" / cell["cell_id"]
    task_runs = sorted((cell_path / "sforge" / "runs").glob(f"*/{cell['task_id']}"))
    observations = [
        score_task_run(task_run, cell)
        for task_run in task_runs
        if (task_run / "final_result.json").is_file()
    ]
    valid = [item for item in observations if "edgebench_score" in item]
    best = max(valid, key=lambda item: float(item["edgebench_score"])) if valid else None
    completion_evidence = goal_plus_completion_evidence(
        cell, observations, valid_trajectories=len(valid)
    )
    summary = {
        "schema_version": 1,
        "cell_id": cell["cell_id"],
        "task_id": cell["task_id"],
        "method": cell["method"],
        "model": cell["model"],
        "reasoning_effort": cell["reasoning_effort"],
        "metric_direction": cell["metric_direction"],
        "wall_time_seconds": cell["wall_time_seconds"],
        "live_search_concurrency": cell["live_search_concurrency"],
        "outer_replicas": cell["outer_replicas"],
        "inner_search_concurrency": cell["inner_search_concurrency"],
        "expected_trajectories": cell["outer_replicas"],
        "completed_trajectories": len(observations),
        "valid_trajectories": len(valid),
        "observations": observations,
        "best": best,
        "completion_evidence": completion_evidence,
        "incomplete_reason": completion_evidence.get("reason"),
        "protocol_classification": cell.get("protocol_classification"),
        "official_edgebench_comparable": cell.get(
            "official_edgebench_comparable", False
        ),
        "protocol_diff": cell.get("protocol_diff", []),
        "known_protocol_issue": paper_protocol_issue(cell),
        "finalized_at": io.utc_now(),
    }
    io.write_json(cell_path / "summary.json", summary)
    return summary
