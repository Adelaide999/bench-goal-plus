"""Finalize Frontier-Engineering campaigns into the generic report contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bench_artifacts import utc_now
from experiments.benchmark_campaign.experiment import coordination_metrics, trajectory_metrics
from experiments.openevolve_compare.reporting import collect_run, render_markdown

from .config import write_json


TERMINAL = {"completed", "partial", "failed", "interrupted"}


def finalize_campaign(destination: Path) -> dict[str, Any]:
    campaign = json.loads((destination / "campaign.json").read_text(encoding="utf-8"))
    if campaign["state"] not in TERMINAL:
        raise RuntimeError(f"cannot finalize non-terminal campaign: {campaign['state']}")
    records = []
    for cell in campaign["cells"]:
        run_dir = Path(cell["run_dir"])
        record = collect_run(
            run_dir,
            campaign_id=campaign["campaign_id"],
            campaign=campaign,
            entry=cell,
            ledger=cell,
        )
        manifest_path = run_dir / "experiment.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file()
            else {}
        )
        score = record.get("score") or {}
        protocol = record.get("protocol") or {}
        record.update(
            {
                "benchmark_id": "frontier-engineering",
                "cell_id": cell["cell_id"],
                "task_id": cell["task_id"],
                "effective_concurrency": campaign["budget"]["live_search_concurrency"],
                "trajectory": trajectory_metrics(
                    run_dir,
                    manifest,
                    seed_score=score.get("seed_best"),
                    direction=protocol.get("direction"),
                    threshold=None,
                ),
                "coordination": coordination_metrics(manifest),
            }
        )
        records.append(record)
    accepted = all(
        record.get("status") == "finished"
        and (record.get("score") or {}).get("valid") is True
        for record in records
    )
    final_state = (
        "completed"
        if campaign["state"] == "completed" and accepted
        else campaign["state"]
        if campaign["state"] != "completed"
        else "partial"
    )
    summary = {
        "schema_version": 1,
        "report_kind": "campaign",
        "campaign_id": campaign["campaign_id"],
        "benchmark": "frontier-engineering",
        "suite": "v1-lite",
        "state": final_state,
        "updated_at": utc_now(),
        "record_count": len(records),
        "budget": campaign["budget"],
        "wall_time_seconds": campaign["budget"]["wall_time_seconds"],
        "live_search_concurrency": campaign["budget"]["live_search_concurrency"],
        "cell_concurrency": campaign["budget"]["cell_concurrency"],
        "attempts": campaign["budget"]["attempts"],
        "records": records,
        "coverage": {
            "final_score": "upstream Frontier-Engineering UnifiedTask evaluator",
            "trajectory": "controller evaluator histories",
            "coordination": "Goal Plus Search Space evidence when applicable",
        },
    }
    summary_path = destination / "campaign-summary.json"
    markdown_path = destination / "campaign-summary.md"
    write_json(summary_path, summary)
    markdown_path.write_text(
        render_markdown(
            summary,
            title=f"Frontier-Engineering v1-lite: {campaign['campaign_id']}",
            output_path=markdown_path,
        ),
        encoding="utf-8",
    )
    return summary
