#!/usr/bin/env python3
"""Extract reproducible EdgeBench checkpoint scores from campaign artifacts."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EDGE_ROOT = ROOT / "third_party" / "edgebench"
RUNS_ROOT = ROOT / "runs" / "edgebench"
TASKS_DIR = EDGE_ROOT / "tasks"

for source_root in (ROOT, EDGE_ROOT):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from bench_runtime_paths import configure_temp_environment
from sforge.harness.score_rescale import (
    parse_rescale_spec,
    rescale_score,
    rescale_score_extended,
)
from sforge.harness.selection import select_best


configure_temp_environment()

IDENTITY_0_100_TASKS = {
    "borden_source_inversion",
    "college_english_exam_bank",
    "cta_risk_budget_optimization",
    "dabic_gravity_inversion",
    "jagua_nesting_optimization",
    "k12_math_recommendation",
    "portfolio_risk_calibration",
}
TICK_PATTERN = re.compile(
    r"^\[(?P<at>[^]]+)] submitted \d+ bytes -> "
    r"(?P<submission_id>\S+) round=(?P<round>\S+)$"
)
REPORT_FIELDS = (
    "submission_id",
    "status",
    "valid",
    "pass_rate",
    "score",
    "score_0_100",
    "score_0_100_extended",
    "passed",
    "failed",
    "errors",
    "total_tests",
    "summary",
    "submitted_at",
    "runtime_seconds",
)
TERMINAL_CELL_STATES = {"completed", "failed", "interrupted"}
TERMINAL_CAMPAIGN_STATES = {"completed", "failed", "interrupted", "partial"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def portable_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.new")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def resolve_campaign(value: str) -> Path:
    supplied = Path(value).expanduser()
    candidates = [supplied] if supplied.is_absolute() else [ROOT / supplied, RUNS_ROOT / supplied]
    for candidate in candidates:
        if (candidate / "campaign.json").is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"EdgeBench campaign not found: {value}")


def resolve_output_dir(campaign: Path, value: Path | None) -> Path:
    if value is None:
        return campaign / "timecurve"
    value = value.expanduser()
    return value.resolve() if value.is_absolute() else (ROOT / value).resolve()


def finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def checkpoint_seconds(hours: float) -> int:
    if not math.isfinite(hours) or hours <= 0:
        raise ValueError(f"checkpoint hours must be positive: {hours}")
    seconds = hours * 3600.0
    rounded = round(seconds)
    if not math.isclose(seconds, rounded, abs_tol=1e-6):
        raise ValueError(f"checkpoint does not resolve to whole seconds: {hours}")
    return int(rounded)


def checkpoint_label(hours: float) -> str:
    return f"{hours:g}h"


def parse_epoch(value: Any) -> float | None:
    numeric = finite_float(value)
    if numeric is not None:
        return numeric
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.timestamp()


def task_started_at(task_run: Path, cell: dict[str, Any]) -> float | None:
    started_path = task_run / "started_at"
    if started_path.is_file():
        try:
            lines = started_path.read_text(encoding="utf-8").strip().splitlines()
        except OSError:
            lines = []
        for line in reversed(lines):
            parsed = parse_epoch(line)
            if parsed is not None:
                return parsed
    return parse_epoch(cell.get("started_at"))


def task_run_dir(campaign: Path, cell: dict[str, Any]) -> Path | None:
    cell_path = campaign / "cells" / str(cell["cell_id"])
    run_id = str(cell.get("sforge_run_id") or "")
    task_id = str(cell["task_id"])
    exact = cell_path / "sforge" / "runs" / run_id / task_id
    if exact.is_dir():
        return exact
    candidates = sorted((cell_path / "sforge" / "runs").glob(f"{run_id}*/{task_id}"))
    return candidates[-1] if candidates else None


def task_config(task_id: str) -> dict[str, Any]:
    path = TASKS_DIR / f"{task_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"EdgeBench task definition not found: {path}")
    return read_json(path)


def parse_auto_ticks(task_run: Path) -> dict[str, dict[str, Any]]:
    path = task_run / "auto_eval_ticks.log"
    if not path.is_file():
        return {}
    ticks: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = TICK_PATTERN.match(line.strip())
        if not match:
            continue
        data = match.groupdict()
        data["source"] = portable_path(path)
        ticks[data["round"]] = data
    return ticks


def checkpoint_round(seconds: int, eval_interval: int) -> str | None:
    if eval_interval <= 0:
        return None
    ratio = seconds / eval_interval
    rounded = round(ratio)
    if rounded < 1 or not math.isclose(ratio, rounded, abs_tol=1e-9):
        return None
    return f"auto-{rounded}"


def judge_reports(
    campaign: Path,
    cell: dict[str, Any],
    task_run: Path,
) -> tuple[dict[str, tuple[dict[str, Any], Path]], dict[str, tuple[dict[str, Any], Path]]]:
    run_id = str(cell["sforge_run_id"])
    task_id = str(cell["task_id"])
    roots = [
        campaign / "judge" / "runs" / run_id / task_id / "submissions",
        task_run / "submissions",
    ]
    by_id: dict[str, tuple[dict[str, Any], Path]] = {}
    by_round: dict[str, tuple[dict[str, Any], Path]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*/report.json")):
            try:
                report = read_json(path)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            submission_id = str(report.get("submission_id") or "")
            if submission_id:
                by_id[submission_id] = (report, path)
            by_round[path.parent.name] = (report, path)
    return by_id, by_round


def merged_history(
    campaign: Path,
    cell: dict[str, Any],
    task_run: Path,
) -> list[dict[str, Any]]:
    history_path = task_run / "run_history.json"
    if not history_path.is_file():
        return []
    history = read_json(history_path)
    raw_entries = history.get("entries")
    if not isinstance(raw_entries, list):
        return []
    by_id, by_round = judge_reports(campaign, cell, task_run)
    entries: list[dict[str, Any]] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        entry = dict(raw_entry)
        submission_id = str(entry.get("submission_id") or "")
        round_id = str(entry.get("round") or "")
        found = by_id.get(submission_id) if submission_id else None
        found = found or by_round.get(round_id)
        if found is not None:
            report, path = found
            for field in REPORT_FIELDS:
                if field in report:
                    entry[field] = report[field]
            entry["status"] = "completed"
            entry["_report_path"] = portable_path(path)
        entries.append(entry)
    return entries


def normalized_score(
    task_id: str,
    config: dict[str, Any],
    entry: dict[str, Any],
) -> tuple[float | None, float | None, str]:
    reported = finite_float(entry.get("score_0_100"))
    reported_extended = finite_float(entry.get("score_0_100_extended"))
    if reported is not None:
        return reported, reported_extended if reported_extended is not None else reported, "judge_report"

    raw = finite_float(entry.get("score"))
    if raw is None:
        return None, None, "unavailable"
    rescale = config.get("judge", {}).get("rescale")
    spec = parse_rescale_spec(rescale if isinstance(rescale, dict) else None)
    if spec is not None:
        official = finite_float(rescale_score(spec, raw))
        extended = finite_float(
            rescale_score_extended(spec, raw, valid=entry.get("valid", True) is not False)
        )
        return official, extended, "task_rescale"
    if task_id in IDENTITY_0_100_TASKS:
        identity = max(0.0, min(100.0, raw))
        return identity, identity, "identity_native_0_100"
    return None, None, "missing_rescale"


def base_row(
    campaign_payload: dict[str, Any],
    cell: dict[str, Any],
    hours: float,
    config: dict[str, Any],
) -> dict[str, Any]:
    judge = config.get("judge") if isinstance(config.get("judge"), dict) else {}
    return {
        "campaign_id": campaign_payload.get("campaign_id"),
        "campaign_state": campaign_payload.get("state"),
        "cell_id": cell.get("cell_id"),
        "cell_state": cell.get("state"),
        "task_id": cell.get("task_id"),
        "method": cell.get("method"),
        "model": cell.get("model"),
        "sforge_run_id": cell.get("sforge_run_id"),
        "checkpoint_hours": hours,
        "checkpoint_seconds": checkpoint_seconds(hours),
        "checkpoint_label": checkpoint_label(hours),
        "game_mode": config.get("game_mode") is True,
        "selection_policy": judge.get("selection") or "pass_rate_first",
        "score_direction": judge.get("score_direction") or "maximize",
        "status": "unavailable",
        "strict_checkpoint": False,
        "valid": None,
        "best_round": None,
        "raw_score": None,
        "score_0_100": None,
        "score_0_100_extended": None,
        "pass_rate": None,
        "normalization_source": None,
        "candidate_count": 0,
        "scored_candidate_count": 0,
        "source": None,
        "reason": None,
    }


def select_checkpoint_best(
    entries: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    judge = config.get("judge") if isinstance(config.get("judge"), dict) else {}
    policy = str(judge.get("selection") or "pass_rate_first")
    direction = str(judge.get("score_direction") or "maximize")
    best = select_best(entries, direction, policy)
    best_round = str(best.get("best_round") or "")
    selected = next(
        (entry for entry in reversed(entries) if str(entry.get("round") or "") == best_round),
        None,
    )
    return best, selected


def ordinary_checkpoint_row(
    campaign: Path,
    campaign_payload: dict[str, Any],
    cell: dict[str, Any],
    config: dict[str, Any],
    hours: float,
) -> dict[str, Any]:
    row = base_row(campaign_payload, cell, hours, config)
    task_run = task_run_dir(campaign, cell)
    if task_run is None:
        row["status"] = "not_started" if cell.get("state") == "prepared" else "missing_task_run"
        row["reason"] = "current SForge task run directory is unavailable"
        return row
    history_path = task_run / "run_history.json"
    if not history_path.is_file():
        row["status"] = "pending_history" if cell.get("state") == "running" else "missing_history"
        row["reason"] = "run_history.json is not available yet"
        return row

    entries = merged_history(campaign, cell, task_run)
    wall_time = int(cell.get("wall_time_seconds") or 0)
    final_checkpoint = wall_time > 0 and row["checkpoint_seconds"] == wall_time
    if final_checkpoint:
        row["anchor_round"] = "final-closeout"
        if cell.get("state") != "completed":
            row["status"] = "pending_final_closeout"
            row["reason"] = "the full-budget checkpoint requires completed closeout artifacts"
            return row
        if not entries:
            row["status"] = "no_scored_submission"
            row["reason"] = "final run history has no submissions"
            return row
        prefix = entries
        anchor_index = len(prefix) - 1
        tick = None
        final_path = task_run / "final_result.json"
        final = read_json(final_path) if final_path.is_file() else {}
        runtime = finite_float(final.get("runtime_seconds"))
        row["strict_checkpoint"] = bool(
            runtime is not None and runtime >= row["checkpoint_seconds"] - 5.0
        )
        row["anchor_offset_seconds"] = runtime
    else:
        eval_interval = int(cell.get("eval_interval_seconds") or 0)
        anchor_round = checkpoint_round(row["checkpoint_seconds"], eval_interval)
        row["anchor_round"] = anchor_round
        if anchor_round is None:
            row["status"] = "unsupported_checkpoint"
            row["reason"] = "checkpoint is not aligned with the configured eval interval"
            return row
        anchor_index = next(
            (index for index, entry in enumerate(entries) if entry.get("round") == anchor_round),
            None,
        )
        if anchor_index is None:
            row["status"] = (
                "checkpoint_not_reached" if cell.get("state") == "running" else "missing_anchor"
            )
            row["reason"] = f"{anchor_round} is absent from run_history.json"
            return row
        prefix = entries[: anchor_index + 1]
        ticks = parse_auto_ticks(task_run)
        tick = ticks.get(anchor_round)

    anchor_entry = prefix[-1]
    row["anchor_submission_id"] = anchor_entry.get("submission_id")
    row["anchor_tick_at"] = tick.get("at") if tick else None
    row["anchor_tick_source"] = tick.get("source") if tick else None
    row["anchor_order_index"] = anchor_index
    row["candidate_count"] = len(prefix)
    row["scored_candidate_count"] = sum(
        1
        for entry in prefix
        if entry.get("status") in (None, "completed") and finite_float(entry.get("score")) is not None
    )
    if not final_checkpoint:
        row["strict_checkpoint"] = bool(
            tick
            and str(tick.get("submission_id") or "")
            == str(anchor_entry.get("submission_id") or "")
        )

    started = task_started_at(task_run, cell)
    row["task_started_at_epoch"] = started
    tick_epoch = parse_epoch(tick.get("at")) if tick else None
    row["anchor_tick_epoch"] = tick_epoch
    if not final_checkpoint:
        row["anchor_offset_seconds"] = (
            tick_epoch - started if tick_epoch is not None and started is not None else None
        )

    best, selected = select_checkpoint_best(prefix, config)
    if selected is None or finite_float(best.get("best_score")) is None:
        row["status"] = "no_scored_submission"
        row["reason"] = "no completed scored submission exists at this checkpoint"
        return row

    task_id = str(cell["task_id"])
    selected_for_score = dict(selected)
    if finite_float(selected_for_score.get("score")) is None:
        selected_for_score["score"] = best.get("best_score")
    normalized, extended, normalization_source = normalized_score(
        task_id, config, selected_for_score
    )
    valid = selected.get("valid", best.get("best_valid", True)) is not False
    row.update(
        {
            "status": "available" if normalized is not None else "available_raw_only",
            "valid": valid,
            "best_round": selected.get("round"),
            "best_submission_id": selected.get("submission_id"),
            "raw_score": finite_float(best.get("best_score")),
            "score_0_100": normalized,
            "score_0_100_extended": extended,
            "pass_rate": finite_float(selected.get("pass_rate")),
            "normalization_source": normalization_source,
            "source": selected.get("_report_path") or portable_path(history_path),
            "reason": None if normalized is not None else "raw score has no approved 0-100 mapping",
        }
    )
    return row


def game_snapshot_path(output_dir: Path, cell_id: str, seconds: int) -> Path:
    return output_dir / "game_snapshots" / cell_id / f"{seconds}.json"


def game_checkpoint_row(
    campaign: Path,
    campaign_payload: dict[str, Any],
    cell: dict[str, Any],
    config: dict[str, Any],
    hours: float,
    output_dir: Path,
) -> dict[str, Any]:
    row = base_row(campaign_payload, cell, hours, config)
    snapshot_path = game_snapshot_path(output_dir, str(cell["cell_id"]), row["checkpoint_seconds"])
    if not snapshot_path.is_file():
        row["status"] = (
            "pending_game_snapshot"
            if cell.get("state") in {"prepared", "running"}
            else "missing_game_snapshot"
        )
        row["reason"] = "game-mode checkpoints require a live watcher snapshot"
        return row
    snapshot = read_json(snapshot_path)
    if snapshot.get("unavailable") is True:
        row["status"] = "missing_game_snapshot"
        row["reason"] = snapshot.get("reason") or "game-mode checkpoint is unavailable"
        row["snapshot"] = portable_path(snapshot_path)
        return row
    sessions = snapshot.get("sessions") if isinstance(snapshot.get("sessions"), list) else []
    entries: list[dict[str, Any]] = []
    for session in sessions:
        if not isinstance(session, dict):
            continue
        score = finite_float(session.get("score"))
        if score is None:
            continue
        entries.append(
            {
                "type": "game",
                "status": "completed",
                "round": session.get("round"),
                "score": score,
                "max_score": session.get("max_score"),
                "pass_rate": session.get("pass_rate"),
                "valid": True,
                "_source_path": session.get("source"),
            }
        )

    if entries:
        best, selected = select_checkpoint_best(entries, config)
        assert selected is not None
        raw = finite_float(best.get("best_score"))
        pass_rate = finite_float(selected.get("pass_rate"))
        best_round = selected.get("round")
        source = selected.get("_source_path") or portable_path(snapshot_path)
    else:
        raw = 0.0
        pass_rate = 0.0
        best_round = None
        source = portable_path(snapshot_path)
        selected = {"score": raw, "valid": True}

    normalized, extended, normalization_source = normalized_score(
        str(cell["task_id"]), config, selected
    )
    row.update(
        {
            "status": "available" if normalized is not None else "available_raw_only",
            "strict_checkpoint": snapshot.get("strict_checkpoint") is True,
            "valid": True,
            "best_round": best_round,
            "raw_score": raw,
            "score_0_100": normalized,
            "score_0_100_extended": extended,
            "pass_rate": pass_rate,
            "normalization_source": normalization_source,
            "candidate_count": len(entries),
            "scored_candidate_count": len(entries),
            "source": source,
            "snapshot": portable_path(snapshot_path),
            "capture_delay_seconds": snapshot.get("capture_delay_seconds"),
            "reason": None if normalized is not None else "raw score has no approved 0-100 mapping",
        }
    )
    return row


def build_timecurve(campaign: Path, hours: list[float], output_dir: Path) -> dict[str, Any]:
    campaign_payload = read_json(campaign / "campaign.json")
    rows: list[dict[str, Any]] = []
    for summary in campaign_payload.get("cells", []):
        if not isinstance(summary, dict):
            continue
        cell_path = campaign / "cells" / str(summary["cell_id"]) / "cell.json"
        cell = read_json(cell_path)
        config = task_config(str(cell["task_id"]))
        for checkpoint in hours:
            if config.get("game_mode") is True:
                row = game_checkpoint_row(
                    campaign, campaign_payload, cell, config, checkpoint, output_dir
                )
            else:
                row = ordinary_checkpoint_row(
                    campaign, campaign_payload, cell, config, checkpoint
                )
            rows.append(row)

    aggregates: list[dict[str, Any]] = []
    for checkpoint in hours:
        checkpoint_rows = [row for row in rows if row["checkpoint_hours"] == checkpoint]
        available = [
            row
            for row in checkpoint_rows
            if row.get("valid") is True and finite_float(row.get("score_0_100")) is not None
        ]
        scores = [float(row["score_0_100"]) for row in available]
        statuses = Counter(str(row["status"]) for row in checkpoint_rows)
        aggregates.append(
            {
                "checkpoint_hours": checkpoint,
                "checkpoint_seconds": checkpoint_seconds(checkpoint),
                "task_count": len(checkpoint_rows),
                "available_count": len(available),
                "strict_count": sum(row.get("strict_checkpoint") is True for row in available),
                "valid_coverage": len(available) / len(checkpoint_rows) if checkpoint_rows else 0.0,
                "mean_score_0_100": sum(scores) / len(scores) if scores else None,
                "status_counts": dict(sorted(statuses.items())),
            }
        )
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "campaign_id": campaign_payload.get("campaign_id"),
        "campaign_state": campaign_payload.get("state"),
        "campaign": portable_path(campaign),
        "edgebench_commit": campaign_payload.get("edgebench_commit"),
        "model": campaign_payload.get("model"),
        "reasoning_effort": campaign_payload.get("reasoning_effort"),
        "checkpoint_semantics": (
            "before the full wall budget, select the best submission no later than "
            "the inclusive auto-eval anchor; at the full wall budget, use completed "
            "native closeout history; late Judge reports are joined by submission_id"
        ),
        "official_comparison_available": False,
        "official_comparison_note": "The public EdgeBench curves start at 2h; sub-2h rows are local development checkpoints.",
        "aggregates": aggregates,
        "rows": rows,
    }


CSV_FIELDS = (
    "campaign_id",
    "cell_id",
    "task_id",
    "method",
    "model",
    "cell_state",
    "checkpoint_hours",
    "checkpoint_seconds",
    "status",
    "strict_checkpoint",
    "valid",
    "best_round",
    "best_submission_id",
    "raw_score",
    "score_0_100",
    "score_0_100_extended",
    "pass_rate",
    "selection_policy",
    "score_direction",
    "normalization_source",
    "candidate_count",
    "scored_candidate_count",
    "anchor_round",
    "anchor_submission_id",
    "anchor_tick_at",
    "source",
    "reason",
)


def write_timecurve(output_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "timecurve.json"
    csv_path = output_dir / "timecurve.csv"
    write_json_atomic(json_path, payload)
    temporary = csv_path.with_name(csv_path.name + ".new")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(payload["rows"])
    temporary.replace(csv_path)
    return json_path, csv_path


def last_json_line(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    last: dict[str, Any] | None = None
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                last = value
    return last


def game_sessions_at_capture(campaign: Path, cell: dict[str, Any]) -> list[dict[str, Any]]:
    root = (
        campaign
        / "judge"
        / "runs"
        / str(cell["sforge_run_id"])
        / str(cell["task_id"])
        / "submissions"
    )
    sessions: list[dict[str, Any]] = []
    if not root.is_dir():
        return sessions
    for session_dir in sorted(root.glob("game-*")):
        result_path = session_dir / "game_result.json"
        steps_path = session_dir / "steps.jsonl"
        data: dict[str, Any] | None = None
        source: Path | None = None
        if result_path.is_file():
            try:
                data = read_json(result_path)
                source = result_path
            except (OSError, json.JSONDecodeError, ValueError):
                data = None
        if data is None:
            data = last_json_line(steps_path)
            source = steps_path if data is not None else None
        if data is None:
            continue
        score = finite_float(data.get("final_score", data.get("score")))
        if score is None:
            continue
        max_score = finite_float(data.get("max_score"))
        sessions.append(
            {
                "round": session_dir.name,
                "score": score,
                "peak_score": finite_float(data.get("peak_score")),
                "max_score": max_score,
                "pass_rate": score / max_score if max_score not in (None, 0.0) else 0.0,
                "moves": data.get("moves", data.get("move")),
                "done": data.get("done"),
                "source": portable_path(source) if source else None,
            }
        )
    return sessions


def capture_game_snapshot(
    campaign: Path,
    cell: dict[str, Any],
    seconds: int,
    output_dir: Path,
    *,
    observed_at: float | None = None,
    poll_seconds: float = 5.0,
) -> dict[str, Any]:
    observed = time.time() if observed_at is None else observed_at
    task_run = task_run_dir(campaign, cell)
    started = task_started_at(task_run, cell) if task_run is not None else None
    target = started + seconds if started is not None else None
    delay = observed - target if target is not None else None
    snapshot = {
        "schema_version": 1,
        "captured_at": utc_now(),
        "campaign_id": read_json(campaign / "campaign.json").get("campaign_id"),
        "cell_id": cell.get("cell_id"),
        "cell_state": cell.get("state"),
        "task_id": cell.get("task_id"),
        "sforge_run_id": cell.get("sforge_run_id"),
        "checkpoint_seconds": seconds,
        "task_started_at_epoch": started,
        "target_at_epoch": target,
        "observed_at_epoch": observed,
        "capture_delay_seconds": delay,
        "poll_seconds": poll_seconds,
        "strict_checkpoint": bool(
            delay is not None and 0.0 <= delay <= max(10.0, poll_seconds * 2.0)
        ),
        "sessions": game_sessions_at_capture(campaign, cell),
    }
    write_json_atomic(
        game_snapshot_path(output_dir, str(cell["cell_id"]), seconds), snapshot
    )
    return snapshot


def unavailable_game_snapshot(
    campaign: Path,
    cell: dict[str, Any],
    seconds: int,
    output_dir: Path,
    reason: str,
) -> None:
    payload = {
        "schema_version": 1,
        "captured_at": utc_now(),
        "campaign_id": read_json(campaign / "campaign.json").get("campaign_id"),
        "cell_id": cell.get("cell_id"),
        "cell_state": cell.get("state"),
        "task_id": cell.get("task_id"),
        "sforge_run_id": cell.get("sforge_run_id"),
        "checkpoint_seconds": seconds,
        "strict_checkpoint": False,
        "sessions": [],
        "unavailable": True,
        "reason": reason,
    }
    write_json_atomic(
        game_snapshot_path(output_dir, str(cell["cell_id"]), seconds), payload
    )


def game_cells(campaign: Path) -> list[dict[str, Any]]:
    campaign_payload = read_json(campaign / "campaign.json")
    cells: list[dict[str, Any]] = []
    for summary in campaign_payload.get("cells", []):
        if not isinstance(summary, dict):
            continue
        cell = read_json(campaign / "cells" / str(summary["cell_id"]) / "cell.json")
        if task_config(str(cell["task_id"])).get("game_mode") is True:
            cells.append(cell)
    return cells


def process_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        os.kill(value, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def watch_game_checkpoints(
    campaign: Path,
    hours: list[float],
    output_dir: Path,
    poll_seconds: float,
) -> int:
    if poll_seconds <= 0 or poll_seconds > 60:
        raise ValueError("poll seconds must be in (0, 60]")
    seconds_values = [checkpoint_seconds(value) for value in hours]
    initial_cells = game_cells(campaign)
    expected = {
        (str(cell["cell_id"]), seconds)
        for cell in initial_cells
        for seconds in seconds_values
    }
    cell_ids = {str(cell["cell_id"]) for cell in initial_cells}
    if not expected:
        return 0
    metadata_path = output_dir / "watcher.json"
    while True:
        campaign_payload = read_json(campaign / "campaign.json")
        cells = {
            cell_id: read_json(campaign / "cells" / cell_id / "cell.json")
            for cell_id in cell_ids
        }
        now = time.time()
        for cell_id, seconds in sorted(expected):
            path = game_snapshot_path(output_dir, cell_id, seconds)
            if path.is_file():
                continue
            cell = cells[cell_id]
            task_run = task_run_dir(campaign, cell)
            started = task_started_at(task_run, cell) if task_run is not None else None
            if started is not None and now >= started + seconds:
                capture_game_snapshot(
                    campaign,
                    cell,
                    seconds,
                    output_dir,
                    observed_at=now,
                    poll_seconds=poll_seconds,
                )
            elif cell.get("state") in TERMINAL_CELL_STATES:
                unavailable_game_snapshot(
                    campaign,
                    cell,
                    seconds,
                    output_dir,
                    "cell reached a terminal state before the checkpoint",
                )

        remaining = [
            (cell_id, seconds)
            for cell_id, seconds in sorted(expected)
            if not game_snapshot_path(output_dir, cell_id, seconds).is_file()
        ]
        metadata = {
            "schema_version": 1,
            "pid": os.getpid(),
            "campaign": portable_path(campaign),
            "campaign_state": campaign_payload.get("state"),
            "checkpoint_seconds": seconds_values,
            "poll_seconds": poll_seconds,
            "remaining": [
                {"cell_id": cell_id, "checkpoint_seconds": seconds}
                for cell_id, seconds in remaining
            ],
            "updated_at": utc_now(),
        }
        write_json_atomic(metadata_path, metadata)
        if not remaining:
            return 0
        if campaign_payload.get("state") in TERMINAL_CAMPAIGN_STATES:
            for cell_id, seconds in remaining:
                unavailable_game_snapshot(
                    campaign,
                    cells[cell_id],
                    seconds,
                    output_dir,
                    "campaign ended before the checkpoint was captured",
                )
            return 0
        time.sleep(poll_seconds)


def launch_watcher(
    campaign: Path,
    hours: list[float],
    output_dir: Path,
    poll_seconds: float,
) -> int:
    metadata_path = output_dir / "watcher.json"
    if metadata_path.is_file():
        metadata = read_json(metadata_path)
        if process_alive(metadata.get("pid")):
            raise RuntimeError(f"timecurve watcher is already running: {metadata['pid']}")
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_watch",
        "--campaign",
        str(campaign),
        "--checkpoint-hours",
        *[str(value) for value in hours],
        "--output-dir",
        str(output_dir),
        "--poll-seconds",
        str(poll_seconds),
    ]
    log_path = output_dir / "watcher.log"
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=dict(configure_temp_environment(dict(os.environ))),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    write_json_atomic(
        metadata_path,
        {
            "schema_version": 1,
            "pid": process.pid,
            "campaign": portable_path(campaign),
            "checkpoint_seconds": [checkpoint_seconds(value) for value in hours],
            "poll_seconds": poll_seconds,
            "log": portable_path(log_path),
            "launched_at": utc_now(),
        },
    )
    print(json.dumps({"pid": process.pid, "log": portable_path(log_path)}))
    return 0


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--campaign", required=True, help="campaign ID or directory")
    parser.add_argument(
        "--checkpoint-hours",
        nargs="+",
        type=float,
        default=[1.0],
        help="one or more checkpoint hours (default: 1)",
    )
    parser.add_argument("--output-dir", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="write timecurve.json and timecurve.csv")
    add_common_arguments(extract)
    watch = commands.add_parser("watch", help="capture live game-mode checkpoints")
    add_common_arguments(watch)
    watch.add_argument("--poll-seconds", type=float, default=5.0)
    watch.add_argument("--detach", action="store_true")
    hidden = commands.add_parser("_watch", help=argparse.SUPPRESS)
    add_common_arguments(hidden)
    hidden.add_argument("--poll-seconds", type=float, default=5.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    campaign = resolve_campaign(args.campaign)
    output_dir = resolve_output_dir(campaign, args.output_dir)
    hours = sorted(set(args.checkpoint_hours))
    for value in hours:
        checkpoint_seconds(value)
    if args.command == "extract":
        payload = build_timecurve(campaign, hours, output_dir)
        json_path, csv_path = write_timecurve(output_dir, payload)
        print(
            json.dumps(
                {
                    "json": portable_path(json_path),
                    "csv": portable_path(csv_path),
                    "aggregates": payload["aggregates"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "watch" and args.detach:
        return launch_watcher(campaign, hours, output_dir, args.poll_seconds)
    return watch_game_checkpoints(campaign, hours, output_dir, args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
