#!/usr/bin/env python3
"""Invoke the upstream UnifiedTask evaluator in its locked driver runtime."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any


def as_payload(result: Any, diagnostics: str) -> dict[str, Any]:
    if isinstance(result, dict):
        metrics = dict(result)
        artifacts: dict[str, Any] = {}
    else:
        metrics = getattr(result, "metrics", None)
        artifacts = getattr(result, "artifacts", None) or {}
        if not isinstance(metrics, dict) or not isinstance(artifacts, dict):
            raise TypeError(f"unsupported evaluator result: {type(result).__name__}")
    return {
        "metrics": metrics,
        "artifacts": artifacts,
        "diagnostics": diagnostics,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--runtime-env", required=True)
    parser.add_argument("--runtime-python-env")
    args = parser.parse_args(argv)

    upstream = args.upstream_root.expanduser().absolute()
    sys.path.insert(0, str(upstream))
    from omegaconf import OmegaConf
    from frontier_eval.tasks.unified.evaluator.python import evaluate
    from frontier_eval.tasks.unified.spec import load_unified_task_spec

    runtime: dict[str, str] = {"env_name": args.runtime_env}
    if args.runtime_python_env:
        runtime["python_path"] = f"uv-env:{args.runtime_python_env}"
    task_cfg = OmegaConf.create(
        {
            "name": "unified",
            "benchmark": args.task_id,
            "benchmark_root": "benchmarks",
            "metadata_dir": "frontier_eval",
            "timeout": float(os.environ.get("FRONTIER_EVAL_EVALUATOR_TIMEOUT_S", "300")),
            "runtime": runtime,
        }
    )
    spec = load_unified_task_spec(task_cfg=task_cfg, repo_root=upstream)
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        result = evaluate(str(args.candidate.expanduser().absolute()), spec=spec)
    print(json.dumps(as_payload(result, captured.getvalue()), ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
