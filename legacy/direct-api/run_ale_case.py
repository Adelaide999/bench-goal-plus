#!/usr/bin/env python3
"""Run one minimal ALE-Bench Lite case through its legacy direct-API path."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ale_bench_eval.__main__ import evaluate_contest
from ale_bench_eval.prompts.builder import PromptArgs
from ale_bench_eval.safe_generation import parse_model_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem-id", default="ahc027")
    parser.add_argument("--model-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is required")
    with args.model_config.open() as handle:
        model_config = parse_model_config(json.load(handle))

    args.output.mkdir(parents=True, exist_ok=True)
    evaluate_contest(
        prompt_args=PromptArgs(
            code_language="cpp20",
            judge_version="202301",
            prompt_language="en",
            use_image=False,
        ),
        model_name="deepseek-v4-flash",
        model_config=model_config,
        n_repeated_sampling=1,
        n_self_refine=0,
        problem_id=args.problem_id,
        lite_version=True,
        num_workers=1,
        reuse_containers=False,
        n_public_cases=1,
        selection_method="best",
        root_path=args.output,
        max_repeated_sampling_workers=1,
    )


if __name__ == "__main__":
    main()

