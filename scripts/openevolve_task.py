#!/usr/bin/env python3
"""Materialize and evaluate an OpenEvolve example from a managed branch snapshot."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UPSTREAM_ROOT = ROOT / "third_party/openevolve"
DEFAULT_RUNTIME_PYTHON = ROOT / ".bench-env/venv/bin/python"
sys.path.insert(0, str(ROOT))

from bench_runtime_paths import configure_temp_environment  # noqa: E402
from adapters.openevolve_examples.adapter import (  # noqa: E402
    BudgetExhausted,
    archive_workspace,
    describe_task,
    evaluate_workspace,
    list_catalog_tasks,
    materialize_workspace,
    resolve_task,
)

configure_temp_environment()


def batch_seed_smoke(args: argparse.Namespace) -> dict:
    run_root = args.run_root.expanduser().absolute()
    runtime_python = args.runtime_python.expanduser().absolute()
    run_root.mkdir(parents=True, exist_ok=False)
    results = []
    for catalog_item in list_catalog_tasks(args.task_set):
        task_id = catalog_item["task_id"]
        result = {
            "task_id": task_id,
            "passed": False,
            "profile": catalog_item["profile"],
            "primary_metric": None,
            "elapsed_seconds": None,
            "workspace_commit": None,
            "error": None,
        }
        try:
            task = resolve_task(task_id, args.upstream_root)
            task_root = run_root / task_id
            workspace = task_root / "workspace"
            description = describe_task(task, runtime_python)
            materialized = materialize_workspace(
                task,
                workspace,
                runtime_python,
                max_evaluator_calls=None,
                reserved_final_calls=1,
                description=description,
                controller_runtime_dir=task_root / "controller-runtime",
            )
            evaluation = evaluate_workspace(workspace, "public")
            value = (evaluation.get("primary_metric") or {}).get("value")
            result.update(
                {
                    "passed": bool(
                        evaluation.get("valid") is True
                        and isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and math.isfinite(float(value))
                    ),
                    "profile": task.profile,
                    "primary_metric": evaluation.get("primary_metric"),
                    "elapsed_seconds": evaluation.get("elapsed_seconds"),
                    "workspace_commit": materialized["workspace_commit"],
                }
            )
        except Exception as error:  # Preserve diagnostics for the remaining tasks.
            result["error"] = f"{type(error).__name__}: {error}"
        results.append(result)
    payload = {
        "schema_version": 1,
        "task_set": args.task_set,
        "ok": all(item["passed"] for item in results),
        "task_count": len(results),
        "passed_count": sum(1 for item in results if item["passed"]),
        "results": results,
    }
    (run_root / "summary.json").write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--task-set")

    batch_parser = subparsers.add_parser("batch-seed-smoke")
    batch_parser.add_argument("--task-set", default="cpu_portable")
    batch_parser.add_argument(
        "--upstream-root", type=Path, default=DEFAULT_UPSTREAM_ROOT
    )
    batch_parser.add_argument(
        "--runtime-python", type=Path, default=DEFAULT_RUNTIME_PYTHON
    )
    batch_parser.add_argument("--run-root", type=Path, required=True)

    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("--task-id", required=True)
    materialize_parser.add_argument(
        "--upstream-root", type=Path, default=DEFAULT_UPSTREAM_ROOT
    )
    materialize_parser.add_argument("--workspace", type=Path, required=True)
    materialize_parser.add_argument(
        "--runtime-python", type=Path, default=DEFAULT_RUNTIME_PYTHON
    )
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
    if args.command == "list":
        payload = {
            "schema_version": 1,
            "task_set": args.task_set,
            "tasks": list_catalog_tasks(args.task_set),
        }
    elif args.command == "batch-seed-smoke":
        payload = batch_seed_smoke(args)
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 2
    elif args.command == "materialize":
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
