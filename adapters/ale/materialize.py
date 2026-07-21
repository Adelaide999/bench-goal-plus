#!/usr/bin/env python3
"""Create an isolated ALE-Bench task workspace for Codex."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


OPTIONAL_LOOP = "while (walk.size() - 1 < MAX_L) {"
BOUNDED_OPTIONAL_LOOP = "while (false && walk.size() - 1 < MAX_L) {"


def load_starter(results_path: Path | None) -> tuple[str, str]:
    if results_path is None:
        return (
            "#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    return 0;\n}\n",
            "empty-cpp20-skeleton",
        )
    data = json.loads(results_path.read_text())
    code = data["repeated_sampling"]["code"]
    if code.count(OPTIONAL_LOOP) == 1:
        code = code.replace(OPTIONAL_LOOP, BOUNDED_OPTIONAL_LOOP)
        provenance = "legacy-deepseek-smoke-with-optional-unbounded-loop-disabled"
    else:
        provenance = "legacy-deepseek-smoke-unmodified"
    return code.rstrip() + "\n", provenance


def load_problem(problem_id: str) -> tuple[str, dict]:
    from ale_bench.data import load_problem

    problem, _, _, _, _ = load_problem(problem_id=problem_id, lite_version=True)
    metadata = {
        "problem_id": problem_id,
        "lite_version": True,
        "score_type": problem.metadata.score_type.value,
        "problem_type": problem.metadata.problem_type.value,
        "time_limit_seconds": problem.constraints.time_limit,
        "memory_limit_bytes": problem.constraints.memory_limit,
        "code_language": "cpp20",
        "judge_version": "202301",
    }
    return problem.statement, metadata


def init_git(workspace: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(workspace)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(workspace), "config", "user.email", "bench-goal-plus@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(workspace), "config", "user.name", "bench-goal-plus"], check=True)
    subprocess.run(["git", "-C", str(workspace), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "commit", "-m", "materialize ALE-Bench task"],
        check=True,
        capture_output=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem-id", default="ahc027")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--starter-results", type=Path)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    statement, metadata = load_problem(args.problem_id)
    starter, provenance = load_starter(args.starter_results)
    metadata["starter_provenance"] = provenance
    workspace.mkdir(parents=True, exist_ok=False)

    (workspace / "PROBLEM.md").write_text(statement.rstrip() + "\n")
    (workspace / "solution.cpp").write_text(starter)
    (workspace / "task.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (workspace / "TASK.md").write_text(
        "# Task\n\n"
        "Read `PROBLEM.md` and improve `solution.cpp` for the heuristic optimization problem. "
        "The current program is a valid but weak connectivity starter. Preserve correctness and "
        "termination under the stated time limit, and make a concrete edit to `solution.cpp`. "
        "Use C++20. Do not access files outside this Git workspace and do not use the network. "
        "The official public evaluator is controller-owned and will run after this turn.\n"
    )
    (workspace / "AGENTS.md").write_text(
        "# ALE task rules\n\n"
        "- Only edit `solution.cpp`.\n"
        "- Do not inspect parent directories, hidden benchmark data, evaluator code, or network resources.\n"
        "- Keep the implementation deterministic and compatible with C++20.\n"
        "- The program must terminate within the problem time limit for every input.\n"
        "- Do not change `PROBLEM.md`, `TASK.md`, `task.json`, or this file.\n"
    )
    init_git(workspace)
    print(json.dumps({"workspace": str(workspace), **metadata}, indent=2))


if __name__ == "__main__":
    main()
