#!/usr/bin/env python3
"""Evaluate one Codex workspace with the official ALE public evaluator."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--num-workers", type=int, default=4)
    args = parser.parse_args()

    import ale_bench

    workspace = args.workspace.resolve()
    metadata = json.loads((workspace / "task.json").read_text())
    code = (workspace / "solution.cpp").read_text()
    started = time.monotonic()
    session = ale_bench.start(
        problem_id=metadata["problem_id"],
        lite_version=metadata["lite_version"],
        maximum_num_call_public_eval=1,
        num_workers=args.num_workers,
    )
    try:
        result = session.public_eval(
            code,
            code_language=metadata["code_language"],
            judge_version=metadata["judge_version"],
        )
        payload = {
            "schema_version": 1,
            "benchmark": "ale-bench-lite",
            "problem_id": metadata["problem_id"],
            "split": "public-lite",
            "score_type": metadata["score_type"],
            "evaluator_calls": 1,
            "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
            "overall_judge_result": result.overall_judge_result.value,
            "overall_absolute_score": result.overall_absolute_score,
            "overall_relative_score": result.overall_relative_score,
            "elapsed_seconds": time.monotonic() - started,
            "cases": [
                {
                    "judge_result": case.judge_result.value,
                    "absolute_score": case.absolute_score,
                    "relative_score": case.relative_score,
                    "execution_time": case.execution_time,
                    "memory_usage": case.memory_usage,
                    "message": case.message,
                }
                for case in result.case_results
            ],
        }
    finally:
        session.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
