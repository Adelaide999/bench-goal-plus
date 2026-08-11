#!/usr/bin/env python3
"""Identify same-task, same-model gains in EdgeBench public checkpoint curves."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_README = ROOT / "third_party" / "edgebench" / "tasks" / "README.md"
CHECKPOINT_HOURS = (2, 4, 6, 8, 10, 12)
TABLE_MARKER = "Per-Task Scores by Time Budget (51 tasks)"


def _markdown_cells(line: str) -> list[str]:
    return [
        cell.strip().replace("**", "")
        for cell in line.strip().strip("|").split("|")
    ]


def _source_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _parse_curve(cell: str, *, task_id: str, model: str) -> dict[str, float | None]:
    values = [value.strip() for value in cell.split("/")]
    if len(values) != len(CHECKPOINT_HOURS):
        raise ValueError(
            f"expected {len(CHECKPOINT_HOURS)} checkpoints for {task_id}/{model}, "
            f"got {len(values)}"
        )
    curve: dict[str, float | None] = {}
    for hour, value in zip(CHECKPOINT_HOURS, values, strict=True):
        if value in {"", "-", "—"}:
            curve[str(hour)] = None
            continue
        try:
            score = float(value)
        except ValueError as exc:
            raise ValueError(
                f"invalid score {value!r} for {task_id}/{model}@{hour}h"
            ) from exc
        if not math.isfinite(score):
            raise ValueError(f"non-finite score for {task_id}/{model}@{hour}h")
        curve[str(hour)] = score
    return curve


def parse_reference_table(
    path: Path,
    *,
    expected_task_count: int = 51,
) -> dict[str, Any]:
    selected = path.expanduser().resolve()
    raw = selected.read_bytes()
    lines = raw.decode("utf-8").splitlines()
    try:
        marker_index = next(
            index for index, line in enumerate(lines) if TABLE_MARKER in line
        )
        header_index = next(
            index
            for index in range(marker_index + 1, len(lines))
            if lines[index].lstrip().startswith("| Task |")
        )
    except StopIteration as exc:
        raise ValueError(f"EdgeBench checkpoint table not found in {selected}") from exc

    headers = _markdown_cells(lines[header_index])
    if headers[:2] != ["Task", "Category"] or len(headers) < 3:
        raise ValueError(f"invalid EdgeBench checkpoint table header in {selected}")
    models = headers[2:]
    tasks: dict[str, dict[str, Any]] = {}
    for line in lines[header_index + 2 :]:
        if not line.lstrip().startswith("|"):
            break
        cells = _markdown_cells(line)
        if len(cells) != len(headers):
            raise ValueError(f"invalid checkpoint row in {selected}: {line}")
        task_id, category = cells[:2]
        if task_id in tasks:
            raise ValueError(f"duplicate task {task_id!r} in {selected}")
        tasks[task_id] = {
            "category": category,
            "models": {
                model: _parse_curve(value, task_id=task_id, model=model)
                for model, value in zip(models, cells[2:], strict=True)
            },
        }

    if len(tasks) != expected_task_count:
        raise ValueError(
            f"expected {expected_task_count} public tasks in {selected}, got {len(tasks)}"
        )
    return {
        "schema_version": 1,
        "source": {
            "path": _source_path(selected),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "table": TABLE_MARKER,
        },
        "score_scale": "0-100",
        "checkpoint_hours": list(CHECKPOINT_HOURS),
        "models": models,
        "task_count": len(tasks),
        "tasks": tasks,
    }


def _resolve_models(available: list[str], requested: list[str] | None) -> list[str]:
    if not requested:
        return list(available)
    lookup = {model.casefold(): model for model in available}
    selected: list[str] = []
    for value in requested:
        model = lookup.get(value.casefold())
        if model is None:
            raise ValueError(
                f"unknown model {value!r}; choose from: {', '.join(available)}"
            )
        if model not in selected:
            selected.append(model)
    return selected


def identify_gains(
    reference: dict[str, Any],
    *,
    start_hour: int = 2,
    end_hour: int = 12,
    models: list[str] | None = None,
    min_gain: float = 10.0,
    min_model_count: int = 1,
    top: int | None = None,
) -> dict[str, Any]:
    checkpoints = reference["checkpoint_hours"]
    if start_hour not in checkpoints or end_hour not in checkpoints:
        raise ValueError(f"checkpoint hours must be chosen from {checkpoints}")
    if start_hour >= end_hour:
        raise ValueError("start hour must be earlier than end hour")
    if not math.isfinite(min_gain):
        raise ValueError("minimum gain must be finite")
    if min_model_count <= 0:
        raise ValueError("minimum model count must be a positive integer")
    if top is not None and top <= 0:
        raise ValueError("top must be a positive integer")

    selected_models = _resolve_models(reference["models"], models)
    comparable: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    start_key, end_key = str(start_hour), str(end_hour)
    for task_id, task in reference["tasks"].items():
        for model in selected_models:
            curve = task["models"][model]
            start_score, end_score = curve[start_key], curve[end_key]
            if start_score is None or end_score is None:
                missing.append(
                    {
                        "task_id": task_id,
                        "category": task["category"],
                        "model": model,
                        "start_score": start_score,
                        "end_score": end_score,
                    }
                )
                continue
            comparable.append(
                {
                    "task_id": task_id,
                    "category": task["category"],
                    "model": model,
                    "start_score": start_score,
                    "end_score": end_score,
                    "gain_points": round(end_score - start_score, 10),
                }
            )

    threshold_matches = [
        row for row in comparable if row["gain_points"] >= min_gain
    ]
    task_model_counts: dict[str, int] = {}
    for row in threshold_matches:
        task_id = row["task_id"]
        task_model_counts[task_id] = task_model_counts.get(task_id, 0) + 1
    eligible_tasks = {
        task_id
        for task_id, model_count in task_model_counts.items()
        if model_count >= min_model_count
    }
    qualifying = sorted(
        (row for row in threshold_matches if row["task_id"] in eligible_tasks),
        key=lambda row: (-row["gain_points"], row["task_id"], row["model"]),
    )
    for row in qualifying:
        row["qualifying_models_for_task"] = task_model_counts[row["task_id"]]
    qualifying_count = len(qualifying)
    qualifying_tasks = len(eligible_tasks)
    reported = qualifying[:top] if top is not None else qualifying
    return {
        "schema_version": 1,
        "source": reference["source"],
        "comparison": {
            "start_hour": start_hour,
            "end_hour": end_hour,
            "gain": "end_score - start_score",
            "metric_direction": "higher_is_better",
            "min_gain_points": min_gain,
            "min_qualifying_models_per_task": min_model_count,
            "models": selected_models,
            "intended_use": (
                "Public checkpoint-curve screening; not a paired per-run causal effect."
            ),
        },
        "summary": {
            "public_tasks": reference["task_count"],
            "selected_models": len(selected_models),
            "comparable_task_model_pairs": len(comparable),
            "missing_endpoint_pairs": len(missing),
            "threshold_matching_pairs_before_task_filter": len(threshold_matches),
            "qualifying_pairs": qualifying_count,
            "qualifying_tasks": qualifying_tasks,
            "reported_pairs": len(reported),
        },
        "candidates": reported,
        "missing_endpoint_pairs": missing,
    }


def render_markdown(report: dict[str, Any]) -> str:
    comparison = report["comparison"]
    summary = report["summary"]
    lines = [
        "# EdgeBench same-model checkpoint gains",
        "",
        f"- Source: `{report['source']['path']}`",
        f"- Source SHA256: `{report['source']['sha256']}`",
        f"- Comparison: {comparison['start_hour']}h → {comparison['end_hour']}h",
        f"- Models: {', '.join(comparison['models'])}",
        f"- Threshold: gain ≥ {comparison['min_gain_points']:g} points",
        f"- Task filter: at least {comparison['min_qualifying_models_per_task']} "
        "selected model(s) meet the threshold",
        f"- Intended use: {comparison['intended_use']}",
        f"- Coverage: {summary['comparable_task_model_pairs']} comparable pairs; "
        f"{summary['missing_endpoint_pairs']} missing endpoint pairs",
        f"- Matches: {summary['qualifying_pairs']} task/model pairs across "
        f"{summary['qualifying_tasks']} unique tasks",
        "",
        "| Rank | Task | Category | Model | Start | End | Gain |",
        "|---:|---|---|---|---:|---:|---:|",
    ]
    for rank, row in enumerate(report["candidates"], start=1):
        lines.append(
            f"| {rank} | `{row['task_id']}` | {row['category']} | {row['model']} | "
            f"{row['start_score']:.1f} | {row['end_score']:.1f} | "
            f"+{row['gain_points']:.1f} |"
        )
    if not report["candidates"]:
        lines.append("| — | No matching task/model pairs | — | — | — | — | — |")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    parser.add_argument("--start-hour", type=int, default=2, choices=CHECKPOINT_HOURS)
    parser.add_argument("--end-hour", type=int, default=12, choices=CHECKPOINT_HOURS)
    parser.add_argument(
        "--model",
        action="append",
        help="model to include; repeat for multiple models; default: all",
    )
    parser.add_argument("--min-gain", type=float, default=10.0)
    parser.add_argument(
        "--min-model-count",
        type=int,
        default=1,
        help="require this many selected models to meet the gain threshold per task",
    )
    parser.add_argument("--top", type=int)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reference = parse_reference_table(args.readme)
    report = identify_gains(
        reference,
        start_hour=args.start_hour,
        end_hour=args.end_hour,
        models=args.model,
        min_gain=args.min_gain,
        min_model_count=args.min_model_count,
        top=args.top,
    )
    rendered = (
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(output)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
