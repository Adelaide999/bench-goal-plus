#!/usr/bin/env python3
"""Run HeuriGym operator scheduling with Plain Codex or Goal Plus + Codex."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adapters.heurigym.adapter import (  # noqa: E402
    ARTIFACT_NAME,
    DIRECTION,
    PRIMARY_METRIC,
    TASK_ID,
    evaluate_workspace,
    git_commit,
    materialize_workspace,
)
from experiments.openevolve_compare.experiment import (  # noqa: E402
    DEFAULT_REASONING_EFFORT,
    append_unique_lines,
    codex_goal_plus_mcp_args,
    codex_provider_args,
    collect_goal_plus_state,
    commit_workspace,
    copy_goal_plus_assets,
    finalize_goal_plus_search,
    goal_plus_incomplete_reason,
    parse_codex_events,
    primary_score,
    render_goal,
    render_plain_prompt,
    run_controlled,
    run_controlled_many,
    sha256_text,
    utc_now,
    write_json,
)


DEFAULT_ENV_MANIFEST = ROOT / "environment/upstreams.json"
DEFAULT_CHECKOUT_ROOT = ROOT / "third_party"
DEFAULT_VENV = ROOT / ".bench-env/venv"
DEFAULT_RUNS = ROOT / "runs/heurigym-compare"
DEFAULT_MODEL = "gpt-5.6-sol"
METHODS = ("plain-codex", "goal-plus-codex")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def default_run_dir(method: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return DEFAULT_RUNS / f"{timestamp}-{TASK_ID}-{method}"


def runtime_bin(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def prepare(args: argparse.Namespace) -> int:
    if args.wall_time_seconds <= args.soft_closeout_seconds:
        raise ValueError("wall time must exceed the closeout reserve")
    if args.concurrency < 1:
        raise ValueError("concurrency must be positive")
    exploration_seconds = args.wall_time_seconds - args.soft_closeout_seconds
    if not 1 <= args.worker_runtime_seconds <= exploration_seconds:
        raise ValueError("worker runtime must fit inside the exploration budget")
    environment = load_json(args.environment_manifest)
    upstreams = environment["upstreams"]
    checkout_root = args.checkout_root.expanduser().absolute()
    heurigym_root = checkout_root / upstreams["heurigym"]["checkout_dir"]
    goal_plus_root = checkout_root / upstreams["goal_plus"]["checkout_dir"]
    for name, path in (("heurigym", heurigym_root), ("goal_plus", goal_plus_root)):
        if not (path / ".git").exists():
            raise FileNotFoundError(
                f"managed {name} checkout is missing: {path}; run repro_env.py bootstrap"
            )
        expected = upstreams[name]["pinned_commit"]
        actual = git_commit(path)
        if actual != expected:
            raise RuntimeError(f"{name} commit mismatch: expected {expected}, got {actual}")

    run_dir = (args.run_dir or default_run_dir(args.method)).expanduser().absolute()
    run_dir.mkdir(parents=True, exist_ok=False)
    workspaces: list[Path] = []
    workspace_commits: list[str] = []

    if args.method == "plain-codex":
        for lane_index in range(args.concurrency):
            lane = f"lane-{lane_index:02d}"
            workspace = run_dir / "workspaces" / lane
            materialized = materialize_workspace(
                heurigym_root,
                workspace,
            )
            workspaces.append(workspace)
            workspace_commits.append(materialized["workspace_commit"])
        task_text = (workspaces[0] / "TASK.md").read_text()
        common_prompt = render_plain_prompt(
            task_text, args.wall_time_seconds, args.soft_closeout_seconds
        )
        prompt_contract = {
            "mode": "plain_codex_common_prompt",
            "common_prompt_sha256": sha256_text(common_prompt),
            "transform": "identity",
        }
        workspace_value = None
        goal_plus_config = None
    else:
        workspace = run_dir / "workspace"
        materialized = materialize_workspace(
            heurigym_root,
            workspace,
        )
        copy_goal_plus_assets(goal_plus_root, workspace)
        append_unique_lines(workspace / ".gitignore", [".gp/", ".codex-log/"])
        task_text = (workspace / "TASK.md").read_text()
        goal_prompt = render_goal(
            task_text=task_text,
            artifact_name=ARTIFACT_NAME,
            metric_name=PRIMARY_METRIC,
            metric_direction=DIRECTION,
            wall_seconds=args.wall_time_seconds,
            closeout_seconds=args.soft_closeout_seconds,
            concurrency=args.concurrency,
            worker_host="codex",
            worker_model=args.model,
            worker_runtime_seconds=args.worker_runtime_seconds,
        )
        (workspace / "GOAL.md").write_text(goal_prompt)
        workspaces.append(workspace)
        workspace_commits.append(
            commit_workspace(workspace, "install pinned Goal Plus host assets")
        )
        common_prompt = render_plain_prompt(
            task_text, args.wall_time_seconds, args.soft_closeout_seconds
        )
        prompt_contract = {
            "mode": "natural_goal_plus_entry",
            "common_prompt_sha256": sha256_text(common_prompt),
            "transform": "/goal-plus prefix plus aligned Goal Plus constraints",
            "goal_prompt_sha256": sha256_text(goal_prompt),
        }
        workspace_value = str(workspace)
        goal_plus_config = {
            "entrypoint": "/goal-plus mode=autonomous",
            "worker_host": "codex",
            "worker_model": args.model,
            "metric_name": PRIMARY_METRIC,
            "metric_direction": DIRECTION,
            "artifact_name": ARTIFACT_NAME,
            "state_at_t0": "absent; natural prompt creates all Goal Plus state inside T",
        }

    manifest = {
        "schema_version": 1,
        "status": "prepared",
        "prepared_at": utc_now(),
        "method": args.method,
        "task_id": TASK_ID,
        "model": args.model,
        "reasoning_effort": DEFAULT_REASONING_EFFORT,
        "budget": {
            "wall_time_seconds": args.wall_time_seconds,
            "concurrency": args.concurrency,
            "soft_closeout_seconds": args.soft_closeout_seconds,
            "hard_kill_grace_seconds": args.hard_kill_grace_seconds,
            "worker_runtime_seconds": args.worker_runtime_seconds,
        },
        "task": {
            "artifact_name": ARTIFACT_NAME,
            "primary_metric": PRIMARY_METRIC,
            "direction": DIRECTION,
            "upstream_commit": git_commit(heurigym_root),
            "case_set": "operator_scheduling/demo (5 public cases)",
        },
        "environment": {
            "manifest": str(args.environment_manifest.absolute()),
            "checkout_root": str(checkout_root),
            "heurigym_root": str(heurigym_root),
            "heurigym_commit": git_commit(heurigym_root),
            "goal_plus_root": str(goal_plus_root),
            "goal_plus_commit": git_commit(goal_plus_root),
            "runtime_bin": str(runtime_bin(args.venv.expanduser().absolute())),
        },
        "workspace": workspace_value,
        "workspaces": [str(path) for path in workspaces],
        "workspace_commits": workspace_commits,
        "prompt_contract": prompt_contract,
        "goal_plus_config": goal_plus_config,
        "secret_policy": "credentials are inherited and never serialized",
    }
    write_json(run_dir / "experiment.json", manifest)
    print(run_dir)
    return 0


def evaluator_budget(workspace: Path) -> dict[str, Any]:
    return load_json(workspace / ".bench-runtime/budget.json")


def evaluate(workspace: Path, mode: str) -> dict[str, Any]:
    metadata = load_json(workspace / "task.json")
    return evaluate_workspace(
        workspace, Path(metadata["upstream_root"]), mode
    )


def codex_command(
    *,
    codex_bin: str,
    workspace: Path,
    output_last_message: Path,
    model: str,
    api_base: str | None,
    goal_plus: bool,
    ephemeral: bool,
) -> list[str]:
    command = [
        codex_bin,
        "exec",
        "--json",
        "--sandbox",
        "workspace-write",
        "--cd",
        str(workspace),
        "--output-last-message",
        str(output_last_message),
        "--ignore-user-config",
        "--color",
        "never",
        "--config",
        f'model_reasoning_effort="{DEFAULT_REASONING_EFFORT}"',
    ]
    if ephemeral:
        command.append("--ephemeral")
    if api_base:
        command.extend(codex_provider_args(api_base))
    if goal_plus:
        command.extend(
            ["--dangerously-bypass-hook-trust", *codex_goal_plus_mcp_args()]
        )
    command.extend(["--model", model, "-"])
    return command


def execute_plain(
    manifest: dict[str, Any],
    run_dir: Path,
    args: argparse.Namespace,
    environment: dict[str, str],
) -> dict[str, Any]:
    budget = manifest["budget"]
    workspaces = [Path(path) for path in manifest["workspaces"]]
    lanes_root = run_dir / "lanes"
    lanes_root.mkdir()
    jobs = []
    seeds = []
    setup_calls = 0
    for lane_index, workspace in enumerate(workspaces):
        lane_name = f"lane-{lane_index:02d}"
        lane_dir = lanes_root / lane_name
        lane_dir.mkdir()
        seed = evaluate(workspace, "public")
        write_json(lane_dir / "seed-eval.json", seed)
        seeds.append({"lane": lane_name, "evaluation": seed})
        setup_calls += evaluator_budget(workspace)["total_claimed"]
        prompt = render_plain_prompt(
            (workspace / "TASK.md").read_text(),
            budget["wall_time_seconds"],
            budget["soft_closeout_seconds"],
        )
        (lane_dir / "prompt.md").write_text(prompt)
        command = codex_command(
            codex_bin=args.codex_bin,
            workspace=workspace,
            output_last_message=lane_dir / "final-message.txt",
            model=args.model,
            api_base=args.api_base,
            goal_plus=False,
            ephemeral=True,
        )
        jobs.append(
            {
                "name": lane_name,
                "command": command,
                "cwd": workspace,
                "stdin_text": prompt,
                "stdout_path": lane_dir / "events.jsonl",
                "stderr_path": lane_dir / "stderr.log",
            }
        )
    write_json(run_dir / "seed-evals.json", {"lanes": seeds})
    control = run_controlled_many(
        jobs,
        environment=environment,
        wall_time_seconds=budget["wall_time_seconds"],
        hard_kill_grace_seconds=budget["hard_kill_grace_seconds"],
    )
    lane_results = []
    for lane_index, workspace in enumerate(workspaces):
        lane_name = f"lane-{lane_index:02d}"
        lane_dir = lanes_root / lane_name
        final = evaluate(workspace, "final")
        write_json(lane_dir / "final-eval.json", final)
        candidate = lane_dir / ARTIFACT_NAME
        shutil.copy2(workspace / ARTIFACT_NAME, candidate)
        lane_results.append(
            {
                "lane": lane_name,
                "workspace": str(workspace),
                "candidate": str(candidate),
                "evaluation": final,
                "codex": parse_codex_events(lane_dir / "events.jsonl"),
            }
        )
    selected = min(lane_results, key=lambda item: primary_score(item["evaluation"]))
    write_json(run_dir / "lane-results.json", {"lanes": lane_results})
    write_json(run_dir / "final-eval.json", selected["evaluation"])
    shutil.copy2(selected["candidate"], run_dir / ARTIFACT_NAME)
    control["selected_lane"] = selected["lane"]
    control["selected_score"] = primary_score(selected["evaluation"])
    control["codex"] = {
        "lanes": [
            {"lane": item["lane"], **item["codex"]} for item in lane_results
        ]
    }
    control["evaluator_calls"] = {
        "lane_count": len(lane_results),
        "total_claimed": sum(
            item["evaluation"]["budget"]["total_claimed"] for item in lane_results
        ),
        "setup_claimed_before_t": setup_calls,
    }
    bad = [
        lane["name"]
        for lane in control["lanes"]
        if lane["returncode"] != 0 or lane["hard_killed"]
    ]
    if bad:
        control["result_incomplete_reason"] = (
            "plain Codex lanes did not exit cleanly: " + ", ".join(bad)
        )
    return control


def execute_goal_plus(
    manifest: dict[str, Any],
    run_dir: Path,
    args: argparse.Namespace,
    environment: dict[str, str],
) -> dict[str, Any]:
    budget = manifest["budget"]
    workspace = Path(manifest["workspace"])
    if (workspace / ".gp").exists():
        raise RuntimeError("standard Goal Plus run must start without .gp")
    seed = evaluate(workspace, "public")
    write_json(run_dir / "seed-eval.json", seed)
    setup_calls = evaluator_budget(workspace)["total_claimed"]
    deadline = datetime.now(timezone.utc) + timedelta(
        seconds=budget["wall_time_seconds"]
    )
    environment["GOAL_PLUS_OUTER_DEADLINE_AT"] = deadline.isoformat()
    prompt = render_goal(
        task_text=(workspace / "TASK.md").read_text(),
        artifact_name=ARTIFACT_NAME,
        metric_name=PRIMARY_METRIC,
        metric_direction=DIRECTION,
        wall_seconds=budget["wall_time_seconds"],
        closeout_seconds=budget["soft_closeout_seconds"],
        concurrency=budget["concurrency"],
        worker_host="codex",
        worker_model=args.model,
        worker_runtime_seconds=budget["worker_runtime_seconds"],
    )
    (run_dir / "prompt.md").write_text(prompt)
    command = codex_command(
        codex_bin=args.codex_bin,
        workspace=workspace,
        output_last_message=run_dir / "final-message.txt",
        model=args.model,
        api_base=args.api_base,
        goal_plus=True,
        ephemeral=False,
    )
    control = run_controlled(
        command,
        cwd=workspace,
        environment=environment,
        stdin_text=prompt,
        stdout_path=run_dir / "events.jsonl",
        stderr_path=run_dir / "stderr.log",
        wall_time_seconds=budget["wall_time_seconds"],
        hard_kill_grace_seconds=budget["hard_kill_grace_seconds"],
    )
    control["goal_plus_controller_closeout"] = finalize_goal_plus_search(workspace)
    final = evaluate(workspace, "final")
    write_json(run_dir / "final-eval.json", final)
    shutil.copy2(workspace / ARTIFACT_NAME, run_dir / ARTIFACT_NAME)
    control["codex"] = parse_codex_events(run_dir / "events.jsonl")
    control["goal_plus"] = collect_goal_plus_state(workspace)
    control["evaluator_calls"] = {
        **final["budget"],
        "setup_claimed_before_t": setup_calls,
    }
    reason = goal_plus_incomplete_reason(
        control["goal_plus"],
        expected_concurrency=budget["concurrency"],
        minimum_worker_verified_candidates=1,
    )
    if reason:
        control["result_incomplete_reason"] = reason
    if not control["goal_plus_controller_closeout"].get("completed"):
        control["result_incomplete_reason"] = (
            "Goal Plus controller closeout failed: "
            + control["goal_plus_controller_closeout"].get("error", "unknown error")
        )
    if control["hard_killed"]:
        control["result_incomplete_reason"] = "Goal Plus exceeded hard-kill grace"
    if final.get("valid") is not True:
        control["result_incomplete_reason"] = "official final evaluator rejected the artifact"
    return control


def execute(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().absolute()
    manifest_path = run_dir / "experiment.json"
    manifest = load_json(manifest_path)
    if manifest["status"] != "prepared":
        raise RuntimeError(f"run is not prepared: {manifest['status']}")
    if args.model != manifest["model"]:
        raise ValueError(f"model mismatch: prepared {manifest['model']}, got {args.model}")
    if args.api_base and not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required with --api-base")
    environment = os.environ.copy()
    bin_dir = Path(manifest["environment"]["runtime_bin"])
    environment["PATH"] = str(bin_dir) + os.pathsep + environment.get("PATH", "")
    manifest["status"] = "running"
    manifest["execution_started_at"] = utc_now()
    write_json(manifest_path, manifest)
    if manifest["method"] == "plain-codex":
        control = execute_plain(manifest, run_dir, args, environment)
    else:
        control = execute_goal_plus(manifest, run_dir, args, environment)

    expected_deadline_stop = (
        control.get("deadline_reached")
        and not control.get("hard_killed")
        and control.get("returncode") in {0, -signal.SIGTERM, 128 + signal.SIGTERM}
    )
    if (
        control.get("returncode", 0) != 0
        and not expected_deadline_stop
        and not control.get("result_incomplete_reason")
    ):
        control["result_incomplete_reason"] = (
            f"controlled process exited nonzero ({control['returncode']})"
        )
    manifest["status"] = (
        "incomplete" if control.get("result_incomplete_reason") else "finished"
    )
    manifest["provider_mode"] = (
        "openai_compatible" if args.api_base else "codex_native_auth"
    )
    manifest["api_base"] = args.api_base
    version = subprocess.run(
        [args.codex_bin, "--version"], capture_output=True, text=True, check=False
    )
    manifest["runner_version"] = (version.stdout or version.stderr).strip() or None
    manifest["execution"] = control
    write_json(manifest_path, manifest)
    print(json.dumps(control, indent=2))
    return 0 if manifest["status"] == "finished" else 2


def seed_smoke(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().absolute()
    manifest = load_json(run_dir / "experiment.json")
    results = []
    for workspace_text in manifest["workspaces"]:
        workspace = Path(workspace_text)
        results.append(
            {"workspace": str(workspace), "evaluation": evaluate(workspace, "public")}
        )
    payload = {"task_id": TASK_ID, "results": results}
    write_json(run_dir / "seed-smoke.json", payload)
    print(json.dumps(payload, indent=2))
    return 0 if all(item["evaluation"]["valid"] for item in results) else 2


def repair_closeout(args: argparse.Namespace) -> int:
    """Re-audit an interrupted or conservatively classified Goal Plus run."""
    run_dir = args.run_dir.expanduser().absolute()
    manifest_path = run_dir / "experiment.json"
    manifest = load_json(manifest_path)
    if manifest["method"] != "goal-plus-codex":
        raise ValueError("closeout is only valid for Goal Plus + Codex runs")
    workspace = Path(manifest["workspace"])
    control = dict(manifest.get("execution") or {})
    control["goal_plus_controller_closeout_repair"] = finalize_goal_plus_search(
        workspace
    )
    final = evaluate(workspace, "final")
    write_json(run_dir / "final-eval.json", final)
    shutil.copy2(workspace / ARTIFACT_NAME, run_dir / ARTIFACT_NAME)
    control["goal_plus"] = collect_goal_plus_state(workspace)
    budget = manifest["budget"]
    reason = goal_plus_incomplete_reason(
        control["goal_plus"],
        expected_concurrency=budget["concurrency"],
        minimum_worker_verified_candidates=1,
    )
    if not control["goal_plus_controller_closeout_repair"].get("completed"):
        reason = (
            "Goal Plus controller closeout failed: "
            + control["goal_plus_controller_closeout_repair"].get(
                "error", "unknown error"
            )
        )
    if final.get("valid") is not True:
        reason = "official final evaluator rejected the artifact"
    if control.get("hard_killed"):
        reason = "Goal Plus exceeded hard-kill grace"
    if reason:
        control["result_incomplete_reason"] = reason
        manifest["status"] = "incomplete"
    else:
        control.pop("result_incomplete_reason", None)
        manifest["status"] = "finished"
    control["evaluator_calls"] = {
        **evaluator_budget(workspace),
        "setup_claimed_before_t": control.get("evaluator_calls", {}).get(
            "setup_claimed_before_t", 0
        ),
    }
    manifest["execution"] = control
    manifest["closeout_repaired_at"] = utc_now()
    write_json(manifest_path, manifest)
    print(json.dumps(control["goal_plus_controller_closeout_repair"], indent=2))
    return 0 if manifest["status"] == "finished" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--method", choices=METHODS, required=True)
    prepare_parser.add_argument("--model", default=DEFAULT_MODEL)
    prepare_parser.add_argument("--wall-time-seconds", type=int, default=300)
    prepare_parser.add_argument("--concurrency", type=int, default=2)
    prepare_parser.add_argument("--soft-closeout-seconds", type=int, default=60)
    prepare_parser.add_argument("--hard-kill-grace-seconds", type=int, default=30)
    prepare_parser.add_argument("--worker-runtime-seconds", type=int, default=120)
    prepare_parser.add_argument("--run-dir", type=Path)
    prepare_parser.add_argument(
        "--environment-manifest", type=Path, default=DEFAULT_ENV_MANIFEST
    )
    prepare_parser.add_argument(
        "--checkout-root", type=Path, default=DEFAULT_CHECKOUT_ROOT
    )
    prepare_parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--run-dir", type=Path, required=True)
    run_parser.add_argument("--codex-bin", default="codex")
    run_parser.add_argument("--model", default=DEFAULT_MODEL)
    run_parser.add_argument("--api-base")

    smoke_parser = subparsers.add_parser("seed-smoke")
    smoke_parser.add_argument("--run-dir", type=Path, required=True)

    closeout_parser = subparsers.add_parser("closeout")
    closeout_parser.add_argument("--run-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "prepare":
        return prepare(args)
    if args.command == "seed-smoke":
        return seed_smoke(args)
    if args.command == "closeout":
        return repair_closeout(args)
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
