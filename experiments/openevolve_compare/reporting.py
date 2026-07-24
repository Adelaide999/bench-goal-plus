"""Collect OpenEvolve comparison runs into portable JSON and Markdown reports."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
REPORT_SCHEMA_VERSION = 1


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def portable_path(path: Path) -> str:
    resolved = path.expanduser().absolute()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def seed_evaluations(run_dir: Path) -> tuple[list[dict[str, Any]], Path | None]:
    single = run_dir / "seed-eval.json"
    if single.is_file():
        payload = load_json(single)
        return [payload], single
    lanes = run_dir / "seed-evals.json"
    if lanes.is_file():
        payload = load_json(lanes)
        evaluations = [
            item["evaluation"]
            for item in payload.get("lanes") or []
            if isinstance(item, dict) and isinstance(item.get("evaluation"), dict)
        ]
        return evaluations, lanes
    return [], None


def direction_best(values: list[float], direction: str | None) -> float | None:
    if not values:
        return None
    return min(values) if direction == "minimize" else max(values)


def collect_usage(execution: dict[str, Any]) -> dict[str, Any]:
    usages: list[dict[str, Any]] = []
    coverage = None
    common = execution.get("usage")
    if isinstance(common, dict):
        usages.append(common)
        coverage = common.get("coverage")
    codex = execution.get("codex")
    if isinstance(codex, dict):
        coverage = codex.get("coverage")
        for lane in codex.get("lanes") or []:
            if isinstance(lane, dict) and isinstance(lane.get("top_level_usage"), dict):
                usages.append(lane["top_level_usage"])
        if isinstance(codex.get("top_level_usage"), dict):
            usages.append(codex["top_level_usage"])
    pi = execution.get("pi")
    if isinstance(pi, dict) and isinstance(pi.get("usage"), dict):
        usages.append(pi["usage"])
        coverage = pi.get("coverage", coverage)

    aliases = {
        "input_tokens": ("input_tokens", "input"),
        "cached_input_tokens": ("cached_input_tokens", "cache_read"),
        "output_tokens": ("output_tokens", "output"),
        "reasoning_output_tokens": ("reasoning_output_tokens",),
    }
    totals: dict[str, int] = {}
    for target, candidates in aliases.items():
        total = 0
        found = False
        for usage in usages:
            for source in candidates:
                value = numeric(usage.get(source))
                if value is not None:
                    total += int(value)
                    found = True
                    break
        if found:
            totals[target] = total
    return {
        **totals,
        "coverage": coverage
        or (
            "missing: no persisted model usage"
            if not usages
            else "available fields aggregated across persisted top-level sessions"
        ),
    }


def collect_evaluator_calls(execution: dict[str, Any]) -> dict[str, Any]:
    calls = execution.get("evaluator_calls")
    if isinstance(calls, dict):
        return dict(calls)
    coverage = execution.get("telemetry_coverage")
    note = coverage.get("evaluator_calls") if isinstance(coverage, dict) else None
    return {"coverage": note or "missing: evaluator call ledger unavailable"}


def evidence_paths(
    run_dir: Path,
    seed_path: Path | None,
    manifest: dict[str, Any],
) -> dict[str, str]:
    task = manifest.get("task") if isinstance(manifest.get("task"), dict) else {}
    workspace_value = manifest.get("workspace")
    workspaces = manifest.get("workspaces") or []
    workspace = (
        Path(workspace_value)
        if isinstance(workspace_value, str) and workspace_value
        else (
            Path(workspaces[0])
            if workspaces and isinstance(workspaces[0], str)
            else None
        )
    )
    candidates = {
        "run_dir": run_dir,
        "manifest": run_dir / "experiment.json",
        "task": workspace / "TASK.md" if workspace is not None else None,
        "evaluator": (
            Path(task["evaluator"]) if isinstance(task.get("evaluator"), str) else None
        ),
        "seed": seed_path,
        "final": run_dir / "final-eval.json",
        "candidate": run_dir / "final-candidate.py",
        "events": run_dir / "events.jsonl",
        "stdout": run_dir / "stdout.log",
        "lanes": run_dir / "lanes",
        "goal_plus": run_dir / "workspace" / ".gp",
    }
    return {
        name: portable_path(path)
        for name, path in candidates.items()
        if path is not None and path.exists()
    }


def collect_run(
    run_dir: Path,
    *,
    campaign_id: str | None = None,
    campaign: dict[str, Any] | None = None,
    entry: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
    launcher: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.expanduser().absolute()
    manifest_path = run_dir / "experiment.json"
    manifest = load_json(manifest_path) if manifest_path.is_file() else {}
    campaign = campaign or {}
    entry = entry or {}
    ledger = ledger or {}
    launcher = launcher or {}

    task = manifest.get("task") if isinstance(manifest.get("task"), dict) else {}
    budget = manifest.get("budget") if isinstance(manifest.get("budget"), dict) else {}
    if not budget and isinstance(campaign.get("budget"), dict):
        budget = campaign["budget"]
    execution = (
        manifest.get("execution") if isinstance(manifest.get("execution"), dict) else {}
    )
    seeds, seed_path = seed_evaluations(run_dir)
    final_path = run_dir / "final-eval.json"
    final = load_json(final_path) if final_path.is_file() else {}
    final_metric = (
        final.get("primary_metric")
        if isinstance(final.get("primary_metric"), dict)
        else {}
    )
    metric_name = final_metric.get("name") or task.get("primary_metric")
    direction = final_metric.get("direction") or task.get("direction")
    seed_values = [
        value
        for evaluation in seeds
        if isinstance(evaluation, dict)
        for value in [
            numeric(
                (evaluation.get("primary_metric") or {}).get("value")
                if isinstance(evaluation.get("primary_metric"), dict)
                else None
            )
        ]
        if value is not None
    ]
    seed_best = direction_best(seed_values, direction)
    final_score = numeric(final_metric.get("value"))
    gain = None
    if seed_best is not None and final_score is not None:
        gain = (
            seed_best - final_score
            if direction == "minimize"
            else final_score - seed_best
        )

    status = (
        ledger.get("status")
        or manifest.get("status")
        or ("prepared" if entry.get("prepared") else "prepare_failed")
    )
    return {
        "campaign_id": campaign_id,
        "run_dir": portable_path(run_dir),
        "task_id": manifest.get("task_id")
        or entry.get("task_id")
        or ledger.get("task_id"),
        "method": manifest.get("method") or entry.get("method") or ledger.get("method"),
        "status": status,
        "returncode": ledger.get("returncode", execution.get("returncode")),
        "error": ledger.get("error"),
        "model": manifest.get("model") or campaign.get("model"),
        "reasoning_effort": (
            manifest.get("reasoning_effort")
            or launcher.get("reasoning_effort")
            or campaign.get("reasoning_effort")
        ),
        "seed": manifest.get("seed", campaign.get("seed")),
        "protocol": {
            "wall_time_seconds": budget.get("wall_time_seconds"),
            "concurrency": budget.get("concurrency"),
            "metric_name": metric_name,
            "direction": direction,
            "upstream_commit": task.get("upstream_commit"),
            "evaluator_sha256": task.get("evaluator_sha256"),
            "sandbox": manifest.get("codex_sandbox"),
        },
        "score": {
            "valid": final.get("valid"),
            "seed_values": seed_values,
            "seed_best": seed_best,
            "final": final_score,
            "directional_gain": gain,
            "raw_metrics": (
                final.get("raw_metrics")
                if isinstance(final.get("raw_metrics"), dict)
                else {}
            ),
        },
        "execution": {
            "duration_seconds": execution.get("duration_seconds"),
            "deadline_reached": execution.get("deadline_reached"),
            "hard_killed": execution.get("hard_killed"),
            "selected_lane": execution.get("selected_lane"),
            "native_best_iteration": (
                (execution.get("native_best") or {}).get("iteration")
                if isinstance(execution.get("native_best"), dict)
                else None
            ),
            "evaluator_calls": collect_evaluator_calls(execution),
            "usage": collect_usage(execution),
        },
        "evidence": evidence_paths(run_dir, seed_path, manifest),
    }


def is_campaign_source(path: Path) -> bool:
    return (path.is_file() and path.name == "campaign.json") or (
        path.is_dir() and (path / "campaign.json").is_file()
    )


def collect_campaign(source: Path) -> list[dict[str, Any]]:
    campaign_path = source if source.is_file() else source / "campaign.json"
    campaign = load_json(campaign_path)
    root = campaign_path.parent
    results_path = root / "campaign-results.json"
    results = (
        load_json(results_path).get("results", []) if results_path.is_file() else []
    )
    ledgers = {
        (item.get("task_id"), item.get("method")): item
        for item in results
        if isinstance(item, dict)
    }
    launcher_path = root / "launcher-config.json"
    launcher = load_json(launcher_path) if launcher_path.is_file() else {}
    records = []
    seen: set[tuple[Any, Any]] = set()
    for entry in campaign.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        key = (entry.get("task_id"), entry.get("method"))
        seen.add(key)
        records.append(
            collect_run(
                Path(entry["run_dir"]),
                campaign_id=root.name,
                campaign=campaign,
                entry=entry,
                ledger=ledgers.get(key),
                launcher=launcher,
            )
        )
    for key, ledger in ledgers.items():
        if key in seen or not ledger.get("run_dir"):
            continue
        records.append(
            collect_run(
                Path(ledger["run_dir"]),
                campaign_id=root.name,
                campaign=campaign,
                ledger=ledger,
                launcher=launcher,
            )
        )
    return records


def campaign_context_for_run(run_dir: Path) -> dict[str, Any]:
    resolved_run = run_dir.expanduser().absolute()
    for parent in resolved_run.parents:
        campaign_path = parent / "campaign.json"
        if not campaign_path.is_file():
            continue
        campaign = load_json(campaign_path)
        entry = next(
            (
                item
                for item in campaign.get("entries") or []
                if isinstance(item, dict)
                and item.get("run_dir")
                and Path(item["run_dir"]).expanduser().absolute() == resolved_run
            ),
            None,
        )
        if entry is None:
            continue
        results_path = parent / "campaign-results.json"
        results = (
            load_json(results_path).get("results", []) if results_path.is_file() else []
        )
        ledger = next(
            (
                item
                for item in results
                if isinstance(item, dict)
                and item.get("task_id") == entry.get("task_id")
                and item.get("method") == entry.get("method")
            ),
            None,
        )
        launcher_path = parent / "launcher-config.json"
        return {
            "campaign_id": parent.name,
            "campaign": campaign,
            "entry": entry,
            "ledger": ledger,
            "launcher": load_json(launcher_path) if launcher_path.is_file() else {},
        }
    return {}


def collect_sources(sources: Iterable[Path]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    source_paths = []
    seen_runs: set[str] = set()
    for source in sources:
        source = source.expanduser().absolute()
        if not source.exists():
            raise FileNotFoundError(source)
        source_paths.append(portable_path(source))
        source_records = (
            collect_campaign(source)
            if is_campaign_source(source)
            else [collect_run(source, **campaign_context_for_run(source))]
        )
        for record in source_records:
            if record["run_dir"] in seen_runs:
                continue
            seen_runs.add(record["run_dir"])
            records.append(record)
    records.sort(
        key=lambda item: (
            str(item.get("task_id") or ""),
            str(item.get("method") or ""),
            str(item.get("campaign_id") or ""),
            item["run_dir"],
        )
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "sources": source_paths,
        "record_count": len(records),
        "records": records,
    }


def markdown_escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def format_number(value: Any) -> str:
    number = numeric(value)
    if number is None:
        return "-"
    if number == 0:
        return "0"
    return f"{number:.8g}"


def format_seed(score: dict[str, Any]) -> str:
    values = score.get("seed_values") or []
    if not values:
        return "-"
    low = min(values)
    high = max(values)
    if math.isclose(low, high, rel_tol=1e-12, abs_tol=1e-12):
        rendered = format_number(low)
    else:
        rendered = f"{format_number(low)}..{format_number(high)}"
    return f"{rendered} (n={len(values)})" if len(values) > 1 else rendered


def format_budget(record: dict[str, Any]) -> str:
    protocol = record["protocol"]
    actual = numeric(record["execution"].get("duration_seconds"))
    limit = numeric(protocol.get("wall_time_seconds"))
    k = protocol.get("concurrency")
    if actual is None and limit is None:
        time_text = "-"
    elif actual is None:
        time_text = f"-/{format_number(limit)}s"
    elif limit is None:
        time_text = f"{format_number(actual)}s"
    else:
        time_text = f"{format_number(actual)}/{format_number(limit)}s"
    return f"T {time_text}; K {k if k is not None else '-'}"


def format_calls(calls: dict[str, Any]) -> str:
    total = calls.get("total_claimed")
    if total is None:
        return markdown_escape(calls.get("coverage") or "-")
    public = calls.get("public_claimed")
    final = calls.get("final_claimed")
    return f"{total} ({public if public is not None else '-'} public/{final if final is not None else '-'} final)"


def format_usage(usage: dict[str, Any]) -> str:
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if input_tokens is None and output_tokens is None:
        return markdown_escape(usage.get("coverage") or "-")
    return f"in {input_tokens if input_tokens is not None else '-'} / out {output_tokens if output_tokens is not None else '-'}"


def format_raw_metrics(metrics: dict[str, Any]) -> str:
    numeric_metrics = [
        (key, value)
        for key, value in sorted(metrics.items())
        if numeric(value) is not None
    ]
    if not numeric_metrics:
        return "-"
    return markdown_escape(
        "; ".join(f"{key}={format_number(value)}" for key, value in numeric_metrics)
    )


def evidence_links(record: dict[str, Any], output_path: Path | None) -> str:
    evidence = record.get("evidence") or {}
    links = []
    for key in (
        "manifest",
        "task",
        "evaluator",
        "seed",
        "final",
        "candidate",
        "events",
        "lanes",
        "goal_plus",
    ):
        value = evidence.get(key)
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = ROOT / path
        target = (
            os.path.relpath(path, output_path.parent).replace(os.sep, "/")
            if output_path is not None
            else portable_path(path)
        )
        links.append(f"[{key}]({target})")
    return " ".join(links) or "-"


def render_markdown(
    report: dict[str, Any],
    *,
    title: str = "OpenEvolve Comparison Results",
    output_path: Path | None = None,
) -> str:
    lines = [
        f"# {title}",
        "",
        "Scores are raw evaluator metrics. Compare scores only within the same task, evaluator hash, upstream commit, and direction; values are not normalized across tasks. `Gain` is direction-aware against the best recorded seed (`final - seed` for maximize, `seed - final` for minimize), so a positive value is better.",
        "",
        "| Task | Method | Attempt | Status | Model / reasoning | Metric | Direction | Seed | Final | Gain | Raw metrics | Valid | Budget | Evaluator calls | Usage | Evidence |",
        "|---|---|---|---|---|---|---|---:|---:|---:|---|---|---|---|---|---|",
    ]
    for record in report.get("records") or []:
        protocol = record["protocol"]
        score = record["score"]
        valid = score.get("valid")
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_escape(record.get("task_id") or "-"),
                    markdown_escape(record.get("method") or "-"),
                    markdown_escape(record.get("campaign_id") or "standalone"),
                    markdown_escape(record.get("status") or "-"),
                    markdown_escape(
                        f"{record.get('model') or '-'} / {record.get('reasoning_effort') or '-'}"
                    ),
                    markdown_escape(protocol.get("metric_name") or "-"),
                    markdown_escape(protocol.get("direction") or "-"),
                    format_seed(score),
                    format_number(score.get("final")),
                    format_number(score.get("directional_gain")),
                    format_raw_metrics(score.get("raw_metrics") or {}),
                    "-" if valid is None else str(bool(valid)).lower(),
                    format_budget(record),
                    format_calls(record["execution"]["evaluator_calls"]),
                    format_usage(record["execution"]["usage"]),
                    evidence_links(record, output_path),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Reading The Score",
            "",
            "- `Final` is the evaluator's unchanged primary metric. It is not automatically a percentage or pass rate.",
            "- `Direction` determines whether larger or smaller is better.",
            "- `Seed` shows the observed seed score or range across independent lanes. `n` is the number of seed evaluations.",
            "- `Gain > 0` means the final artifact improved on the best observed seed; it does not make gains comparable across tasks.",
            "- `Raw metrics` expands numeric components only; structured evaluator artifacts remain in JSON and the linked final evaluation.",
            "- Missing evaluator calls or token usage remain explicitly missing rather than being treated as zero.",
            "",
        ]
    )
    return "\n".join(lines)


def atomic_write(path: Path, text: str) -> None:
    path = path.expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text)
    os.replace(temporary, path)


def write_report(
    report: dict[str, Any],
    *,
    markdown_path: Path,
    json_path: Path,
    title: str,
) -> None:
    atomic_write(json_path, json.dumps(report, indent=2) + "\n")
    atomic_write(
        markdown_path,
        render_markdown(report, title=title, output_path=markdown_path),
    )


def write_campaign_report(campaign_root: Path) -> dict[str, Any]:
    campaign_root = campaign_root.expanduser().absolute()
    report = collect_sources([campaign_root])
    write_report(
        report,
        markdown_path=campaign_root / "campaign-summary.md",
        json_path=campaign_root / "campaign-summary.json",
        title=f"OpenEvolve Campaign: {campaign_root.name}",
    )
    return report
