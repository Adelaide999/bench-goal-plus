"""Read the frozen Main identity for supported local Goal Plus evidence."""

from collections.abc import Mapping
from typing import Any, Literal


def frozen_worker_host(frozen: Mapping[str, Any]) -> Literal["codex", "pi-rpc"] | None:
    spec = frozen.get("spec")
    workspace = spec.get("workspace") if isinstance(spec, Mapping) else None
    if not isinstance(workspace, Mapping) or workspace.get("backend") not in {
        "git_worktree", "copy",
    }:
        return None
    native_host = frozen.get("native_host")
    if native_host == "codex":
        return "codex"
    if native_host == "pi":
        return "pi-rpc"
    return None
