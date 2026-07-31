"""Command-line interface for the benchmark Agent Skill engine."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from .application import BenchmarkAgent
from .errors import BenchGoalPlusError, ContractError


def add_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--benchmark", action="append", default=[])
    parser.add_argument("--preset")
    parser.add_argument("--profile")


def add_start_arguments(parser: argparse.ArgumentParser) -> None:
    add_selection(parser)
    parser.add_argument("--campaign-id")
    parser.add_argument("--campaign-dir", type=Path)
    parser.add_argument("--method", action="append", default=[])
    parser.add_argument("--condition", action="append", default=[])
    parser.add_argument("--seed", action="append", type=int, default=[])
    parser.add_argument("--model")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high", "xhigh"))
    parser.add_argument("--wall-time-seconds", type=int)
    parser.add_argument("--live-search-concurrency", type=int)
    parser.add_argument("--cell-concurrency", type=int)
    parser.add_argument("--worker-runtime-seconds", type=int)
    parser.add_argument("--worker-min-runtime-seconds", type=int)
    parser.add_argument("--skip-bootstrap", action="store_true")
    parser.add_argument("--skip-provision", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--foreground", action="store_true")
    parser.add_argument("--dry-run", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Set up, run, resume, finalize, and report registered benchmarks."
    )
    children = parser.add_subparsers(dest="command", required=True)
    catalog = children.add_parser("catalog")
    catalog.add_argument("--json", action="store_true")

    setup = children.add_parser("setup")
    add_selection(setup)
    setup.add_argument("--skip-bootstrap", action="store_true")
    setup.add_argument("--skip-provision", action="store_true")
    setup.add_argument("--dry-run", action="store_true")

    for name in ("plan", "start", "launch"):
        add_start_arguments(children.add_parser(name))
    e2e = children.add_parser("e2e")
    add_start_arguments(e2e)
    e2e.add_argument("--markdown-out", type=Path)
    e2e.add_argument("--xlsx-out", type=Path)

    for name in ("status", "stop", "resume"):
        child = children.add_parser(name)
        child.add_argument("--campaign", required=True)
        child.add_argument("--benchmark")
        child.add_argument("--dry-run", action="store_true")

    finish = children.add_parser("finish")
    finish.add_argument("--campaign", required=True)
    finish.add_argument("--benchmark")
    finish.add_argument("--markdown-out", type=Path)
    finish.add_argument("--xlsx-out", type=Path)
    finish.add_argument("--dry-run", action="store_true")

    check = children.add_parser("check")
    check.add_argument("--benchmark", required=True)
    check.add_argument("--dry-run", action="store_true")
    return parser


def spec_from_args(agent: BenchmarkAgent, args: argparse.Namespace):
    return agent.resolve_spec(
        target_ids=args.benchmark,
        preset_id=args.preset,
        profile=args.profile,
        campaign_id=args.campaign_id,
        campaign_dir=args.campaign_dir,
        methods=args.method,
        conditions=args.condition,
        seeds=args.seed,
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        wall_time_seconds=args.wall_time_seconds,
        live_search_concurrency=args.live_search_concurrency,
        cell_concurrency=args.cell_concurrency,
        worker_runtime_seconds=args.worker_runtime_seconds,
        worker_min_runtime_seconds=args.worker_min_runtime_seconds,
    )


def render_catalog(agent: BenchmarkAgent, *, as_json: bool) -> int:
    payload = agent.catalog.as_dict()
    if as_json:
        print(json.dumps(payload, indent=2))
        return 0
    for runner in payload["runners"]:
        capabilities = runner["capabilities"]
        print(
            f"runner {runner['id']}: {runner['kind']} "
            f"detach={capabilities['detach']} stop={capabilities['stop']} "
            f"resume={capabilities['resume']} C={capabilities['cell_concurrency']}"
        )
    for target in payload["targets"]:
        docker = target["docker"]
        print(
            f"{target['id']}: runner={target['runner']} adapter={target['adapter'] or '-'} "
            f"docker={docker['requirement']}/{docker['owner']}/{docker['provision_mode']}"
        )
    for preset in payload["presets"]:
        print(f"preset {preset['id']}: {preset['description']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    agent = BenchmarkAgent()
    if args.command == "catalog":
        return render_catalog(agent, as_json=args.json)
    if args.command == "setup":
        targets, preset = agent.resolve_targets(
            target_ids=args.benchmark, preset_id=args.preset
        )
        result = agent.setup(
            targets,
            profile=args.profile or (preset.profile if preset else None),
            skip_bootstrap=args.skip_bootstrap,
            skip_provision=args.skip_provision,
            dry_run=args.dry_run,
        )
    elif args.command in {"plan", "start", "launch", "e2e"}:
        if args.command == "e2e" and args.prepare_only:
            raise ContractError("e2e cannot be combined with --prepare-only")
        spec = spec_from_args(agent, args)
        dry_run = args.dry_run or args.command == "plan"
        result = agent.start(
            spec,
            skip_bootstrap=args.skip_bootstrap,
            skip_provision=args.skip_provision,
            prepare_only=args.prepare_only,
            foreground=args.foreground or args.command == "e2e",
            dry_run=dry_run,
        )
        if args.command == "e2e" and not dry_run:
            result = {
                "start": result,
                "finish": agent.finish(
                    result["campaign"]["path"],
                    benchmark=None,
                    markdown_out=args.markdown_out,
                    xlsx_out=args.xlsx_out,
                    dry_run=False,
                ),
            }
    elif args.command == "status":
        result = agent.status(args.campaign, benchmark=args.benchmark)
    elif args.command == "stop":
        result = agent.stop(args.campaign, benchmark=args.benchmark, dry_run=args.dry_run)
    elif args.command == "resume":
        result = agent.resume(args.campaign, benchmark=args.benchmark, dry_run=args.dry_run)
    elif args.command == "finish":
        result = agent.finish(
            args.campaign,
            benchmark=args.benchmark,
            markdown_out=args.markdown_out,
            xlsx_out=args.xlsx_out,
            dry_run=args.dry_run,
        )
    else:
        result = agent.check(args.benchmark, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0


def entrypoint(argv: list[str] | None = None) -> int:
    try:
        return main(argv)
    except (BenchGoalPlusError, FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=__import__("sys").stderr)
        return 2
