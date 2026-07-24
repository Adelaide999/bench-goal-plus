#!/usr/bin/env python3
"""Render one or more OpenEvolve campaign/run paths as JSON and Markdown."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.openevolve_compare.reporting import (  # noqa: E402
    atomic_write,
    collect_sources,
    render_markdown,
    write_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Collect campaign directories, campaign.json files, or individual run "
            "directories into a deterministic OpenEvolve result table."
        )
    )
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--method", action="append", dest="methods")
    parser.add_argument("--task", action="append", dest="tasks")
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--title", default="OpenEvolve Comparison Results")
    args = parser.parse_args()

    report = collect_sources(args.sources)
    if args.methods:
        selected = set(args.methods)
        report["records"] = [
            item for item in report["records"] if item.get("method") in selected
        ]
    if args.tasks:
        selected = set(args.tasks)
        report["records"] = [
            item for item in report["records"] if item.get("task_id") in selected
        ]
    report["record_count"] = len(report["records"])

    if args.markdown_out and args.json_out:
        write_report(
            report,
            markdown_path=args.markdown_out,
            json_path=args.json_out,
            title=args.title,
        )
    else:
        if args.json_out:
            atomic_write(args.json_out, json.dumps(report, indent=2) + "\n")
        markdown = render_markdown(
            report,
            title=args.title,
            output_path=args.markdown_out,
        )
        if args.markdown_out:
            atomic_write(args.markdown_out, markdown)
        else:
            print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
