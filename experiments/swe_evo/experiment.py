#!/usr/bin/env python3
"""Provision, run, and officially score SWE-EVO campaigns."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import signal
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bench_runtime_paths import configure_temp_environment, ensure_temp_root  # noqa: E402
from experiments.swe_evo.dataset import (  # noqa: E402
    DatasetContractError,
    assert_worker_safe,
    load_records,
    normalize_image_ref,
    select_records,
    sha256_file,
    worker_record,
)
from experiments.swe_evo.evaluate import EvaluationError, evaluate_patch, freeze_patch  # noqa: E402


SWE_EVO_ROOT = ROOT / "third_party" / "swe-evo"
EDGE_ROOT = ROOT / "third_party" / "edgebench"
GOAL_PLUS_ROOT = ROOT / "third_party" / "goal-plus"
DATASET_PATH = SWE_EVO_ROOT / "hf_out" / "hf_dataset" / "test" / "data-00000-of-00001.arrow"
PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
RUNS_ROOT = ROOT / "runs" / "swe-evo"
UPSTREAM_MANIFEST = ROOT / "environment" / "upstreams.json"
VENV = ROOT / ".bench-env" / "venv"
VENV_BIN = VENV / ("Scripts" if sys.platform == "win32" else "bin")
VENV_PYTHON = VENV_BIN / ("python.exe" if sys.platform == "win32" else "python")
SFORGE = VENV_BIN / ("sforge.exe" if sys.platform == "win32" else "sforge")
METHODS = {"plain-codex", "goal-plus-codex"}
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
FULL_SHA = re.compile(r"[0-9a-f]{40}")


def _load_edge_controller() -> Any:
    path = ROOT / "experiments" / "edgebench" / "experiment.py"
    spec = importlib.util.spec_from_file_location("swe_evo_edge_lifecycle", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load shared SForge lifecycle: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EDGE = _load_edge_controller()
_EDGE_CELL_ENVIRONMENT = EDGE.cell_environment


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def campaign_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Any, *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if private:
        temporary.chmod(0o600)
    temporary.replace(path)


def git_value(path: Path, *args: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def git_state(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "branch": git_value(path, "branch", "--show-current"),
        "commit": git_value(path, "rev-parse", "HEAD"),
        "dirty": bool(git_value(path, "status", "--porcelain")) if path.is_dir() else None,
    }


def sanitize_id(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    if not clean:
        raise ValueError("id must contain a letter or digit")
    return clean


def load_profile(value: str | Path) -> tuple[Path, dict[str, Any]]:
    candidate = Path(value)
    if not candidate.suffix:
        candidate = PROFILE_DIR / f"{candidate.name}.json"
    elif not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()
    profile = read_json(candidate)
    if profile.get("schema_version") != 1 or profile.get("benchmark_id") != "swe-evo":
        raise ValueError(f"invalid SWE-EVO profile: {candidate}")
    if profile.get("id") != candidate.stem:
        raise ValueError("SWE-EVO profile id must match its filename")
    if FULL_SHA.fullmatch(str(profile.get("upstream_commit") or "")) is None:
        raise ValueError("SWE-EVO profile must pin a full upstream commit")
    dataset_sha = str(profile.get("dataset_sha256") or "")
    if re.fullmatch(r"[0-9a-f]{64}", dataset_sha) is None:
        raise ValueError("SWE-EVO profile must pin the Arrow SHA256")
    task_ids = profile.get("task_ids")
    if task_ids != "all" and (
        not isinstance(task_ids, list)
        or not task_ids
        or any(not isinstance(item, str) or not item for item in task_ids)
        or len(task_ids) != len(set(task_ids))
    ):
        raise ValueError("SWE-EVO task_ids must be a unique non-empty list or 'all'")
    methods = profile.get("methods")
    if not isinstance(methods, list) or not methods or set(methods) - METHODS:
        raise ValueError(f"SWE-EVO methods must use {sorted(METHODS)}")
    for key in (
        "wall_time_seconds",
        "concurrency",
        "cell_concurrency",
        "worker_runtime_seconds",
        "eval_interval_seconds",
        "official_evaluator_timeout_seconds",
        "image_provision_concurrency",
    ):
        if not isinstance(profile.get(key), int) or isinstance(profile[key], bool) or profile[key] < 1:
            raise ValueError(f"SWE-EVO profile {key} must be positive")
    if profile["worker_runtime_seconds"] > profile["wall_time_seconds"]:
        raise ValueError("worker_runtime_seconds must fit inside T")
    image_digests = profile.get("source_image_digests", {})
    if not isinstance(image_digests, dict) or any(
        not isinstance(task_id, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(digest)) is None
        for task_id, digest in image_digests.items()
    ):
        raise ValueError("SWE-EVO source_image_digests must map task ids to sha256 digests")
    return candidate, profile


def selected_records(profile: dict[str, Any]) -> list[dict[str, Any]]:
    records = load_records(DATASET_PATH)
    task_ids = None if profile["task_ids"] == "all" else profile["task_ids"]
    return select_records(records, task_ids)


def _hash_json(payload: Any) -> str:
    # Match SForge's TaskSpec hash byte-for-byte so preflight image names are exact.
    encoded = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def image_contract(record: dict[str, Any]) -> dict[str, Any]:
    task_id = str(record["instance_id"])
    base_key = "task-" + hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12]
    base_spec = {
        "official_image": normalize_image_ref(str(record["image"])),
        "extra_packages": ["git", "curl", "jq", "ca-certificates"],
        "post_install_directive": "RUN test -d /testbed/.git\nENTRYPOINT []\n",
    }
    base_hash = _hash_json({"key": base_key, "spec": base_spec})
    reset = (
        "cd /testbed && git config --global --add safe.directory /testbed "
        f"&& git reset --hard {record['base_commit']} && git clean -fdx"
    )
    work_setup = [reset]
    judge_setup = [reset]
    work_hash = _hash_json(
        {
            "base_hash": base_hash,
            "platform": "linux/amd64",
            "cwd": "/testbed",
            "setup_cmds": work_setup,
        }
    )
    judge_hash = _hash_json(
        {
            "base_hash": base_hash,
            "platform": "linux/amd64",
            "cwd": "/testbed",
            "setup_cmds": judge_setup,
        }
    )
    return {
        "base_key": base_key,
        "base_spec": base_spec,
        "base_image": f"swe-evo.base.{base_key}:{base_hash[:12]}",
        "work_setup": work_setup,
        "judge_setup": judge_setup,
        "work_tag": work_hash[:12],
        "judge_tag": judge_hash[:12],
        "work_image": f"swe-evo.work.{task_id}:{work_hash[:12]}",
        "judge_image": f"swe-evo.judge.{task_id}:{judge_hash[:12]}",
    }


def _process_eval_command() -> str:
    script = (
        "import json,subprocess; "
        "p=subprocess.run(['git','diff','--check'],capture_output=True,text=True); "
        "n=subprocess.run(['git','diff','--name-only','HEAD'],capture_output=True,text=True); "
        "changed=[x for x in n.stdout.splitlines() if x]; valid=p.returncode==0 and bool(changed); "
        "r={'valid':valid,'score':1.0 if valid else 0.0,'pass_rate':1.0 if valid else 0.0,"
        "'total_tests':1,'passed':1 if valid else 0,'failed':0 if valid else 1,'errors':0,"
        "'summary':'process-only diff integrity; not the official SWE-EVO score',"
        "'details':[{'name':'git_diff_check','status':'PASSED' if valid else 'FAILED',"
        "'score':1.0 if valid else 0.0,'message':p.stderr or p.stdout or ('changed_files=%d'%len(changed))}],"
        "'metrics':{'changed_files':len(changed),'official':False}}; "
        "print('>>>>> Start Structured Result'); print(json.dumps(r)); print('>>>>> End Structured Result')"
    )
    return "cd /testbed && python -c " + json.dumps(script)


def task_payload(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    safe = worker_record(record)
    contract = image_contract(record)
    prompt = (
        f"Resolve SWE-EVO instance {safe['instance_id']} in repository {safe['repo']} at "
        f"base commit {safe['base_commit']}. Work only in /testbed. Preserve existing behavior "
        "outside the requested change and leave the repository with a clean, reviewable patch.\n\n"
        + str(safe["problem_statement"])
    )
    task = {
        "task_id": safe["instance_id"],
        "name": f"SWE-EVO {safe['instance_id']}",
        "category": "Software Engineering",
        "base_image": contract["base_key"],
        "platform": "linux/amd64",
        "internet": False,
        "cwd": "/testbed",
        "submit_paths": ["."],
        "submit_exclude": [
            ".git",
            ".codex",
            ".goal-plus-verifiers",
            ".tmp",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "__pycache__",
            ".DS_Store",
            "results.tsv",
        ],
        "work": {
            "specs_dir": "/testbed",
            "agent_query": prompt,
            "setup_cmds": contract["work_setup"],
            "image_tag": contract["work_tag"],
        },
        "judge": {
            "eval_cmd": _process_eval_command(),
            "eval_timeout": 120,
            "parser": "structured_json",
            "score_direction": "maximize",
            "selection": "valid_then_score",
            "setup_cmds": contract["judge_setup"],
            "image_tag": contract["judge_tag"],
        },
    }
    assert_worker_safe(task)
    return task, contract


def materialize_tasks(records: list[dict[str, Any]], destination: Path) -> list[dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    base_images: dict[str, Any] = {}
    contracts = []
    for record in records:
        task, contract = task_payload(record)
        base_images[contract["base_key"]] = contract["base_spec"]
        write_json(destination / f"{record['instance_id']}.json", task)
        contracts.append({"task_id": record["instance_id"], **contract})
    (destination / "BENCHMARK.yaml").write_text(
        yaml.safe_dump({"name": "swe-evo", "base_images": base_images}, sort_keys=True),
        encoding="utf-8",
    )
    return contracts


def docker_inspect(image: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
        check=False,
    )
    details: dict[str, Any] = {"image": image, "available": completed.returncode == 0}
    if completed.returncode == 0:
        try:
            payload = json.loads(completed.stdout)[0]
            details.update(
                {
                    "id": payload.get("Id"),
                    "repo_digests": payload.get("RepoDigests") or [],
                    "architecture": payload.get("Architecture"),
                    "os": payload.get("Os"),
                }
            )
        except (IndexError, json.JSONDecodeError):
            details["available"] = False
    else:
        details["error"] = completed.stderr.strip()[-600:] or None
    return details


def image_has_digest(details: dict[str, Any], expected: str) -> bool:
    return any(
        str(repo_digest).rpartition("@")[2] == expected
        for repo_digest in details.get("repo_digests") or []
    )


def mirror_image_ref(source: str, mirror: str) -> str:
    normalized = normalize_image_ref(source)
    _, separator, repository = normalized.partition("/")
    if not separator or not repository:
        raise ValueError(f"source image has no registry component: {source}")
    mirror = mirror.strip().rstrip("/")
    if not mirror or "://" in mirror:
        raise ValueError("SWE_EVO_IMAGE_MIRROR must be a registry host without a URL scheme")
    return f"{mirror}/{repository}"


def manifest_digest(image: str) -> str:
    try:
        completed = subprocess.run(
            ["skopeo", "inspect", "--format", "{{.Digest}}", f"docker://{image}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"cannot inspect image manifest for {image}: {error}") from error
    digest = completed.stdout.strip()
    if completed.returncode != 0 or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
        detail = completed.stderr.strip()[-600:] or digest or "unknown skopeo error"
        raise RuntimeError(f"cannot inspect image manifest for {image}: {detail}")
    return digest


def pull_source_image(
    record: dict[str, Any], expected_digest: str | None
) -> dict[str, Any]:
    source = normalize_image_ref(str(record["image"]))
    inspected = docker_inspect(source)
    if inspected["available"] and (
        expected_digest is None or image_has_digest(inspected, expected_digest)
    ):
        return inspected

    pull_ref = source
    mirror = os.environ.get("SWE_EVO_IMAGE_MIRROR")
    if mirror:
        pull_ref = mirror_image_ref(source, mirror)
        mirror_digest = manifest_digest(pull_ref)
        authoritative_digest = expected_digest or manifest_digest(source)
        if mirror_digest != authoritative_digest:
            raise RuntimeError(
                f"mirror digest mismatch for {source}: expected {authoritative_digest}, "
                f"found {mirror_digest}"
            )
    elif expected_digest:
        repository = source.rpartition("/")[0] + "/" + source.rpartition("/")[2].split(":", 1)[0]
        pull_ref = f"{repository}@{expected_digest}"

    subprocess.run(["docker", "pull", pull_ref], check=True)
    if pull_ref != source:
        subprocess.run(["docker", "tag", pull_ref, source], check=True)
    inspected = docker_inspect(source)
    if not inspected["available"]:
        raise RuntimeError(f"source image is unavailable after pull: {source}")
    if expected_digest and not image_has_digest(inspected, expected_digest):
        raise RuntimeError(f"source image digest does not match {expected_digest}: {source}")
    return inspected


def provision(profile: dict[str, Any]) -> int:
    records = selected_records(profile)
    tasks_dir = ensure_temp_root("swe-evo") / "provision" / str(profile["id"])
    materialize_tasks(records, tasks_dir)
    if not SFORGE.is_file():
        raise FileNotFoundError("managed SForge entrypoint is missing; bootstrap edgebench first")
    expected = profile.get("source_image_digests") or {}
    with ThreadPoolExecutor(max_workers=int(profile["image_provision_concurrency"])) as pool:
        source_images = list(
            pool.map(
                lambda record: pull_source_image(record, expected.get(str(record["instance_id"]))),
                records,
            )
        )
    for record in records:
        subprocess.run(
            [
                str(SFORGE),
                "--tasks-dir",
                str(tasks_dir),
                "--silent",
                "build",
                "--task",
                str(record["instance_id"]),
            ],
            cwd=ROOT,
            env=dict(configure_temp_environment(dict(os.environ))),
            check=True,
        )
    print(
        json.dumps(
            {"profile": profile["id"], "source_images": source_images},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def doctor_payload(profile: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, **details: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), **details})

    add("runtime:repository-local-temp", ensure_temp_root().is_dir(), path=".tmp")
    actual_sha = sha256_file(DATASET_PATH) if DATASET_PATH.is_file() else None
    add(
        "dataset:arrow-sha256",
        actual_sha == profile["dataset_sha256"],
        expected=profile["dataset_sha256"],
        actual=actual_sha,
    )
    records: list[dict[str, Any]] = []
    try:
        records = selected_records(profile)
        add("dataset:selected-records", True, count=len(records))
    except (DatasetContractError, OSError) as error:
        add("dataset:selected-records", False, error=str(error))
    for label, path, expected_branch, expected_commit in (
        ("swe-evo", SWE_EVO_ROOT, "main", profile["upstream_commit"]),
        ("edgebench", EDGE_ROOT, "mac", None),
        ("goal-plus", GOAL_PLUS_ROOT, "main", None),
    ):
        state = git_state(path)
        passed = state["branch"] == expected_branch and state["dirty"] is False
        if expected_commit:
            passed = passed and state["commit"] == expected_commit
        add(f"checkout:{label}", passed, expected_branch=expected_branch, expected_commit=expected_commit, **state)
    add("entrypoint:sforge", SFORGE.is_file(), path=str(SFORGE))
    add("entrypoint:managed-python", VENV_PYTHON.is_file(), path=str(VENV_PYTHON))
    codex_cache = Path.home() / ".cache" / "sforge" / "codex" / "codex-0.144.1-linux-x64.tgz"
    add(
        "runtime:codex-host-cache",
        codex_cache.is_file() and codex_cache.stat().st_size > 0,
        path=str(codex_cache),
    )
    docker_info = subprocess.run(
        ["docker", "info", "--format", "{{json .}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    architecture = None
    if docker_info.returncode == 0:
        try:
            architecture = json.loads(docker_info.stdout).get("Architecture")
        except json.JSONDecodeError:
            pass
    add("docker:linux-amd64", architecture in {"x86_64", "amd64"}, actual=architecture)
    judge_port = int(profile["judge_port"])
    add(
        "runtime:judge-port",
        port_available(judge_port),
        port=judge_port,
        requirement="free before campaign launch",
    )
    api_config = EDGE.resolve_agent_api_config(protocol="openai")
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    add(
        "auth:agent",
        bool(api_config.get("api_key")) or (codex_home / "auth.json").is_file(),
        mode="api_key" if api_config.get("api_key") else "oauth",
        api_key_source=api_config.get("api_key_source"),
        api_base_url_source=api_config.get("api_base_url_source"),
    )
    generated = ensure_temp_root("swe-evo") / "doctor" / str(profile["id"])
    if records:
        contracts = materialize_tasks(records, generated)
        expected = profile.get("source_image_digests") or {}
        for record, contract in zip(records, contracts):
            source = docker_inspect(normalize_image_ref(str(record["image"])))
            add(f"image:source:{record['instance_id']}", source["available"], **source)
            expected_digest = expected.get(str(record["instance_id"]))
            if expected_digest:
                add(
                    f"image:digest:{record['instance_id']}",
                    image_has_digest(source, expected_digest),
                    expected=expected_digest,
                    repo_digests=source.get("repo_digests") or [],
                )
            for role in ("work", "judge"):
                inspected = docker_inspect(str(contract[f"{role}_image"]))
                add(f"image:{role}:{record['instance_id']}", inspected["available"], **inspected)
        try:
            for task_path in generated.glob("*.json"):
                assert_worker_safe(read_json(task_path))
            add("integrity:worker-payload", True, task_count=len(records))
        except DatasetContractError as error:
            add("integrity:worker-payload", False, error=str(error))
    return {
        "schema_version": 1,
        "benchmark_id": "swe-evo",
        "profile": profile["id"],
        "checked_at": utc_now(),
        "ok": all(check["passed"] for check in checks),
        "checks": checks,
    }


def doctor(profile: dict[str, Any], output: Path | None = None) -> int:
    payload = doctor_payload(profile)
    if output:
        write_json(output, payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["ok"] else 1


def _resolved_value(args: argparse.Namespace, profile: dict[str, Any], name: str) -> Any:
    value = getattr(args, name, None)
    return profile[name] if value is None else value


def prepare(args: argparse.Namespace, profile: dict[str, Any]) -> Path:
    records = selected_records(profile)
    methods = args.method or list(profile["methods"])
    unknown = set(methods) - METHODS
    if unknown:
        raise ValueError("unknown SWE-EVO methods: " + ", ".join(sorted(unknown)))
    wall_time = int(_resolved_value(args, profile, "wall_time_seconds"))
    concurrency = int(_resolved_value(args, profile, "concurrency"))
    cell_concurrency = int(_resolved_value(args, profile, "cell_concurrency"))
    model = str(_resolved_value(args, profile, "model"))
    reasoning = str(_resolved_value(args, profile, "reasoning_effort"))
    if min(wall_time, concurrency, cell_concurrency) < 1:
        raise ValueError("T, K, and C must be positive")
    campaign_id = sanitize_id(args.campaign_id or f"{profile['id']}-{campaign_stamp()}")
    destination = RUNS_ROOT / campaign_id
    if destination.exists():
        raise FileExistsError(f"campaign already exists: {destination}")
    destination.mkdir(parents=True)
    contracts = materialize_tasks(records, destination / "sforge_tasks")
    evaluator_records = destination / "evaluator" / "instances.json"
    write_json(evaluator_records, records, private=True)
    source_locks = []
    for record, contract in zip(records, contracts):
        source_locks.append(
            {
                "instance_id": record["instance_id"],
                "expected_source_digest": (profile.get("source_image_digests") or {}).get(
                    str(record["instance_id"])
                ),
                "source": docker_inspect(normalize_image_ref(str(record["image"]))),
                "work": docker_inspect(str(contract["work_image"])),
                "judge": docker_inspect(str(contract["judge_image"])),
            }
        )
    write_json(destination / "images.lock.json", {"schema_version": 1, "images": source_locks})
    cells = []
    for record in records:
        prompt = str(task_payload(record)[0]["work"]["agent_query"])
        for method in methods:
            inner = method == "goal-plus-codex"
            outer_replicas = 1 if inner else concurrency
            cell_id = sanitize_id(f"{record['instance_id']}--{method}")
            cell = {
                "schema_version": 1,
                "cell_id": cell_id,
                "task_id": record["instance_id"],
                "method": method,
                "sforge_agent": "codex-goal-plus" if inner else "codex",
                "api_protocol": "openai",
                "backend": "docker",
                "model": model,
                "reasoning_effort": reasoning,
                "wall_time_seconds": wall_time,
                "live_search_concurrency": concurrency,
                "outer_replicas": outer_replicas,
                "outer_replica_concurrency": concurrency if outer_replicas > 1 else 1,
                "inner_search_concurrency": concurrency if inner else 0,
                "worker_runtime_seconds": min(wall_time, int(profile["worker_runtime_seconds"])),
                "eval_interval_seconds": int(profile["eval_interval_seconds"]),
                "judge_concurrency": 1,
                "judge_port": int(profile["judge_port"]),
                "work_cpu_limit": int(profile["work_cpu_limit"]),
                "work_mem_limit": str(profile["work_mem_limit"]),
                "judge_cpu_limit": int(profile["judge_cpu_limit"]),
                "judge_mem_limit": str(profile["judge_mem_limit"]),
                "submission_cooldown": 60,
                "max_submissions": None,
                "auto_eval_enabled": True,
                "auto_resume_enabled": True,
                "stop_hook_enabled": True,
                "internet": False,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "metric_direction": "maximize",
                "process_metric_only": True,
                "official_metric": "resolved/fix_rate",
                "sforge_run_id": sanitize_id(f"{campaign_id}-{record['instance_id']}-{method}"),
                "state": "prepared",
                "created_at": utc_now(),
            }
            cell_path = destination / "cells" / cell_id
            cell_path.mkdir(parents=True)
            write_json(cell_path / "cell.json", cell)
            cells.append(
                {
                    "cell_id": cell_id,
                    "task_id": record["instance_id"],
                    "method": method,
                    "state": "prepared",
                }
            )
    resolved_profile = {
        **profile,
        "task_ids": [record["instance_id"] for record in records],
        "methods": methods,
        "model": model,
        "reasoning_effort": reasoning,
        "wall_time_seconds": wall_time,
        "concurrency": concurrency,
        "cell_concurrency": cell_concurrency,
        "api_protocol": "openai",
    }
    write_json(destination / "profile.json", resolved_profile)
    write_json(
        destination / "dataset.lock.json",
        {
            "schema_version": 1,
            "upstream_commit": profile["upstream_commit"],
            "dataset_path": "third_party/swe-evo/hf_out/hf_dataset/test/data-00000-of-00001.arrow",
            "dataset_sha256": sha256_file(DATASET_PATH),
            "selected_task_ids": resolved_profile["task_ids"],
            "hidden_record_path": "evaluator/instances.json",
            "worker_visibility": "problem statement and public repository identity only",
        },
    )
    write_json(
        destination / "campaign.json",
        {
            "schema_version": 1,
            "benchmark_id": "swe-evo",
            "campaign_id": campaign_id,
            "profile": profile["id"],
            "state": "prepared",
            "created_at": utc_now(),
            "task_ids": resolved_profile["task_ids"],
            "methods": methods,
            "model": model,
            "reasoning_effort": reasoning,
            "wall_time_seconds": wall_time,
            "concurrency": concurrency,
            "cell_concurrency": cell_concurrency,
            "T_K_C_R": {"T": wall_time, "K": concurrency, "C": cell_concurrency, "R": 1},
            "swe_evo_commit": git_state(SWE_EVO_ROOT)["commit"],
            "edgebench_commit": git_state(EDGE_ROOT)["commit"],
            "goal_plus_commit": git_state(GOAL_PLUS_ROOT)["commit"],
            "official_evaluator": "SWE-EVO/SWE-bench/evaluate_instance.py semantics",
            "cells": cells,
        },
    )
    write_json(
        destination / "controller.json",
        {"schema_version": 1, "state": "prepared", "created_at": utc_now(), "pid": None, "pgid": None},
    )
    print(destination)
    return destination


def campaign_dir(value: str | Path) -> Path:
    direct = Path(value).expanduser()
    candidate = direct if direct.is_dir() else RUNS_ROOT / direct
    resolved = candidate.resolve()
    try:
        resolved.relative_to(RUNS_ROOT.resolve())
    except ValueError as error:
        raise ValueError(f"campaign must be under {RUNS_ROOT}") from error
    if not (resolved / "campaign.json").is_file():
        raise FileNotFoundError(f"campaign manifest is missing: {resolved}")
    return resolved


def task_images(task_id: str) -> tuple[str, str]:
    task = read_json(EDGE.TASKS_DIR / f"{task_id}.json")
    return (
        f"swe-evo.work.{task_id}:{task['work']['image_tag']}",
        f"swe-evo.judge.{task_id}:{task['judge']['image_tag']}",
    )


def cell_environment(cell: dict[str, Any], **kwargs: Any) -> dict[str, str]:
    env = _EDGE_CELL_ENVIRONMENT(cell, **kwargs)
    if cell["method"] == "goal-plus-codex":
        EDGE.merge_agent_extra_env(
            env,
            {"SFORGE_GOAL_PLUS_PARALLEL_NUM": str(cell["inner_search_concurrency"])},
        )
    return env


def sforge_judge_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/openapi.json", timeout=1.0
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return response.status == 200 and "/api/v1/register" in (payload.get("paths") or {})
    except (OSError, ValueError, urllib.error.URLError):
        return False


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def configure_shared_lifecycle(destination: Path) -> None:
    EDGE.TASKS_DIR = destination / "sforge_tasks"
    EDGE.RUNS_ROOT = RUNS_ROOT
    EDGE.EDGE_ROOT = EDGE_ROOT
    EDGE.GOAL_PLUS_ROOT = GOAL_PLUS_ROOT
    EDGE.task_images = task_images
    EDGE.cell_environment = cell_environment
    EDGE.judge_ready = sforge_judge_ready
    EDGE.finalize_campaign = finalize_campaign


def _trajectory_dirs(destination: Path, cell: dict[str, Any]) -> list[Path]:
    root = destination / "cells" / str(cell["cell_id"]) / "sforge" / "runs"
    return sorted(path.parent for path in root.glob(f"*/{cell['task_id']}/final_archive.tar.gz"))


def _record_index(destination: Path) -> dict[str, dict[str, Any]]:
    records = json.loads((destination / "evaluator" / "instances.json").read_text(encoding="utf-8"))
    return {str(record["instance_id"]): record for record in records}


def _goal_plus_provenance(trajectory: Path) -> dict[str, Any]:
    status_path = trajectory / "goal-plus-live-status.json"
    if not status_path.is_file():
        return {
            "valid": False,
            "reason": "goal-plus-live-status.json is missing",
            "status_path": str(status_path),
        }
    status = read_json(status_path)
    goal_statuses = status.get("goal_statuses") or []
    promoted = status.get("promoted_candidate_ids") or []
    valid = bool(promoted) and bool(goal_statuses) and all(
        item.get("status") == "complete" for item in goal_statuses
    )
    return {
        "valid": valid,
        "reason": None if valid else "Goal Plus has no completed promoted candidate",
        "status_path": str(status_path),
        "terminal_ready": bool(status.get("terminal_ready")),
        "actual_worker_launch_count": int(status.get("actual_worker_launch_count") or 0),
        "worker_verifier_runs": int(status.get("worker_verifier_runs") or 0),
        "candidate_ids": status.get("candidate_ids") or [],
        "selected_candidate_ids": status.get("selected_candidate_ids") or [],
        "promoted_candidate_ids": promoted,
        "goal_statuses": goal_statuses,
        "search_run_states": status.get("search_run_states") or {},
    }


def _evaluate_trajectory(
    destination: Path,
    profile: dict[str, Any],
    cell: dict[str, Any],
    trajectory: Path,
    index: int,
    record: dict[str, Any],
) -> dict[str, Any]:
    attempt = destination / "evaluator" / "attempts" / str(cell["cell_id"]) / f"trajectory-{index}"
    result_path = attempt / "result.json"
    if result_path.is_file():
        result = read_json(result_path)
        if cell["method"] == "goal-plus-codex":
            provenance = _goal_plus_provenance(trajectory)
            result["goal_plus_provenance"] = provenance
            result["method_valid"] = provenance["valid"]
            result["method_invalid_reason"] = provenance["reason"]
            write_json(result_path, result)
        return result
    attempt.mkdir(parents=True, exist_ok=True)
    write_json(
        attempt / "attempt.json",
        {
            "schema_version": 1,
            "state": "started",
            "started_at": utc_now(),
            "archive": str(trajectory / "final_archive.tar.gz"),
            "official_harness": "third_party/swe-evo/SWE-bench",
        },
    )
    result: dict[str, Any] = {
        "trajectory": index,
        "run_id": trajectory.parent.name,
        "archive": str(trajectory / "final_archive.tar.gz"),
        "official": False,
    }
    try:
        expected_digest = (profile.get("source_image_digests") or {}).get(
            str(record["instance_id"])
        )
        freeze = freeze_patch(
            record,
            trajectory / "final_archive.tar.gz",
            attempt / "model.patch",
            expected_image_digest=expected_digest,
        )
        result["freeze"] = freeze
        if not freeze["integrity_ok"]:
            raise EvaluationError(
                "candidate patch overlaps hidden test-patch paths: "
                + ", ".join(freeze["hidden_test_path_overlap"])
            )
        patch = (attempt / "model.patch").read_text(encoding="utf-8")
        official = evaluate_patch(
            record,
            patch,
            swe_evo_root=SWE_EVO_ROOT,
            evidence_dir=attempt / "official",
            run_id=sanitize_id(f"{destination.name}-{cell['cell_id']}-{index}"),
            timeout_seconds=int(profile["official_evaluator_timeout_seconds"]),
            expected_image_digest=expected_digest,
        )
        result.update(official)
        if cell["method"] == "goal-plus-codex":
            provenance = _goal_plus_provenance(trajectory)
            result["goal_plus_provenance"] = provenance
            result["method_valid"] = provenance["valid"]
            result["method_invalid_reason"] = provenance["reason"]
        else:
            result["method_valid"] = True
        result["state"] = "completed"
    except Exception as error:
        result.update({"state": "failed", "error": str(error)})
    result["finished_at"] = utc_now()
    write_json(result_path, result)
    return result


def _comparison_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# SWE-EVO campaign: {payload['campaign_id']}",
        "",
        "The process judge is diagnostic only. All metrics below come from SWE-EVO's vendored SWE-bench harness.",
        "",
        "| Task | Method | Official attempts | Valid trajectories | Resolved rate | Mean fix rate | Patch apply rate | Selection |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for cell in payload["cells"]:
        lines.append(
            "| {task_id} | {method} | {official_attempts} | {official_trajectories} | {resolved_rate:.3f} | "
            "{mean_fix_rate:.3f} | {patch_apply_rate:.3f} | {selection_policy} |".format(**cell)
        )
    lines.extend(
        [
            "",
            "Plain Codex K trajectories are independent observations. `oracle_best_fix_rate` is reported only as an explicitly labeled post-hoc diagnostic and is not equivalent to Goal Plus selection.",
            "",
        ]
    )
    return "\n".join(lines)


def finalize_campaign(destination: Path, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
    campaign = read_json(destination / "campaign.json")
    profile = read_json(destination / "profile.json")
    records = _record_index(destination)
    summaries = []
    for cell_summary in campaign["cells"]:
        cell = read_json(destination / "cells" / cell_summary["cell_id"] / "cell.json")
        observations = [
            _evaluate_trajectory(destination, profile, cell, path, index, records[str(cell["task_id"])])
            for index, path in enumerate(_trajectory_dirs(destination, cell), start=1)
        ]
        official_attempts = [
            item
            for item in observations
            if item.get("official") and item.get("state") == "completed"
        ]
        official = [item for item in official_attempts if item.get("method_valid", True)]
        count = len(official)
        resolved_rate = sum(bool(item.get("resolved")) for item in official) / count if count else 0.0
        patch_apply_rate = sum(bool(item.get("patch_applied")) for item in official) / count if count else 0.0
        mean_fix_rate = sum(float(item.get("fix_rate") or 0.0) for item in official) / count if count else 0.0
        oracle = max((float(item.get("fix_rate") or 0.0) for item in official), default=0.0)
        invalid_reasons = sorted(
            {
                str(item.get("method_invalid_reason"))
                for item in official_attempts
                if not item.get("method_valid", True) and item.get("method_invalid_reason")
            }
        )
        summaries.append(
            {
                "task_id": cell["task_id"],
                "cell_id": cell["cell_id"],
                "method": cell["method"],
                "model": cell["model"],
                "reasoning_effort": cell["reasoning_effort"],
                "wall_time_seconds": cell["wall_time_seconds"],
                "live_search_concurrency": cell["live_search_concurrency"],
                "outer_replicas": cell["outer_replicas"],
                "metric_direction": "maximize",
                "official_attempts": len(official_attempts),
                "official_trajectories": count,
                "resolved_rate": resolved_rate,
                "mean_fix_rate": mean_fix_rate,
                "patch_apply_rate": patch_apply_rate,
                "oracle_best_fix_rate": oracle if cell["method"] == "plain-codex" else None,
                "selection_policy": (
                    (
                        "Goal Plus selected promotion"
                        if count
                        else "Goal Plus invalid/incomplete; no promoted candidate"
                    )
                    if cell["method"] == "goal-plus-codex"
                    else "independent K; oracle diagnostic only"
                ),
                "invalid_reasons": invalid_reasons,
                "observations": observations,
            }
        )
    payload = {
        "schema_version": 1,
        "benchmark_id": "swe-evo",
        "campaign_id": campaign["campaign_id"],
        "state": "finalized",
        "wall_time_seconds": campaign["wall_time_seconds"],
        "live_search_concurrency": campaign["concurrency"],
        "cell_concurrency": campaign["cell_concurrency"],
        "dataset_revision": profile["upstream_commit"],
        "dataset_sha256": profile["dataset_sha256"],
        "official_evaluator": True,
        "process_judge_is_official": False,
        "cells": summaries,
        "finalized_at": utc_now(),
    }
    write_json(destination / "comparison.json", payload)
    (destination / "comparison.md").write_text(_comparison_markdown(payload), encoding="utf-8")
    return payload


def execute_campaign(destination: Path) -> int:
    configure_shared_lifecycle(destination)
    return int(EDGE.execute_campaign(destination))


def launch(destination: Path, *, detach: bool) -> int:
    configure_shared_lifecycle(destination)
    controller = read_json(destination / "controller.json")
    if EDGE.process_alive(controller.get("pid")):
        raise RuntimeError(f"campaign controller is already running: {controller['pid']}")
    if not detach:
        return execute_campaign(destination)
    command = [
        str(VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)),
        str(Path(__file__).resolve()),
        "_execute",
        "--campaign",
        str(destination),
    ]
    log = (destination / "controller.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=dict(configure_temp_environment(dict(os.environ))),
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    log.close()
    controller.update(
        {
            "state": "launching",
            "launched_at": utc_now(),
            "pid": process.pid,
            "pgid": process.pid,
            "command": command,
        }
    )
    write_json(destination / "controller.json", controller)
    print(json.dumps({"pid": process.pid, "campaign": str(destination)}))
    return 0


def verify_official(profile: dict[str, Any], task_id: str | None, output: Path | None) -> int:
    records = selected_records(profile)
    record = next((item for item in records if task_id is None or item["instance_id"] == task_id), None)
    if record is None:
        raise ValueError(f"task is not selected by profile: {task_id}")
    evidence = ensure_temp_root("swe-evo") / "official-smoke" / sanitize_id(str(record["instance_id"]))
    result = evaluate_patch(
        record,
        str(record.get("patch") or ""),
        swe_evo_root=SWE_EVO_ROOT,
        evidence_dir=evidence,
        run_id=sanitize_id(f"gold-{record['instance_id']}"),
        timeout_seconds=int(profile["official_evaluator_timeout_seconds"]),
        expected_image_digest=(profile.get("source_image_digests") or {}).get(
            str(record["instance_id"])
        ),
    )
    payload = {
        "schema_version": 1,
        "benchmark_id": "swe-evo",
        "kind": "official-gold-patch-smoke",
        "profile": profile["id"],
        "dataset_revision": profile["upstream_commit"],
        "dataset_sha256": profile["dataset_sha256"],
        "result": result,
        "checked_at": utc_now(),
    }
    if output:
        write_json(output, payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if result["patch_applied"] and result["resolved"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("provision", "doctor", "verify-official"):
        child = subparsers.add_parser(name)
        child.add_argument("--profile", default="ghcr-smoke-1")
        if name in {"doctor", "verify-official"}:
            child.add_argument("--output", type=Path)
        if name == "verify-official":
            child.add_argument("--task-id")
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--profile", default="ghcr-smoke-1")
    prepare_parser.add_argument("--campaign-id")
    prepare_parser.add_argument("--method", action="append", choices=sorted(METHODS))
    prepare_parser.add_argument("--model")
    prepare_parser.add_argument("--reasoning-effort")
    prepare_parser.add_argument("--wall-time-seconds", type=int)
    prepare_parser.add_argument("--concurrency", type=int)
    prepare_parser.add_argument("--cell-concurrency", type=int)
    for name in ("run", "status", "stop", "finalize", "_execute"):
        child = subparsers.add_parser(name)
        child.add_argument("--campaign", required=True)
        if name == "run":
            child.add_argument("--detach", action="store_true")
        elif name == "status":
            child.add_argument("--json", action="store_true")
        elif name == "stop":
            child.add_argument("--wait-seconds", type=int, default=10)
    return parser


def main() -> int:
    configure_temp_environment()
    args = build_parser().parse_args()
    if args.command in {"provision", "doctor", "prepare", "verify-official"}:
        _, profile = load_profile(args.profile)
        if args.command == "provision":
            return provision(profile)
        if args.command == "doctor":
            return doctor(profile, args.output)
        if args.command == "verify-official":
            return verify_official(profile, args.task_id, args.output)
        prepare(args, profile)
        return 0
    destination = campaign_dir(args.campaign)
    configure_shared_lifecycle(destination)
    if args.command == "run":
        return launch(destination, detach=args.detach)
    if args.command == "_execute":
        return execute_campaign(destination)
    if args.command == "status":
        return EDGE.print_status(destination, as_json=args.json)
    if args.command == "stop":
        return EDGE.stop_campaign(destination, wait_seconds=args.wait_seconds)
    if args.command == "finalize":
        print(json.dumps(finalize_campaign(destination), indent=2, ensure_ascii=False))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
