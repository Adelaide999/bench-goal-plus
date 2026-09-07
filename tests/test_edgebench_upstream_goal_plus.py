from __future__ import annotations

import base64
import subprocess
import unittest

from sforge.harness.agent.factory import get_agent_class
from sforge.harness.agent.pi import PiAgent
from sforge.harness.agent.pi_goal_plus import PiGoalPlusAgent
from sforge.harness.agent.pi_goal_plus_provider import PiGoalPlusProviderAgent
from sforge.harness.agent.codex_goal_plus import CodexGoalPlusAgent
from sforge.harness.agent.codex_goal_plus_solo import CodexGoalPlusSoloAgent
from sforge.harness.config import SForgeConfig
from sforge.harness.agent.goal_plus_runtime import goal_plus_search_mode_config
from bench_goal_plus.search_scheduler import GoalPlusSearchScheduler, render_search_scheduler_instructions


class EdgeBenchUpstreamGoalPlusContractTest(unittest.TestCase):
    def test_scheduler_instructions_reach_all_native_adapters_as_literal_text(self) -> None:
        config = GoalPlusSearchScheduler(
            model="test/model", reasoning_effort="low", timeout_seconds=60,
            reward="evidence_llm_value/v3 @prompt literal $(exit 41) `exit 42`",
            allocation="value_guided_replace/v2",
        )
        instructions = render_search_scheduler_instructions(config)
        values = {"SFORGE_GOAL_PLUS_SEARCH_SCHEDULER_INSTRUCTIONS_B64":
                  base64.urlsafe_b64encode(instructions.encode()).decode()}
        fragment = goal_plus_search_mode_config(values)
        result = subprocess.run(["bash", "-c", f'printf "%s" "{fragment}"'],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, instructions)
        for agent_class in (PiGoalPlusAgent, PiGoalPlusProviderAgent, CodexGoalPlusAgent):
            with self.subTest(agent=agent_class.name):
                command = agent_class(SForgeConfig(agent_extra_env=values)).format_run_cmd(
                    "prompt.md", model="test/model",
                )
                self.assertIn(fragment, command)
                self.assertNotIn("parallel_loops", command)
                self.assertNotIn("__GOAL_PLUS_SEARCH_MODE_CONFIG__", command)

    def test_invalid_scheduler_encoding_is_rejected_before_launch(self) -> None:
        for encoded in ("!invalid", "", "AA=="):
            with self.subTest(encoded=encoded), self.assertRaises(ValueError):
                goal_plus_search_mode_config({
                    "SFORGE_GOAL_PLUS_SEARCH_SCHEDULER_INSTRUCTIONS_B64": encoded,
                })

    def test_all_goal_plus_agents_inherit_native_host(self) -> None:
        for agent_class, model in (
            (PiGoalPlusAgent, "gpt-test"),
            (PiGoalPlusProviderAgent, "zai/glm-test"),
            (CodexGoalPlusAgent, "gpt-test"),
            (CodexGoalPlusSoloAgent, "gpt-test"),
        ):
            with self.subTest(agent=agent_class.name):
                command = agent_class(SForgeConfig()).format_run_cmd("prompt.md", model=model)
                self.assertNotIn("strategy.worker_host", command)
                self.assertNotIn("agent_profile", command)
                self.assertNotIn("evidence_annotator.host", command)
                self.assertIn("parallel_loops", command)

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
            "workspace_backend=git_worktree promotion_mode=artifact_only "
            "strategy=agent_guided workers=openai-codex/gpt-test*2 ",
            command,
        )
        self.assertIn("Leave strategy.search_scheduler unset", command)
        self.assertIn('"max_runtime_seconds": 240', command)
        self.assertIn('"min_runtime_seconds": 180', command)
        self.assertIn('"min_verifier_runs": 1', command)
        self.assertIn("reserve_closeout_seconds to 60", command)
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
