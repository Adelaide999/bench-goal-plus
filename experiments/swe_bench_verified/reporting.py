"""Finalize SWE-bench evidence without re-running the official evaluator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import SweBenchContractError, read_json, utc_now, write_json
from .runtime import MANIFEST, TERMINAL_STATES


def _record(campaign: Path, manifest: dict[str, Any], cell: dict[str, Any]) -> dict[str, Any]:
    evaluation = cell.get("evaluation") or {}
    agent = cell.get("agent") or {}
    goal_plus = agent.get("goal_plus") or {}
    goal_plus_completion = goal_plus.get("completion") or {}
    resolved = evaluation.get("resolved")
    final_metric = int(resolved) if isinstance(resolved, bool) else None
    return {
        "benchmark_id": "swe-bench-verified",
        "task_id": cell["task_id"],
        "cell_id": cell["cell_id"],
        "method": cell["method"],
        "model": cell["model"],
        "reasoning_effort": cell["reasoning_effort"],
        "seed": 1,
        "status": "succeeded" if cell["state"] == "completed" else cell["state"],
        "incomplete_reason": cell.get("incomplete_reason") or cell.get("error"),
        "budget": {
            "wall_time_seconds": manifest["budget"]["wall_time_seconds"],
            "live_search_concurrency": manifest["budget"][
                "live_search_concurrency"
            ],
            "cell_concurrency": manifest["budget"]["cell_concurrency"],
            "attempts": manifest["budget"]["attempts"],
        },
        "protocol": {
            "metric_name": "resolved",
            "direction": "maximize",
            "dataset": manifest["dataset"]["name"],
            "dataset_revision": manifest["dataset"]["revision"],
            "swebench_commit": manifest["source"]["swebench_commit"],
            "image": cell["image"],
            "base_commit": cell["base_commit"],
            "agent_provider": cell.get("agent_provider"),
            "official_evaluator": True,
            "official_evaluator_once": evaluation.get("calls") == 1,
            "goal_plus": {
                "required": cell["method"] == "goal-plus-pi",
                "completion": goal_plus_completion or None,
                "actual_subagent_count": goal_plus.get("actual_subagent_count"),
                "runs": goal_plus.get("runs") or [],
                "active_pi_pool_jobs": goal_plus.get("active_pi_pool_jobs") or [],
                "evidence_annotator": (
                    (agent.get("runtime") or {}).get("evidence_annotator")
                ),
            },
        },
        "score": {
            "final": final_metric,
            "raw_metrics": {
                "resolved": resolved,
                "patch_applied": evaluation.get("patch_applied"),
            },
            "valid": evaluation.get("state") == "completed",
        },
        "execution": {
            "agent_runtime_seconds": agent.get("runtime_seconds"),
            "agent_total_runtime_seconds": agent.get("total_runtime_seconds"),
            "agent_setup_runtime_seconds": agent.get("setup_runtime_seconds"),
            "finalization_grace_seconds": agent.get("finalization_grace_seconds"),
            "evaluator_runtime_seconds": evaluation.get("runtime_seconds"),
            "evaluator_calls": {
                "total_claimed": evaluation.get("calls"),
                "coverage": (
                    "complete" if isinstance(evaluation.get("calls"), int) else "missing"
                ),
            },
            "usage": {
                "outer_agent": agent.get("usage")
                or {"coverage": "unavailable"},
                "goal_plus_workers": goal_plus.get("worker_usage")
                or {"coverage": "unavailable"},
            },
            "goal_plus_closeout": agent.get("goal_plus_closeout"),
            "agent_container": agent.get("container"),
        },
        "patch": {
            "exists": agent.get("patch_exists"),
            "path": cell["patch_file"],
            "apply_status": evaluation.get("patch_applied"),
        },
        "run_dir": str(campaign),
        "evidence": {
            "agent_stdout": agent.get("stdout_file"),
            "agent_stderr": agent.get("stderr_file"),
            "official_report": evaluation.get("report_file"),
            "official_stdout": evaluation.get("stdout_file"),
            "official_stderr": evaluation.get("stderr_file"),
            "goal_plus_state": (
                (goal_plus.get("export") or {}).get("destination")
                if goal_plus
                else None
            ),
            "goal_plus_export": goal_plus.get("export") if goal_plus else None,
        },
    }


def _markdown(summary: dict[str, Any]) -> str:
    record = summary["records"][0]
    raw = record["score"]["raw_metrics"]
    lines = [
        f"# SWE-bench Verified report: {summary['campaign_id']}",
        "",
        f"Execution state: `{summary['state']}`.",
        "",
        "| Task | Method | Model | Resolved | Patch applied | Subagents | Evaluator calls |",
        "|---|---|---|---:|---:|---:|---:|",
        (
            f"| {record['task_id']} | {record['method']} | {record['model']} | "
            f"{raw['resolved'] if raw['resolved'] is not None else ''} | "
            f"{raw['patch_applied'] if raw['patch_applied'] is not None else ''} | "
            f"{record['protocol']['goal_plus']['actual_subagent_count'] if record['protocol']['goal_plus']['required'] else ''} | "
            f"{record['execution']['evaluator_calls']['total_claimed']} |"
        ),
        "",
        f"Dataset revision: `{record['protocol']['dataset_revision']}`.",
        "",
        f"Official SWE-bench harness commit: `{record['protocol']['swebench_commit']}`.",
        "",
    ]
    return "\n".join(lines)


def finalize_campaign(campaign: Path) -> dict[str, Any]:
    manifest = read_json(campaign / MANIFEST)
    if manifest.get("state") not in TERMINAL_STATES:
        raise SweBenchContractError(
            f"campaign is not terminal: {manifest.get('state')!r}"
        )
    records = [_record(campaign, manifest, cell) for cell in manifest["cells"]]
    evaluated = [
        record
        for record in records
        if isinstance(record["score"]["raw_metrics"]["resolved"], bool)
    ]
    applied = [
        record
        for record in records
        if isinstance(record["score"]["raw_metrics"]["patch_applied"], bool)
    ]
    summary = {
        "schema_version": 1,
        "report_kind": "swe-bench-verified",
        "campaign_id": manifest["campaign_id"],
        "benchmark_id": "swe-bench-verified",
        "state": manifest["state"],
        "generated_at": utc_now(),
        "budget": manifest["budget"],
        "dataset": manifest["dataset"],
        "source": manifest["source"],
        "aggregates": {
            "task_count": len(records),
            "evaluated_count": len(evaluated),
            "resolved_count": sum(
                record["score"]["raw_metrics"]["resolved"] for record in evaluated
            ),
            "resolved_rate": (
                sum(
                    record["score"]["raw_metrics"]["resolved"]
                    for record in evaluated
                )
                / len(evaluated)
                if evaluated
                else None
            ),
            "patch_apply_rate": (
                sum(
                    record["score"]["raw_metrics"]["patch_applied"]
                    for record in applied
                )
                / len(applied)
                if applied
                else None
            ),
            "official_evaluator_calls": sum(
                record["execution"]["evaluator_calls"]["total_claimed"]
                for record in records
                if isinstance(
                    record["execution"]["evaluator_calls"]["total_claimed"], int
                )
            ),
        },
        "records": records,
    }
    write_json(campaign / "campaign-summary.json", summary)
    (campaign / "campaign-summary.md").write_text(
        _markdown(summary), encoding="utf-8"
    )
    return summary
