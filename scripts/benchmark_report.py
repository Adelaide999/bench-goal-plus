#!/usr/bin/env python3
"""Export evidence-backed benchmark campaign summaries to Markdown and XLSX."""

from __future__ import annotations

import argparse
import json
import math
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape, quoteattr


INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def sum_known(values: Iterable[Any]) -> int | float | None:
    known = [
        value
        for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return sum(known) if known else None


def edgebench_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for cell in payload.get("cells", []):
        observations = cell.get("observations") or []
        best = cell.get("best") or {}
        completion = cell.get("completion_evidence") or {}
        completion_checks = completion.get("checks") or {}
        if cell.get("method") == "goal-plus-codex":
            actual_subagents = completion_checks.get("actual_worker_launches") or {}
        elif cell.get("method") == "goal-plus-pi":
            actual_subagents = completion_checks.get("agent_sessions") or {}
        else:
            actual_subagents = {}
        usage_records = [item.get("codex_usage") or {} for item in observations]
        token_records = [item.get("tokens") or {} for item in usage_records]
        paper = ((payload.get("paper_reference") or {}).get("tasks") or {}).get(
            cell.get("task_id"), {}
        )
        edgebench_score = best.get("edgebench_score")
        paper_mean = paper.get("mean")
        rows.append(
            {
                "task_id": cell.get("task_id"),
                "method": cell.get("method"),
                "model": cell.get("model"),
                "reasoning_effort": cell.get("reasoning_effort"),
                "raw_metric_direction": cell.get("metric_direction"),
                "wall_time_seconds": cell.get("wall_time_seconds"),
                "live_search_concurrency_k": cell.get("live_search_concurrency"),
                "outer_replicas": cell.get("outer_replicas"),
                "completed_trajectories": cell.get("completed_trajectories"),
                "valid_trajectories": cell.get("valid_trajectories"),
                "raw_score": best.get("raw_score"),
                "extended_score": best.get("extended_score"),
                "edgebench_score_0_100": edgebench_score,
                "paper_gpt_5_5_mean": paper_mean,
                "delta_vs_paper_pp": (
                    edgebench_score - paper_mean
                    if isinstance(edgebench_score, (int, float))
                    and isinstance(paper_mean, (int, float))
                    else None
                ),
                "evaluator_calls": sum_known(
                    item.get("evaluator_calls") for item in observations
                ),
                "runtime_seconds": sum_known(
                    item.get("runtime_seconds") for item in observations
                ),
                "input_tokens": sum_known(
                    item.get("input_tokens") for item in token_records
                ),
                "cached_input_tokens": sum_known(
                    item.get("cached_input_tokens") for item in token_records
                ),
                "output_tokens": sum_known(
                    item.get("output_tokens") for item in token_records
                ),
                "usage_coverage": ", ".join(
                    sorted(
                        {
                            str(item["coverage"])
                            for item in usage_records
                            if item.get("coverage")
                        }
                    )
                )
                or None,
                "official_edgebench_comparable": cell.get(
                    "official_edgebench_comparable"
                ),
                "protocol_classification": cell.get("protocol_classification"),
                "known_protocol_issue": cell.get("known_protocol_issue"),
                "actual_goal_plus_subagents": actual_subagents.get("actual"),
                "goal_plus_candidates": (
                    completion_checks.get("candidates") or {}
                ).get("actual"),
                "goal_plus_worker_sessions": (
                    completion_checks.get("agent_sessions") or {}
                ).get("actual"),
                "goal_plus_verifier_runs": (
                    completion_checks.get("worker_verifier_runs") or {}
                ).get("actual"),
                "completion_evidence_passed": completion.get("passed"),
                "incomplete_reason": cell.get("incomplete_reason"),
            }
        )
    return rows


def generic_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for record in payload.get("records", []):
        score = record.get("score") or {}
        execution = record.get("execution") or {}
        calls = execution.get("evaluator_calls") or {}
        usage = execution.get("usage") or {}
        protocol = record.get("protocol") or {}
        rows.append(
            {
                "benchmark_id": record.get("benchmark_id"),
                "task_id": record.get("task_id"),
                "cell_id": record.get("cell_id"),
                "condition": record.get("condition"),
                "method": record.get("method"),
                "model": record.get("model"),
                "reasoning_effort": record.get("reasoning_effort"),
                "seed": record.get("seed"),
                "status": record.get("status", record.get("state")),
                "incomplete_reason": record.get("incomplete_reason"),
                "metric_name": protocol.get("metric_name"),
                "metric_direction": protocol.get("direction"),
                "raw_final_metric": score.get("final"),
                "raw_metrics": score.get("raw_metrics"),
                "directional_gain": score.get("directional_gain"),
                "valid": score.get("valid"),
                "wall_time_seconds": (record.get("budget") or {}).get(
                    "wall_time_seconds"
                ),
                "live_concurrency_k": record.get(
                    "effective_concurrency",
                    (record.get("budget") or {}).get(
                        "live_search_concurrency",
                        (record.get("budget") or {}).get(
                            "concurrency",
                            (record.get("budget") or {}).get(
                                "requested_live_concurrency"
                            ),
                        ),
                    ),
                ),
                "evaluator_calls": calls.get("total_claimed"),
                "evaluator_call_coverage": calls.get("coverage"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "token_coverage": usage.get("coverage"),
                "run_dir": record.get("run_dir"),
                "error": record.get("error"),
            }
        )
    return rows


def load_campaign(
    campaign: Path,
) -> tuple[str, dict[str, Any], Path | None, Path]:
    comparison = campaign / "comparison.json"
    summary = campaign / "campaign-summary.json"
    if comparison.is_file():
        payload = read_json(comparison)
        kind = str(payload.get("report_kind") or "edgebench")
        return kind, payload, campaign / "comparison.md", comparison
    if summary.is_file():
        payload = read_json(summary)
        kind = str(payload.get("report_kind") or "campaign")
        return kind, payload, campaign / "campaign-summary.md", summary
    raise FileNotFoundError(
        f"no finalized comparison.json or campaign-summary.json under {campaign}"
    )


def fallback_markdown(
    campaign_id: str, kind: str, rows: list[dict[str, Any]]
) -> str:
    lines = [f"# Benchmark report: {campaign_id}", "", f"Kind: `{kind}`.", ""]
    if not rows:
        return "\n".join(lines + ["No result rows are available.", ""])
    headers = list(rows[0])
    lines.extend(
        [
            "| " + " | ".join(headers) + " |",
            "|" + "|".join("---" for _ in headers) + "|",
        ]
    )
    for row in rows:
        values = [
            str(row.get(header, "") if row.get(header) is not None else "")
            for header in headers
        ]
        lines.append(
            "| "
            + " | ".join(value.replace("|", "\\|") for value in values)
            + " |"
        )
    return "\n".join(lines) + "\n"


def clean_xml(value: Any) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return INVALID_XML.sub("", str(value))


def column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def cell_xml(reference: str, value: Any, *, header: bool = False) -> str:
    style = 1 if header else 2
    if value is None:
        return f'<c r="{reference}" s="{style}"/>'
    if isinstance(value, bool):
        return f'<c r="{reference}" s="{style}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            value = str(value)
        else:
            return f'<c r="{reference}" s="{style}"><v>{value}</v></c>'
    return (
        f'<c r="{reference}" s="{style}" t="inlineStr"><is><t xml:space="preserve">'
        f"{escape(clean_xml(value))}</t></is></c>"
    )


def worksheet_xml(rows: list[list[Any]]) -> str:
    width_count = max((len(row) for row in rows), default=1)
    widths = []
    for index in range(width_count):
        values = [clean_xml(row[index]) for row in rows if index < len(row)]
        width = min(60, max(10, max((len(value) for value in values), default=10) + 2))
        widths.append(f'<col min="{index + 1}" max="{index + 1}" width="{width}" customWidth="1"/>')
    row_parts = []
    for row_index, row in enumerate(rows, start=1):
        cells = "".join(
            cell_xml(
                f"{column_name(column_index)}{row_index}",
                value,
                header=row_index == 1,
            )
            for column_index, value in enumerate(row, start=1)
        )
        row_parts.append(f'<row r="{row_index}">{cells}</row>')
    last_column = column_name(width_count)
    last_row = max(1, len(rows))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{last_column}{last_row}"/>'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f"<cols>{''.join(widths)}</cols><sheetData>{''.join(row_parts)}</sheetData>"
        f'<autoFilter ref="A1:{last_column}{last_row}"/></worksheet>'
    )


def write_xlsx(path: Path, sheets: list[tuple[str, list[list[Any]]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet_entries = "".join(
        f'<sheet name={quoteattr(name[:31])} sheetId="{index}" r:id="rId{index}"/>'
        for index, (name, _) in enumerate(sheets, start=1)
    )
    relationships = "".join(
        '<Relationship '
        f'Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, len(sheets) + 1)
    )
    relationships += (
        '<Relationship Id="rIdStyles" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, len(sheets) + 1)
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{overrides}</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{sheet_entries}</sheets></workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{relationships}</Relationships>"
        ),
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Aptos"/></font>'
            '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos"/></font></fonts>'
            '<fills count="3"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/>'
            '<bgColor indexed="64"/></patternFill></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1" '
            'applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>'
            '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" '
            'applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '</styleSheet>'
        ),
    }
    for index, (_, rows) in enumerate(sheets, start=1):
        files[f"xl/worksheets/sheet{index}.xml"] = worksheet_xml(rows)
    temporary = path.with_name(f".{path.name}.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    temporary.replace(path)


def tabular_rows(records: list[dict[str, Any]]) -> list[list[Any]]:
    if not records:
        return [["status"], ["no result rows"]]
    headers = list(records[0])
    return [headers, *[[record.get(header) for header in headers] for record in records]]


def safe_filename(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    if not sanitized:
        raise ValueError("campaign id cannot produce an empty report filename")
    return sanitized


def export(campaign: Path, markdown_out: Path | None, xlsx_out: Path | None) -> dict[str, str]:
    kind, payload, source_markdown, source_json = load_campaign(campaign)
    campaign_id = str(payload.get("campaign_id") or campaign.name)
    rows = edgebench_rows(payload) if kind == "edgebench" else generic_rows(payload)
    markdown_path = markdown_out or campaign / "report.md"
    xlsx_path = xlsx_out or campaign / f"{safe_filename(campaign_id)}.xlsx"
    if source_markdown and source_markdown.is_file():
        markdown = source_markdown.read_text(encoding="utf-8")
    else:
        markdown = fallback_markdown(campaign_id, kind, rows)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    summary_rows = [
        ["field", "value"],
        ["campaign_id", campaign_id],
        ["campaign_kind", kind],
        ["state", payload.get("state", "finalized")],
        ["record_count", len(rows)],
        [
            "wall_time_seconds",
            payload.get(
                "wall_time_seconds",
                (payload.get("budget") or {}).get("wall_time_seconds"),
            ),
        ],
        [
            "live_search_concurrency_k",
            payload.get(
                "live_search_concurrency",
                (payload.get("budget") or {}).get(
                    "live_search_concurrency",
                    (payload.get("budget") or {}).get(
                        "concurrency",
                        (payload.get("budget") or {}).get(
                            "requested_live_concurrency"
                        ),
                    ),
                ),
            ),
        ],
        [
            "cell_concurrency_c",
            payload.get(
                "cell_concurrency",
                (payload.get("budget") or {}).get("cell_concurrency"),
            ),
        ],
        [
            "independent_attempts_r",
            payload.get("attempts", (payload.get("budget") or {}).get("attempts")),
        ],
        ["generated_at", datetime.now(timezone.utc).isoformat()],
        ["source_json", source_json.name],
    ]
    write_xlsx(xlsx_path, [("Summary", summary_rows), ("Results", tabular_rows(rows))])
    return {"markdown": str(markdown_path), "xlsx": str(xlsx_path)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--xlsx-out", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    outputs = export(
        args.campaign.expanduser().absolute(),
        args.markdown_out.expanduser().absolute() if args.markdown_out else None,
        args.xlsx_out.expanduser().absolute() if args.xlsx_out else None,
    )
    print(json.dumps(outputs, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
