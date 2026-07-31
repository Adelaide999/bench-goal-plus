#!/usr/bin/env python3
"""Skill entrypoint for validating a registered benchmark integration."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from scripts import bench  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(bench.entrypoint(["check", *sys.argv[1:]]))
