from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from experiments.openevolve_compare import experiment  # noqa: E402


class OpenEvolveComparisonTest(unittest.TestCase):
    def test_four_canonical_methods_and_experiment_defaults(self) -> None:
        self.assertEqual(
            experiment.METHODS,
            ("openevolve", "plain-codex", "goal-plus-codex", "goal-plus-pi"),
        )
        parser = experiment.build_parser()
        args = parser.parse_args(["prepare", "--method", "plain-codex"])
        self.assertEqual(args.wall_time_seconds, 300)
        self.assertEqual(args.concurrency, 2)
        self.assertEqual(args.model, "gpt-5.6-luna")

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

    def test_goal_plus_pi_assets_copy_only_project_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            goal_plus = temp / "goal-plus"
            pi = goal_plus / ".pi"
            (pi / "extensions").mkdir(parents=True)
            (pi / "skills/goal-plus").mkdir(parents=True)
            (pi / "prompts").mkdir(parents=True)
            (pi / "extensions/goal-plus.ts").write_text("export default {}\n")
            (pi / "skills/goal-plus/SKILL.md").write_text("# Goal Plus\n")
            (pi / "prompts/search-candidate-worker.md").write_text("worker\n")
            workspace = temp / "workspace"
            workspace.mkdir()

            experiment.copy_goal_plus_pi_assets(goal_plus, workspace)

            self.assertTrue((workspace / ".pi/extensions/goal-plus.ts").is_file())
            self.assertTrue((workspace / ".pi/skills/goal-plus/SKILL.md").is_file())
            self.assertTrue(
                (workspace / ".pi/prompts/search-candidate-worker.md").is_file()
            )

    def test_goal_prompt_freezes_outer_budget_without_call_cap(self) -> None:
        prompt = experiment.render_goal(
            "# Objective\nImprove it.",
            300,
            60,
            2,
            worker_host="pi-rpc",
            worker_model="bench-openai/gpt-5.6-luna",
        )
        self.assertTrue(prompt.startswith("/goal-plus mode=autonomous"))
        self.assertIn("max_candidates=2", prompt)
        self.assertIn("max_parallel=2", prompt)
        self.assertIn("240 seconds", prompt)
        self.assertIn("not hard-capped", prompt)
        self.assertIn("GOAL_PLUS_OUTER_DEADLINE_AT", prompt)
        self.assertIn('worker_host="pi-rpc"', prompt)
        self.assertIn('worker_launch.model="bench-openai/gpt-5.6-luna"', prompt)
        self.assertIn('worker_launch.reasoning_effort="high"', prompt)

    def test_prepared_goal_prompt_resumes_exact_search_ids(self) -> None:
        prompt = experiment.render_goal(
            "# Objective\nImprove it.",
            300,
            60,
            2,
            worker_host="codex",
            worker_model="gpt-5.6-luna",
            prepared_search={
                "goal_plus_id": "gp_0001",
                "frozen_spec_id": "spec_test",
                "run_id": "run_test",
            },
        )
        self.assertTrue(
            prompt.startswith("Resume the controller-prepared Goal Plus Search state")
        )
        self.assertNotIn("/goal-plus", prompt.splitlines()[0])
        self.assertIn("goal_plus_id=gp_0001", prompt)
        self.assertIn("run_id=run_test", prompt)
        self.assertIn("Do not create another Goal Plus record", prompt)

    def test_controller_prepared_spec_keeps_runtime_files_outside_edit_surface(
        self,
    ) -> None:
        spec = experiment.build_goal_plus_search_spec(
            workspace=Path("/tmp/example-workspace"),
            task_text="# Objective\nImprove it.",
            artifact_name="candidate.py",
            metric_name="combined_score",
            metric_direction="maximize",
            wall_seconds=300,
            closeout_seconds=60,
            concurrency=2,
            worker_host="pi-rpc",
            worker_model="bench-openai/gpt-5.6-luna",
        )
        self.assertEqual(spec["budget"], {"max_candidates": 2, "max_parallel": 2})
        self.assertEqual(spec["edit_surface"]["allow"], ["candidate.py"])
        self.assertNotIn(".bench-runtime/**", spec["edit_surface"]["allow"])
        self.assertEqual(spec["strategy"]["worker_budget"]["max_runtime_seconds"], 120)

    def test_promotion_patch_is_applied_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir()
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            subprocess.run(
                ["git", "-C", str(workspace), "config", "user.name", "Test"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(workspace),
                    "config",
                    "user.email",
                    "test@example.invalid",
                ],
                check=True,
            )
            artifact = workspace / "candidate.py"
            artifact.write_text("value = 1\n")
            subprocess.run(
                ["git", "-C", str(workspace), "add", "candidate.py"], check=True
            )
            subprocess.run(
                ["git", "-C", str(workspace), "commit", "-qm", "seed"], check=True
            )
            artifact.write_text("value = 2\n")
            patch_path = Path(temp_dir) / "promotion.patch"
            patch_path.write_text(
                subprocess.run(
                    ["git", "-C", str(workspace), "diff", "--", "candidate.py"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout
            )
            artifact.write_text("value = 1\n")
            self.assertEqual(
                experiment.apply_promotion_patch(workspace, patch_path), "applied"
            )
            self.assertEqual(artifact.read_text(), "value = 2\n")
            self.assertEqual(
                experiment.apply_promotion_patch(workspace, patch_path),
                "already_applied",
            )

    def test_evaluator_budget_snapshot_uses_controller_runtime_at_t0(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            workspace = temp / "workspace"
            runtime = temp / "controller-runtime"
            workspace.mkdir()
            runtime.mkdir()
            (workspace / "task.json").write_text(
                json.dumps({"controller_runtime_dir": str(runtime)}) + "\n"
            )
            expected = {
                "total_claimed": 2,
                "public_claimed": 2,
                "final_claimed": 0,
            }
            (runtime / "budget.json").write_text(json.dumps(expected) + "\n")

            self.assertEqual(
                experiment.evaluator_budget_for_workspace(workspace), expected
            )

    def test_pi_model_config_uses_environment_reference_not_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            experiment.write_pi_models_config(
                target,
                api_base="http://proxy.example/v1",
                model="gpt-5.6-luna",
            )
            raw = (target / "models.json").read_text()
            payload = json.loads(raw)
            provider = payload["providers"][experiment.PI_PROVIDER_ID]
            self.assertEqual(provider["apiKey"], "$OPENAI_API_KEY")
            self.assertEqual(
                provider["models"][0]["thinkingLevelMap"], {"high": "high"}
            )
            self.assertNotRegex(raw, r"\bsk-[A-Za-z0-9_-]{16,}\b")

    def test_codex_provider_args_select_responses_and_high_reasoning(self) -> None:
        args = experiment.codex_provider_args("http://proxy.example/v1")
        joined = "\n".join(args)
        self.assertIn('wire_api="responses"', joined)
        self.assertIn('env_key="OPENAI_API_KEY"', joined)
        self.assertIn('model_reasoning_effort="high"', joined)

    def test_codex_goal_plus_mcp_args_register_runtime_explicitly(self) -> None:
        joined = "\n".join(experiment.codex_goal_plus_mcp_args())
        self.assertIn('approval_policy="never"', joined)
        self.assertIn('mcp_servers.goal-plus.command="goal-plus"', joined)
        self.assertIn('mcp_servers.goal-plus.args=["--root", ".gp"]', joined)
        self.assertIn("mcp_servers.goal-plus.tool_timeout_sec=300", joined)
        self.assertIn(
            'mcp_servers.goal-plus.default_tools_approval_mode="approve"', joined
        )
        self.assertIn("mcp_servers.goal-plus.enabled=true", joined)

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
