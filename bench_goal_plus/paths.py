"""Stable repository paths used by the agent engine."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "runs"
RUNNER_REGISTRY = ROOT / "benchmarks" / "runners.json"
ASSET_PACK_REGISTRY = ROOT / "benchmarks" / "asset-packs.json"
UPSTREAM_REGISTRY = ROOT / "environment" / "upstreams.json"
ADAPTER_REGISTRY = ROOT / "benchmarks" / "task-adapters.json"
MANAGED_VENV = ROOT / ".bench-env" / "venv"


def managed_python() -> Path:
    return MANAGED_VENV / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
