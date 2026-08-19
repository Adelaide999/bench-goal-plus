"""Repository paths and injectable runtime context for EdgeBench."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from bench_goal_plus.upstreams import registered_upstream_source_path


@dataclass(frozen=True)
class EdgeBenchPaths:
    root: Path
    edge_root: Path
    goal_plus_root: Path
    tasks_dir: Path
    profile_dir: Path
    official_codex_protocol_path: Path
    paper_reference_path: Path
    runs_root: Path
    upstream_manifest: Path
    venv: Path
    venv_python: Path
    sforge: Path

    @classmethod
    def from_root(cls, root: Path) -> "EdgeBenchPaths":
        resolved = root.resolve()
        edge_root = resolved / "third_party" / "edgebench"
        venv = resolved / ".bench-env" / "venv"
        venv_bin = venv / ("Scripts" if sys.platform == "win32" else "bin")
        return cls(
            root=resolved,
            edge_root=edge_root,
            goal_plus_root=registered_upstream_source_path(
                "goal_plus",
                repository_root=resolved,
            ),
            tasks_dir=edge_root / "tasks",
            profile_dir=resolved / "experiments" / "edgebench" / "profiles",
            official_codex_protocol_path=(
                edge_root
                / "examples"
                / "all-tasks-k8s"
                / "experiment-codex.yaml"
            ),
            paper_reference_path=(
                resolved
                / "experiments"
                / "edgebench"
                / "references"
                / "paper-gpt-5.5-codex-12h.json"
            ),
            runs_root=resolved / "runs" / "edgebench",
            upstream_manifest=resolved / "environment" / "upstreams.json",
            venv=venv,
            venv_python=venv_bin / (
                "python.exe" if sys.platform == "win32" else "python"
            ),
            sforge=venv_bin / (
                "sforge.exe" if sys.platform == "win32" else "sforge"
            ),
        )


DEFAULT_PATHS = EdgeBenchPaths.from_root(Path(__file__).resolve().parents[3])
_current_paths = DEFAULT_PATHS


def current_paths() -> EdgeBenchPaths:
    return _current_paths


def set_paths(paths: EdgeBenchPaths) -> None:
    global _current_paths
    _current_paths = paths
