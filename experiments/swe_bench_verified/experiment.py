#!/usr/bin/env python3
"""Compatibility entrypoint for the native SWE-bench Verified controller."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments.swe_bench_verified.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
