"""Read the frozen Main identity for supported local Goal Plus evidence."""

from collections.abc import Mapping
from typing import Any, Literal


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
