"""Shared helpers for portable benchmark manifests and artifact paths."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".new")
    write_json(temporary, payload)
    temporary.replace(path)


def portable_path(path: Path) -> str:
    resolved = path.expanduser().absolute()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def sanitize_id(value: str) -> str:
    rendered = "".join(character if character.isalnum() else "-" for character in value)
    return "-".join(part for part in rendered.split("-") if part).lower()
