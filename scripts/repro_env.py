#!/usr/bin/env python3
"""Create and verify the portable OpenEvolve + Goal Plus runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "environment/upstreams.json"
DEFAULT_LOCK = ROOT / "environment/requirements.lock"
DEFAULT_VENV = ROOT / ".bench-env/venv"
DEFAULT_CHECKOUT_ROOT = ROOT.parent
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
    if payload.get("schema_version") != 1:
        raise RuntimeError("unsupported environment manifest schema")
    return payload


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if sys.platform == "win32" else "bin")


def checkout_paths(manifest: dict[str, Any], checkout_root: Path) -> dict[str, Path]:
    return {
        name: checkout_root / entry["checkout_dir"]
        for name, entry in manifest["upstreams"].items()
    }


def git_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": path.exists(), "is_git": False, "head": None, "dirty": None}
    head = run(["git", "-C", str(path), "rev-parse", "HEAD"], check=False)
    status = run(["git", "-C", str(path), "status", "--porcelain"], check=False)
    return {
        "exists": True,
        "is_git": head.returncode == 0,
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


def ensure_checkout(path: Path, entry: dict[str, Any]) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", entry["repository"], str(path)])
        run(["git", "-C", str(path), "checkout", "--detach", entry["pinned_commit"]])
        return
    state = git_state(path)
    if not state["is_git"]:
        raise RuntimeError(f"existing checkout path is not a Git repository: {path}")
    if state["head"] != entry["pinned_commit"]:
        raise RuntimeError(
            f"checkout mismatch for {path}: expected {entry['pinned_commit']}, "
            f"got {state['head']}; use a separate checkout root rather than rewriting it"
        )
    if state["dirty"]:
        raise RuntimeError(f"checkout has local changes and will not be used: {path}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_versions(python: Path) -> dict[str, str | None]:
    packages = ("openevolve", "goal-plus", "fastmcp", "numpy", "scipy", "openai")
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
) -> dict[str, Any]:
    python = venv_python(venv)
    paths = checkout_paths(manifest, checkout_root)
    checks: list[dict[str, Any]] = []

    for name, entry in manifest["upstreams"].items():
        state = git_state(paths[name])
        passed = bool(
            state["is_git"]
            and state["head"] == entry["pinned_commit"]
            and state["dirty"] is False
        )
        checks.append(
            {
                "name": f"checkout:{name}",
                "passed": passed,
                "expected_commit": entry["pinned_commit"],
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
        "schema_version": 1,
        "ok": all(item["passed"] for item in checks),
        "platform": platform.platform(),
        "python": str(python),
        "venv": str(venv),
        "checkout_root": str(checkout_root),
        "requirements_lock_sha256": sha256_file(lock) if lock.is_file() else None,
        "packages": versions,
        "checks": checks,
    }


def bootstrap(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    checkout_root = args.checkout_root.expanduser().absolute()
    venv = args.venv.expanduser().absolute()
    for name, entry in manifest["upstreams"].items():
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
        paths = checkout_paths(manifest, checkout_root)
        run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--no-build-isolation",
                "--no-deps",
                "-e",
                str(paths["openevolve"]),
                "-e",
                str(paths["goal_plus"]),
            ],
            capture=False,
        )

    payload = collect_doctor(manifest, checkout_root, venv, args.lock)
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

    subparsers.add_parser("doctor")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return bootstrap(args) if args.command == "bootstrap" else doctor(args)


if __name__ == "__main__":
    raise SystemExit(main())
