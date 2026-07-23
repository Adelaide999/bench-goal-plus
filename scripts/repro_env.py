#!/usr/bin/env python3
"""Create and verify the portable benchmark runtime and managed checkouts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench_runtime_paths import (  # noqa: E402
    DEFAULT_TEMP_ROOT,
    configure_temp_environment,
    ensure_temp_root,
)


DEFAULT_MANIFEST = ROOT / "environment/upstreams.json"
DEFAULT_LOCK = ROOT / "environment/requirements.lock"
DEFAULT_VENV = ROOT / ".bench-env/venv"
DEFAULT_CHECKOUT_ROOT = ROOT / "third_party"
STATE_PATH = ROOT / ".bench-env/state.json"


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=capture,
        text=True,
        check=check,
    )


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if payload.get("schema_version") != 2:
        raise RuntimeError("unsupported environment manifest schema")
    for name, entry in payload.get("upstreams", {}).items():
        branch = entry.get("tracking_branch")
        if not isinstance(branch, str) or not branch:
            raise RuntimeError(f"{name}: tracking_branch is required")
        if branch.startswith(("-", ".", "/")) or ".." in branch:
            raise RuntimeError(f"{name}: unsafe tracking_branch {branch!r}")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", branch) is None:
            raise RuntimeError(f"{name}: invalid tracking_branch {branch!r}")
    return payload


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if sys.platform == "win32" else "bin")


def selected_upstreams(
    manifest: dict[str, Any], only: list[str] | None = None
) -> dict[str, dict[str, Any]]:
    upstreams = manifest["upstreams"]
    if not only:
        return dict(upstreams)
    requested = set(only)
    unknown = requested - set(upstreams)
    if unknown:
        raise ValueError("unknown managed checkout(s): " + ", ".join(sorted(unknown)))
    return {
        name: entry
        for name, entry in upstreams.items()
        if entry.get("always") is True or name in requested
    }


def checkout_paths(
    manifest: dict[str, Any],
    checkout_root: Path,
    only: list[str] | None = None,
) -> dict[str, Path]:
    return {
        name: checkout_root / entry["checkout_dir"]
        for name, entry in selected_upstreams(manifest, only).items()
    }


def normalize_repository(value: str | None) -> str | None:
    return value.rstrip("/").removesuffix(".git") if value else None


def git_state(path: Path, tracking_branch: str | None = None) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "is_git": False,
            "head": None,
            "branch": None,
            "upstream": None,
            "remote_head": None,
            "origin_url": None,
            "dirty": None,
        }
    head = run(["git", "-C", str(path), "rev-parse", "HEAD"], check=False)
    status = run(["git", "-C", str(path), "status", "--porcelain"], check=False)
    branch = run(
        ["git", "-C", str(path), "symbolic-ref", "--short", "-q", "HEAD"],
        check=False,
    )
    upstream = run(
        [
            "git",
            "-C",
            str(path),
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        ],
        check=False,
    )
    origin = run(
        ["git", "-C", str(path), "remote", "get-url", "origin"],
        check=False,
    )
    remote_head = None
    if tracking_branch:
        remote = run(
            [
                "git",
                "-C",
                str(path),
                "rev-parse",
                f"refs/remotes/origin/{tracking_branch}",
            ],
            check=False,
        )
        remote_head = remote.stdout.strip() if remote.returncode == 0 else None
    return {
        "exists": True,
        "is_git": head.returncode == 0,
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "branch": branch.stdout.strip() if branch.returncode == 0 else None,
        "upstream": upstream.stdout.strip() if upstream.returncode == 0 else None,
        "remote_head": remote_head,
        "origin_url": origin.stdout.strip() if origin.returncode == 0 else None,
        "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


def ensure_checkout(path: Path, entry: dict[str, Any]) -> None:
    branch = entry["tracking_branch"]
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = path.with_name(path.name + "_bootstrap_incomplete")
        if staging.exists():
            raise RuntimeError(
                f"preserved incomplete checkout exists: {staging}; rename it to *_bak "
                "after inspection before retrying"
            )
        staging.mkdir()
        run(["git", "-C", str(staging), "init", "-q"])
        run(
            [
                "git",
                "-C",
                str(staging),
                "remote",
                "add",
                "origin",
                entry["repository"],
            ]
        )
        fetch_command = ["git", "-C", str(staging), "fetch"]
        if entry.get("sparse_paths"):
            fetch_command.append("--filter=blob:none")
        fetch_command.extend(
            [
                "--depth",
                "1",
                "origin",
                f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
            ]
        )
        run(fetch_command)
        if entry.get("sparse_paths"):
            run(
                [
                    "git",
                    "-C",
                    str(staging),
                    "sparse-checkout",
                    "set",
                    "--no-cone",
                    *entry["sparse_paths"],
                ]
            )
        run(
            [
                "git",
                "-C",
                str(staging),
                "checkout",
                "-q",
                "-b",
                branch,
                "--track",
                f"origin/{branch}",
            ]
        )
        staging.rename(path)
        return
    state = git_state(path, branch)
    if not state["is_git"]:
        raise RuntimeError(f"existing checkout path is not a Git repository: {path}")
    if state["dirty"]:
        raise RuntimeError(f"checkout has local changes and will not be used: {path}")
    if normalize_repository(state["origin_url"]) != normalize_repository(
        entry["repository"]
    ):
        raise RuntimeError(
            f"origin mismatch for {path}: expected {entry['repository']}, "
            f"got {state['origin_url']}; use a separate checkout root"
        )
    fetch_command = ["git", "-C", str(path), "fetch", "--prune"]
    if entry.get("sparse_paths"):
        fetch_command.append("--filter=blob:none")
    fetch_command.extend(
        [
            "origin",
            f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
        ]
    )
    run(fetch_command)
    state = git_state(path, branch)
    if state["branch"] is None:
        local_branch = run(
            [
                "git",
                "-C",
                str(path),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{branch}",
            ],
            check=False,
        )
        if local_branch.returncode == 0:
            run(["git", "-C", str(path), "checkout", "-q", branch])
        else:
            run(
                [
                    "git",
                    "-C",
                    str(path),
                    "checkout",
                    "-q",
                    "-b",
                    branch,
                    "--track",
                    f"origin/{branch}",
                ]
            )
    elif state["branch"] != branch:
        raise RuntimeError(
            f"checkout {path} is on branch {state['branch']!r}, expected {branch!r}; "
            "switch it explicitly or use a separate checkout root"
        )
    state = git_state(path, branch)
    expected_upstream = f"origin/{branch}"
    if state["upstream"] != expected_upstream:
        run(
            [
                "git",
                "-C",
                str(path),
                "branch",
                "--set-upstream-to",
                expected_upstream,
                branch,
            ]
        )
    merged = run(
        ["git", "-C", str(path), "merge", "--ff-only", expected_upstream],
        check=False,
    )
    if merged.returncode != 0:
        raise RuntimeError(
            f"checkout {path} cannot fast-forward to {expected_upstream}: "
            f"{merged.stderr.strip() or merged.stdout.strip()}"
        )
    state = git_state(path, branch)
    if state["head"] != state["remote_head"]:
        raise RuntimeError(
            f"checkout {path} has unpublished or divergent commits on {branch}; "
            "push them to the tracked branch or use a separate checkout root"
        )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_versions(python: Path) -> dict[str, str | None]:
    packages = (
        "openevolve",
        "goal-plus",
        "sforge",
        "fastapi",
        "fastmcp",
        "numpy",
        "scipy",
        "openai",
    )
    script = (
        "import importlib.metadata,json\n"
        f"names={packages!r}\n"
        "out={}\n"
        "for name in names:\n"
        "  try: out[name]=importlib.metadata.version(name)\n"
        "  except importlib.metadata.PackageNotFoundError: out[name]=None\n"
        "print(json.dumps(out))\n"
    )
    result = run([str(python), "-c", script], check=False)
    if result.returncode != 0:
        return {name: None for name in packages}
    return json.loads(result.stdout)


def parse_codex_version(text: str) -> tuple[int, ...] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(part) for part in match.groups()) if match else None


def collect_doctor(
    manifest: dict[str, Any],
    checkout_root: Path,
    venv: Path,
    lock: Path = DEFAULT_LOCK,
    only: list[str] | None = None,
) -> dict[str, Any]:
    ensure_temp_root()
    python = venv_python(venv)
    chosen = selected_upstreams(manifest, only)
    paths = checkout_paths(manifest, checkout_root, only)
    checks: list[dict[str, Any]] = []
    checks.append(
        {
            "name": "runtime:repository-local-temp",
            "passed": bool(
                DEFAULT_TEMP_ROOT.parent == ROOT
                and DEFAULT_TEMP_ROOT.name == ".tmp"
                and DEFAULT_TEMP_ROOT.is_dir()
                and os.access(DEFAULT_TEMP_ROOT, os.W_OK)
            ),
            "path": ".tmp",
        }
    )

    for name, entry in chosen.items():
        branch = entry["tracking_branch"]
        state = git_state(paths[name], branch)
        passed = bool(
            state["is_git"]
            and state["branch"] == branch
            and state["upstream"] == f"origin/{branch}"
            and state["head"] == state["remote_head"]
            and normalize_repository(state["origin_url"])
            == normalize_repository(entry["repository"])
            and state["dirty"] is False
        )
        checks.append(
            {
                "name": f"checkout:{name}",
                "passed": passed,
                "expected_branch": branch,
                "expected_repository": entry["repository"],
                **state,
            }
        )

    python_version = None
    if python.is_file():
        result = run([str(python), "--version"], check=False)
        python_version = (result.stdout or result.stderr).strip()
    checks.append(
        {
            "name": "runtime:python",
            "passed": bool(
                python_version
                and python_version.startswith(f"Python {manifest['python']}.")
            ),
            "version": python_version,
        }
    )

    versions = package_versions(python) if python.is_file() else {}
    for package in ("openevolve", "goal-plus", "fastmcp", "numpy", "scipy"):
        checks.append(
            {
                "name": f"package:{package}",
                "passed": bool(versions.get(package)),
                "version": versions.get(package),
            }
        )
    if "edgebench" in chosen:
        for package in ("sforge", "fastapi"):
            checks.append(
                {
                    "name": f"package:{package}",
                    "passed": bool(versions.get(package)),
                    "version": versions.get(package),
                }
            )

    for executable in (
        "openevolve-run",
        "goal-plus",
        "goal-plus-pi-tool",
        "goal-plus-pi-worker",
        "goal-plus-pi-pool",
    ):
        path = venv_bin(venv) / executable
        result = run([str(path), "--help"], check=False) if path.is_file() else None
        checks.append(
            {
                "name": f"entrypoint:{executable}",
                "passed": bool(result and result.returncode == 0),
            }
        )
    if "edgebench" in chosen:
        path = venv_bin(venv) / "sforge"
        result = run([str(path), "--help"], check=False) if path.is_file() else None
        checks.append(
            {
                "name": "entrypoint:sforge",
                "passed": bool(result and result.returncode == 0),
            }
        )

    codex_path = shutil.which("codex")
    codex_text = None
    codex_version = None
    if codex_path:
        result = run([codex_path, "--version"], check=False)
        codex_text = (result.stdout or result.stderr).strip()
        codex_version = parse_codex_version(codex_text)
    minimum = tuple(int(part) for part in manifest["codex_min_version"].split("."))
    checks.append(
        {
            "name": "host:codex",
            "passed": bool(codex_version and codex_version >= minimum),
            "version": codex_text,
            "minimum": manifest["codex_min_version"],
        }
    )

    pi_path = shutil.which("pi")
    pi_text = None
    pi_version = None
    if pi_path:
        result = run([pi_path, "--version"], check=False)
        pi_text = (result.stdout or result.stderr).strip()
        pi_version = parse_codex_version(pi_text)
    pi_minimum = tuple(int(part) for part in manifest["pi_min_version"].split("."))
    checks.append(
        {
            "name": "host:pi",
            "passed": bool(pi_version and pi_version >= pi_minimum),
            "version": pi_text,
            "minimum": manifest["pi_min_version"],
        }
    )

    return {
        "schema_version": 2,
        "ok": all(item["passed"] for item in checks),
        "platform": platform.platform(),
        "python": str(python),
        "venv": str(venv),
        "checkout_root": str(checkout_root),
        "managed_checkouts": list(chosen),
        "requirements_lock_sha256": sha256_file(lock) if lock.is_file() else None,
        "packages": versions,
        "checks": checks,
    }


def bootstrap(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    checkout_root = args.checkout_root.expanduser().absolute()
    venv = args.venv.expanduser().absolute()
    chosen = selected_upstreams(manifest, args.only)
    for name, entry in chosen.items():
        ensure_checkout(checkout_root / entry["checkout_dir"], entry)

    uv = shutil.which(args.uv)
    if not uv:
        raise RuntimeError("uv is required; install it first, then rerun bootstrap")
    python = venv_python(venv)
    if not python.is_file():
        venv.parent.mkdir(parents=True, exist_ok=True)
        run([uv, "venv", str(venv), "--python", manifest["python"]])
    version = run([str(python), "--version"], check=False)
    version_text = (version.stdout or version.stderr).strip()
    if not version_text.startswith(f"Python {manifest['python']}."):
        raise RuntimeError(
            f"existing venv uses {version_text}, expected Python {manifest['python']}; "
            "preserve it and choose a fresh --venv path"
        )
    if not args.skip_install:
        if not args.lock.is_file():
            raise FileNotFoundError(args.lock)
        run(
            [uv, "pip", "install", "--python", str(python), "-r", str(args.lock)],
            capture=False,
        )
        paths = checkout_paths(manifest, checkout_root, args.only)
        editable_paths = [
            paths[name] for name, entry in chosen.items() if entry.get("editable") is True
        ]
        if editable_paths:
            editable_args: list[str] = []
            for path in editable_paths:
                editable_args.extend(["-e", str(path)])
            run(
                [
                    uv,
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    "--no-build-isolation",
                    "--no-deps",
                    *editable_args,
                ],
                capture=False,
            )

    payload = collect_doctor(
        manifest, checkout_root, venv, args.lock, only=args.only
    )
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


def doctor(args: argparse.Namespace) -> int:
    payload = collect_doctor(
        load_manifest(args.manifest),
        args.checkout_root.expanduser().absolute(),
        args.venv.expanduser().absolute(),
        args.lock,
        only=args.only,
    )
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--checkout-root", type=Path, default=DEFAULT_CHECKOUT_ROOT)
    parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--uv", default="uv")
    bootstrap_parser.add_argument("--skip-install", action="store_true")
    bootstrap_parser.add_argument(
        "--only",
        action="append",
        help="clone/check one named benchmark plus the always-managed runtime checkouts",
    )

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--only", action="append")
    return parser


def main() -> int:
    configure_temp_environment()
    args = build_parser().parse_args()
    return bootstrap(args) if args.command == "bootstrap" else doctor(args)


if __name__ == "__main__":
    raise SystemExit(main())
