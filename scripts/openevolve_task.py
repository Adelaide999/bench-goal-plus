#!/usr/bin/env python3
"""Materialize and evaluate a pinned OpenEvolve example task."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.openevolve_examples.adapter import (  # noqa: E402
    BudgetExhausted,
    archive_workspace,
    evaluate_workspace,
    materialize_workspace,
    resolve_task,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("--task-id", required=True)
    materialize_parser.add_argument("--upstream-root", type=Path, required=True)
    materialize_parser.add_argument("--workspace", type=Path, required=True)
    materialize_parser.add_argument("--runtime-python", type=Path, required=True)
    materialize_parser.add_argument(
        "--max-evaluator-calls",
        type=int,
        help="optional hard cap; omit for wall-clock-budget experiments",
    )
    materialize_parser.add_argument("--reserved-final-calls", type=int, default=1)

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--workspace", type=Path, required=True)
    evaluate_parser.add_argument("--mode", choices=["public", "final"], default="public")
    evaluate_parser.add_argument("--output", type=Path)

    archive_parser = subparsers.add_parser("archive")
    archive_parser.add_argument("--workspace", type=Path, required=True)
    archive_parser.add_argument("--run-dir", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "materialize":
        task = resolve_task(args.task_id, args.upstream_root)
        payload = materialize_workspace(
            task,
            args.workspace,
            args.runtime_python,
            args.max_evaluator_calls,
            args.reserved_final_calls,
        )
    elif args.command == "evaluate":
        try:
            payload = evaluate_workspace(args.workspace, args.mode)
        except BudgetExhausted as error:
            print(json.dumps({"error": str(error), "mode": args.mode}, indent=2), file=sys.stderr)
            return 2
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, indent=2) + "\n")
    else:
        payload = archive_workspace(args.workspace, args.run_dir)

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
