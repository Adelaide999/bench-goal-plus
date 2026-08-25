#!/usr/bin/env python3
"""Materialize and evaluate TorchBench CUDA eval model optimizations."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import textwrap
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from adapters.portable import (  # noqa: E402
    append_history,
    claim_evaluator_call,
    git_commit,
    init_git,
    utc_now,
    write_json,
)
from bench_runtime_paths import (  # noqa: E402
    configure_temp_environment,
    ensure_temp_root,
    temporary_directory,
)


CONTROLLER_PATH = Path(__file__).resolve()
WORKER_PATH = CONTROLLER_PATH.with_name("worker.py")
MODEL_CATALOG_PATH = CONTROLLER_PATH.with_name("models.json")
UPSTREAM_KEY = "torchbench"
BENCHMARK_NAME = "TorchBench model optimization"
PRIMARY_METRIC = "median_latency_ms"
DIRECTION = "minimize"
CODEX_SANDBOX = "danger-full-access"
GOAL_PLUS_MCP_ENV_VARS = (
    "BENCH_GOAL_PLUS_TORCHBENCH_PYTHON",
    "BENCH_GOAL_PLUS_TORCHBENCH_GPUS",
    "BENCH_GOAL_PLUS_TORCH_HOME",
)
VERIFIER_TIMEOUT_SECONDS = 600
OFFICIAL_BENCHMARK_COMPARABLE = False
INVALID_LATENCY_MS = 1.0e12
SAFE_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


class AdapterError(RuntimeError):
    pass


def load_catalog() -> dict[str, dict[str, Any]]:
    payload = json.loads(MODEL_CATALOG_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("models"), dict):
        raise AdapterError("invalid TorchBench model catalog")
    return payload["models"]


MODEL_CATALOG = load_catalog()
DEFAULT_MODEL = "alexnet"
ACTIVE_MODEL = DEFAULT_MODEL
TASK_ID = f"{DEFAULT_MODEL}-eval-cuda"
ARTIFACT_NAME = f"torchbenchmark/models/{DEFAULT_MODEL}"
CASE_SET_DESCRIPTION = f"TorchBench {DEFAULT_MODEL} eval on one CUDA device"


def list_task_ids() -> tuple[str, ...]:
    return tuple(MODEL_CATALOG)


def configure_task(task_id: str | None) -> None:
    model = task_id or DEFAULT_MODEL
    if SAFE_MODEL.fullmatch(model) is None or model not in MODEL_CATALOG:
        raise AdapterError(
            f"unsupported TorchBench model {model!r}; choose one of "
            + ", ".join(list_task_ids())
        )
    global ACTIVE_MODEL, TASK_ID, ARTIFACT_NAME, CASE_SET_DESCRIPTION
    ACTIVE_MODEL = model
    TASK_ID = f"{model}-eval-cuda"
    ARTIFACT_NAME = f"torchbenchmark/models/{model}"
    CASE_SET_DESCRIPTION = f"TorchBench {model} eval on one CUDA device"


def model_policy(model: str | None = None) -> dict[str, Any]:
    return MODEL_CATALOG[model or ACTIVE_MODEL]


def copy_tracked_checkout(source_root: Path, destination: Path) -> None:
    archived = subprocess.run(
        ["git", "-C", str(source_root), "archive", "--format=tar", "HEAD"],
        capture_output=True,
        check=True,
    )
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archived.stdout), mode="r:") as archive:
        archive.extractall(destination, filter="data")


def append_gitignore(workspace: Path) -> None:
    path = workspace / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    additions = [".bench-runtime/", ".codex-log/", ".gp/", ".pi-log/"]
    lines = existing.splitlines()
    for item in additions:
        if item not in lines:
            lines.append(item)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def task_text(model: str, policy: dict[str, Any]) -> str:
    validation = ", ".join(str(item) for item in policy["validation_batch_sizes"])
    return f"""# Objective

Optimize the TorchBench `{model}` CUDA eval workload. Minimize synchronized median
latency while preserving the outputs of the upstream eager model.

# Evaluation

- Run `python evaluate.py` for the fixed batch-size {policy['batch_size']} public workload.
- The primary metric is `{PRIMARY_METRIC}` in milliseconds; lower is better.
- Final validation also checks batch size {validation} to reject input-specific shortcuts.

