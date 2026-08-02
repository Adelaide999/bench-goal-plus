"""Shared Codex CLI configuration for OpenAI-compatible Responses providers."""

from __future__ import annotations

import json


DEFAULT_PROVIDER_ID = "bench_proxy"
DEFAULT_PROVIDER_NAME = "Benchmark OpenAI-compatible proxy"


def codex_responses_provider_args(
    base_url: str,
    *,
    provider_id: str = DEFAULT_PROVIDER_ID,
    provider_name: str = DEFAULT_PROVIDER_NAME,
    api_key_env: str = "OPENAI_API_KEY",
) -> list[str]:
    """Return a fail-closed Codex custom-provider configuration."""
    return [
        "--config",
        f'model_provider="{provider_id}"',
        "--config",
        f"model_providers.{provider_id}.name={json.dumps(provider_name)}",
        "--config",
        f"model_providers.{provider_id}.base_url={json.dumps(base_url)}",
        "--config",
        f'model_providers.{provider_id}.env_key="{api_key_env}"',
        "--config",
        f'model_providers.{provider_id}.wire_api="responses"',
    ]
