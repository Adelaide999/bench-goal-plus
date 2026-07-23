#!/usr/bin/env python3
"""Evaluate a VLIW solution against the local public and held-out case sets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adapters.local_vliw.adapter import run_source_evaluator  # noqa: E402


SOURCE_ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--solution",
        type=Path,
        default=SOURCE_ROOT / "task/starter_solution.py",
    )
    parser.add_argument(
        "--cases",
        choices=("public", "held-out", "both"),
        default="both",
    )
    args = parser.parse_args()
    modes = {
        "public": ("public",),
        "held-out": ("final",),
        "both": ("public", "final"),
    }[args.cases]
    payload = {
        mode: run_source_evaluator(
            SOURCE_ROOT,
            args.solution.expanduser().absolute(),
            mode,
        )[0]
        for mode in modes
    }
    print(json.dumps(payload, indent=2))
    return 0 if all(report.get("all_correct") for report in payload.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
