from __future__ import annotations

import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.openevolve_compare import experiment  # noqa: E402


class OpenEvolveComparisonTest(unittest.TestCase):
    def test_goal_plus_assets_copy_only_portable_project_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            goal_plus = temp / "goal-plus"
            codex = goal_plus / ".codex"
            (codex / "agents").mkdir(parents=True)
            (codex / "skills/demo").mkdir(parents=True)
            (codex / "agents/worker.toml").write_text("name='worker'\n")
            (codex / "skills/demo/SKILL.md").write_text("# demo\n")
            (codex / "hooks.json").write_text("{}\n")
            (codex / "config.example.toml").write_text("[mcp_servers.goal-plus]\n")
            (codex / "config.toml").write_text("secret='must-not-copy'\n")
            workspace = temp / "workspace"
            workspace.mkdir()

            experiment.copy_goal_plus_assets(goal_plus, workspace)

            target = workspace / ".codex"
            self.assertTrue((target / "agents/worker.toml").is_file())
            self.assertTrue((target / "skills/demo/SKILL.md").is_file())
            self.assertEqual(
                (target / "config.toml").read_text(),
                "[mcp_servers.goal-plus]\n",
            )
            self.assertNotIn(
                "must-not-copy",
                "\n".join(p.read_text() for p in target.rglob("*.*")),
            )

    def test_goal_prompt_freezes_outer_budget_without_call_cap(self) -> None:
        prompt = experiment.render_goal("# Objective\nImprove it.", 600, 60, 3)
        self.assertTrue(prompt.startswith("/goal-plus mode=autonomous"))
        self.assertIn("max_candidates=3", prompt)
        self.assertIn("max_parallel=3", prompt)
        self.assertIn("540 seconds", prompt)
        self.assertIn("not hard-capped", prompt)
        self.assertIn("GOAL_PLUS_OUTER_DEADLINE_AT", prompt)

    @unittest.skipUnless(hasattr(signal, "SIGTERM"), "requires POSIX-style SIGTERM")
    def test_outer_controller_requests_soft_stop_at_deadline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            code = (
                "import signal,sys,time\n"
                "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
                "while True: time.sleep(0.1)\n"
            )
            result = experiment.run_controlled(
                [sys.executable, "-c", code],
                cwd=temp,
                environment=os.environ.copy(),
                stdin_text=None,
                stdout_path=temp / "stdout.log",
                stderr_path=temp / "stderr.log",
                wall_time_seconds=1,
                hard_kill_grace_seconds=2,
            )
            self.assertTrue(result["deadline_reached"])
            self.assertFalse(result["hard_killed"])
            self.assertEqual(result["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
