#!/usr/bin/env python3
"""Thin compatibility entrypoint for the repository-owned agent engine."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench_goal_plus.cli import build_parser, entrypoint, main  # noqa: E402,F401


if __name__ == "__main__":
    raise SystemExit(entrypoint())
