"""Pinned SWE-EVO dataset loading and hidden-data boundaries."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


REQUIRED_FIELDS = {
    "repo",
    "instance_id",
    "base_commit",
    "patch",
    "test_patch",
    "problem_statement",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "image",
    "version",
}
WORKER_FIELDS = {
    "repo",
    "instance_id",
    "base_commit",
    "problem_statement",
    "image",
    "start_version",
    "end_version",
}
HIDDEN_FIELDS = {
    "patch",
    "test_patch",
    "FAIL_TO_PASS",
    "PASS_TO_PASS",
    "all_patch",
    "test_cmds",
    "log_parser",
}
DIFF_PATH = re.compile(r"^(?:---|\+\+\+)\s+(?:[ab]/)?([^\t\n]+)", re.MULTILINE)


class DatasetContractError(ValueError):
    """Raised when the pinned SWE-EVO artifact violates its contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        return _json_value(value.item())
    return str(value)


def load_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise DatasetContractError(f"SWE-EVO Arrow stream is missing: {path}")
    try:
        import polars as pl
    except ImportError as error:
        raise DatasetContractError(
            "polars is required; bootstrap the managed benchmark environment"
        ) from error
    try:
        rows = pl.read_ipc_stream(path).to_dicts()
    except Exception as error:
        raise DatasetContractError(f"cannot read SWE-EVO Arrow stream: {error}") from error
    records = [{str(key): _json_value(value) for key, value in row.items()} for row in rows]
    validate_records(records)
    return records


def validate_records(records: list[dict[str, Any]]) -> None:
    if len(records) != 48:
        raise DatasetContractError(f"expected 48 SWE-EVO records, found {len(records)}")
    seen: set[str] = set()
    for index, record in enumerate(records):
        missing = REQUIRED_FIELDS - set(record)
        if missing:
            raise DatasetContractError(f"record {index} is missing {sorted(missing)}")
        instance_id = record.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise DatasetContractError(f"record {index} has an invalid instance_id")
        if instance_id in seen:
            raise DatasetContractError(f"duplicate SWE-EVO instance_id: {instance_id}")
        seen.add(instance_id)
        for field in ("repo", "base_commit", "problem_statement", "image", "version"):
            if not isinstance(record.get(field), str) or not record[field]:
                raise DatasetContractError(f"{instance_id}: {field} must be non-empty")


def select_records(
    records: list[dict[str, Any]], task_ids: Iterable[str] | None
) -> list[dict[str, Any]]:
    if task_ids is None:
        return list(records)
    requested = list(task_ids)
    indexed = {str(record["instance_id"]): record for record in records}
    missing = [task_id for task_id in requested if task_id not in indexed]
    if missing:
        raise DatasetContractError("unknown SWE-EVO task(s): " + ", ".join(missing))
    return [indexed[task_id] for task_id in requested]


def worker_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in sorted(WORKER_FIELDS) if key in record}


def assert_worker_safe(payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    lowered = serialized.lower()
    leaked = sorted(field for field in HIDDEN_FIELDS if f'"{field.lower()}"' in lowered)
    if leaked:
        raise DatasetContractError(f"worker payload contains hidden fields: {leaked}")


def normalize_image_ref(value: str) -> str:
    if "@" in value:
        return value
    tail = value.rsplit("/", 1)[-1]
    return value if ":" in tail else f"{value}:latest"


def merge_patches(code_patch: str, test_patch: str) -> str:
    parts = []
    for value in (test_patch, code_patch):
        normalized = (value or "").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
        if normalized:
            parts.append(normalized)
    return "\n\n".join(parts) + ("\n" if parts else "")


def patch_paths(patch: str) -> set[str]:
    paths = set()
    for match in DIFF_PATH.finditer(patch or ""):
        path = match.group(1).strip()
        if path != "/dev/null":
            paths.add(path)
    return paths
