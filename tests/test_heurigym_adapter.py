from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from adapters.heurigym import adapter


ROOT = Path(__file__).resolve().parents[1]


class HeuriGymAdapterTest(unittest.TestCase):
    def test_seed_solver_handles_a_synthetic_parallel_dag(self) -> None:
        problem = {
            "delay": {"mul": 3, "sub": 1},
            "resource": {"mul": 2, "sub": 1},
            "nodes": [["n1", "mul"], ["n2", "mul"], ["n3", "sub"]],
            "edges": [["n1", "n3", "lhs"], ["n2", "n3", "rhs"]],
        }
        namespace: dict[str, object] = {}
        exec(adapter.SEED_SOLVER, namespace)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.json"
            output = root / "output.txt"
            source.write_text(json.dumps(problem))
            namespace["solve"](str(source), str(output))
            starts = dict(
                line.split(":", 1) for line in output.read_text().splitlines()
            )
        self.assertEqual(set(starts), {"n1", "n2", "n3"})
        self.assertGreaterEqual(int(starts["n3"]), int(starts["n1"]) + 3)
        self.assertGreaterEqual(int(starts["n3"]), int(starts["n2"]) + 3)

    def test_task_contract_has_one_editable_artifact_and_raw_metric(self) -> None:
        text = adapter.task_text(adapter.CASE_NAMES)
        self.assertIn("Only edit `solver.py`", text)
        self.assertIn("`total_cost`", text)
        self.assertIn("lower is better", text)
        self.assertEqual(adapter.DIRECTION, "minimize")
        self.assertRegex(adapter.DATASET_REVISION, r"^[0-9a-f]{40}$")
        self.assertEqual(set(adapter.CASE_NAMES), set(adapter.EXPECTED_CASE_SHA256))

    def test_goal_plus_verifier_uses_controller_and_numeric_metric(self) -> None:
        rendered = adapter.render_goal_plus_verifier(
            ROOT / ".tmp/tests/pinned-upstream"
        )
        self.assertIn(
            "GOAL_PLUS_VERIFIER_TMPDIR",
            adapter.evaluate_workspace.__code__.co_consts,
        )
        self.assertIn("official evaluator rejected the candidate", rendered)
        self.assertIn("'total_cost': float(value)", rendered)

    def test_edit_surface_detects_tracked_and_untracked_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Test"], check=True
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "config",
                    "user.email",
                    "test@example.invalid",
                ],
                check=True,
            )
            (root / "solver.py").write_text("seed\n")
            (root / "TASK.md").write_text("frozen\n")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-q", "-m", "seed"],
                check=True,
            )
            (root / "solver.py").write_text("candidate\n")
            self.assertEqual(adapter.changed_workspace_paths(root), {"solver.py"})
            (root / "TASK.md").write_text("tampered\n")
            (root / "extra.txt").write_text("unexpected\n")
            self.assertEqual(
                adapter.changed_workspace_paths(root),
                {"solver.py", "TASK.md", "extra.txt"},
            )


if __name__ == "__main__":
    unittest.main()
