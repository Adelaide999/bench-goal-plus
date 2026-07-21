#!/usr/bin/env python3
"""Turn a generated ALE candidate into a bounded valid baseline and score it.

The one-shot model candidate spent its whole time budget in an optional local
search loop.  Disabling only that loop preserves its BFS/DFS construction and
provides a deterministic validity smoke for all Lite public/private seeds.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import ale_bench


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--problem-id", default="ahc027")
    parser.add_argument("--num-workers", type=int, default=4)
    args = parser.parse_args()

    generated = json.loads(args.source_results.read_text())["repeated_sampling"]["code"]
    original = "while (walk.size() - 1 < MAX_L) {"
    replacement = "while (false && walk.size() - 1 < MAX_L) {"
    if generated.count(original) != 1:
        raise RuntimeError("expected exactly one optional search loop")
    bounded = generated.replace(original, replacement)

    session = ale_bench.start(
        problem_id=args.problem_id,
        lite_version=True,
        num_workers=args.num_workers,
    )
    try:
        public = session.public_eval(bounded, code_language="cpp20", judge_version="202301")
        private, rank, performance = session.private_eval(
            bounded,
            code_language="cpp20",
            judge_version="202301",
        )
    finally:
        session.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "problem_id": args.problem_id,
                "public_cases": len(public.case_results),
                "public_score": public.overall_absolute_score,
                "private_cases": len(private.case_results),
                "private_score": private.overall_absolute_score,
                "rank": rank,
                "performance": performance,
                "change": "disabled the generated candidate's optional unbounded local-search loop",
            },
            indent=2,
        )
        + "\n"
    )
    print(args.output.read_text(), end="")


if __name__ == "__main__":
    main()
