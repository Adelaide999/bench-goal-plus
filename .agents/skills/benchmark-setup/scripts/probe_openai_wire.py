#!/usr/bin/env python3
"""Probe OpenAI Responses and Chat Completions without exposing credentials."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe an OpenAI-compatible endpoint and prefer Responses when "
            "both wire APIs work. The API key is read only from an env var."
        )
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", required=True)
    parser.add_argument(
        "--probe",
        choices=("both", "responses", "chat"),
        default="both",
    )
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-output-tokens", type=int, default=64)
    parser.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high", "xhigh", "max"),
        help="Add an OpenAI Responses reasoning object to that probe.",
    )
    return parser.parse_args()


def _error_fields(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    error = payload.get("error")
    if not isinstance(error, dict):
        return {}
    return {
        key: error[key]
        for key in ("type", "code", "param")
        if isinstance(error.get(key), (str, int, float, bool))
    }


def _response_facts(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    facts: dict[str, Any] = {}
    for key in ("object", "model"):
        if isinstance(payload.get(key), str):
            facts[key] = payload[key]
    if isinstance(payload.get("status"), str):
        facts["response_status"] = payload["status"]

    output = payload.get("output")
    if isinstance(output, list):
        facts["output_types"] = [
            item.get("type")
            for item in output
            if isinstance(item, dict) and isinstance(item.get("type"), str)
        ]

    usage = payload.get("usage")
    if isinstance(usage, dict):
        details = usage.get("output_tokens_details")
        if isinstance(details, dict) and isinstance(
            details.get("reasoning_tokens"), int
        ):
            facts["reasoning_tokens"] = details["reasoning_tokens"]
    return facts


def _post_json(
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "bench-goal-plus-openai-wire-probe/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "http_status": None,
            "transport_error": type(exc.reason).__name__,
        }

    try:
        decoded: Any = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        decoded = None

    result: dict[str, Any] = {
        "ok": 200 <= status < 300,
        "http_status": status,
    }
    if result["ok"]:
        result.update(_response_facts(decoded))
    else:
        result.update(_error_fields(decoded))
    return result


def main() -> int:
    args = _parse_args()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.api_key_env):
        raise SystemExit("--api-key-env must be an environment variable name")
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"missing credential environment variable: {args.api_key_env}")
    if args.max_output_tokens <= 0:
        raise SystemExit("--max-output-tokens must be positive")

    base_url = args.base_url.rstrip("/")
    probes: dict[str, dict[str, Any]] = {}

    if args.probe in ("both", "responses"):
        payload: dict[str, Any] = {
            "model": args.model,
            "input": "Reply with exactly WIRE_OK.",
            "max_output_tokens": args.max_output_tokens,
        }
        if args.reasoning_effort:
            payload["reasoning"] = {
                "effort": args.reasoning_effort,
                "summary": "auto",
            }
        probes["openai-responses"] = _post_json(
            f"{base_url}/responses", api_key, payload, args.timeout
        )

    if args.probe in ("both", "chat"):
        probes["openai-completions"] = _post_json(
            f"{base_url}/chat/completions",
            api_key,
            {
                "model": args.model,
                "messages": [
                    {"role": "user", "content": "Reply with exactly WIRE_OK."}
                ],
                "max_tokens": args.max_output_tokens,
            },
            args.timeout,
        )

    recommendation = None
    if probes.get("openai-responses", {}).get("ok"):
        recommendation = "openai-responses"
    elif probes.get("openai-completions", {}).get("ok"):
        recommendation = "openai-completions"

    print(
        json.dumps(
            {
                "base_url": base_url,
                "model": args.model,
                "api_key_env": args.api_key_env,
                "probes": probes,
                "recommended_pi_api": recommendation,
                "recommendation_scope": "wire-only; require a Pi streaming tool loop",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if recommendation else 1


if __name__ == "__main__":
    raise SystemExit(main())
