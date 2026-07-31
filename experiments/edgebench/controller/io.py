"""Small persistence, Git, command, and portable-path helpers."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .context import current_paths


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def campaign_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head(path: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def git_branch(path: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(path), "symbolic-ref", "--short", "-q", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def git_dirty(path: Path) -> bool | None:
    completed = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(completed.stdout.strip()) if completed.returncode == 0 else None


def upstream_entry(name: str) -> dict[str, Any]:
    manifest = read_json(current_paths().upstream_manifest)
    return dict(manifest["upstreams"][name])


def campaign_dir(value: str | Path) -> Path:
    paths = current_paths()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        direct = (paths.root / candidate).resolve()
        candidate = direct if direct.is_dir() else (paths.runs_root / candidate).resolve()
    else:
        candidate = candidate.resolve()
    try:
        candidate.relative_to(paths.runs_root.resolve())
    except ValueError as exc:
        raise ValueError(f"campaign must be under {paths.runs_root}") from exc
    if not (candidate / "campaign.json").is_file():
        raise FileNotFoundError(f"campaign.json not found in {candidate}")
    return candidate


def portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(current_paths().root))
    except ValueError:
        return resolved.name


def portable_command(command: Iterable[str]) -> list[str]:
    replacements = (
        (str(current_paths().root.resolve()), "<bench-goal-plus>"),
        (str(Path.home().resolve()), "<home>"),
    )
    result: list[str] = []
    for argument in command:
        clean = str(argument)
        for source, replacement in replacements:
            clean = clean.replace(source, replacement)
        result.append(clean)
    return result


def run_capture(
    command: list[str], *, env: dict[str, str] | None = None
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=current_paths().root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        return {"returncode": 127, "stdout": "", "stderr": str(exc)}
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def sanitize_id(value: str) -> str:
    clean = "".join(character if character.isalnum() or character in "-_." else "-" for character in value)
    return clean.strip("-.") or "campaign"
