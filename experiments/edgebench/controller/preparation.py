"""Resolve an EdgeBench profile into immutable campaign and cell manifests."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from . import io
from .context import current_paths
from .environment import task_config
from .profiles import (
    ALLOWED_PROTOCOL_OVERRIDE_FIELDS,
    METHODS,
    OFFICIAL_SCHEDULED_RUNS,
    api_protocol_for_methods,
    load_official_codex_protocol,
    official_task_protocol,
    profile_task_protocol,
    protocol_diff,
    validate_claude_thinking_contract,
)


def prepare(args: argparse.Namespace, profile: dict[str, Any]) -> Path:
    paths = current_paths()
    official_protocol = load_official_codex_protocol()
    methods = args.method or list(profile["methods"])
    unknown = set(methods) - set(METHODS)
    if unknown:
        raise ValueError("unknown EdgeBench method(s): " + ", ".join(sorted(unknown)))
    api_protocol = api_protocol_for_methods(methods)
    wall_time = int(args.wall_time_seconds or profile["wall_time_seconds"])
    concurrency = int(args.concurrency or profile["concurrency"])
    cell_concurrency = int(
        getattr(args, "cell_concurrency", None)
        or profile.get("cell_concurrency", 1)
    )
    model = args.model or profile["model"]
    requested_reasoning = getattr(args, "reasoning_effort", None)
    if requested_reasoning is not None:
        reasoning = requested_reasoning
    elif "reasoning_effort" in profile:
        reasoning = profile["reasoning_effort"]
    elif api_protocol == "anthropic":
        reasoning = None
    else:
        reasoning = "high"
    thinking = profile.get("thinking") if api_protocol == "anthropic" else None
    if api_protocol == "anthropic":
        validate_claude_thinking_contract(thinking, reasoning)
    backend = str(profile.get("backend") or "docker")
    judge_concurrency = int(profile.get("judge_concurrency", 1))
    override_reasons = dict(profile["protocol_override_reasons"])
    profile_protocol_overrides = dict(profile.get("protocol_overrides") or {})
    allowed_protocol_override_fields = (
        ALLOWED_PROTOCOL_OVERRIDE_FIELDS | set(profile_protocol_overrides)
    )
    if wall_time < 1 or concurrency < 1 or cell_concurrency < 1:
        raise ValueError(
            "wall time, concurrency, and cell concurrency must be positive"
        )

    campaign_id = io.sanitize_id(
        args.campaign_id or f"{profile['id']}-{io.campaign_stamp()}"
    )
    destination = paths.runs_root / campaign_id
    if destination.exists():
        raise FileExistsError(
            f"campaign already exists and will not be overwritten: {destination}"
        )
    destination.mkdir(parents=True)

    cells: list[dict[str, Any]] = []
    for task_id in profile["task_ids"]:
        config = task_config(task_id)
        official_effective = official_task_protocol(
            official_protocol, task_id, config
        )
        profile_effective = profile_task_protocol(
            profile, official_protocol, task_id, config
        )
        official_contract = {
            **official_effective,
            "attempts_per_task": OFFICIAL_SCHEDULED_RUNS,
            "cell_concurrency": None,
            "judge_concurrency": None,
            "model": official_protocol["official_model"],
            "reasoning_effort": None,
        }
        prompt = str(config["work"]["agent_query"])
        for method in methods:
            method_config = METHODS[method]
            cell_id = io.sanitize_id(f"{task_id}--{method}")
            outer_replicas = (
                concurrency
                if method_config["outer_replicas"] == "concurrency"
                else int(method_config["outer_replicas"])
            )
            effective_contract = {
                **profile_effective,
                "agent": method_config["agent"],
                "attempts_per_task": outer_replicas,
                "backend": backend,
                "cell_concurrency": cell_concurrency,
                "judge_concurrency": judge_concurrency,
                "model": model,
                "reasoning_effort": reasoning,
                "timeout": wall_time,
            }
            differences = protocol_diff(
                official=official_contract,
                effective=effective_contract,
                reasons=override_reasons,
                allowed_fields=allowed_protocol_override_fields,
            )
            cell = {
                "schema_version": 1,
                "cell_id": cell_id,
                "task_id": task_id,
                "method": method,
                "sforge_agent": method_config["agent"],
                "api_protocol": method_config["api_protocol"],
                "backend": backend,
                "model": model,
                "reasoning_effort": reasoning,
                "thinking": thinking,
                "claude_context_window_tokens": profile.get(
                    "claude_context_window_tokens"
                ),
                "claude_autocompact_percent": profile.get(
                    "claude_autocompact_percent"
                ),
                "wall_time_seconds": wall_time,
                "live_search_concurrency": concurrency,
                "outer_replicas": outer_replicas,
                "outer_replica_concurrency": concurrency if outer_replicas > 1 else 1,
                "inner_search_concurrency": (
                    concurrency if method_config["inner_search"] else 0
                ),
                "worker_runtime_seconds": min(
                    wall_time,
                    int(profile.get("worker_runtime_seconds", wall_time)),
                ),
                "goal_plus_finalization_grace_seconds": int(
                    profile.get("goal_plus_finalization_grace_seconds", 300)
                ),
                "eval_interval_seconds": int(effective_contract["eval_interval"]),
                "judge_concurrency": judge_concurrency,
                "judge_port": int(profile.get("judge_port", 8080)),
                "work_cpu_limit": effective_contract["work_cpu_limit"],
                "work_mem_limit": effective_contract["work_mem_limit"],
                "judge_cpu_limit": effective_contract["judge_cpu_limit"],
                "judge_mem_limit": effective_contract["judge_mem_limit"],
                "submission_cooldown": effective_contract["submission_cooldown"],
                "max_submissions": effective_contract["max_submissions"],
                "auto_eval_enabled": not effective_contract["disable_auto_eval"],
                "auto_resume_enabled": not effective_contract[
                    "disable_auto_resume"
                ],
                "stop_hook_enabled": not effective_contract["disable_stop_hook"],
                "internet": effective_contract["internet"],
                "internet_source": (
                    f"profiles/{profile['id']}.protocol_overrides.internet"
                    if "internet" in profile_protocol_overrides
                    else f"tasks/{task_id}.json"
                ),
                "protocol_source": {
                    "path": official_protocol["source"],
                    "sha256": official_protocol["source_sha256"],
                },
                "official_defaults": official_protocol["defaults"],
                "official_task_overrides": official_protocol["tasks"][task_id],
                "official_effective_protocol": official_contract,
                "effective_protocol": effective_contract,
                "intentional_overrides": {
                    entry["field"]: {
                        "value": entry["effective"],
                        "reason": entry["reason"],
                    }
                    for entry in differences
                },
                "protocol_diff": differences,
                "protocol_classification": (
                    "official_protocol"
                    if not differences
                    else "official_protocol_with_intentional_overrides"
                ),
                "official_edgebench_comparable": not differences,
                "prompt_sha256": io.sha256_text(prompt),
                "metric_direction": config["judge"].get(
                    "score_direction", "maximize"
                ),
                "sforge_run_id": io.sanitize_id(
                    f"{campaign_id}-{task_id}-{method}"
                ),
                "state": "prepared",
                "created_at": io.utc_now(),
            }
            cell_path = destination / "cells" / cell_id
            cell_path.mkdir(parents=True)
            io.write_json(cell_path / "cell.json", cell)
            cells.append(
                {
                    "cell_id": cell_id,
                    "task_id": task_id,
                    "method": method,
                    "state": "prepared",
                    "official_edgebench_comparable": not differences,
                }
            )

    snapshot = {
        **profile,
        "methods": methods,
        "model": model,
        "reasoning_effort": reasoning,
        "api_protocol": api_protocol,
        "thinking": thinking,
        "wall_time_seconds": wall_time,
        "concurrency": concurrency,
        "cell_concurrency": cell_concurrency,
        "protocol_source": {
            "path": official_protocol["source"],
            "sha256": official_protocol["source_sha256"],
        },
    }
    io.write_json(destination / "profile.json", snapshot)
    campaign_official_comparable = all(
        item["official_edgebench_comparable"] for item in cells
    )
    io.write_json(
        destination / "campaign.json",
        {
            "schema_version": 1,
            "campaign_id": campaign_id,
            "profile": profile["id"],
            "state": "prepared",
            "created_at": io.utc_now(),
            "edgebench_tracking_branch": io.upstream_entry("edgebench")[
                "tracking_branch"
            ],
            "edgebench_branch": io.git_branch(paths.edge_root),
            "edgebench_commit": io.git_head(paths.edge_root),
            "goal_plus_tracking_branch": io.upstream_entry("goal_plus")[
                "tracking_branch"
            ],
            "goal_plus_branch": io.git_branch(paths.goal_plus_root),
            "goal_plus_commit": io.git_head(paths.goal_plus_root),
            "dataset_revision": profile["dataset_revision"],
            "task_ids": list(profile["task_ids"]),
            "methods": methods,
            "model": model,
            "reasoning_effort": reasoning,
            "api_protocol": api_protocol,
            "thinking": thinking,
            "wall_time_seconds": wall_time,
            "concurrency": concurrency,
            "cell_concurrency": cell_concurrency,
            "worker_runtime_seconds": profile.get("worker_runtime_seconds"),
            "goal_plus_finalization_grace_seconds": int(
                profile.get("goal_plus_finalization_grace_seconds", 300)
            ),
            "protocol_source": {
                "path": official_protocol["source"],
                "sha256": official_protocol["source_sha256"],
                "official_model": official_protocol["official_model"],
                "stagger_seconds": official_protocol["stagger_seconds"],
            },
            "protocol_classification": (
                "official_protocol"
                if campaign_official_comparable
                else "official_protocol_with_intentional_overrides"
            ),
            "official_edgebench_comparable": campaign_official_comparable,
            "cells": cells,
        },
    )
    io.write_json(
        destination / "controller.json",
        {
            "schema_version": 1,
            "state": "prepared",
            "created_at": io.utc_now(),
            "pid": None,
            "pgid": None,
        },
    )
    print(io.portable_path(destination))
    return destination