# Constraints

- Only edit `{ARTIFACT_NAME}`.
- Preserve the TorchBench `Model(test="eval", device="cuda", batch_size=...)` contract.
- Do not modify the evaluator, task metadata, reference data, Git configuration, or files
  outside the model directory.
- Do not cache expected outputs, specialize on frozen input values, or bypass model work.
- Do not use the network. Leave the best verifier-valid implementation in the workspace.
"""


def render_evaluate_wrapper(upstream_root: Path, model: str) -> str:
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        \"\"\"Controller-owned public evaluator wrapper; do not edit.\"\"\"
        import subprocess
        import sys
        from pathlib import Path

        CONTROLLER = Path({str(CONTROLLER_PATH)!r})
        UPSTREAM = Path({str(upstream_root)!r})
        raise SystemExit(subprocess.call([
            sys.executable, str(CONTROLLER), "evaluate",
            "--workspace", str(Path(__file__).resolve().parent),
            "--upstream-root", str(UPSTREAM), "--model", {model!r},
            "--mode", "public",
        ]))
        """
    )


def render_goal_plus_verifier(upstream_root: Path, model: str) -> str:
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        \"\"\"Controller-owned Goal Plus verifier; do not edit.\"\"\"
        import json
        import subprocess
        import sys
        from pathlib import Path

        completed = subprocess.run([
            sys.executable, {str(CONTROLLER_PATH)!r}, "evaluate",
            "--workspace", str(Path.cwd()),
            "--upstream-root", {str(upstream_root)!r}, "--model", {model!r},
            "--mode", "public",
        ], capture_output=True, text=True)
        if completed.returncode != 0:
            sys.stderr.write(completed.stderr)
            raise SystemExit(completed.returncode)
        report = json.loads(completed.stdout)
        metric = report.get("primary_metric") or {{}}
        value = metric.get("value")
        if report.get("valid") is not True or not isinstance(value, (int, float)):
            raise SystemExit("TorchBench evaluator rejected the candidate")
        print(json.dumps({{{PRIMARY_METRIC!r}: float(value), "valid": True}}))
        """
    )


def materialize_workspace(source_root: Path, workspace: Path) -> dict[str, Any]:
    source_root = source_root.expanduser().absolute()
    workspace = workspace.expanduser().absolute()
    model = ACTIVE_MODEL
    artifact = source_root / "torchbenchmark/models" / model
    if not (source_root / ".git").exists():
        raise AdapterError(f"TorchBench source is not a Git checkout: {source_root}")
    if not (artifact / "__init__.py").is_file():
        raise AdapterError(f"TorchBench model is missing: {artifact}")
    if workspace.exists():
        raise FileExistsError(workspace)

    copy_tracked_checkout(source_root, workspace)
    append_gitignore(workspace)
    policy = model_policy(model)
    (workspace / "TASK.md").write_text(task_text(model, policy), encoding="utf-8")
    (workspace / "AGENTS.md").write_text(
        f"# TorchBench task rules\n\n"
        f"- Only edit `{ARTIFACT_NAME}`.\n"
        "- Run `python evaluate.py` for synchronized correctness and latency feedback.\n"
        "- Do not inspect parent directories, use the network, or bypass model work.\n",
        encoding="utf-8",
    )
    (workspace / "evaluate.py").write_text(
        render_evaluate_wrapper(source_root, model), encoding="utf-8"
    )
    verifier_dir = workspace / ".goal-plus-verifiers"
    verifier_dir.mkdir()
    (verifier_dir / "primary_metric.py").write_text(
        render_goal_plus_verifier(source_root, model), encoding="utf-8"
    )
    metadata = {
        "schema_version": 1,
        "adapter": "torchbench",
        "task_id": TASK_ID,
        "model": model,
        "test": "eval",
        "device": "cuda",
        "artifact": ARTIFACT_NAME,
        "primary_metric": PRIMARY_METRIC,
        "direction": DIRECTION,
        "policy": policy,
        "upstream_root": str(source_root),
        "upstream_commit": git_commit(source_root),
        "source_revision": git_commit(source_root),
        "suite": "TorchBench model wrapper eval",
        "evaluator": "adapter-owned differential correctness plus TorchBench get_latencies",
        "official_benchmark_comparable": False,
    }
    write_json(workspace / "task.json", metadata)
    workspace_commit = init_git(workspace, f"materialize TorchBench {model} eval")
    return {
        **metadata,
        "workspace": str(workspace),
        "workspace_commit": workspace_commit,
    }


def runtime_python() -> Path:
    configured = os.environ.get("BENCH_GOAL_PLUS_TORCHBENCH_PYTHON")
    if not configured:
        raise AdapterError(
            "set BENCH_GOAL_PLUS_TORCHBENCH_PYTHON to the Python executable of "
            "an installed CUDA TorchBench environment"
        )
    resolved = shutil.which(configured) or configured
    path = Path(resolved).expanduser().absolute()
    if not path.is_file():
        raise AdapterError(f"TorchBench Python executable does not exist: {path}")
    return path


def assigned_gpu(workspace: Path) -> str:
    raw = os.environ.get("BENCH_GOAL_PLUS_TORCHBENCH_GPUS")
    if not raw:
        raw = os.environ.get("CUDA_VISIBLE_DEVICES", "0")
    devices = [item.strip() for item in raw.split(",") if item.strip()]
    if not devices:
        raise AdapterError("TorchBench GPU pool is empty")
    lane_index = 0
    for part in reversed(workspace.parts):
        candidate = re.fullmatch(r"c(\d+)", part)
        lane = re.fullmatch(r"lane-(\d+)", part)
        if candidate:
            lane_index = int(candidate.group(1)) - 1
            break
        if lane:
            lane_index = int(lane.group(1))
            break
    return devices[lane_index % len(devices)]


def worker_environment(gpu: str) -> dict[str, str]:
    environment = dict(os.environ)
    environment["CUDA_VISIBLE_DEVICES"] = gpu
    torch_home = environment.get("BENCH_GOAL_PLUS_TORCH_HOME")
    if torch_home:
        environment["TORCH_HOME"] = torch_home
    return dict(configure_temp_environment(environment))


def run_worker(command: list[str], *, gpu: str) -> dict[str, Any]:
    completed = subprocess.run(
        [str(runtime_python()), str(WORKER_PATH), *command],
        capture_output=True,
        text=True,
        env=worker_environment(gpu),
        timeout=VERIFIER_TIMEOUT_SECONDS,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    payload = json.loads(lines[-1]) if lines else {}
    if completed.returncode != 0 or payload.get("valid") is not True:
        detail = payload.get("error") or completed.stderr.strip()[-1000:]
        raise AdapterError(detail or "TorchBench worker failed without diagnostics")
    return payload


def reference_path(
    source_root: Path,
    model: str,
    batch_size: int,
    gpu: str,
) -> Path:
    executable = runtime_python()
    identity = {
        "cache_format": 2,
        "source_commit": git_commit(source_root),
        "model": model,
        "batch_size": batch_size,
        "python": str(executable),
        "python_mtime_ns": executable.stat().st_mtime_ns,
        "gpu": gpu,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return ensure_temp_root("torchbench/references") / f"{model}-{batch_size}-{digest}.pt"


def ensure_reference(
    source_root: Path,
    model: str,
    batch_size: int,
    gpu: str,
) -> Path:
    destination = reference_path(source_root, model, batch_size, gpu)
    lock_path = destination.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        if not destination.is_file():
            with temporary_directory(
                prefix="reference-",
                namespace="torchbench",
            ) as temporary:
                clean = temporary / "repository"
                copy_tracked_checkout(source_root, clean)
                run_worker(
                    [
                        "reference",
                        "--repository",
                        str(clean),
                        "--model",
                        model,
                        "--batch-size",
                        str(batch_size),
                        "--reference",
                        str(destination),
                    ],
                    gpu=gpu,
                )
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return destination


def validate_artifact(artifact: Path) -> None:
    if not artifact.is_dir() or not (artifact / "__init__.py").is_file():
        raise AdapterError(f"candidate model directory is missing: {artifact}")
    symlinks = [path for path in artifact.rglob("*") if path.is_symlink()]
    if symlinks:
        raise AdapterError(f"candidate model contains symlinks: {symlinks[0]}")


def artifact_sha256(artifact: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in artifact.rglob("*") if item.is_file()):
        digest.update(path.relative_to(artifact).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def prepare_evaluation_tree(
    source_root: Path,
    artifact: Path,
    model: str,
    destination: Path,
) -> Path:
    copy_tracked_checkout(source_root, destination)
    target = destination / "torchbenchmark/models" / model
    shutil.rmtree(target)
    shutil.copytree(artifact, target)
    return destination


def evaluate_variant(
    repository: Path,
    source_root: Path,
    model: str,
    batch_size: int,
    policy: dict[str, Any],
    gpu: str,
) -> dict[str, Any]:
    reference = ensure_reference(source_root, model, batch_size, gpu)
    return run_worker(
        [
            "evaluate",
            "--repository",
            str(repository),
            "--model",
            model,
            "--batch-size",
            str(batch_size),
            "--reference",
            str(reference),
            "--warmups",
            str(policy["timing"]["warmup_iterations"]),
            "--samples",
            str(policy["timing"]["sample_count"]),
            "--atol",
            str(policy["correctness"]["atol"]),
            "--rtol",
            str(policy["correctness"]["rtol"]),
        ],
        gpu=gpu,
    )


def evaluate_workspace(workspace: Path, source_root: Path, mode: str) -> dict[str, Any]:
    started = time.monotonic()
    workspace = workspace.expanduser().absolute()
    source_root = source_root.expanduser().absolute()
    destination, budget = claim_evaluator_call(workspace, mode)
    model = ACTIVE_MODEL
    policy = model_policy(model)
    artifact = workspace / ARTIFACT_NAME
    gpu = assigned_gpu(workspace)
    variants: list[dict[str, Any]] = []
    error: str | None = None
    artifact_hash: str | None = None

    try:
        validate_artifact(artifact)
        artifact_hash = artifact_sha256(artifact)
        with temporary_directory(
            prefix="candidate-",
            namespace="torchbench",
        ) as temporary:
            repository = prepare_evaluation_tree(
                source_root,
                artifact,
                model,
                temporary / "repository",
            )
            batch_sizes = [policy["batch_size"]]
            if mode == "final":
                batch_sizes.extend(policy["validation_batch_sizes"])
            for batch_size in batch_sizes:
                variants.append(
                    evaluate_variant(
                        repository,
                        source_root,
                        model,
                        batch_size,
                        policy,
                        gpu,
                    )
                )
    except (AdapterError, OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exception:
        error = f"{type(exception).__name__}: {exception}"

    valid = error is None and len(variants) >= 1
    score = float(variants[0][PRIMARY_METRIC]) if valid else INVALID_LATENCY_MS
    report = {
        "schema_version": 1,
        "benchmark": "torchbench",
        "task_id": f"{model}-eval-cuda",
        "mode": mode,
        "valid": valid,
        "primary_metric": {
            "name": PRIMARY_METRIC,
            "value": score,
            "direction": DIRECTION,
        },
        PRIMARY_METRIC: score,
        "model": model,
        "test": "eval",
        "device": "cuda",
        "assigned_gpu": gpu,
        "variants": variants,
        "error": error,
        "artifact_sha256": artifact_hash,
        "duration_seconds": time.monotonic() - started,
        "budget": budget,
        "classification": "adapter-owned TorchBench differential evaluation",
        "official_benchmark_comparable": False,
        "evaluated_at": utc_now(),
    }
    append_history(destination, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    children = parser.add_subparsers(dest="command", required=True)
    materialize = children.add_parser("materialize")
    materialize.add_argument("--upstream-root", type=Path, required=True)
    materialize.add_argument("--workspace", type=Path, required=True)
    materialize.add_argument("--model", choices=list_task_ids(), default=DEFAULT_MODEL)
    evaluate = children.add_parser("evaluate")
    evaluate.add_argument("--workspace", type=Path, required=True)
    evaluate.add_argument("--upstream-root", type=Path, required=True)
    evaluate.add_argument("--model", choices=list_task_ids(), default=DEFAULT_MODEL)
    evaluate.add_argument("--mode", choices=("public", "final"), default="public")
    evaluate.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    configure_task(args.model)
    if args.command == "materialize":
        print(json.dumps(materialize_workspace(args.upstream_root, args.workspace), indent=2))
        return 0
    report = evaluate_workspace(args.workspace, args.upstream_root, args.mode)
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, indent=2))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
