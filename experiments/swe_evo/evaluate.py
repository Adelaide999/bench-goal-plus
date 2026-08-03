"""Patch freezing and the official SWE-EVO final evaluator."""

from __future__ import annotations

import json
import os
import sys
import tarfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .dataset import merge_patches, normalize_image_ref, patch_paths


class EvaluationError(RuntimeError):
    """Raised when patch freezing or the official harness cannot complete."""


def _decode(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _safe_archive(path: Path) -> None:
    if not path.is_file():
        raise EvaluationError(f"final workspace archive is missing: {path}")
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts
                if member.name.startswith("/") or ".." in parts:
                    raise EvaluationError(f"unsafe archive member: {member.name}")
    except tarfile.TarError as error:
        raise EvaluationError(f"invalid final workspace archive: {error}") from error


def _assert_image_digest(image: Any, expected_digest: str | None) -> None:
    if not expected_digest:
        return
    repo_digests = image.attrs.get("RepoDigests") or []
    if not any(str(value).rpartition("@")[2] == expected_digest for value in repo_digests):
        raise EvaluationError(
            f"source image does not match pinned digest {expected_digest}: {repo_digests}"
        )


def freeze_patch(
    record: dict[str, Any],
    archive: Path,
    output: Path,
    *,
    expected_image_digest: str | None = None,
) -> dict[str, Any]:
    """Overlay a SForge archive on a fresh task image and freeze a binary Git diff."""
    _safe_archive(archive)
    try:
        import docker
    except ImportError as error:
        raise EvaluationError("docker Python package is required") from error
    client = docker.from_env()
    source_image = normalize_image_ref(str(record["image"]))
    name = f"bench-swe-evo-freeze-{uuid.uuid4().hex[:12]}"
    container = None
    try:
        _assert_image_digest(client.images.get(source_image), expected_image_digest)
        container = client.containers.run(
            source_image,
            ["infinity"],
            name=name,
            detach=True,
            entrypoint="sleep",
            user="root",
            network_disabled=True,
        )
        reset = container.exec_run(
            ["bash", "-lc", f"cd /testbed && git reset --hard {record['base_commit']} && git clean -fdx"],
            user="root",
        )
        if reset.exit_code != 0:
            raise EvaluationError("cannot reset fresh task image: " + _decode(reset.output)[-1000:])
        with archive.open("rb") as source:
            if not container.put_archive("/testbed", source.read()):
                raise EvaluationError("Docker refused the final workspace archive")
        diff = container.exec_run(
            [
                "bash",
                "-lc",
                (
                    "cd /testbed && git add -N . && "
                    f"git diff --binary --full-index --no-ext-diff {record['base_commit']}"
                ),
            ],
            user="root",
        )
        if diff.exit_code != 0:
            raise EvaluationError("cannot freeze Git patch: " + _decode(diff.output)[-1000:])
        patch = _decode(diff.output)
    finally:
        if container is not None:
            container.remove(force=True)
        client.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(patch, encoding="utf-8")
    hidden_overlap = sorted(patch_paths(patch) & patch_paths(str(record.get("test_patch") or "")))
    return {
        "patch_path": str(output),
        "patch_bytes": len(patch.encode("utf-8")),
        "patch_sha256": __import__("hashlib").sha256(patch.encode("utf-8")).hexdigest(),
        "changed_paths": sorted(patch_paths(patch)),
        "hidden_test_path_overlap": hidden_overlap,
        "integrity_ok": not hidden_overlap,
    }


@contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    path.mkdir(parents=True, exist_ok=True)
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _load_official_harness(swe_evo_root: Path) -> dict[str, Any]:
    harness_root = swe_evo_root / "SWE-bench"
    if not (harness_root / "swebench" / "harness" / "run_evaluation.py").is_file():
        raise EvaluationError(f"vendored SWE-bench harness is missing: {harness_root}")
    sys.path.insert(0, str(harness_root))
    try:
        from swebench.harness.constants import KEY_INSTANCE_ID, KEY_MODEL, KEY_PREDICTION
        from swebench.harness.run_evaluation import run_instances
        from swebench.harness.test_spec.test_spec import make_test_spec
    except Exception as error:
        raise EvaluationError(f"cannot import the SWE-EVO official harness: {error}") from error
    return {
        "KEY_INSTANCE_ID": KEY_INSTANCE_ID,
        "KEY_MODEL": KEY_MODEL,
        "KEY_PREDICTION": KEY_PREDICTION,
        "run_instances": run_instances,
        "make_test_spec": make_test_spec,
    }


def evaluate_patch(
    record: dict[str, Any],
    code_patch: str,
    *,
    swe_evo_root: Path,
    evidence_dir: Path,
    run_id: str,
    timeout_seconds: int,
    expected_image_digest: str | None = None,
) -> dict[str, Any]:
    """Run one frozen patch through SWE-EVO's vendored SWE-bench harness."""
    official = _load_official_harness(swe_evo_root)
    try:
        import docker
    except ImportError as error:
        raise EvaluationError("docker Python package is required") from error
    instance = dict(record)
    instance["code_patch"] = code_patch
    instance["all_patch"] = merge_patches(code_patch, str(instance.get("test_patch") or ""))
    model = run_id
    prediction = {
        official["KEY_INSTANCE_ID"]: instance["instance_id"],
        official["KEY_MODEL"]: model,
        official["KEY_PREDICTION"]: instance["all_patch"],
    }
    predictions = {str(instance["instance_id"]): prediction}
    spec = official["make_test_spec"](instance, namespace=None)
    client = docker.from_env()
    try:
        source = client.images.get(normalize_image_ref(str(instance["image"])))
        _assert_image_digest(source, expected_image_digest)
        for target in (spec.instance_image_key, spec.env_image_key):
            source.tag(target)
    finally:
        client.close()
    with _working_directory(evidence_dir):
        official["run_instances"](
            predictions,
            [instance],
            "instance",
            False,
            False,
            1,
            run_id,
            timeout_seconds,
            namespace=None,
            instance_image_tag="latest",
            rewrite_reports=False,
        )
    report_path = (
        evidence_dir
        / "logs"
        / "run_evaluation"
        / run_id
        / model
        / str(instance["instance_id"])
        / "report.json"
    )
    if not report_path.is_file():
        raise EvaluationError(f"official report is missing: {report_path}")
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    report = raw.get(str(instance["instance_id"])) or {}
    statuses = report.get("tests_status") or {}
    fail_to_pass = statuses.get("FAIL_TO_PASS") or {}
    pass_to_pass = statuses.get("PASS_TO_PASS") or {}
    successes = len(fail_to_pass.get("success") or [])
    failures = len(fail_to_pass.get("failure") or [])
    regressions = len(pass_to_pass.get("failure") or [])
    denominator = successes + failures
    fix_rate = successes / denominator if denominator and regressions == 0 else 0.0
    return {
        "official": True,
        "instance_id": instance["instance_id"],
        "resolved": bool(report.get("resolved")),
        "patch_exists": bool(report.get("patch_exists")),
        "patch_applied": bool(report.get("patch_successfully_applied")),
        "fix_rate": fix_rate,
        "fail_to_pass_success": successes,
        "fail_to_pass_failure": failures,
        "pass_to_pass_failure": regressions,
        "report_path": str(report_path),
        "raw_report": raw,
    }
