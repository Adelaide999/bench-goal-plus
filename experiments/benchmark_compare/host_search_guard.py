#!/usr/bin/env python3
"""Keep agent find/grep inside the session cwd so a freeze-spec error cannot stall the wall clock."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


GUARD_BIN = Path(__file__).resolve().parent / "bin"
TIMEOUT_SECONDS = 60
BLOCK_MESSAGE = (
    "host-search-guard blocked {tool} on {path}: stay inside the session cwd; "
    "selection.ranking_keys may only be hard_score or quality_score"
)
FIND_VALUE_OPTIONS = {
    "-amin",
    "-anewer",
    "-atime",
    "-cmin",
    "-cnewer",
    "-ctime",
    "-fprintf",
    "-fstype",
    "-gid",
    "-group",
    "-ilname",
    "-iname",
    "-inum",
    "-ipath",
    "-iregex",
    "-iwholename",
    "-links",
    "-lname",
    "-mmin",
    "-mtime",
    "-name",
    "-newer",
    "-newerXY",
    "-path",
    "-perm",
    "-printf",
    "-regex",
    "-regextype",
    "-samefile",
    "-size",
    "-type",
    "-uid",
    "-used",
    "-user",
    "-wholename",
    "-xtype",
    "-context",
    "-maxdepth",
    "-mindepth",
}


def prepend_to_path(environment: dict[str, str]) -> None:
    guard = str(GUARD_BIN)
    parts = [item for item in environment.get("PATH", "").split(os.pathsep) if item]
    if guard not in parts:
        environment["PATH"] = os.pathsep.join([guard, *parts]) if parts else guard


def _cwd_root(cwd: str) -> str:
    return os.path.realpath(cwd).rstrip("/") or "/"


def path_outside_cwd(path: str, cwd: str) -> bool:
    if not path.startswith("/") or path in {"/dev/null", "/dev/stdin", "/dev/stdout", "/dev/stderr"}:
        return False
    root = _cwd_root(cwd)
    candidate = os.path.abspath(os.path.join(cwd, path)).rstrip("/") or "/"
    return candidate != root and not candidate.startswith(root + "/")


def _which_real(name: str) -> str | None:
    here = str(GUARD_BIN.resolve())
    search = os.pathsep.join(
        item
        for item in os.environ.get("PATH", "").split(os.pathsep)
        if item and os.path.realpath(item) != here
    )
    return shutil.which(name, path=search)


def blocked_find_path(args: list[str], cwd: str) -> str | None:
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in {"-exec", "-execdir", "-ok", "-okdir"}:
            return None
        if arg in FIND_VALUE_OPTIONS or arg.startswith("-newer"):
            skip = True
            continue
        if arg.startswith("-"):
            continue
        if arg == "/" or path_outside_cwd(arg, cwd):
            return arg
    return None


def _grep_is_recursive(args: list[str]) -> bool:
    for arg in args:
        if arg == "--":
            break
        if arg in {"-r", "-R", "--recursive", "--dereference-recursive"}:
            return True
        if arg.startswith("-") and not arg.startswith("--") and any(
            flag in arg[1:] for flag in ("r", "R")
        ):
            return True
    return False


def blocked_grep_path(args: list[str], cwd: str) -> str | None:
    if not _grep_is_recursive(args):
        return None
    takes_value = {
        "-e",
        "-f",
        "-m",
        "-A",
        "-B",
        "-C",
        "-D",
        "-d",
        "--regexp",
        "--file",
        "--max-count",
        "--include",
        "--exclude",
        "--exclude-dir",
    }
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg == "--":
            continue
        if arg.startswith("-") and arg != "-":
            option = arg.split("=", 1)[0]
            if option in takes_value and "=" not in arg:
                skip = True
            continue
        if arg == "/" or path_outside_cwd(arg, cwd):
            return arg
    return None


def blocked_path(tool: str, args: list[str], cwd: str) -> str | None:
    if tool == "find":
        return blocked_find_path(args, cwd)
    if tool in {"grep", "rg"}:
        return blocked_grep_path(args, cwd)
    raise ValueError(f"unsupported host-search-guard tool: {tool}")


def _exec_real(tool: str, args: list[str]) -> int:
    real = _which_real(tool)
    if real is None:
        print(f"{tool}: not found", file=sys.stderr)
        return 127
    timeout = _which_real("timeout")
    if timeout is not None:
        os.execv(
            timeout,
            [timeout, "--kill-after=2", str(TIMEOUT_SECONDS), real, *args],
        )
    os.execv(real, [real, *args])
    return 127


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        print("host-search-guard: missing tool name", file=sys.stderr)
        return 2
    tool, *args = arguments
    blocked = blocked_path(tool, args, os.getcwd())
    if blocked is not None:
        message = BLOCK_MESSAGE.format(tool=tool, path=blocked)
        print(message)
        print(message, file=sys.stderr)
        return 2
    return _exec_real(tool, args)


if __name__ == "__main__":
    raise SystemExit(main())
