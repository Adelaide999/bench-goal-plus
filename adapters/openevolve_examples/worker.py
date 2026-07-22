#!/usr/bin/env python3
"""Run OpenEvolve config/evaluator code inside its pinned Python environment."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import random
import sys
import time
import uuid
from pathlib import Path
from typing import Any


def json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {
            "encoding": "base64",
            "data": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def load_openevolve(upstream_root: Path) -> tuple[Any, Any]:
    sys.path.insert(0, str(upstream_root))
    from openevolve.config import load_config
    from openevolve.evaluator import Evaluator

    return load_config, Evaluator


def describe(args: argparse.Namespace) -> dict[str, Any]:
    load_config, _ = load_openevolve(args.upstream_root)
    config = load_config(args.config)
    return {
        "schema_version": 1,
        "prompt": {
            "system_message": config.prompt.system_message,
            "programs_as_changes_description": config.prompt.programs_as_changes_description,
        },
        "evaluation": {
            "primary_metric": config.early_stopping_metric,
            "direction": "maximize",
            "timeout_seconds": config.evaluator.timeout,
            "max_retries": config.evaluator.max_retries,
            "cascade_evaluation": config.evaluator.cascade_evaluation,
            "cascade_thresholds": config.evaluator.cascade_thresholds,
            "parallel_evaluations": config.evaluator.parallel_evaluations,
        },
        "random_seed": config.random_seed,
        "diff_based_evolution": config.diff_based_evolution,
        "file_suffix": config.file_suffix,
    }


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    load_config, Evaluator = load_openevolve(args.upstream_root)
    config = load_config(args.config)

    if config.random_seed is not None:
        random.seed(config.random_seed)
        try:
            import numpy as np

            np.random.seed(config.random_seed)
        except ImportError:
            pass

    evaluator = Evaluator(
        config.evaluator,
        str(args.evaluator),
        suffix=args.artifact.suffix or config.file_suffix,
    )
    program_id = str(uuid.uuid4())
    program_code = args.artifact.read_text()
    started = time.monotonic()
    metrics = await evaluator.evaluate_program(program_code, program_id)
    artifacts = evaluator.get_pending_artifacts(program_id) or {}
    elapsed_seconds = time.monotonic() - started
    primary_metric = config.early_stopping_metric
    primary_value = metrics.get(primary_metric)
    error_value = metrics.get("error")
    valid = not (
        metrics.get("timeout") is True
        or ("error" in metrics and error_value not in (None, "", 0, 0.0, False))
    )
    return {
        "schema_version": 1,
        "valid": valid,
        "primary_metric": {
            "name": primary_metric,
            "value": json_safe(primary_value),
            "direction": "maximize",
        },
        "raw_metrics": json_safe(metrics),
        "artifacts": json_safe(artifacts),
        "elapsed_seconds": elapsed_seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    describe_parser = subparsers.add_parser("describe")
    describe_parser.add_argument("--upstream-root", type=Path, required=True)
    describe_parser.add_argument("--config", type=Path, required=True)
    describe_parser.add_argument("--output", type=Path, required=True)

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--upstream-root", type=Path, required=True)
    evaluate_parser.add_argument("--config", type=Path, required=True)
    evaluate_parser.add_argument("--evaluator", type=Path, required=True)
    evaluate_parser.add_argument("--artifact", type=Path, required=True)
    evaluate_parser.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "describe":
        result = describe(args)
    else:
        result = asyncio.run(evaluate(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
