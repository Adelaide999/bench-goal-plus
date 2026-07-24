"""Bench-owned configuration and evidence helpers for SkyDiscover."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


METHOD_PREFIX = "skydiscover-"
SUPPORTED_ALGORITHMS = ("best_of_n", "evox", "adaevolve")
METHODS = tuple(
    METHOD_PREFIX + algorithm.replace("_", "-") for algorithm in SUPPORTED_ALGORITHMS
)


def is_method(method: str) -> bool:
    return method in METHODS


def algorithm_for_method(method: str) -> str:
    if not is_method(method):
        raise ValueError(f"unsupported SkyDiscover method: {method}")
    return method.removeprefix(METHOD_PREFIX).replace("-", "_")


def database_config(algorithm: str, seed: int) -> dict[str, Any]:
    """Return explicit native search controls for one SkyDiscover algorithm."""
    if algorithm == "best_of_n":
        controls: dict[str, Any] = {
            "best_of_n": 5,
        }
    elif algorithm == "evox":
        controls = {
            "auto_generate_variation_operators": True,
        }
    elif algorithm == "adaevolve":
        controls = {
            "population_size": 20,
            "num_islands": 2,
            "use_adaptive_search": True,
            "use_ucb_selection": True,
            "use_migration": True,
            "use_unified_archive": True,
            "use_dynamic_islands": True,
            "use_paradigm_breakthrough": True,
        }
    else:
        raise ValueError(f"unsupported SkyDiscover algorithm: {algorithm}")

    # SkyDiscover does not currently consume this consistently across these
    # algorithms. Persist it for audit without claiming end-to-end determinism.
    controls["random_seed"] = seed
    return controls


def write_config(
    target: Path,
    *,
    algorithm: str,
    task_prompt: str,
    file_suffix: str,
    evaluator_timeout_seconds: int,
    concurrency: int,
    iterations_ceiling: int,
    seed: int,
    reasoning_effort: str,
) -> dict[str, Any]:
    """Write a secret-free SkyDiscover config owned by the experiment."""
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise ValueError(f"unsupported SkyDiscover algorithm: {algorithm}")
    if concurrency < 1:
        raise ValueError("SkyDiscover concurrency must be positive")
    if iterations_ceiling < 1:
        raise ValueError("SkyDiscover iteration ceiling must be positive")

    try:
        import yaml
    except ImportError as error:
        raise RuntimeError(
            "PyYAML is missing; run scripts/repro_env.py bootstrap"
        ) from error

    payload: dict[str, Any] = {
        "max_iterations": iterations_ceiling,
        "checkpoint_interval": 1,
        "log_level": "INFO",
        "file_suffix": file_suffix,
        "max_parallel_iterations": concurrency,
        "diff_based_generation": True,
        "max_solution_length": 60000,
        "llm": {
            # The CLI replaces this placeholder with the explicit run model.
            "models": [{"name": "bench-model-placeholder", "weight": 1.0}],
            "temperature": 0.7,
            "max_tokens": 32000,
            "timeout": 600,
            "retries": 1,
            "retry_delay": 1,
            "reasoning_effort": reasoning_effort,
        },
        "search": {
            "type": algorithm,
            "num_context_programs": 4,
            # EvoX must use the run model for both candidate and search-strategy
            # evolution. The field is harmless for the other native algorithms.
            "share_llm": True,
            "database": database_config(algorithm, seed),
        },
        "prompt": {
            "system_message": task_prompt,
        },
        "evaluator": {
            "timeout": evaluator_timeout_seconds,
            "max_retries": 0,
            "cascade_evaluation": False,
            "inject_evaluator_context": False,
            "llm_as_judge": False,
        },
        "monitor": {"enabled": False},
    }
    target.write_text(yaml.safe_dump(payload, sort_keys=False))
    return payload


def best_candidate(output_dir: Path, suffix: str) -> Path:
    extension = suffix if suffix.startswith(".") else f".{suffix}"
    return output_dir / "best" / f"best_program{extension}"


def collect_best_info(output_dir: Path) -> dict[str, Any] | None:
    path = output_dir / "best" / "best_program_info.json"
    return json.loads(path.read_text()) if path.is_file() else None
