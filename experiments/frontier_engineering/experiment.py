#!/usr/bin/env python3
"""Compatibility entrypoint for Frontier-Engineering native campaigns."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments.frontier_engineering.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
