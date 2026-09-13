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
from bench_goal_plus.goal_plus_evidence import (
    frozen_agent_harness,
    session_agent_harness,
    session_worker_intervals,
)
from bench_goal_plus.search_scheduler import summarize_worker_concurrency
from bench_runtime_paths import configure_temp_environment

from . import io
from .asset_issues import asset_issue_matches_revision, known_asset_issues
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
    add_pi_usage_values(total, usage)
    return True


def add_pi_usage_values(total: dict[str, int | float], usage: dict[str, Any]) -> None:
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
    total["assistant_messages"] += int(usage.get("assistantMessages", 1))
    if isinstance(usage.get("costTotal"), (int, float)):
        total["cost_usd"] += float(usage["costTotal"])


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
    initial_candidates: set[tuple[str, str]] = set()
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
    goal_records_seen = 0
    completed_goal_reports: list[bool] = []
    annotation_usage: dict[str, int | float] = {}
    annotation_tasks = 0
    annotation_attempts = 0
    annotation_states: dict[str, int] = defaultdict(int)
    worker_usage: dict[str, int | float] = defaultdict(int)
    worker_logs = 0
    native_worker_usage: dict[str, int | float] = defaultdict(int)
    native_worker_sessions = 0
    run_records: dict[str, dict[str, Any]] = {}
    frozen_specs: dict[str, dict[str, Any]] = {}
    worker_intervals: list[dict[str, Any]] = []
    try:
        with tarfile.open(archive_path) as archive:
            archive_files = {
                member.name for member in archive.getmembers()
                if member.isfile() and member.size > 0
            }
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
                            run_records[run_match.group(1)] = payload
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
                    run_id, candidate_id = match.groups()
                    search_runs.add(run_id)
                    candidates.add((run_id, candidate_id))
                    extracted = archive.extractfile(member)
                    if extracted:
                        try:
                            payload = json.loads(
                                extracted.read().decode("utf-8", errors="replace")
                            )
                            task = payload.get("task")
                            task = task if isinstance(task, dict) else {}
                            if int(task.get("allocation_depth") or 0) == 0:
                                initial_candidates.add((run_id, candidate_id))
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
                if "/goal-plus/" in member.name and member.name.endswith(
                    "/goal.json"
                ):
                    goal_records_seen += 1
                    extracted = archive.extractfile(member)
                    if extracted:
                        try:
                            payload = json.loads(
                                extracted.read().decode("utf-8", errors="replace")
                            )
                            if not isinstance(payload, dict):
                                continue
                            linked = payload.get("linked_search")
                            linked = linked if isinstance(linked, dict) else {}
                            report_names = []
                            for key in ("report_path", "html_report_path"):
                                value = linked.get(key)
                                if isinstance(value, str) and value.startswith("/home/agent/.goal-plus/"):
                                    relative = value.removeprefix("/home/agent/.goal-plus/")
                                    report_names.append(member.name.split("/goal-plus/", 1)[0] + "/" + relative)
                            completed_goal_reports.append(bool(
                                payload.get("status") == "complete"
                                and linked.get("result_recorded_at")
                                and len(report_names) == 2
                                and all(name in archive_files for name in report_names)
                            ))
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
                                | {
                                    "linked_run_id": (
                                        (payload.get("linked_search") or {}).get(
                                            "run_id"
                                        )
                                    )
                                }
                            )
                        except (json.JSONDecodeError, TypeError):
                            pass
                spec_match = re.search(
                    r"/specs/([^/]+)/frozen_spec\.json$", member.name
                )
                if spec_match:
                    extracted = archive.extractfile(member)
                    if extracted:
                        try:
                            payload = json.loads(
                                extracted.read().decode("utf-8", errors="replace")
                            )
                            if isinstance(payload, dict):
                                frozen_specs[spec_match.group(1)] = payload
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
                            harness = session_agent_harness(payload)
                            intervals = session_worker_intervals(payload)
                            worker_intervals.extend(intervals)
                            worker_sessions.append(
                                {
                                    key: value
                                    for key, value in {
                                        "agent_session_id": session_id,
                                        "run_id": payload.get("run_id"),
                                        "candidate_id": candidate_id,
                                        "agent_harness": harness,
                                        "runtime_provider": payload.get("runtime_provider"),
                                        "execution_generation": payload.get("execution_generation", 0),
                                        "launch_confirmed": bool(harness and (intervals or session_verifier_runs)),
                                        "verifier_runs": session_verifier_runs,
                                        "updated_at": payload.get("updated_at"),
                                    }.items()
                                    if value is not None
                                }
                            )
                            handle = payload.get("session_handle")
                            if harness == "pi" and isinstance(handle, dict):
                                metrics = (handle.get("metadata") or {}).get("pi_metrics") or {}
                                usage = metrics.get("usage_total")
                                if isinstance(usage, dict) and usage:
                                    add_pi_usage_values(native_worker_usage, usage)
                                    native_worker_sessions += 1
                            if harness and isinstance(handle, dict) and session_id and (intervals or session_verifier_runs):
                                compact_handle = {
                                    key: handle.get(key)
                                    for key in (
                                        "agent_harness",
                                        "runtime_provider",
                                        "external_id",
                                    )
                                    if handle.get(key) is not None
                                }
                                if compact_handle:
                                    bound_worker_handles.append(
                                        {
                                            "agent_session_id": session_id,
                                            "run_id": payload.get("run_id"),
                                            "candidate_id": candidate_id,
                                            "execution_generation": payload.get("execution_generation", 0),
                                            **compact_handle,
                                        }
                                    )
                            if (
                                harness and session_verifier_runs > 0
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
    linked_run_ids = {
        str(item["linked_run_id"])
        for item in goal_statuses
        if isinstance(item.get("linked_run_id"), str)
        and item.get("linked_run_id")
    }
    contract_run_ids = linked_run_ids or search_runs
    search_run_contracts = []
    for run_id in sorted(contract_run_ids):
        run = run_records.get(run_id) or {}
        frozen_spec_id = run.get("frozen_spec_id")
        frozen = frozen_specs.get(str(frozen_spec_id)) or {}
        spec = frozen.get("spec") if isinstance(frozen.get("spec"), dict) else {}
        strategy = spec.get("strategy") if isinstance(spec.get("strategy"), dict) else {}
        budget = spec.get("budget") if isinstance(spec.get("budget"), dict) else {}
        search_run_contracts.append(
            {
                "run_id": run_id,
                "frozen_spec_id": frozen_spec_id,
                "frozen_spec_present": bool(frozen),
                "agent_harness": frozen_agent_harness(frozen),
                "runtime_provider": frozen.get("runtime_provider"),
                "max_parallel": budget.get("max_parallel"),
                "max_candidates": budget.get("max_candidates"),
                "orchestration_mode": strategy.get("orchestration_mode"),
                "search_scheduler": strategy.get("search_scheduler"),
            }
        )
    initial_candidate_ids = {candidate_id for _, candidate_id in initial_candidates}
    worker_concurrency = summarize_worker_concurrency(worker_intervals)
    initial_worker_concurrency = summarize_worker_concurrency(
        interval
        for interval in worker_intervals
        if interval.get("candidate_id") in initial_candidate_ids
    )
    run_evidence = []
    for run_id in sorted(search_runs):
        run = run_records.get(run_id) or {}
        frozen = frozen_specs.get(str(run.get("frozen_spec_id"))) or {}
        spec = frozen.get("spec") or {}
        run_candidates = {candidate for owner, candidate in candidates if owner == run_id}
        initial = {candidate for owner, candidate in initial_candidates if owner == run_id}
        run_sessions = [item for item in worker_sessions if item.get("run_id") == run_id]
        handles = [item for item in bound_worker_handles if item.get("run_id") == run_id]
        intervals = [item for item in worker_intervals if item.get("run_id") == run_id]
        selected = run.get("selected_candidate_id")
        harness = frozen_agent_harness(frozen)
        run_evidence.append({
            "run_id": run_id,
            "agent_harness": harness,
            "execution_contract_valid": bool(
                harness and all(
                    item.get("agent_harness") == harness
                    and item.get("runtime_provider") == "direct"
                    for item in run_sessions
                )
            ),
            "state": run.get("state"),
            "invalidated_at": run.get("invalidated_at"),
            "max_parallel": (spec.get("budget") or {}).get("max_parallel"),
            "candidates": len(run_candidates),
            "candidate_ids": sorted(run_candidates),
            "initial_candidates": len(initial),
            "initial_candidate_ids": sorted(initial),
            "agent_sessions": len(run_sessions),
            "bound_worker_handles": handles,
            "initial_agent_sessions": sum(item.get("candidate_id") in initial and item.get("execution_generation", 0) == 0 for item in run_sessions),
            "initial_bound_worker_handles": sum(item.get("candidate_id") in initial and item.get("execution_generation", 0) == 0 for item in handles),
            "actual_worker_launches": len(handles),
            "recovery_agent_sessions": sum(item.get("execution_generation", 0) > 0 for item in run_sessions),
            "confirmed_initial_worker_launches": sum(item.get("execution_generation", 0) == 0 and item.get("launch_confirmed", False) for item in run_sessions),
            "worker_verifier_runs": sum(item.get("verifier_runs", 0) for item in run_sessions),
            "verifier_candidate_ids": sorted({item["candidate_id"] for item in run_sessions if item.get("verifier_runs", 0) > 0}),
            "selected_candidate_ids": [selected] if selected else [],
            "promoted_candidate_ids": [selected] if selected and run.get("state") == "promoted" else [],
            "search_run_contracts": [item for item in search_run_contracts if item["run_id"] == run_id],
            "worker_concurrency": summarize_worker_concurrency(intervals),
            "initial_worker_concurrency": summarize_worker_concurrency(item for item in intervals if item.get("candidate_id") in initial),
        })
    harnesses = {item["agent_harness"] for item in run_evidence}
    if native_worker_sessions:
        worker_usage = native_worker_usage
        worker_logs = native_worker_sessions
    return {
        "search_runs": len(search_runs),
        "agent_harness": next(iter(harnesses)) if len(harnesses) == 1 else None,
        "execution_contract_valid": bool(
            run_evidence and len(harnesses) == 1
            and sessions == len(worker_sessions)
            and sessions == sum(item["agent_sessions"] for item in run_evidence)
            and all(item["execution_contract_valid"] for item in run_evidence)
        ),
        "actual_worker_launches": len({
            (item["agent_harness"], item["runtime_provider"], item["external_id"])
            for item in bound_worker_handles
        }),
        "run_evidence": run_evidence,
        "completion_run_ids": sorted(contract_run_ids),
        "worker_identity_concurrency": summarize_worker_concurrency(
            {**item, "candidate_id": f"{item['run_id']}/{item['candidate_id']}"}
            for item in worker_intervals
            if item.get("run_id") and item.get("candidate_id")
        ),
        "candidates": len(candidates),
        "candidate_ids": sorted({candidate_id for _, candidate_id in candidates}),
        "initial_candidates": len(initial_candidates),
        "initial_candidate_ids": sorted(initial_candidate_ids),
        "agent_sessions": sessions,
        "worker_sessions": worker_sessions,
        "bound_worker_handles": bound_worker_handles,
        "initial_agent_sessions": sum(
            (str(item.get("run_id")), str(item.get("candidate_id")))
            in initial_candidates
            and item.get("execution_generation", 0) == 0
            for item in worker_sessions
        ),
        "initial_bound_worker_handles": sum(
            (str(item.get("run_id")), str(item.get("candidate_id")))
            in initial_candidates
            and item.get("execution_generation", 0) == 0
            for item in bound_worker_handles
        ),
        "recovery_agent_sessions": sum(item.get("execution_generation", 0) > 0 for item in worker_sessions),
        "confirmed_initial_worker_launches": sum(item.get("execution_generation", 0) == 0 and item.get("launch_confirmed", False) for item in worker_sessions),
        "confirmed_cumulative_worker_launches": sum(item.get("launch_confirmed", False) for item in worker_sessions),
        "worker_verifier_runs": verifier_runs,
        "verifier_candidate_ids": sorted(verifier_candidates),
        "verifier_candidate_count": len(verifier_candidates),
        "search_run_states": dict(sorted(search_run_states.items())),
        "selected_candidate_ids": sorted(selected_candidate_ids),
        "promoted_candidate_ids": sorted(promoted_candidate_ids),
        "goal_statuses": goal_statuses,
        "terminal_ready": bool(
            goal_records_seen and len(completed_goal_reports) == goal_records_seen
            and all(completed_goal_reports)
        ),
        "search_run_contracts": search_run_contracts,
        "worker_concurrency": worker_concurrency,
        "initial_worker_concurrency": initial_worker_concurrency,
        "worker_usage": {
            **dict(sorted(worker_usage.items())),
            "sessions": worker_logs,
            "coverage": (
                "persisted native Pi session usage" if native_worker_sessions
                else "persisted Pi worker message usage"
            ),
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


def remaining_time(
    cell: dict[str, Any], task_run: Path | None = None
) -> dict[str, int | None]:
    started: datetime | None = None
    if task_run is not None:
        try:
            lines = (task_run / "started_at").read_text(encoding="utf-8").splitlines()
            if len(lines) >= 2:
                started = datetime.fromtimestamp(float(lines[1]), tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass
    if started is None:
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
        "actual_worker_launch_count": (
            int(events["spawned_agent_thread_count"])
            if cell.get("method") == "goal-plus-codex"
            else max(
                int(event_goal_plus["bound_worker_handle_count"]),
                int((live or {}).get("actual_worker_launch_count") or 0),
                int((archived or {}).get("agent_sessions") or 0),
            )
        ),
        "worker_launches_by_generation": (live or {}).get("worker_launches_by_generation"),
        "confirmed_worker_launch_count": (live or {}).get("confirmed_worker_launch_count"),
        "pi_live_worker_count": (live or {}).get("pi_live_worker_count"),
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
        "remaining": remaining_time(cell, task_run),
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
    if any(int((item.get("goal_plus") or {}).get("search_runs") or 0) > 1 for item in observations):
        return successor_completion_evidence(cell, observations, valid_trajectories=valid_trajectories)
    expected_workers = int(cell["inner_search_concurrency"])
    scheduler_contract = (cell.get("goal_plus_config") or {}).get(
        "search_scheduler"
    )
    scheduler_enabled = isinstance(scheduler_contract, dict)
    max_candidates = (
        scheduler_contract.get("max_candidates") if scheduler_enabled else None
    )
    candidates = 0
    initial_candidates = 0
    agent_sessions = 0
    initial_agent_sessions = 0
    recovery_agent_sessions = 0
    confirmed_initial_worker_launches = 0
    recovery_concurrency: list[dict[str, Any]] = []
    verifier_candidates: set[str] = set()
    verifier_runs = 0
    spawned_worker_threads = 0
    bound_worker_handles = 0
    initial_bound_worker_handles = 0
    selected: set[str] = set()
    promoted: set[str] = set()
    actual_scheduler_contracts: list[dict[str, Any]] = []
    scheduler_worker_evidence: list[dict[str, Any]] = []
    execution_contract_valid = bool(observations)
    terminal_ready = bool(observations)
    for observation in observations:
        archived = observation.get("goal_plus") or {}
        terminal_ready = terminal_ready and archived.get("terminal_ready") is True
        expected_harness = "codex" if cell["method"] == "goal-plus-codex" else "pi"
        execution_contract_valid = (
            execution_contract_valid and archived.get("execution_contract_valid") is True
            and archived.get("agent_harness") == expected_harness
        )
        events = observation.get("agent_events") or {}
        event_goal_plus = events.get("goal_plus") or {}
        candidates = max(
            candidates,
            int(archived.get("candidates") or 0),
            len(event_goal_plus.get("candidate_ids") or []),
        )
        initial_candidates = max(
            initial_candidates,
            int(archived.get("initial_candidates") or 0),
        )
        agent_sessions = max(
            agent_sessions,
            int(archived.get("agent_sessions") or 0),
            len(event_goal_plus.get("agent_session_ids") or []),
        )
        initial_agent_sessions = max(
            initial_agent_sessions,
            int(archived.get("initial_agent_sessions") or 0),
        )
        recovered = int(archived.get("recovery_agent_sessions") or 0)
        recovery_agent_sessions = max(recovery_agent_sessions, recovered)
        confirmed_initial_worker_launches = max(confirmed_initial_worker_launches, int(archived.get("confirmed_initial_worker_launches") or 0))
        if recovered:
            recovery_concurrency.append(archived.get("worker_concurrency") or {})
        spawned_worker_threads = max(
            spawned_worker_threads,
            int(events.get("spawned_agent_thread_count") or 0),
            int(archived.get("actual_worker_launches") or 0),
        )
        bound_worker_handles = max(
            bound_worker_handles,
            len(archived.get("bound_worker_handles") or []),
            int(event_goal_plus.get("bound_worker_handle_count") or 0),
        )
        initial_bound_worker_handles = max(
            initial_bound_worker_handles,
            int(archived.get("initial_bound_worker_handles") or 0),
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
        actual_scheduler_contracts.extend(
            contract
            for contract in archived.get("search_run_contracts") or []
            if isinstance(contract, dict)
        )
        scheduler_worker_evidence.append(
            {
                "candidate_ids": archived.get("candidate_ids") or [],
                "initial_candidate_ids": archived.get("initial_candidate_ids") or [],
                "all": archived.get("worker_concurrency") or {},
                "initial": archived.get("initial_worker_concurrency") or {},
            }
        )

    requested_scheduler_spec = (
        scheduler_contract.get("search_scheduler") if scheduler_enabled else None
    )
    scheduler_contract_passed = bool(
        not scheduler_enabled
        or (
            actual_scheduler_contracts
            and all(
                contract.get("frozen_spec_present") is True
                and contract.get("max_parallel") == expected_workers
                and contract.get("max_candidates") == max_candidates
                and contract.get("orchestration_mode") == "adaptive_search"
                and contract.get("search_scheduler") == requested_scheduler_spec
                for contract in actual_scheduler_contracts
            )
        )
    )
    live_worker_limit_passed = bool(
        not scheduler_enabled
        or (
            scheduler_worker_evidence
            and all(
                evidence["all"].get("invalid_interval_count") == 0
                and set(evidence["all"].get("candidate_ids") or [])
                == set(evidence["candidate_ids"])
                and isinstance(evidence["all"].get("max_live_workers"), int)
                and evidence["all"]["max_live_workers"] <= expected_workers
                and evidence["initial"].get("invalid_interval_count") == 0
                and set(evidence["initial"].get("candidate_ids") or [])
                == set(evidence["initial_candidate_ids"])
                and len(evidence["initial_candidate_ids"]) == expected_workers
                for evidence in scheduler_worker_evidence
            )
        )
    )

    candidate_limit_passed = (
        candidates >= expected_workers
        and (not scheduler_enabled or initial_candidates == expected_workers)
        and (max_candidates is None or candidates <= int(max_candidates))
    )
    agent_sessions_passed = (
        initial_agent_sessions == expected_workers and agent_sessions >= candidates
        if scheduler_enabled
        else agent_sessions >= expected_workers
    )
    actual_worker_launches_passed = (
        initial_bound_worker_handles == expected_workers
        if scheduler_enabled
        else spawned_worker_threads >= expected_workers
    )
    spawn_coverage_passed = max(spawned_worker_threads, bound_worker_handles) >= (
        candidates if scheduler_enabled else expected_workers
    )
    checks: dict[str, dict[str, Any]] = {
        "valid_trajectory": {
            "expected": 1,
            "actual": valid_trajectories,
        },
        "candidates": {
            "expected": (
                {
                    "initial": expected_workers,
                    "cumulative_minimum": expected_workers,
                    "cumulative_maximum": max_candidates,
                }
                if scheduler_enabled
                else expected_workers
            ),
            "actual": candidates,
        },
        "agent_sessions": {
            "expected": (
                {"initial": expected_workers, "cumulative_minimum": candidates}
                if scheduler_enabled
                else expected_workers
            ),
            "actual": (
                {
                    "initial": initial_agent_sessions,
                    "cumulative": agent_sessions,
                }
                if scheduler_enabled
                else agent_sessions
            ),
        },
        "worker_verifier_runs": {
            "expected": expected_workers,
            "actual": verifier_runs,
        },
        "promotion": {
            "expected": 1,
            "actual": max(len(selected), len(promoted)),
        },
        "search_scheduler_contract": {
            "expected": (
                {
                    "max_parallel": expected_workers,
                    "max_candidates": max_candidates,
                    "orchestration_mode": "adaptive_search",
                    "search_scheduler": requested_scheduler_spec,
                }
                if scheduler_enabled
                else "not required"
            ),
            "actual": actual_scheduler_contracts,
        },
        "scheduler_live_worker_limit": {
            "expected": (
                {"initial_workers": expected_workers, "maximum_live": expected_workers}
                if scheduler_enabled
                else "not required"
            ),
            "actual": scheduler_worker_evidence,
        },
    }
    if cell["method"] == "goal-plus-codex":
        checks["actual_worker_launches"] = {
            "expected": expected_workers,
            "actual": (
                initial_bound_worker_handles
                if scheduler_enabled
                else spawned_worker_threads
            ),
        }
        checks["spawn_agent_event_coverage"] = {
            "expected": candidates if scheduler_enabled else expected_workers,
            "actual": max(spawned_worker_threads, bound_worker_handles),
        }
    checks["verifier_candidate_coverage"] = {
        "expected": expected_workers,
        "actual": len(verifier_candidates),
    }
    required_evidence_present = all(
        (
            execution_contract_valid,
            valid_trajectories >= 1,
            candidate_limit_passed,
            agent_sessions_passed,
            verifier_runs >= expected_workers,
            max(len(selected), len(promoted)) >= 1,
            len(verifier_candidates) >= expected_workers,
            scheduler_contract_passed,
            live_worker_limit_passed,
            (
                actual_worker_launches_passed and spawn_coverage_passed
                if cell["method"] == "goal-plus-codex"
                else True
            ),
        )
    )
    actual_subagent_check = (
        checks["actual_worker_launches"]
        if cell["method"] == "goal-plus-codex"
        else checks["agent_sessions"]
    )
    actual_subagent_count = (
        confirmed_initial_worker_launches
        if recovery_agent_sessions
        else
        initial_agent_sessions
        if scheduler_enabled and cell["method"] != "goal-plus-codex"
        else int(actual_subagent_check["actual"])
    )
    if cell["method"] != "goal-plus-codex":
        actual_subagent_count = confirmed_initial_worker_launches
        checks["actual_worker_launches"] = {
            "expected": expected_workers, "actual": actual_subagent_count,
        }
    checks["execution_contract"] = {"expected": True, "actual": execution_contract_valid}
    checks["goal_terminal_and_reports"] = {"expected": True, "actual": terminal_ready}
    actual_subagent_count_matches_k = actual_subagent_count == expected_workers
    recovery_parallelism_passed = not recovery_agent_sessions or bool(
        recovery_concurrency and all(
            item.get("invalid_interval_count") == 0
            and isinstance(item.get("max_live_workers"), int)
            and item["max_live_workers"] <= expected_workers
            and set(item.get("candidate_ids") or []) >= verifier_candidates
            for item in recovery_concurrency
        )
    )
    if recovery_agent_sessions:
        checks["recovery_workers"] = {
            "expected": {"initial_actual_workers": expected_workers, "maximum_live": expected_workers},
            "actual": {"initial_actual_workers": confirmed_initial_worker_launches,
                       "recovery_sessions": recovery_agent_sessions, "concurrency": recovery_concurrency},
        }
    passed = required_evidence_present and actual_subagent_count_matches_k and recovery_parallelism_passed and terminal_ready
    return {
        "required": True,
        "passed": passed,
        "checks": checks,
        "reason": (
            None
            if passed
            else "Goal Plus Goal terminal status or final reports are missing"
            if not terminal_ready
            else "Goal Plus method did not persist the required initial K actual "
            "subagents, scheduler candidate limit, verifier, promotion, and official "
            "trajectory evidence"
        ),
        "search_scheduler_enabled": scheduler_enabled,
        "actual_subagent_count": actual_subagent_count,
        "cumulative_candidate_count": candidates,
        "cumulative_agent_session_count": agent_sessions,
        "recovery_agent_session_count": recovery_agent_sessions,
        "recovery_parallelism_passed": recovery_parallelism_passed,
    }


def successor_completion_evidence(
    cell: dict[str, Any], observations: list[dict[str, Any]], *, valid_trajectories: int,
) -> dict[str, Any]:
    """Verify the current Search separately from invalidated predecessor runs."""
    expected_workers = int(cell["inner_search_concurrency"])
    results = []
    histories = []
    cumulative_candidates = cumulative_sessions = 0
    for observation in observations:
        archived = observation.get("goal_plus") or {}
        runs = archived.get("run_evidence") or []
        current_ids = set(archived.get("completion_run_ids") or [])
        current = [run for run in runs if run.get("run_id") in current_ids]
        concurrency = archived.get("worker_identity_concurrency") or {}
        expected_identities = {
            f"{run['run_id']}/{handle['candidate_id']}"
            for run in runs for handle in run.get("bound_worker_handles") or []
        }
        history_passed = bool(
            archived.get("execution_contract_valid") is True
            and len(runs) == archived.get("search_runs")
            and len({run.get("run_id") for run in runs}) == len(runs)
            and len(current_ids) == len(current) == 1
            and all(run.get("max_parallel") == expected_workers for run in runs)
            and all(
                run.get("state") == "aborted" and run.get("invalidated_at")
                and run.get("initial_bound_worker_handles", 0) <= expected_workers
                for run in runs if run.get("run_id") not in current_ids
            )
            and concurrency.get("invalid_interval_count") == 0
            and isinstance(concurrency.get("max_live_workers"), int)
            and concurrency["max_live_workers"] <= expected_workers
            and expected_identities
            and set(concurrency.get("candidate_ids") or []) == expected_identities
        )
        histories.append({"passed": history_passed, "completion_run_ids": sorted(current_ids), "concurrency": concurrency})
        for run in current:
            result = goal_plus_completion_evidence(
                cell, [{"goal_plus": {**run, "terminal_ready": archived.get("terminal_ready")}}],
                valid_trajectories=valid_trajectories,
            )
            result["passed"] = result["passed"] and run.get("initial_bound_worker_handles") == expected_workers
            results.append(result)
        cumulative_candidates = max(cumulative_candidates, int(archived.get("candidates") or 0))
        cumulative_sessions = max(cumulative_sessions, int(archived.get("agent_sessions") or 0))
    passed = bool(results and all(item["passed"] for item in results) and all(item["passed"] for item in histories))
    return {
        "required": True, "passed": passed,
        "checks": {"current_search": {"expected": expected_workers, "actual": results},
                   "successor_history": {"expected": "invalidated predecessors and trajectory live workers <= K", "actual": histories}},
        "reason": None if passed else "Goal Plus current Search evidence or successor worker isolation is incomplete",
        "search_scheduler_enabled": isinstance((cell.get("goal_plus_config") or {}).get("search_scheduler"), dict),
        "actual_subagent_count": max((item["actual_subagent_count"] for item in results), default=0),
        "cumulative_candidate_count": cumulative_candidates,
        "cumulative_agent_session_count": cumulative_sessions,
        "recovery_agent_session_count": sum(item.get("recovery_agent_session_count", 0) for item in results),
        "recovery_parallelism_passed": all(item.get("recovery_parallelism_passed", False) for item in results),
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


def asset_protocol_issue(task_id: str, dataset_revision: str | None) -> str | None:
    for issue in known_asset_issues():
        if (
            issue.get("task_id") == task_id
            and asset_issue_matches_revision(issue, dataset_revision)
            and issue.get("severity") == "blocking"
        ):
            return f"{issue['id']}: {issue['reason']}"
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
    campaign = io.read_json(destination / "campaign.json")
    known_issue = paper_protocol_issue(cell) or asset_protocol_issue(
        str(cell["task_id"]), campaign.get("dataset_revision")
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
        "known_protocol_issue": known_issue,
        "finalized_at": io.utc_now(),
    }
    io.write_json(cell_path / "summary.json", summary)
    return summary
