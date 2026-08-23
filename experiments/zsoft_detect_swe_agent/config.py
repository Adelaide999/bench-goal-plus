"""Frozen profiles and paths for the ZSoft-only SWE-agent runner."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from adapters.zsoft_detect import adapter as zsoft_adapter


ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
RUNS_ROOT = ROOT / "runs" / "zsoft-detect-swe-agent"
ASSET_ROOT = ROOT / ".bench-env" / "zsoft-detect-swe-agent"
DEFAULT_SWE_AGENT_ROOT = ASSET_ROOT / "SWE-agent"
SOURCE_ROOT = ASSET_ROOT / "sources"
BENCHMARK_ROOT = zsoft_adapter.BENCHMARK_ROOT
UPSTREAM_RUNNER = BENCHMARK_ROOT / "runners" / "launch.py"
UPSTREAM_ENV_CHECK = BENCHMARK_ROOT / "scripts" / "check_runner_env.py"
PINNED_SWE_AGENT_COMMIT = "6aff2155dd6fb2a8d19069f5c344f85a54f6c2fa"
PINNED_SWE_REX_VERSION = "1.4.0"
PINNED_LITELLM_VERSION = "1.93.0"
SWE_AGENT_REPOSITORY = "https://github.com/SWE-agent/SWE-agent.git"
SUPPORTED_METHODS = {"zsoft-swe-agent"}
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
MODEL_ID = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._:-]*(?:/[A-Za-z0-9][A-Za-z0-9._:-]*)*"
)


class ZSoftSWEAgentContractError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ZSoftSWEAgentContractError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ZSoftSWEAgentContractError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_profile(profile_id: str) -> tuple[Path, dict[str, Any]]:
    if SAFE_ID.fullmatch(profile_id) is None:
        raise ZSoftSWEAgentContractError(f"unsafe profile id: {profile_id!r}")
    path = PROFILE_DIR / f"{profile_id}.json"
    profile = read_json(path)
    validate_profile(profile_id, profile)
    return path, profile


def validate_profile(profile_id: str, profile: dict[str, Any]) -> None:
    if profile.get("schema_version") != 1 or profile.get("id") != profile_id:
        raise ZSoftSWEAgentContractError(
            f"{profile_id}: schema_version/id does not match profile"
        )
    if profile.get("benchmark_id") != "zsoft-detect-swe-agent":
        raise ZSoftSWEAgentContractError(f"{profile_id}: wrong benchmark_id")
    projects = profile.get("projects")
    if (
        not isinstance(projects, list)
        or not projects
        or len(set(projects)) != len(projects)
        or not all(project in zsoft_adapter.PROJECT_COMMITS for project in projects)
    ):
        raise ZSoftSWEAgentContractError(
            f"{profile_id}: projects must be unique registered ZSoft Detect projects"
        )
    if profile.get("task_ids") != [f"{project}-detect" for project in projects]:
        raise ZSoftSWEAgentContractError(
            f"{profile_id}: task_ids must correspond exactly to projects"
        )
    methods = profile.get("methods")
    if methods != ["zsoft-swe-agent"]:
        raise ZSoftSWEAgentContractError(
            f"{profile_id}: methods must be ['zsoft-swe-agent']"
        )
    model = profile.get("model")
    if not isinstance(model, str) or MODEL_ID.fullmatch(model) is None:
        raise ZSoftSWEAgentContractError(f"{profile_id}: invalid model id")
    if not isinstance(profile.get("reasoning_effort"), str):
        raise ZSoftSWEAgentContractError(f"{profile_id}: reasoning_effort is required")
    provider = profile.get("agent_provider")
    if provider != {
        "id": "zsoft-openai-compatible",
        "name": "ZSoft metered OpenAI-compatible proxy",
        "auth_mode": "openai-compatible",
        "base_url_env": "OPENAI_COMPAT_BASE_URL",
        "api_key_env": "OPENAI_COMPAT_API_KEY",
        "wire_api": "chat_completions",
    }:
        raise ZSoftSWEAgentContractError(
            f"{profile_id}: agent_provider must preserve the upstream metered proxy"
        )
    for field in (
        "wall_time_seconds",
        "concurrency",
        "cell_concurrency",
        "max_calls",
        "max_input_tokens",
    ):
        value = profile.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ZSoftSWEAgentContractError(f"{profile_id}: {field} must be positive")
    if profile["concurrency"] != 1:
        raise ZSoftSWEAgentContractError(
            f"{profile_id}: native SWE-agent is a non-Goal-Plus method and requires K=1"
        )
    if profile["cell_concurrency"] != 1:
        raise ZSoftSWEAgentContractError(
            f"{profile_id}: initial ZSoft SWE-agent support requires C=1"
        )
    seeds = profile.get("seeds")
    if (
        not isinstance(seeds, list)
        or not seeds
        or len(set(seeds)) != len(seeds)
        or not all(isinstance(seed, int) and not isinstance(seed, bool) for seed in seeds)
    ):
        raise ZSoftSWEAgentContractError(f"{profile_id}: seeds must be unique integers")
    if profile.get("release") != "0.1.0" or profile.get("track") != "tp":
        raise ZSoftSWEAgentContractError(
            f"{profile_id}: release/track must preserve the native 0.1.0 tp scorer"
        )


def resolve_profile(
    profile: dict[str, Any],
    *,
    methods: list[str] | None = None,
    seeds: list[int] | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    wall_time_seconds: int | None = None,
    concurrency: int | None = None,
    cell_concurrency: int | None = None,
) -> dict[str, Any]:
    resolved = json.loads(json.dumps(profile))
    for field, value in (
        ("methods", methods),
        ("seeds", seeds),
        ("model", model),
        ("reasoning_effort", reasoning_effort),
        ("wall_time_seconds", wall_time_seconds),
        ("concurrency", concurrency),
        ("cell_concurrency", cell_concurrency),
    ):
        if value is not None:
            resolved[field] = value
    validate_profile(str(resolved["id"]), resolved)
    return resolved


def swe_agent_root() -> Path:
    value = os.environ.get("BENCH_GOAL_PLUS_SWE_AGENT_ROOT")
    return Path(value).expanduser().resolve() if value else DEFAULT_SWE_AGENT_ROOT


def source_checkout(project: str) -> Path:
    commit = zsoft_adapter.project_commit(project)
    return SOURCE_ROOT / f"{project}-{commit}"


def campaign_dir(campaign: str | Path) -> Path:
    value = Path(campaign)
    return value.expanduser().absolute() if value.is_absolute() else RUNS_ROOT / value
