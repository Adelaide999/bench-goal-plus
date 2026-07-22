#!/usr/bin/env python3
"""Standard Plain Codex and Goal Plus + Codex benchmark runner."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments.heurigym_compare.experiment import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
