#!/usr/bin/env python3
"""Compatibility entrypoint for the generic standalone benchmark runner."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments.benchmark_compare import experiment as _implementation


def __getattr__(name: str) -> Any:
    return getattr(_implementation, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_implementation)))


def main() -> int:
    return _implementation.main()


if __name__ == "__main__":
    raise SystemExit(main())
