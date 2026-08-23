"""Durable one-trajectory cells around ZSoft's native SWE-agent launcher."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from bench_artifacts import sanitize_id, utc_now
from bench_runtime_paths import configure_temp_environment

from adapters.zsoft_detect import adapter as zsoft_adapter

from .config import (
    BENCHMARK_ROOT,
    PINNED_SWE_AGENT_COMMIT,
    UPSTREAM_RUNNER,
    campaign_dir,
    source_checkout,
    swe_agent_root,
    write_json,
)
from .environment import asset_inventory


TERMINAL_CELL_STATES = {"completed", "partial", "failed", "interrupted"}


def preserve_conflict(path: Path) -> Path | None:
    if not path.exists():
        return None
    for index in range(1, 10_000):
        suffix = "_bak" if index == 1 else f"_bak{index}"
        backup = path.with_name(path.name + suffix)
        if not backup.exists():
            path.rename(backup)
            return backup
    raise RuntimeError(f"cannot preserve conflicting path: {path}")


def prepare(campaign_id: str, profile: dict[str, Any], profile_path: Path) -> Path:
    inventory = asset_inventory(profile)
    if not inventory["ok"]:
        raise RuntimeError(
            "ZSoft SWE-agent assets are not ready; run the profiled check and setup first"
        )
    destination = campaign_dir(campaign_id)
    backup = preserve_conflict(destination)
    destination.mkdir(parents=True)
    campaign: dict[str, Any] = {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "benchmark": "zsoft-detect-swe-agent",
        "benchmark_family": "zsoft-detect",
        "profile": profile["id"],
        "profile_path": str(profile_path),
        "state": "preparing",
        "prepared_at": utc_now(),
        "methods": profile["methods"],
        "model": profile["model"],
        "reasoning_effort": profile["reasoning_effort"],
        "projects": profile["projects"],
        "seeds": profile["seeds"],
        "budget": {
            "wall_time_seconds": profile["wall_time_seconds"],
            "live_search_concurrency": 1,
            "cell_concurrency": 1,
            "attempts": len(profile["seeds"]),
            "max_calls": profile["max_calls"],
            "max_input_tokens": profile["max_input_tokens"],
        },
        "protocol": {
            "native_runner": "swe-agent",
            "swe_agent_commit": PINNED_SWE_AGENT_COMMIT,
            "release": profile["release"],
            "track": profile["track"],
            "metric_name": "f1",
            "direction": "maximize",
            "sandbox": "bubblewrap",
            "usage_source": "upstream_openai_compatible_usage",
            "reasoning_effort_control": "not_exposed_by_upstream_swe_agent_runner",
        },
        "source": {
            "benchmark_root": str(BENCHMARK_ROOT),
            "upstream_runner": str(UPSTREAM_RUNNER),
            "swe_agent_root": str(swe_agent_root()),
        },
        "preserved_conflict": str(backup) if backup else None,
        "secret_policy": (
            "OPENAI_COMPAT_* values are inherited only by the native launcher "
            "and are never serialized"
        ),
        "cells": [],
    }
    campaign_path = destination / "campaign.json"
    write_json(campaign_path, campaign)
    try:
        for project in profile["projects"]:
            contract = zsoft_adapter.bench_contract(project, BENCHMARK_ROOT)
            for repeat_index, seed in enumerate(profile["seeds"], start=1):
                cell_id = sanitize_id(f"{project}-zsoft-swe-agent-seed-{seed}")
                cell_dir = destination / "cells" / cell_id
                cell_dir.mkdir(parents=True)
                contract_path = cell_dir / "bench-contract.json"
                write_json(contract_path, contract)
                cell = {
                    "cell_id": cell_id,
                    "task_id": f"{project}-detect",
                    "project": project,
                    "method": "zsoft-swe-agent",
                    "seed": seed,
                    "repeat_index": repeat_index,
                    "cell_dir": str(cell_dir),
                    "run_dir": str(cell_dir / "native-run"),
                    "source_checkout": str(source_checkout(project)),
                    "source_revision": zsoft_adapter.project_commit(project),
                    "bench_contract": str(contract_path),
                    "state": "prepared",
                    "error": None,
                }
                campaign["cells"].append(cell)
                write_json(campaign_path, campaign)
    except Exception as error:
        campaign["state"] = "partial"
        campaign["preparation_error"] = f"{type(error).__name__}: {error}"
        campaign["preparation_finished_at"] = utc_now()
        write_json(campaign_path, campaign)
        raise
    campaign["state"] = "prepared"
    campaign["preparation_finished_at"] = utc_now()
    write_json(campaign_path, campaign)
    return destination


def build_launch_command(campaign: dict[str, Any], cell: dict[str, Any]) -> list[str]:
    budget = campaign["budget"]
    return [
        sys.executable,
        str(UPSTREAM_RUNNER),
        "swe-agent",
        "--source",
        cell["source_checkout"],
        "--bench-contract",
        cell["bench_contract"],
        "--run-dir",
        cell["run_dir"],
        "--model",
        campaign["model"],
        "--timeout-seconds",
        str(budget["wall_time_seconds"]),
        "--swe-agent-root",
        str(swe_agent_root()),
        "--expected-swe-agent-commit",
        PINNED_SWE_AGENT_COMMIT,
        "--max-calls",
        str(budget["max_calls"]),
        "--max-input-tokens",
        str(budget["max_input_tokens"]),
    ]


def score_submission(
    submission: Path, *, project: str, commit: str, release: str, track: str
) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(BENCHMARK_ROOT / "scripts" / "score_submission.py"),
            str(submission),
            "--project",
            project,
            "--commit",
            commit,
            "--release",
            release,
            "--track",
            track,
        ],
        cwd=BENCHMARK_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=configure_temp_environment(dict(os.environ)),
    )
    payload = None
    error = completed.stderr.strip() or None
    if completed.returncode == 0:
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as decode_error:
            error = f"native scorer returned invalid JSON: {decode_error}"
    return {
        "attempted": True,
        "returncode": completed.returncode,
        "payload": payload,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "error": error,
    }


def _controller(destination: Path, *, active: bool, current_cell: str | None = None) -> None:
    write_json(
        destination / "controller.json",
        {
            "pid": os.getpid(),
            "active": active,
            "current_cell": current_cell,
            "updated_at": utc_now(),
        },
    )


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def completion_reasons(
    campaign: dict[str, Any],
    cell: dict[str, Any],
    *,
    launcher_returncode: int,
    metrics: dict[str, Any] | None,
    score: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if launcher_returncode != 0:
        reasons.append(f"native launcher exited {launcher_returncode}")
    if not metrics or metrics.get("status") != "complete":
        reasons.append("run-metrics status is not complete")
    if metrics:
        bench = metrics.get("bench") if isinstance(metrics.get("bench"), dict) else {}
        tool = (
            metrics.get("runner_tool")
            if isinstance(metrics.get("runner_tool"), dict)
            else {}
        )
        sandbox = (
            metrics.get("sandbox") if isinstance(metrics.get("sandbox"), dict) else {}
        )
        if metrics.get("runner") != "swe-agent":
            reasons.append("run-metrics identifies a different native runner")
        if metrics.get("model") != campaign["model"]:
            reasons.append("run-metrics model does not match the campaign")
        if bench.get("project_id") != cell["project"] or bench.get("commit") != cell[
            "source_revision"
        ]:
            reasons.append("run-metrics benchmark revision does not match the cell")
        if tool.get("git_commit") != PINNED_SWE_AGENT_COMMIT:
            reasons.append("run-metrics SWE-agent commit does not match the pin")
        if sandbox.get("engine") != "bubblewrap":
            reasons.append("run-metrics does not prove the Bubblewrap sandbox")
    tokens = metrics.get("tokens") if isinstance(metrics, dict) else {}
    if not isinstance(tokens, dict) or not (
        tokens.get("measurement_complete") and tokens.get("exact")
    ):
        reasons.append("provider token usage is incomplete")
    score_payload = score.get("payload")
    if score.get("returncode") != 0 or not isinstance(score_payload, dict):
        reasons.append(score.get("error") or "official scorer did not return a score")
    elif (
        score_payload.get("project_id") != cell["project"]
        or score_payload.get("commit") != cell["source_revision"]
        or not isinstance(score_payload.get("f1"), (int, float))
        or isinstance(score_payload.get("f1"), bool)
    ):
        reasons.append("official scorer identity or F1 payload does not match the cell")
    return reasons


def execute_campaign(destination: Path) -> int:
    campaign_path = destination / "campaign.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    if campaign["state"] != "prepared":
        raise RuntimeError(f"campaign is not prepared: {campaign['state']}")
    campaign["state"] = "running"
    campaign["execution_started_at"] = utc_now()
    write_json(campaign_path, campaign)
    _controller(destination, active=True)
    interrupted = False
    try:
        for cell in campaign["cells"]:
            if cell["state"] in TERMINAL_CELL_STATES:
                continue
            cell_dir = Path(cell["cell_dir"])
            run_dir = Path(cell["run_dir"])
            preserved = preserve_conflict(run_dir)
            cell["preserved_run_conflict"] = str(preserved) if preserved else None
            cell["state"] = "running"
            cell["started_at"] = utc_now()
            cell["launcher_command"] = build_launch_command(campaign, cell)
            _controller(destination, active=True, current_cell=cell["cell_id"])
            write_json(campaign_path, campaign)
            try:
                with (
                    (cell_dir / "launcher.stdout.log").open("w", encoding="utf-8") as stdout,
                    (cell_dir / "launcher.stderr.log").open("w", encoding="utf-8") as stderr,
                ):
                    completed = subprocess.run(
                        cell["launcher_command"],
                        cwd=BENCHMARK_ROOT,
                        stdout=stdout,
                        stderr=stderr,
                        check=False,
                        env=configure_temp_environment(dict(os.environ)),
                    )
                cell["launcher_returncode"] = completed.returncode
                metrics = _load_json(run_dir / "run-metrics.json")
                cell["run_metrics"] = metrics
                submission = run_dir / "submission"
                score = (
                    score_submission(
                        submission,
                        project=cell["project"],
                        commit=cell["source_revision"],
                        release=campaign["protocol"]["release"],
                        track=campaign["protocol"]["track"],
                    )
                    if submission.is_dir()
                    else {
                        "attempted": False,
                        "returncode": None,
                        "payload": None,
                        "stdout": "",
                        "stderr": "",
                        "error": "native submission directory is missing",
                    }
                )
                (cell_dir / "score.stdout.json").write_text(
                    score.pop("stdout"), encoding="utf-8"
                )
                (cell_dir / "score.stderr.log").write_text(
                    score.pop("stderr"), encoding="utf-8"
                )
                cell["score"] = score
                reasons = completion_reasons(
                    campaign,
                    cell,
                    launcher_returncode=completed.returncode,
                    metrics=metrics,
                    score=score,
                )
                cell["state"] = "completed" if not reasons else "partial"
                cell["error"] = "; ".join(reasons) or None
            except KeyboardInterrupt:
                interrupted = True
                cell["state"] = "interrupted"
                cell["error"] = "controller interrupted"
            except BaseException as error:
                cell["state"] = "failed"
                cell["error"] = f"{type(error).__name__}: {error}"
            cell["finished_at"] = utc_now()
            write_json(campaign_path, campaign)
            if interrupted:
                break
    finally:
        _controller(destination, active=False)
    if interrupted:
        campaign["state"] = "interrupted"
    elif all(cell["state"] == "completed" for cell in campaign["cells"]):
        campaign["state"] = "completed"
    elif any(cell["state"] in TERMINAL_CELL_STATES for cell in campaign["cells"]):
        campaign["state"] = "partial"
    else:
        campaign["state"] = "failed"
    campaign["execution_finished_at"] = utc_now()
    write_json(campaign_path, campaign)
    return 0 if campaign["state"] == "completed" else (130 if interrupted else 2)


def status_payload(destination: Path) -> dict[str, Any]:
    campaign = json.loads((destination / "campaign.json").read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for cell in campaign["cells"]:
        counts[cell["state"]] = counts.get(cell["state"], 0) + 1
    controller_path = destination / "controller.json"
    controller = _load_json(controller_path)
    return {
        "campaign_id": campaign["campaign_id"],
        "state": campaign["state"],
        "counts": counts,
        "controller": controller,
        "cells": campaign["cells"],
    }
