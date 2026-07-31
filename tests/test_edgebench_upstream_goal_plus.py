from __future__ import annotations

import unittest

from sforge.harness.agent.factory import get_agent_class
from sforge.harness.agent.pi import PiAgent
from sforge.harness.agent.pi_goal_plus import PiGoalPlusAgent
from sforge.harness.config import SForgeConfig


class EdgeBenchUpstreamGoalPlusContractTest(unittest.TestCase):
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
                    "SFORGE_GOAL_PLUS_MAX_PARALLEL": "2",
                    "SFORGE_GOAL_PLUS_WORKER_RUNTIME_SECONDS": "240",
                    "SFORGE_GOAL_PLUS_FINALIZATION_GRACE_SECONDS": "120",
                }
            )
        )
        command = agent.format_run_cmd("/tmp/prompt.md", model="gpt-test")

        self.assertIn("budget.max_parallel to 2", command)
        self.assertIn('"max_runtime_seconds": 240', command)
        self.assertNotIn('"max_turns"', command)
        self.assertIn("SFORGE_AGENT_HARD_DEADLINE", command)
        self.assertEqual(agent.get_finalization_grace_seconds(), 120)


if __name__ == "__main__":
    unittest.main()
