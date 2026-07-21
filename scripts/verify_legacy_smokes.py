#!/usr/bin/env python3
"""Verify migrated legacy smoke evidence and optional upstream raw outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPO_ROOT / "evidence/legacy-smokes"
SKYDISCOVER_RUN = EVIDENCE_ROOT / "skydiscover-evox-circle-deepseek-1iter-20260720"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def verify_migrated() -> dict:
    source_summary = read_json(EVIDENCE_ROOT / "source-smoke-results.json")

    ale = read_json(EVIDENCE_ROOT / "ale-ahc027-valid-baseline.json")
    assert ale["public_cases"] == 5
    assert ale["private_cases"] == 200
    assert ale["public_score"] == 61_302_533
    assert ale["private_score"] == 8_602_247_700

    heuristic_output = (EVIDENCE_ROOT / "heurigym-operator-scheduling-demo.output").read_text()
    assert heuristic_output.splitlines() == ["n1:0", "n2:3", "n3:6"]

    autolab = read_json(EVIDENCE_ROOT / "autolab-toy-isa-reward.json")
    assert autolab["correctness"] is True
    assert autolab["metric"] == 2194
    assert autolab["reward"] == 0.9154

    best = read_json(SKYDISCOVER_RUN / "best/best_program_info.json")
    checkpoint = read_json(SKYDISCOVER_RUN / "checkpoints/checkpoint_1/metadata.json")
    best_candidate = read_json(
        SKYDISCOVER_RUN
        / "checkpoints/checkpoint_1/programs/22a62f43-96ae-458d-a8a1-8049a8b71684.json"
    )
    initial_candidate = read_json(
        SKYDISCOVER_RUN
        / "checkpoints/checkpoint_1/programs/c66bf67c-ef8f-42af-93d4-7a5d7e37cc93.json"
    )
    assert checkpoint == {"last_iteration": 1, "best_program_id": best["id"]}
    assert best_candidate["id"] == best["id"]
    assert best_candidate["parent_id"] == initial_candidate["id"]
    assert best_candidate["metrics"]["combined_score"] == best["metrics"]["combined_score"]
    assert (SKYDISCOVER_RUN / "best/best_program.py").read_bytes() == (
        SKYDISCOVER_RUN / "checkpoints/checkpoint_1/best_program.py"
    ).read_bytes()
    assert best["metrics"]["test_combined_score"] == source_summary["benchmarks"][
        "skydiscover_evox"
    ]["independent_rescore_combined_score"]

    log = (SKYDISCOVER_RUN / "logs/evox_20260720_035607.log.txt").read_text()
    assert "Retry 3/3" in log
    assert "Discovery completed" in log
    assert "/Users/" not in log

    return {
        "ale_bench_lite": {
            "public_cases": ale["public_cases"],
            "private_cases": ale["private_cases"],
            "private_score": ale["private_score"],
        },
        "heurigym": {"output_lines": len(heuristic_output.splitlines())},
        "autolab": autolab,
        "skydiscover_evox": {
            "programs": 2,
            "best_program_id": best["id"],
            "combined_score": best["metrics"]["combined_score"],
            "test_combined_score": best["metrics"]["test_combined_score"],
        },
    }


def verify_upstream_raw(upstreams_root: Path) -> dict:
    ale_run = upstreams_root / "ALE-Bench/.tmp/e2e-smoke/ale-deepseek-v4-flash"
    results = read_json(ale_run / "ahc027/results/final_results.json")
    costs = read_json(ale_run / "ahc027/results/total_cost.json")
    repeated = results["repeated_sampling"]
    assert repeated["overall_absolute_score"] is not None
    assert costs["repeated_sampling"]["total_tokens"] > 0

    program_dir = upstreams_root / "HeuriGym/operator_scheduling/program"
    sys.path.insert(0, str(program_dir))
    from evaluator import evaluate  # type: ignore[import-not-found]
    from verifier import verify  # type: ignore[import-not-found]

    input_path = upstreams_root / "HeuriGym/_datasets/operator_scheduling/demo/demo.json"
    output_path = EVIDENCE_ROOT / "heurigym-operator-scheduling-demo.output"
    valid, error = verify(str(input_path), str(output_path))
    assert valid, error

    autolab_root = upstreams_root / "AutoLab/.tmp/jobs/e2e-deepseek-toy-isa"
    reward_paths = list(autolab_root.glob("toy_isa_opt__*/verifier/reward.json"))
    assert len(reward_paths) == 1, reward_paths
    autolab = read_json(reward_paths[0])
    assert autolab == read_json(EVIDENCE_ROOT / "autolab-toy-isa-reward.json")

    return {
        "ale_bench_lite": {
            "generated_one_shot_score": repeated["overall_absolute_score"],
            "tokens": costs["repeated_sampling"]["total_tokens"],
        },
        "heurigym": {"valid": valid, "cost": evaluate(str(input_path), str(output_path))},
        "autolab": autolab,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--upstreams-root",
        type=Path,
        help="Directory containing sibling ALE-Bench, HeuriGym, and AutoLab checkouts.",
    )
    args = parser.parse_args()

    report = {"migrated_evidence": verify_migrated()}
    if args.upstreams_root is not None:
        report["upstream_raw"] = verify_upstream_raw(args.upstreams_root.resolve())
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
