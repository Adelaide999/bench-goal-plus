#!/usr/bin/env python3
"""Inspect the benchmark dataset and panel catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.datasets import (  # noqa: E402
    DOMAINS,
    list_datasets,
    resolve_dataset,
    validated_catalog,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--domain", choices=sorted(DOMAINS))
    list_parser.add_argument("--stage", type=int, choices=range(5))
    list_parser.add_argument("--adapter-status")
    list_parser.add_argument("--json", action="store_true")

    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("dataset_id")
    subparsers.add_parser("validate")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "validate":
        catalog = validated_catalog()
        panel_count = sum(len(dataset["panels"]) for dataset in catalog["datasets"])
        print(f"OK: {len(catalog['datasets'])} datasets and {panel_count} panels validated")
        return 0
    if args.command == "show":
        print(json.dumps(resolve_dataset(args.dataset_id), indent=2))
        return 0

    datasets = list_datasets(
        domain=args.domain,
        stage=args.stage,
        adapter_status=args.adapter_status,
    )
    if args.json:
        print(json.dumps(datasets, indent=2))
        return 0
    print("ID\tDOMAIN\tTASKS\tROLE\tADAPTER\tPANELS")
    for dataset in datasets:
        panels = ",".join(
            f"{panel['id']}:{panel['status']}" for panel in dataset["panels"]
        )
        print(
            f"{dataset['id']}\t{dataset['domain']}\t{dataset['task_count']}\t"
            f"{dataset['claim_role']}\t{dataset['integration']['adapter_status']}\t{panels}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
