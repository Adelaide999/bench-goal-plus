from __future__ import annotations

import unittest
import re
import subprocess

from sforge.harness.agent.factory import get_agent_class
from sforge.harness.agent.pi import PiAgent
from sforge.harness.agent.pi_goal_plus import PiGoalPlusAgent
from sforge.harness.agent.pi_goal_plus_provider import PiGoalPlusProviderAgent
from sforge.harness.agent.codex_goal_plus import CodexGoalPlusAgent
from sforge.harness.agent.codex_goal_plus_solo import CodexGoalPlusSoloAgent
from sforge.harness.config import SForgeConfig


class EdgeBenchUpstreamGoalPlusContractTest(unittest.TestCase):
    def test_all_goal_plus_agents_inherit_native_host(self) -> None:
        for agent_class, model in (
            (PiGoalPlusAgent, "gpt-test"),
            (PiGoalPlusProviderAgent, "zai/glm-test"),
            (CodexGoalPlusAgent, "gpt-test"),
            (CodexGoalPlusSoloAgent, "gpt-test"),
        ):
            with self.subTest(agent=agent_class.name):
                command = agent_class(SForgeConfig()).format_run_cmd("prompt.md", model=model)
                self.assertNotIn("strategy.agent_harness", command)
                self.assertNotIn("strategy.worker_host", command)
                self.assertNotIn("agent_profile", command)
                self.assertNotIn("evidence_annotator.host", command)
                self.assertIn("parallel_loops", command)
                self.assertIn("strategy.selection.ranking_keys", command)
                self.assertIn("hard_score", command)
                self.assertIn("strategy.allocation null", command)
                self.assertNotIn("search_scheduler", command)
                self.assertNotIn("Search-routed work item", command)
                for tool in (
                    "goal_plus_status", "goal_plus_search_freeze_spec", "goal_plus_search_create",
                    "goal_plus_session_run", "goal_plus_session_wait", "goal_plus_session_close",
                    "goal_plus_search_select", "goal_plus_search_promote",
                    "goal_plus_record_search_result", "goal_plus_set_status", "goal_plus_search_report",
                ):
                    self.assertIn(tool, command)
                self.assertIsNone(re.search(r"\b(?:search_promote|search_report|search_start_agent_session|goal_plus_session_open|goal_plus_session_wake)\b", command))
                checked = subprocess.run(["bash", "-n", "-c", command], capture_output=True, text=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_pi_methods_pin_reasoning_and_register_goal_plus_host(self) -> None:
        plain = PiAgent(SForgeConfig())
        goal_plus = PiGoalPlusAgent(SForgeConfig())

        self.assertIs(get_agent_class("pi-goal-plus"), PiGoalPlusAgent)
        self.assertIn(
            '--thinking "$SFORGE_PI_REASONING_EFFORT"',
            plain.format_run_cmd("/tmp/prompt.md", model="gpt-test"),
        )
        self.assertIn(
            '--thinking "$SFORGE_PI_REASONING_EFFORT"',
            goal_plus.format_run_cmd("/tmp/prompt.md", model="gpt-test"),
        )

    def test_pi_goal_plus_uses_profile_driven_worker_and_closeout_budgets(
        self,
    ) -> None:
        agent = PiGoalPlusAgent(
            SForgeConfig(
                agent_extra_env={
                    "SFORGE_GOAL_PLUS_PARALLEL_NUM": "2",
                    "SFORGE_GOAL_PLUS_WORKER_RUNTIME_SECONDS": "240",
                    "SFORGE_GOAL_PLUS_WORKER_MIN_RUNTIME_SECONDS": "180",
                    "SFORGE_GOAL_PLUS_MIN_VERIFIER_RUNS": "1",
                    "SFORGE_GOAL_PLUS_CLOSEOUT_RESERVE_SECONDS": "60",
                    "SFORGE_GOAL_PLUS_FINALIZATION_GRACE_SECONDS": "120",
                }
            )
        )
        command = agent.format_run_cmd("/tmp/prompt.md", model="gpt-test")

        self.assertIn(
            "/goal-plus mode=autonomous max_parallel=2 "
            "workspace_provider=git_worktree promotion_mode=artifact_only "
            "strategy=agent_guided workers=openai-codex/gpt-test*2 ",
            command,
        )
        self.assertIn("parallel_loops", command)
        self.assertIn('"max_runtime_seconds": 240', command)
        self.assertIn("180 seconds per worker", command)
        self.assertIn("1 verifier result(s) per worker", command)
        self.assertIn("Reserve 60 seconds", command)
        self.assertNotIn("min_runtime_seconds", command)
        self.assertNotIn("min_verifier_runs", command)
        self.assertNotIn("reserve_closeout_seconds", command)
        self.assertNotIn('"max_turns"', command)
        self.assertIn("SFORGE_AGENT_HARD_DEADLINE", command)
        self.assertEqual(agent.get_finalization_grace_seconds(), 120)

    def test_pi_goal_plus_cross_process_resume_reauthorizes_exactly(self) -> None:
        agent = PiGoalPlusAgent(SForgeConfig())

        command = agent.format_run_cmd(
            "/tmp/prompt.md", model="gpt-test", resume=True
        )

        self.assertIn("sforge-goal-plus-submit --details --if-new", command)
        self.assertIn("edgebench-resume-sync.log", command)
        self.assertIn("'/goal-plus resume'", command)
        self.assertIn('--session "$SFORGE_PI_GOAL_PLUS_SESSION_ID"', command)
        self.assertNotIn("--goal-plus-headless-continue", command)
        self.assertIn("GOAL_PLUS_RESUME_EXPECTATION", command)
        self.assertNotIn("Continue working", command)


if __name__ == "__main__":
    unittest.main()
