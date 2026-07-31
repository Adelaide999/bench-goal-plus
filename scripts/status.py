#!/usr/bin/env python3
"""Validate and print the benchmark integration registry."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "benchmarks/registry.json"
sys.path.insert(0, str(ROOT))

from adapters.registry import (  # noqa: E402
    AdapterContractError,
    load_adapter,
    load_definitions,
)
from bench_goal_plus.catalog import Catalog  # noqa: E402
from bench_goal_plus.errors import ContractError  # noqa: E402
from benchmarks.datasets import (  # noqa: E402
    load_catalog as load_dataset_catalog,
    validate_catalog as validate_dataset_catalog,
)


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text())


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    allowed = set(data.get("status_values", []))
    docker_values = {"required", "not_required", "mixed", "unavailable"}
    gate_sets = data.get("gate_sets", {})
    seen_ids: set[str] = set()

    if data.get("schema_version") != 2:
        errors.append("schema_version must be 2")

    for item in data.get("items", []):
        item_id = item.get("id", "<missing>")
        if item_id in seen_ids:
            errors.append(f"duplicate item id: {item_id}")
        seen_ids.add(item_id)

        docker_requirement = item.get("docker_requirement")
        if docker_requirement not in docker_values:
            errors.append(
                f"{item_id}: docker_requirement must be one of "
                f"{sorted(docker_values)}, got {docker_requirement!r}"
            )
        if not item.get("docker_scope"):
            errors.append(f"{item_id}: docker_scope must explain the supported path")

        gate_set = item.get("gate_set")
        expected = set(gate_sets.get(gate_set, []))
        actual = set(item.get("stages", {}))
        if expected != actual:
            errors.append(
                f"{item_id}: stage keys differ; missing={sorted(expected - actual)}, "
                f"extra={sorted(actual - expected)}"
            )

        for gate, status in item.get("stages", {}).items():
            if status not in allowed:
                errors.append(f"{item_id}.{gate}: invalid status {status!r}")

        if item.get("stages", {}).get("source_forked") == "pass":
            for repository in item.get("repositories", []):
                if repository.get("upstream_url", "").startswith("https://github.com/"):
                    if not repository.get("fork_url"):
                        errors.append(f"{item_id}: fork_url missing for GitHub upstream")
                branch = repository.get("tracking_branch")
                if (
                    not isinstance(branch, str)
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch) is None
                    or branch.startswith(("-", ".", "/"))
                    or ".." in branch
                ):
                    errors.append(f"{item_id}: tracking_branch must be a safe branch name")

        for evidence in item.get("evidence", []):
            if not (ROOT / evidence).is_file():
                errors.append(f"{item_id}: missing evidence file {evidence}")

    return errors


def validate_task_adapters() -> list[str]:
    try:
        definitions = load_definitions()
        for adapter_id in definitions:
            load_adapter(adapter_id)
    except (AdapterContractError, ImportError, KeyError) as error:
        return [f"task adapter registry: {error}"]
    return []


def validate_datasets() -> list[str]:
    return [
        f"dataset catalog: {error}"
        for error in validate_dataset_catalog(load_dataset_catalog())
    ]


def validate_runner_catalog() -> list[str]:
    try:
        Catalog()
    except ContractError as error:
        return [f"runner catalog: {error}"]
    return []


def compact(status: str) -> str:
    return {
        "pass": "PASS",
        "partial": "PART",
        "todo": "TODO",
        "blocked": "BLOCK",
        "n/a": "N/A",
    }[status]


def compact_docker(requirement: str) -> str:
    return {
        "required": "REQUIRED",
        "not_required": "NO",
        "mixed": "MIXED",
        "unavailable": "N/A",
    }[requirement]


def print_table(data: dict) -> None:
    benchmark_gates = data["gate_sets"]["benchmark"]
    print("# Benchmarks")
    print("| Priority | Benchmark | Docker | " + " | ".join(benchmark_gates) + " |")
    print("|---:|---|---|" + "---|" * len(benchmark_gates))
    benchmarks = [item for item in data["items"] if item["gate_set"] == "benchmark"]
    for item in sorted(benchmarks, key=lambda value: value["priority"]):
        values = [compact(item["stages"][gate]) for gate in benchmark_gates]
        docker = compact_docker(item["docker_requirement"])
        print(
            f"| {item['priority']} | {item['display_name']} | {docker} | "
            + " | ".join(values)
            + " |"
        )

    search_gates = data["gate_sets"]["search_backend"]
    print("\n# Search backends")
    print("| Priority | Backend | Docker | " + " | ".join(search_gates) + " |")
    print("|---:|---|---|" + "---|" * len(search_gates))
    backends = [item for item in data["items"] if item["gate_set"] == "search_backend"]
    for item in sorted(backends, key=lambda value: value["priority"]):
        values = [compact(item["stages"][gate]) for gate in search_gates]
        docker = compact_docker(item["docker_requirement"])
        print(
            f"| {item['priority']} | {item['display_name']} | {docker} | "
            + " | ".join(values)
            + " |"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate without printing the matrix")
    args = parser.parse_args()

    data = load_registry()
    errors = [
        *validate(data),
        *validate_task_adapters(),
        *validate_datasets(),
        *validate_runner_catalog(),
    ]
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if args.check:
        dataset_count = len(load_dataset_catalog()["datasets"])
        print(
            f"OK: {len(data['items'])} registry items and "
            f"{dataset_count} datasets validated"
        )
    else:
        print_table(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
