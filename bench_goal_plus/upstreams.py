"""Resolve managed upstream checkouts and source subdirectories."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


def _relative_path(value: Any, *, field: str, upstream_key: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{upstream_key}: {field} must be a non-empty string")
    if "\\" in value:
        raise ValueError(f"{upstream_key}: {field} must use POSIX separators")
    relative = PurePosixPath(value)
    if (
        not relative.parts
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"{upstream_key}: unsafe {field} {value!r}")
    return Path(*relative.parts)


def upstream_checkout_path(
    checkout_root: Path,
    entry: Mapping[str, Any],
    *,
    upstream_key: str,
) -> Path:
    """Return the Git worktree root for a managed upstream."""

    return checkout_root / _relative_path(
        entry.get("checkout_dir"),
        field="checkout_dir",
        upstream_key=upstream_key,
    )


def upstream_source_path(
    checkout_root: Path,
    entry: Mapping[str, Any],
    *,
    upstream_key: str,
) -> Path:
    """Return the consumable source root within a managed upstream checkout."""

    checkout = upstream_checkout_path(
        checkout_root,
        entry,
        upstream_key=upstream_key,
    )
    source_subdir = entry.get("source_subdir")
    if source_subdir is None:
        return checkout
    return checkout / _relative_path(
        source_subdir,
        field="source_subdir",
        upstream_key=upstream_key,
    )


def registered_upstream_source_path(
    upstream_key: str,
    *,
    repository_root: Path,
) -> Path:
    """Resolve a source root from a repository's environment registry."""

    manifest_path = repository_root / "environment" / "upstreams.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = (manifest.get("upstreams") or {}).get(upstream_key)
    if not isinstance(entry, dict):
        raise ValueError(f"unknown managed upstream: {upstream_key}")
    return upstream_source_path(
        repository_root / "third_party",
        entry,
        upstream_key=upstream_key,
    )


def registered_upstream_branch(
    upstream_key: str,
    *,
    repository_root: Path,
) -> str:
    """Return the tracked branch declared for a managed upstream."""

    manifest_path = repository_root / "environment" / "upstreams.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = (manifest.get("upstreams") or {}).get(upstream_key)
    branch = entry.get("tracking_branch") if isinstance(entry, dict) else None
    if not isinstance(branch, str) or not branch:
        raise ValueError(f"managed upstream {upstream_key!r} has no tracking_branch")
    return branch
