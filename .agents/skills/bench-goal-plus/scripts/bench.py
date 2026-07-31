#!/usr/bin/env python3
"""Stable Skill entrypoint for the repository-owned benchmark agent."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from scripts import bench  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(bench.entrypoint(sys.argv[1:]))
