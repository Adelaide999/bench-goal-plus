"""Provisioning and fail-closed host checks for native ZSoft SWE-agent."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from adapters.zsoft_detect import adapter as zsoft_adapter

from .config import (
    BENCHMARK_ROOT,
    PINNED_LITELLM_VERSION,
    PINNED_SWE_AGENT_COMMIT,
    PINNED_SWE_REX_VERSION,
    SWE_AGENT_REPOSITORY,
    UPSTREAM_ENV_CHECK,
    UPSTREAM_RUNNER,
    source_checkout,
    swe_agent_root,
    write_json,
)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _git_state(path: Path, expected_commit: str) -> dict[str, Any]:
    if not (path / ".git").is_dir():
        return {
            "ok": False,
            "missing": not path.exists(),
            "path": str(path),
            "expected_commit": expected_commit,
            "actual_commit": None,
            "clean": None,
            "error": "checkout is missing" if not path.exists() else "path is not a Git checkout",
        }
    head = _run(["git", "-C", str(path), "rev-parse", "HEAD"])
    status = _run(
        ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=all"]
    )
    actual = head.stdout.strip() if head.returncode == 0 else None
    clean = status.returncode == 0 and not status.stdout.strip()
    return {
        "ok": actual == expected_commit and clean,
        "missing": False,
        "path": str(path),
        "expected_commit": expected_commit,
        "actual_commit": actual,
        "clean": clean,
    }


def _package_version(python: Path, package: str) -> str | None:
    if not python.is_file():
        return None
    completed = _run(
        [
            str(python),
            "-c",
            "import importlib.metadata as m; print(m.version(" + repr(package) + "))",
        ]
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def asset_inventory(profile: dict[str, Any]) -> dict[str, Any]:
    swe_root = swe_agent_root()
    swe_state = _git_state(swe_root, PINNED_SWE_AGENT_COMMIT)
    swe_python = swe_root / ".venv" / "bin" / "python"
    swe_state.update(
        {
            "python": str(swe_python),
            "python_present": swe_python.is_file(),
            "swe_rex_version": _package_version(swe_python, "swe-rex"),
            "expected_swe_rex_version": PINNED_SWE_REX_VERSION,
            "litellm_version": _package_version(swe_python, "litellm"),
            "expected_litellm_version": PINNED_LITELLM_VERSION,
        }
    )
    swe_state["ok"] = bool(
        swe_state["ok"]
        and swe_state["python_present"]
        and swe_state["swe_rex_version"] == PINNED_SWE_REX_VERSION
        and swe_state["litellm_version"] == PINNED_LITELLM_VERSION
    )
    sources = []
    for project in profile["projects"]:
        sources.append(
            {
                "project": project,
                **_git_state(
                    source_checkout(project), zsoft_adapter.project_commit(project)
                ),
            }
        )
    framework = {
        "ok": UPSTREAM_RUNNER.is_file() and UPSTREAM_ENV_CHECK.is_file(),
        "missing": not (UPSTREAM_RUNNER.is_file() and UPSTREAM_ENV_CHECK.is_file()),
        "path": str(BENCHMARK_ROOT),
        "runner": str(UPSTREAM_RUNNER),
    }
    return {
        "read_only": True,
        "acquisition_attempted": False,
        "framework": framework,
        "swe_agent": swe_state,
        "sources": sources,
        "ok": framework["ok"] and swe_state["ok"] and all(item["ok"] for item in sources),
    }


def doctor_payload(
    profile: dict[str, Any],
    *,
    local_assets_only: bool,
    allow_missing_local_assets: bool,
) -> dict[str, Any]:
    inventory = asset_inventory(profile)
    failed_assets = [
        item
        for item in [inventory["framework"], inventory["swe_agent"], *inventory["sources"]]
        if not item["ok"]
    ]
    missing_only = bool(failed_assets) and all(item.get("missing") for item in failed_assets)
    payload: dict[str, Any] = {
        "benchmark": "zsoft-detect-swe-agent",
        "profile": profile["id"],
        "mode": "local-assets-only" if local_assets_only else "full",
        "inventory": inventory,
        "host": None,
        "auth": None,
    }
    if local_assets_only:
        payload["ok"] = bool(
            inventory["ok"] or (allow_missing_local_assets and missing_only)
        )
        payload["missing_assets_allowed"] = bool(
            allow_missing_local_assets and missing_only
        )
        return payload

    bwrap = shutil.which("bwrap")
    bwrap_help = _run([bwrap, "--help"]) if bwrap else None
    required_flags = ("--unshare-user", "--disable-userns")
    bwrap_output = (
        (bwrap_help.stdout or "") + (bwrap_help.stderr or "") if bwrap_help else ""
    )
    bwrap_capable = bool(
        bwrap_help
        and bwrap_help.returncode == 0
        and all(flag in bwrap_output for flag in required_flags)
    )
    headers_valid = True
    headers_error = None
    try:
        headers = json.loads(os.environ.get("OPENAI_COMPAT_HEADERS_JSON", "{}"))
        headers_valid = isinstance(headers, dict)
        if not headers_valid:
            headers_error = "OPENAI_COMPAT_HEADERS_JSON must contain a JSON object"
    except json.JSONDecodeError as error:
        headers_valid = False
        headers_error = f"OPENAI_COMPAT_HEADERS_JSON is invalid JSON: {error}"
    auth_ok = bool(
        os.environ.get("OPENAI_COMPAT_BASE_URL")
        and os.environ.get("OPENAI_COMPAT_API_KEY")
        and headers_valid
    )
    payload["host"] = {
        "ok": platform.system() == "Linux" and bwrap_capable,
        "system": platform.system(),
        "machine": platform.machine(),
        "requires": "Linux host with Bubblewrap user-namespace flags",
        "bwrap": bwrap,
        "bwrap_capable": bwrap_capable,
    }
    payload["auth"] = {
        "ok": auth_ok,
        "base_url_env": "OPENAI_COMPAT_BASE_URL",
        "api_key_env": "OPENAI_COMPAT_API_KEY",
        "headers_env": "OPENAI_COMPAT_HEADERS_JSON",
        "values_persisted": False,
        "headers_error": headers_error,
    }
    native = _run(
        [
            sys.executable,
            str(UPSTREAM_ENV_CHECK),
            "swe-agent",
            "--swe-agent-root",
            str(swe_agent_root()),
        ]
    )
    try:
        native_payload = json.loads(native.stdout)
    except json.JSONDecodeError:
        native_payload = {
            "ok": False,
            "error": native.stderr.strip() or "native preflight returned invalid JSON",
        }
    payload["native_preflight"] = native_payload
    payload["ok"] = bool(
        inventory["ok"]
        and payload["host"]["ok"]
        and auth_ok
        and native.returncode == 0
        and native_payload.get("ok") is True
    )
    return payload


def doctor(
    profile: dict[str, Any],
    *,
    output: Path | None = None,
    local_assets_only: bool = False,
    allow_missing_local_assets: bool = False,
) -> int:
    payload = doctor_payload(
        profile,
        local_assets_only=local_assets_only,
        allow_missing_local_assets=allow_missing_local_assets,
    )
    if output:
        write_json(output, payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["ok"] else 1


def _require_linux_bwrap() -> None:
    if platform.system() != "Linux" or not shutil.which("bwrap"):
        raise RuntimeError(
            "ZSoft native SWE-agent provisioning requires the same Linux+bwrap host "
            "used for execution; OrbStack Docker on macOS is not that native host"
        )


def _provision_source(project: str) -> bool:
    destination = source_checkout(project)
    expected = zsoft_adapter.project_commit(project)
    if destination.exists():
        state = _git_state(destination, expected)
        if not state["ok"]:
            raise RuntimeError(
                f"existing source checkout is not the clean pinned revision: {destination}"
            )
        return False
    staging = destination.with_name(destination.name + "_bootstrap_incomplete")
    if staging.exists():
        raise RuntimeError(f"preserved incomplete source checkout exists: {staging}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    zsoft_adapter.fetch_source_checkout(project, expected, staging)
    staging.rename(destination)
    return True


def _provision_swe_agent() -> bool:
    destination = swe_agent_root()
    if destination.exists():
        state = asset_inventory({"projects": []})["swe_agent"]
        if not state["ok"]:
            raise RuntimeError(
                f"existing SWE-agent checkout is not the pinned ready runtime: {destination}"
            )
        return False
    python311 = shutil.which("python3.11")
    if not python311:
        raise RuntimeError("python3.11 is required to provision pinned SWE-agent 1.0.1")
    staging = destination.with_name(destination.name + "_bootstrap_incomplete")
    if staging.exists():
        raise RuntimeError(f"preserved incomplete SWE-agent checkout exists: {staging}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--quiet", SWE_AGENT_REPOSITORY, str(staging)], check=True
    )
    subprocess.run(
        ["git", "-C", str(staging), "checkout", "--quiet", PINNED_SWE_AGENT_COMMIT],
        check=True,
    )
    staging.rename(destination)
    subprocess.run([python311, "-m", "venv", str(destination / ".venv")], check=True)
    requirements = BENCHMARK_ROOT / "runners" / "swe-agent" / "requirements-runner.txt"
    subprocess.run(
        [
            str(destination / ".venv" / "bin" / "pip"),
            "install",
            "--editable",
            str(destination),
            "--requirement",
            str(requirements),
        ],
        check=True,
    )
    return True


def provision(profile: dict[str, Any]) -> dict[str, Any]:
    _require_linux_bwrap()
    acquired_sources = {
        project: _provision_source(project) for project in profile["projects"]
    }
    acquired_swe_agent = _provision_swe_agent()
    inventory = asset_inventory(profile)
    if not inventory["ok"]:
        raise RuntimeError("provisioned ZSoft SWE-agent assets failed exact inventory")
    return {
        "ok": True,
        "profile": profile["id"],
        "acquired": {
            "swe_agent": acquired_swe_agent,
            "sources": acquired_sources,
        },
        "inventory": inventory,
    }
