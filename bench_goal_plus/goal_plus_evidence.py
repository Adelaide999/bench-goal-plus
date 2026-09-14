"""Read Goal Plus execution identities and summarize native worker evidence."""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Literal


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def summarize_worker_concurrency(
    intervals: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize persisted worker intervals for campaign evidence."""
    normalized: list[dict[str, str]] = []
    invalid_interval_count = 0
    events: list[tuple[datetime, int]] = []
    candidate_ids: set[str] = set()
    for interval in intervals:
        candidate_id = interval.get("candidate_id")
        started_at = interval.get("started_at")
        ended_at = interval.get("ended_at")
        started = _parse_timestamp(started_at)
        ended = _parse_timestamp(ended_at)
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or started is None
            or ended is None
            or ended <= started
        ):
            invalid_interval_count += 1
            continue
        normalized.append(
            {"candidate_id": candidate_id, "started_at": str(started_at),
             "ended_at": str(ended_at)}
        )
        candidate_ids.add(candidate_id)
        events.extend(((started, 1), (ended, -1)))
    live_workers = 0
    max_live_workers = 0
    for _, delta in sorted(events, key=lambda event: (event[0], event[1])):
        live_workers += delta
        max_live_workers = max(max_live_workers, live_workers)
    return {
        "interval_count": len(normalized),
        "invalid_interval_count": invalid_interval_count,
        "candidate_ids": sorted(candidate_ids),
        "max_live_workers": max_live_workers if normalized else None,
        "intervals": normalized,
    }


def session_agent_harness(session: Mapping[str, Any]) -> Literal["codex", "pi"] | None:
    handle = session.get("session_handle")
    harness = session.get("agent_harness")
    if (
        harness not in ("codex", "pi")
        or session.get("runtime_provider") != "direct"
        or not isinstance(handle, Mapping)
        or handle.get("agent_harness") != harness
        or handle.get("runtime_provider") != "direct"
        or not isinstance(handle.get("external_id"), str)
        or not handle["external_id"]
        or any(key in session for key in ("host", "host_handle"))
        or "host" in handle
    ):
        return None
    return harness


def session_worker_intervals(session: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Use native invocation receipts; allocation and resource release are not execution."""
    harness = session_agent_harness(session)
    if harness is None:
        return []
    handle = session["session_handle"]
    metadata = handle.get("metadata")
    if not isinstance(metadata, Mapping):
        return []
    dispatches = metadata.get("dispatches")
    if not isinstance(dispatches, list):
        return []
    receipts: dict[str, Mapping[str, Any]] = {}
    for receipt in dispatches:
        if (
            not isinstance(receipt, Mapping)
            or receipt.get("agent_harness") != harness
            or receipt.get("runtime_provider") != "direct"
            or receipt.get("native_session_id") != handle["external_id"]
            or not isinstance(receipt.get("invocation_id"), str)
            or not receipt["invocation_id"]
        ):
            return []
        invocation = receipt["invocation_id"]
        if invocation in receipts and receipts[invocation] != receipt:
            return []
        receipts[invocation] = receipt
    return [
        {
            "run_id": session.get("run_id"),
            "candidate_id": session.get("candidate_id"),
            "agent_session_id": session.get("agent_session_id"),
            "execution_generation": session.get("execution_generation", 0),
            "invocation_id": invocation,
            "started_at": receipt.get("started_at"),
            "ended_at": receipt.get("ended_at"),
        }
        for invocation, receipt in receipts.items()
    ]


def frozen_agent_harness(frozen: Mapping[str, Any]) -> Literal["codex", "pi"] | None:
    spec = frozen.get("spec")
    workspace = spec.get("workspace") if isinstance(spec, Mapping) else None
    if not isinstance(workspace, Mapping) or workspace.get("provider") not in (
        "git_worktree", "copy",
    ):
        return None
    if frozen.get("runtime_provider") != "direct":
        return None
    if any(key in frozen for key in ("native_host", "worker_host")) or "backend" in workspace:
        return None
    agent_harness = frozen.get("agent_harness")
    if agent_harness in ("codex", "pi"):
        return agent_harness
    return None
