#!/usr/bin/env python3
"""Inventory and provision the registered SkyDiscover evaluator image pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bench_goal_plus.docker_inventory import inspect_exact_images  # noqa: E402
from bench_runtime_paths import configure_temp_environment  # noqa: E402


PROFILE_ROOT = Path(__file__).resolve().parent / "profiles"
UPSTREAM_ROOT = ROOT / "third_party/skydiscover"
SAFE_PROFILE = re.compile(r"[a-z0-9][a-z0-9-]*")
REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
PACK_LABEL = "bench-goal-plus.asset-pack"
PROFILE_LABEL = "bench-goal-plus.asset-profile"
TREE_LABEL = "bench-goal-plus.source-tree"
PIP_INDEX_LABEL = "bench-goal-plus.pip-index"
REVISION_LABEL = "org.opencontainers.image.revision"


def run(
    command: list[str], *, capture: bool = True, timeout: int | None = None
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    configure_temp_environment(environment)
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=capture,
        text=True,
        env=environment,
        timeout=timeout,
    )


def load_profile(profile_id: str) -> dict[str, Any]:
    if SAFE_PROFILE.fullmatch(profile_id) is None:
        raise ValueError(f"unsafe SkyDiscover asset profile: {profile_id!r}")
    path = PROFILE_ROOT / f"{profile_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("id") != profile_id:
        raise ValueError(f"invalid SkyDiscover asset profile: {path}")
    images = payload.get("images")
    if not isinstance(images, list) or not images:
        raise ValueError(f"SkyDiscover asset profile has no images: {path}")
    base_image = payload.get("base_image")
    if not isinstance(base_image, dict):
        raise ValueError(f"SkyDiscover asset profile has no base image: {path}")
    required_base_strings = (
        "reference",
        "architecture",
        "manifest_digest",
        "expected_image_id",
    )
    if not all(
        isinstance(base_image.get(name), str) and base_image[name]
        for name in required_base_strings
    ):
        raise ValueError(f"SkyDiscover asset profile has an invalid base image: {path}")
    if (
        SHA256_DIGEST.fullmatch(base_image["manifest_digest"]) is None
        or SHA256_DIGEST.fullmatch(base_image["expected_image_id"]) is None
    ):
        raise ValueError(f"SkyDiscover base image digests are invalid: {path}")
    sources = base_image.get("sources")
    if not isinstance(sources, list) or not sources or not all(
        isinstance(source, str) and source for source in sources
    ):
        raise ValueError(f"SkyDiscover base image has no transport sources: {path}")
    pip_index_url = payload.get("pip_index_url")
    if (
        not isinstance(pip_index_url, str)
        or not pip_index_url.startswith("https://")
        or any(character.isspace() for character in pip_index_url)
    ):
        raise ValueError(f"SkyDiscover asset profile has an invalid pip index: {path}")
    return payload


def git_value(*arguments: str) -> str | None:
    completed = run(["git", "-C", str(UPSTREAM_ROOT), *arguments])
    return completed.stdout.strip() if completed.returncode == 0 else None


def source_state() -> dict[str, Any]:
    status = run(["git", "-C", str(UPSTREAM_ROOT), "status", "--porcelain"])
    return {
        "path": str(UPSTREAM_ROOT),
        "present": UPSTREAM_ROOT.is_dir(),
        "commit": git_value("rev-parse", "HEAD"),
        "branch": git_value("symbolic-ref", "--short", "-q", "HEAD"),
        "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


def requirement_declared(requirements_text: str, project_name: str) -> bool:
    expected = re.sub(r"[-_.]+", "-", project_name).lower()
    for raw_line in requirements_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        matched = REQUIREMENT_NAME.match(line)
        if matched is None:
            continue
        actual = re.sub(r"[-_.]+", "-", matched.group(1)).lower()
        if actual == expected:
            return True
    return False


def dockerfile_base(dockerfile: Path) -> str | None:
    if not dockerfile.is_file():
        return None
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        matched = re.match(
            r"^\s*FROM(?:\s+--platform=\S+)?\s+(\S+)", line, re.IGNORECASE
        )
        if matched is not None:
            return matched.group(1)
    return None


def image_expectations(profile: dict[str, Any]) -> list[dict[str, Any]]:
    expectations: list[dict[str, Any]] = []
    for raw in profile["images"]:
        context_value = str(raw["context"])
        context = UPSTREAM_ROOT / context_value
        dockerfile = context / "Dockerfile"
        declared_base = dockerfile_base(dockerfile)
        actual_tree = git_value("rev-parse", f"HEAD:{context_value}")
        requirements = context / "requirements.txt"
        requirements_text = (
            requirements.read_text(encoding="utf-8")
            if requirements.is_file()
            else ""
        )
        expectations.append(
            {
                "reference": str(raw["reference"]),
                "context": context_value,
                "context_path": str(context),
                "context_present": context.is_dir(),
                "dockerfile_present": dockerfile.is_file(),
                "dockerfile_base": declared_base,
                "base_image_matches": declared_base
                == profile["base_image"]["reference"],
                "requirements_present": requirements.is_file(),
                "torch_dependency_declared": requirement_declared(
                    requirements_text, "torch"
                ),
                "expected_source_tree": str(raw["source_tree"]),
                "actual_source_tree": actual_tree,
                "source_tree_matches": actual_tree == raw["source_tree"],
                "audited_image_id": str(raw["audited_image_id"]),
            }
        )
    return expectations


def inventory(profile: dict[str, Any]) -> dict[str, Any]:
    source = source_state()
    expected = image_expectations(profile)
    base = profile["base_image"]
    inspected = inspect_exact_images(
        [
            *expected,
            {
                "role": "build-base",
                "reference": base["reference"],
                "required": False,
                "manifest_digest": base["manifest_digest"],
                "expected_image_id": base["expected_image_id"],
            },
        ]
    )
    records = inspected["images"][:-1]
    base_record = inspected["images"][-1]
    base_record["image_id_matches"] = (
        base_record.get("image_id") == base["expected_image_id"]
    )
    base_record["architecture_matches"] = (
        base_record.get("architecture") == base["architecture"]
    )
    base_record["ready"] = bool(
        base_record["present"]
        and base_record["image_id_matches"]
        and base_record["architecture_matches"]
    )
    for image in records:
        labels = image.get("labels") or {}
        image["audited_image_id_matches"] = (
            image.get("image_id") == image["audited_image_id"]
        )
        image["built_provenance_matches"] = bool(
            labels.get(PACK_LABEL) == profile["asset_pack"]
            and labels.get(PROFILE_LABEL) == profile["id"]
            and labels.get(REVISION_LABEL) == profile["source_commit"]
            and labels.get(TREE_LABEL) == image["expected_source_tree"]
            and labels.get(PIP_INDEX_LABEL) == profile["pip_index_url"]
        )
        image["provenance_matches"] = bool(
            image["audited_image_id_matches"]
            or image["built_provenance_matches"]
        )
        image["architecture_matches"] = (
            image.get("architecture") == profile["architecture"]
        )
        image["ready"] = bool(
            image["context_present"]
            and image["dockerfile_present"]
            and image["base_image_matches"]
            and image["source_tree_matches"]
            and not image["torch_dependency_declared"]
            and image["present"]
            and image["provenance_matches"]
            and image["architecture_matches"]
        )
    ready_count = sum(bool(image["ready"]) for image in records)
    source_matches = source["commit"] == profile["source_commit"]
    source_clean = source["dirty"] is False
    return {
        "schema_version": 1,
        "action": "local-asset-inventory",
        "asset_pack": profile["asset_pack"],
        "profile": profile["id"],
        "read_only": True,
        "acquisition_attempted": False,
        "source": {
            **source,
            "expected_commit": profile["source_commit"],
            "commit_matches": source_matches,
        },
        "summary": {
            "images_expected": len(records),
            "images_present": sum(bool(image["present"]) for image in records),
            "images_ready": ready_count,
            "images_missing": sum(not image["present"] for image in records),
            "images_with_provenance_drift": sum(
                bool(image["present"] and not image["provenance_matches"])
                for image in records
            ),
            "matching_containers": len(
                {
                    str(container.get("id") or container.get("name"))
                    for image in records
                    for container in image["containers"]
                }
            ),
        },
        "ready": bool(
            source_matches
            and source_clean
            and ready_count == len(records)
            and inspected["container_check"]["returncode"] == 0
            and not inspected["container_check"]["parse_errors"]
        ),
        "images": records,
        "base_image": base_record,
        "container_check": inspected["container_check"],
        "docker_commands": inspected["docker_commands"],
    }


def backup_reference(reference: str) -> str:
    repository, separator, tag = reference.rpartition(":")
    if not separator or "/" in tag:
        repository = reference
        tag = "untagged"
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return f"{repository}:{tag}_bak_{timestamp}"


def build_dockerfile(
    profile: dict[str, Any], image: dict[str, Any]
) -> Path:
    source = Path(image["context_path"]) / "Dockerfile"
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    insert_at = next(
        (
            index + 1
            for index, line in enumerate(lines)
            if re.match(r"^\s*FROM(?:\s|$)", line, re.IGNORECASE)
        ),
        None,
    )
    if insert_at is None:
        raise RuntimeError(f"Dockerfile has no FROM instruction: {source}")
    lines.insert(insert_at, "ARG PIP_INDEX_URL\n")
    rendered = "".join(lines)
    content_digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()[:16]
    target = (
        ROOT
        / ".tmp/skydiscover-build/dockerfiles"
        / f"{image['expected_source_tree']}-{content_digest}.Dockerfile"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"generated Dockerfile conflict: {target}")
    if not target.exists():
        target.write_text(rendered, encoding="utf-8")
    return target


def ensure_build_base(
    profile: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    base = profile["base_image"]
    reference = base["reference"]
    if current["ready"]:
        return {
            "reference": reference,
            "status": "reused",
            "image_id": current["image_id"],
            "architecture": current["architecture"],
            "preserved_conflicts": [],
            "attempts": [],
        }
    if shutil.which("skopeo") is None:
        raise RuntimeError(
            f"skopeo is required to acquire pinned base image {reference}"
        )

    backups: list[dict[str, str]] = []
    if current["present"]:
        backup = backup_reference(reference)
        completed = run(["docker", "tag", reference, backup])
        if completed.returncode != 0:
            raise RuntimeError(
                completed.stderr.strip()
                or f"failed to preserve conflicting image {reference}"
            )
        backups.append({"reference": reference, "backup": backup})

    attempts: list[dict[str, Any]] = []
    for source in base["sources"]:
        source_reference = f"docker://{source}@{base['manifest_digest']}"
        command = [
            "skopeo",
            "copy",
            "--override-os",
            "linux",
            "--override-arch",
            base["architecture"],
            source_reference,
            f"docker-daemon:{reference}",
        ]
        print("+ " + shlex.join(command), flush=True)
        try:
            completed = run(command, timeout=300)
        except subprocess.TimeoutExpired:
            attempts.append(
                {
                    "source": source,
                    "manifest_digest": base["manifest_digest"],
                    "returncode": None,
                    "error": "transport timed out after 300 seconds",
                }
            )
            continue
        attempt = {
            "source": source,
            "manifest_digest": base["manifest_digest"],
            "returncode": completed.returncode,
        }
        if completed.returncode != 0:
            attempt["error"] = completed.stderr.strip()[-1000:]
            attempts.append(attempt)
            continue
        inspected = run(["docker", "image", "inspect", reference])
        try:
            details = json.loads(inspected.stdout)[0]
        except (json.JSONDecodeError, IndexError, TypeError):
            details = {}
        image_id = details.get("Id")
        architecture = details.get("Architecture")
        attempt["image_id"] = image_id
        attempt["architecture"] = architecture
        attempt["verified"] = bool(
            inspected.returncode == 0
            and image_id == base["expected_image_id"]
            and architecture == base["architecture"]
        )
        attempts.append(attempt)
        if attempt["verified"]:
            return {
                "reference": reference,
                "status": "acquired",
                "source": source,
                "manifest_digest": base["manifest_digest"],
                "image_id": image_id,
                "architecture": architecture,
                "preserved_conflicts": backups,
                "attempts": attempts,
            }
    raise RuntimeError(
        f"failed to acquire pinned base image {reference} from registered sources"
    )


def provision(profile: dict[str, Any]) -> dict[str, Any]:
    before = inventory(profile)
    source = before["source"]
    if not source["commit_matches"] or source["dirty"] is not False:
        raise RuntimeError(
            "SkyDiscover source must be clean and at the profile commit before provision"
        )
    invalid_contexts = [
        image["context"]
        for image in before["images"]
        if not image["context_present"]
        or not image["dockerfile_present"]
        or not image["base_image_matches"]
        or not image["source_tree_matches"]
        or image["torch_dependency_declared"]
    ]
    if invalid_contexts:
        raise RuntimeError(
            "SkyDiscover asset contexts do not match the profile: "
            + ", ".join(invalid_contexts)
        )

    needs_build = any(not image["ready"] for image in before["images"])
    base_image = (
        ensure_build_base(profile, before["base_image"])
        if needs_build
        else {
            "reference": profile["base_image"]["reference"],
            "status": "not-needed",
            "preserved_conflicts": [],
            "attempts": [],
        }
    )

    built: list[str] = []
    reused: list[str] = []
    backups: list[dict[str, str]] = []
    for image in before["images"]:
        reference = image["reference"]
        if image["ready"]:
            reused.append(reference)
            continue
        if image["present"]:
            backup = backup_reference(reference)
            completed = run(["docker", "tag", reference, backup])
            if completed.returncode != 0:
                raise RuntimeError(
                    completed.stderr.strip()
                    or f"failed to preserve conflicting image {reference}"
                )
            backups.append({"reference": reference, "backup": backup})
        command = [
            "docker",
            "build",
            "--pull=false",
            "--build-arg",
            f"PIP_INDEX_URL={profile['pip_index_url']}",
            "--label",
            f"{PACK_LABEL}={profile['asset_pack']}",
            "--label",
            f"{PROFILE_LABEL}={profile['id']}",
            "--label",
            f"{REVISION_LABEL}={profile['source_commit']}",
            "--label",
            f"{TREE_LABEL}={image['expected_source_tree']}",
            "--label",
            f"{PIP_INDEX_LABEL}={profile['pip_index_url']}",
            "-f",
            str(build_dockerfile(profile, image)),
            "-t",
            reference,
            image["context_path"],
        ]
        completed = run(command, capture=False)
        if completed.returncode != 0:
            raise RuntimeError(f"Docker build failed for {reference}")
        built.append(reference)
    after = inventory(profile)
    return {
        "schema_version": 1,
        "action": "provision",
        "asset_pack": profile["asset_pack"],
        "profile": profile["id"],
        "acquisition_attempted": bool(built),
        "acquisition_method": "build-from-pinned-upstream-context",
        "pip_index_url": profile["pip_index_url"],
        "base_image": base_image,
        "built": built,
        "reused": reused,
        "preserved_conflicts": backups,
        "inventory": after,
    }


def doctor(profile: dict[str, Any]) -> dict[str, Any]:
    checked = inventory(profile)
    checks: list[dict[str, Any]] = []
    if checked["ready"]:
        for image in checked["images"]:
            command = [
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                "none",
                "--entrypoint",
                "python",
                image["reference"],
                "-m",
                "pip",
                "check",
            ]
            completed = run(command)
            checks.append(
                {
                    "reference": image["reference"],
                    "command": command,
                    "passed": completed.returncode == 0,
                    "stdout": completed.stdout.strip(),
                    "stderr": completed.stderr.strip(),
                }
            )
    passed = checked["ready"] and len(checks) == len(checked["images"]) and all(
        item["passed"] for item in checks
    )
    return {
        "schema_version": 1,
        "action": "doctor",
        "asset_pack": profile["asset_pack"],
        "profile": profile["id"],
        "passed": passed,
        "inventory": checked,
        "pip_checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("inventory", "provision", "doctor"))
    parser.add_argument("--profile", required=True)
    args = parser.parse_args(argv)
    profile = load_profile(args.profile)
    if args.action == "inventory":
        result = inventory(profile)
    elif args.action == "provision":
        result = provision(profile)
    else:
        result = doctor(profile)
    print(json.dumps(result, indent=2))
    return 0 if args.action != "doctor" or result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
