"""Known EdgeBench asset defects and campaign exclusions."""

from __future__ import annotations

from typing import Any, Iterable

from . import io
from .context import current_paths


EXCLUDED_FROM_CAMPAIGNS = "excluded_from_campaigns"


def known_asset_issues() -> list[dict[str, Any]]:
    path = (
        current_paths().root
        / "experiments"
        / "edgebench"
        / "references"
        / "known-asset-issues.json"
    )
    payload = io.read_json(path)
    issues = (
        payload.get("issues")
        if isinstance(payload, dict) and payload.get("schema_version") == 1
        else None
    )
    if not isinstance(issues, list) or any(not isinstance(item, dict) for item in issues):
        raise ValueError(f"invalid EdgeBench known asset issue registry: {path}")
    return [dict(item) for item in issues]


def asset_issue_matches_revision(
    issue: dict[str, Any], dataset_revision: str | None
) -> bool:
    revisions = issue.get("dataset_revisions")
    if isinstance(revisions, list):
        return dataset_revision in revisions
    return issue.get("dataset_revision") == dataset_revision


def excluded_task_issues(
    task_ids: Iterable[Any], dataset_revision: str | None
) -> list[dict[str, Any]]:
    selected = {str(task_id) for task_id in task_ids}
    return [
        issue
        for issue in known_asset_issues()
        if issue.get("disposition") == EXCLUDED_FROM_CAMPAIGNS
        and str(issue.get("task_id")) in selected
        and asset_issue_matches_revision(issue, dataset_revision)
    ]
