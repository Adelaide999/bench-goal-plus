"""SkyDiscover evaluator bridge for controller-owned benchmark workspaces.

SkyDiscover calls ``evaluate(candidate_path)`` from worker threads. Each call
gets a preserved workspace copy so concurrent candidates never overwrite one
another. The benchmark adapter remains authoritative for validation, raw
metrics, direction, and the shared evaluator-call ledger.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from adapters.openevolve_examples.adapter import evaluate_workspace


TEMPLATE_ENV = "BENCH_SKYDISCOVER_TEMPLATE_WORKSPACE"
EVALUATION_ROOT_ENV = "BENCH_SKYDISCOVER_EVALUATION_ROOT"


def _required_path(env_name: str) -> Path:
    value = os.environ.get(env_name)
    if not value:
        raise RuntimeError(f"{env_name} is required by the SkyDiscover evaluator bridge")
    path = Path(value).expanduser().absolute()
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def metrics_from_report(
    report: dict[str, Any],
    *,
    metric_name: str,
    direction: str,
) -> dict[str, float]:
    metric = report.get("primary_metric")
    raw_value = metric.get("value") if isinstance(metric, dict) else None
    valid = (
        report.get("valid") is True
        and not isinstance(raw_value, bool)
        and isinstance(raw_value, (int, float))
        and math.isfinite(float(raw_value))
    )
    if not valid:
        return {"combined_score": -1e300, "validity": 0.0}

    raw = float(raw_value)
    search_score = raw if direction == "maximize" else -raw
    return {
        metric_name: raw,
        "combined_score": search_score,
        "validity": 1.0,
    }


def evaluate(program_path: str) -> dict[str, float]:
    """Evaluate one SkyDiscover candidate through the existing bench adapter."""
    candidate = Path(program_path).expanduser().absolute()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    template = _required_path(TEMPLATE_ENV)
    evaluation_root = _required_path(EVALUATION_ROOT_ENV)

    call_workspace = evaluation_root / (
        f"candidate-{time.time_ns()}-{uuid.uuid4().hex[:12]}"
    )
    shutil.copytree(template, call_workspace)
    metadata = json.loads((call_workspace / "task.json").read_text())
    artifact = call_workspace / metadata["artifact_name"]
    artifact.write_bytes(candidate.read_bytes())

    report = evaluate_workspace(call_workspace, "public")
    (call_workspace / "skydiscover-eval.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return metrics_from_report(
        report,
        metric_name=metadata["primary_metric"],
        direction=metadata["direction"],
    )
