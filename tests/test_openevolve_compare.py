from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock


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

        batch_args = parser.parse_args(
            [
                "prepare-batch",
                "--run-root",
                "campaign",
                "--methods",
                "goal-plus-codex",
            ]
        )
        self.assertEqual(batch_args.task_set, "cpu_portable")
        self.assertEqual(batch_args.methods, ["goal-plus-codex"])
        self.assertEqual(batch_args.wall_time_seconds, 300)
        self.assertEqual(batch_args.concurrency, 2)

    def test_prepare_batch_expands_every_task_method_cell(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_root = Path(temp_dir) / "campaign"
            args = experiment.build_parser().parse_args(
                [
                    "prepare-batch",
                    "--run-root",
                    str(run_root),
                    "--methods",
                    "plain-codex",
                    "goal-plus-codex",
                ]
            )
            tasks = [{"task_id": "one"}, {"task_id": "two"}]
            with (
                mock.patch.object(experiment, "list_catalog_tasks", return_value=tasks),
                mock.patch.object(experiment, "prepare", return_value=0) as prepare_mock,
            ):
                self.assertEqual(experiment.prepare_batch(args), 0)

            campaign = json.loads((run_root / "campaign.json").read_text())
            self.assertEqual(campaign["task_count"], 2)
            self.assertEqual(campaign["cell_count"], 4)
            self.assertEqual(campaign["prepared_count"], 4)
            self.assertEqual(prepare_mock.call_count, 4)
            self.assertEqual(
                {(item["task_id"], item["method"]) for item in campaign["entries"]},
                {
                    ("one", "plain-codex"),
                    ("one", "goal-plus-codex"),
                    ("two", "plain-codex"),
                    ("two", "goal-plus-codex"),
                },
            )

    def test_run_batch_preserves_results_and_continues_after_incomplete_cell(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            campaign_path = root / "campaign.json"
            campaign_path.write_text(
                json.dumps(
                    {
                        "model": "test-model",
                        "methods": ["goal-plus-codex"],
                        "entries": [
                            {
                                "task_id": "one",
                                "method": "goal-plus-codex",
                                "run_dir": str(root / "one"),
                                "prepared": True,
                                "error": None,
                            },
                            {
                                "task_id": "two",
                                "method": "goal-plus-codex",
                                "run_dir": str(root / "two"),
                                "prepared": True,
                                "error": None,
                            },
                        ],
                    }
                )
            )
            args = experiment.build_parser().parse_args(
                ["run-batch", "--campaign", str(campaign_path)]
            )
            with mock.patch.object(experiment, "execute", side_effect=[2, 0]) as run:
                self.assertEqual(experiment.run_batch(args), 2)

            results = json.loads((root / "campaign-results.json").read_text())
            self.assertEqual(run.call_count, 2)
            self.assertEqual(
                [item["status"] for item in results["results"]],
                ["incomplete", "finished"],
            )
            self.assertNotIn("api_base", results)
            with mock.patch.object(experiment, "execute") as resumed_run:
                self.assertEqual(experiment.run_batch(args), 2)
                resumed_run.assert_not_called()

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

    def test_goal_prompt_uses_natural_entry_and_complete_configuration(self) -> None:
        prompt = experiment.render_goal(
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
        self.assertTrue(prompt.startswith("/goal-plus mode=autonomous"))
        self.assertIn("budget.max_candidates=2", prompt)
        self.assertIn("budget.max_parallel=2", prompt)
        self.assertIn("240 seconds", prompt)
        self.assertIn("not hard-capped", prompt)
        self.assertIn("GOAL_PLUS_OUTER_DEADLINE_AT", prompt)
        self.assertIn('strategy.worker_host="pi-rpc"', prompt)
        self.assertIn('strategy.name="agent_guided"', prompt)
        self.assertIn(
            'strategy.worker_launch.model="bench-openai/gpt-5.6-luna"', prompt
        )
        self.assertIn('strategy.worker_launch.reasoning_effort="high"', prompt)
        self.assertIn("Metric: `combined_score` with direction `maximize`", prompt)
        self.assertIn("python3 .goal-plus-verifiers/primary_metric.py", prompt)
        self.assertIn("do not run a duplicate parent-side process verification", prompt)
        self.assertIn("allow only `candidate.py`", prompt)
        self.assertNotIn("goal_plus_id=", prompt)
        self.assertNotIn("search_start_agent_session", prompt)

    def test_plain_and_goal_plus_prompts_share_exact_common_body(self) -> None:
        task = "# Objective\nImprove it."
        common = experiment.render_plain_prompt(task, 300, 60)
        prompt = experiment.render_goal(
            task_text=task,
            artifact_name="candidate.py",
            metric_name="combined_score",
            metric_direction="maximize",
            wall_seconds=300,
            closeout_seconds=60,
            concurrency=2,
            worker_host="codex",
            worker_model="gpt-5.6-luna",
        )
        self.assertTrue(
            prompt.startswith(
                "/goal-plus mode=autonomous\n\n"
                + common.rstrip()
                + "\n\n# Goal Plus configuration"
            )
        )
        self.assertEqual(common, experiment.render_plain_prompt(task, 300, 60))
        self.assertNotIn("independent lane", common)
        self.assertNotIn("controller-prepared", prompt)

    def test_goal_plus_completion_requires_worker_verifier_evidence_for_every_candidate(
        self,
    ) -> None:
        base_state = {
            "goals": [
                {
                    "goal_plus_id": "gp_0001",
                    "status": "complete",
                    "linked_run_id": "run_test",
                }
            ],
            "runs": [
                {
                    "run_id": "run_test",
                    "candidate_count": 2,
                    "bound_candidate_count": 2,
                    "worker_verified_candidate_count": 2,
                    "unbound_agent_session_count": 0,
                    "session_counts_by_candidate": {"c001": 1, "c002": 1},
                }
            ],
        }
        kwargs = {
            "expected_concurrency": 2,
            "expected_goal_plus_id": "gp_0001",
            "expected_run_id": "run_test",
        }
        self.assertIsNone(experiment.goal_plus_incomplete_reason(base_state, **kwargs))

        missing_worker_evidence = json.loads(json.dumps(base_state))
        missing_worker_evidence["runs"][0]["worker_verified_candidate_count"] = 1
        self.assertIn(
            "completed worker verifier evidence",
            experiment.goal_plus_incomplete_reason(missing_worker_evidence, **kwargs),
        )
        self.assertIsNone(
            experiment.goal_plus_incomplete_reason(
                missing_worker_evidence,
                minimum_worker_verified_candidates=1,
                **kwargs,
            )
        )

        duplicate_session = json.loads(json.dumps(base_state))
        duplicate_session["runs"][0]["session_counts_by_candidate"] = {
            "c001": 2,
            "c002": 2,
        }
        self.assertIn(
            "exactly one session per candidate",
            experiment.goal_plus_incomplete_reason(duplicate_session, **kwargs),
        )

        duplicate_goal = json.loads(json.dumps(base_state))
        duplicate_goal["goals"].append(
            {
                "goal_plus_id": "gp_0002",
                "status": "complete",
                "linked_run_id": "run_test",
            }
        )
        self.assertIn(
            "duplicate Goal Plus records",
            experiment.goal_plus_incomplete_reason(duplicate_goal, **kwargs),
        )

    def test_natural_goal_plus_completion_ignores_aborted_search_history(
        self,
    ) -> None:
        state = {
            "goals": [
                {
                    "goal_plus_id": "gp_0001",
                    "status": "complete",
                    "linked_run_id": "run_final",
                }
            ],
            "runs": [
                {
                    "run_id": "run_aborted",
                    "status": "aborted",
                    "candidate_count": 0,
                    "bound_candidate_count": 0,
                    "worker_verified_candidate_count": 0,
                    "unbound_agent_session_count": 0,
                    "session_counts_by_candidate": {},
                },
                {
                    "run_id": "run_final",
                    "status": "completed",
                    "candidate_count": 2,
                    "bound_candidate_count": 2,
                    "worker_verified_candidate_count": 2,
                    "unbound_agent_session_count": 0,
                    "session_counts_by_candidate": {"c001": 1, "c002": 1},
                },
            ],
        }
        self.assertIsNone(
            experiment.goal_plus_incomplete_reason(
                state,
                expected_concurrency=2,
            )
        )

    def test_goal_plus_configuration_keeps_runtime_files_outside_edit_surface(
        self,
    ) -> None:
        prompt = experiment.render_goal(
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
        self.assertIn("allow only `candidate.py`", prompt)
        self.assertIn("deny `evaluate.py`", prompt)
        self.assertIn("`.goal-plus-verifiers/**`", prompt)
        self.assertIn("allow at most one changed file", prompt)
        self.assertIn('workspace.backend="copy"', prompt)
        self.assertIn("strategy.worker_budget.max_runtime_seconds=60", prompt)
        self.assertIn("total budget, not a success criterion", prompt)

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
