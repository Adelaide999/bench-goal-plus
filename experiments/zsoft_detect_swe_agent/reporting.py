"""Normalize native ZSoft runner, usage, and scorer evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bench_artifacts import utc_now

from .config import write_json


TERMINAL = {"completed", "partial", "failed", "interrupted"}


def _record(campaign: dict[str, Any], cell: dict[str, Any]) -> dict[str, Any]:
    metrics = cell.get("run_metrics") if isinstance(cell.get("run_metrics"), dict) else {}
    tokens = metrics.get("tokens") if isinstance(metrics.get("tokens"), dict) else {}
    score_info = cell.get("score") if isinstance(cell.get("score"), dict) else {}
    raw_score = score_info.get("payload") if isinstance(score_info.get("payload"), dict) else {}
    score_valid = bool(score_info.get("returncode") == 0 and raw_score)
    return {
        "benchmark_id": "zsoft-detect",
        "task_id": cell["task_id"],
        "cell_id": cell["cell_id"],
        "method": cell["method"],
        "model": campaign["model"],
        "reasoning_effort": campaign["reasoning_effort"],
        "seed": cell["seed"],
        "status": "succeeded" if cell["state"] == "completed" else cell["state"],
        "incomplete_reason": cell.get("error"),
        "error": cell.get("error"),
        "run_dir": cell["run_dir"],
        "budget": campaign["budget"],
        "effective_concurrency": 1,
        "protocol": {
            "metric_name": "f1",
            "direction": "maximize",
            "wall_time_seconds": campaign["budget"]["wall_time_seconds"],
            "concurrency": 1,
            "source_revision": cell["source_revision"],
            "native_runner": "swe-agent",
            "swe_agent_commit": campaign["protocol"]["swe_agent_commit"],
            "sandbox": "bubblewrap",
            "dataset_release": campaign["protocol"]["release"],
            "track": campaign["protocol"]["track"],
            "reasoning_effort_control": campaign["protocol"][
                "reasoning_effort_control"
            ],
            "matched_comparison_eligible": False,
            "known_protocol_issue": (
                "the upstream SWE-agent launcher does not expose an explicit "
                "reasoning-effort control"
            ),
        },
        "score": {
            "valid": score_valid,
            "final": raw_score.get("f1") if score_valid else None,
            "directional_gain": None,
            "raw_metrics": raw_score,
        },
        "execution": {
            "duration_seconds": (
                metrics.get("timing", {}).get("elapsed_ms") / 1000
                if isinstance(metrics.get("timing", {}).get("elapsed_ms"), int)
                else None
            ),
            "outer_trajectories": 1 if cell.get("launcher_returncode") is not None else 0,
            "evaluator_calls": {
                "total_claimed": 1 if score_info.get("attempted") else 0,
                "coverage": "complete" if score_info.get("attempted") else "missing",
            },
            "usage": {
                "input_tokens": tokens.get("input_tokens"),
                "cached_input_tokens": tokens.get("cached_input_tokens"),
                "fresh_input_tokens": tokens.get("fresh_input_tokens"),
                "output_tokens": tokens.get("output_tokens"),
                "inference_requests": tokens.get("inference_requests"),
                "coverage": "complete" if tokens.get("measurement_complete") else "incomplete",
                "source": tokens.get("source"),
            },
        },
        "evidence": {
            "run_metrics": str(Path(cell["run_dir"]) / "run-metrics.json"),
            "submission": str(Path(cell["run_dir"]) / "submission"),
            "launcher_stdout": str(Path(cell["cell_dir"]) / "launcher.stdout.log"),
            "launcher_stderr": str(Path(cell["cell_dir"]) / "launcher.stderr.log"),
            "score_stdout": str(Path(cell["cell_dir"]) / "score.stdout.json"),
        },
    }


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# ZSoft Detect SWE-agent: {summary['campaign_id']}",
        "",
        f"State: `{summary['state']}`. Native runner: pinned SWE-agent in Bubblewrap.",
        "",
        "| Task | Seed | State | F1 | TP | FP | FN | Token coverage |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for record in summary["records"]:
        raw = record["score"]["raw_metrics"]
        usage = record["execution"]["usage"]
        values = [
            record["task_id"],
            record["seed"],
            record["status"],
            record["score"]["final"],
            raw.get("tp"),
            raw.get("fp"),
            raw.get("fn"),
            usage["coverage"],
        ]
        rendered = " | ".join(
            "" if value is None else str(value) for value in values
        )
        lines.append(f"| {rendered} |")
    return "\n".join(lines) + "\n"


def finalize_campaign(destination: Path) -> dict[str, Any]:
    campaign_path = destination / "campaign.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    if campaign["state"] not in TERMINAL:
        raise RuntimeError(f"cannot finalize non-terminal campaign: {campaign['state']}")
    records = [_record(campaign, cell) for cell in campaign["cells"]]
    accepted = all(
        record["status"] == "succeeded"
        and record["score"]["valid"]
        and record["execution"]["usage"]["coverage"] == "complete"
        for record in records
    )
    state = "completed" if campaign["state"] == "completed" and accepted else campaign["state"]
    if campaign["state"] == "completed" and not accepted:
        state = "partial"
        campaign["state"] = "partial"
        write_json(campaign_path, campaign)
    summary = {
        "schema_version": 1,
        "report_kind": "campaign",
        "campaign_id": campaign["campaign_id"],
        "benchmark": "zsoft-detect",
        "runner": "zsoft-detect-native",
        "state": state,
        "updated_at": utc_now(),
        "record_count": len(records),
        "budget": campaign["budget"],
        "wall_time_seconds": campaign["budget"]["wall_time_seconds"],
        "live_search_concurrency": 1,
        "cell_concurrency": 1,
        "attempts": campaign["budget"]["attempts"],
        "records": records,
        "coverage": {
            "final_score": "benchmark-owned deterministic score_submission.py",
            "usage": "provider-reported usage through the upstream metered proxy",
            "sandbox": "upstream Bubblewrap launcher",
        },
    }
    write_json(destination / "campaign-summary.json", summary)
    (destination / "campaign-summary.md").write_text(
        _markdown(summary), encoding="utf-8"
    )
    return summary
