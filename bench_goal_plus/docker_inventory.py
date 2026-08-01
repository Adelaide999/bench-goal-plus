"""Read-only helpers for exact local Docker image and container inventory."""

from __future__ import annotations

import json
import subprocess
from typing import Any, Iterable


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True)


def _containers() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    command = [
        "docker",
        "ps",
        "-a",
        "--no-trunc",
        "--format",
        "{{json .}}",
    ]
    completed = _run(command)
    containers: list[dict[str, Any]] = []
    errors: list[str] = []
    if completed.returncode == 0:
        for line_number, line in enumerate(completed.stdout.splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                errors.append(f"line {line_number}: {error.msg}")
                continue
            if isinstance(value, dict):
                containers.append(value)
            else:
                errors.append(f"line {line_number}: expected an object")
    return containers, {
        "command": command,
        "returncode": completed.returncode,
        "stderr": completed.stderr.strip(),
        "parse_errors": errors,
    }


def _container_summary(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": value.get("ID"),
        "name": value.get("Names"),
        "image": value.get("Image"),
        "image_id": value.get("ImageID"),
        "state": value.get("State"),
        "status": value.get("Status"),
    }


def inspect_exact_images(
    images: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Inspect exact refs and associated containers without acquiring assets."""

    containers, container_check = _containers()
    records: list[dict[str, Any]] = []
    docker_commands: list[list[str]] = [container_check["command"]]
    for expected in images:
        reference = str(expected["reference"])
        command = ["docker", "image", "inspect", reference]
        docker_commands.append(command)
        completed = _run(command)
        record: dict[str, Any] = {
            **expected,
            "reference": reference,
            "present": False,
            "image_id": None,
            "repo_tags": [],
            "repo_digests": [],
            "size_bytes": None,
            "architecture": None,
            "os": None,
            "labels": {},
            "containers": [],
        }
        if completed.returncode != 0:
            record["error"] = (
                completed.stderr.strip() or "exact image reference is missing"
            )
            records.append(record)
            continue
        try:
            payload = json.loads(completed.stdout)
            details = payload[0] if isinstance(payload, list) and payload else None
        except json.JSONDecodeError as error:
            record["error"] = f"docker image inspect returned invalid JSON: {error.msg}"
            records.append(record)
            continue
        if not isinstance(details, dict):
            record["error"] = "docker image inspect returned no image object"
            records.append(record)
            continue
        image_id = details.get("Id")
        repo_tags = details.get("RepoTags") or []
        repo_digests = details.get("RepoDigests") or []
        labels = (details.get("Config") or {}).get("Labels") or {}
        aliases = {
            str(item)
            for item in (reference, image_id, *repo_tags, *repo_digests)
            if item
        }
        if isinstance(image_id, str) and image_id.startswith("sha256:"):
            aliases.add(image_id.removeprefix("sha256:"))
        matching = [
            _container_summary(container)
            for container in containers
            if str(container.get("Image") or "") in aliases
            or str(container.get("ImageID") or "") in aliases
        ]
        record.update(
            {
                "present": True,
                "image_id": image_id,
                "repo_tags": list(repo_tags),
                "repo_digests": list(repo_digests),
                "size_bytes": details.get("Size"),
                "architecture": details.get("Architecture"),
                "os": details.get("Os"),
                "labels": dict(labels) if isinstance(labels, dict) else {},
                "containers": matching,
            }
        )
        records.append(record)
    return {
        "images": records,
        "container_check": container_check,
        "docker_commands": docker_commands,
    }
