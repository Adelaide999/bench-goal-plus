from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from experiments.benchmark_compare import experiment
from experiments.benchmark_compare.pi_worker_launcher import (
    GOAL_PLUS_WORKER_LAUNCHER_ENV,
    SANDBOX_POLICY_ENV,
)


class ZSoftPiSandboxTest(unittest.TestCase):
    def tearDown(self) -> None:
        experiment.configure_adapter("heurigym")

    def test_detect_and_l1_publish_distinct_read_only_paths(self) -> None:
        experiment.configure_adapter("zsoft-detect")
        detect = experiment._pi_worker_sandbox_policy("CUSTOM_API_KEY")
        self.assertEqual(detect["engine"], "bubblewrap")
        self.assertEqual(detect["evaluation_mode"], "blind")
        self.assertEqual(detect["workspace_access"], "read_only")
        self.assertEqual(detect["read_only_workspace_paths"], ["source", "schemas"])
        self.assertEqual(detect["writable_workspace_paths"], ["submission"])
        self.assertIn("CUSTOM_API_KEY", detect["pass_env"])

        experiment.configure_adapter("zsoft-l1")
        l1 = experiment._pi_worker_sandbox_policy("CUSTOM_API_KEY")
        self.assertEqual(l1["evaluation_mode"], "blind")
        self.assertEqual(l1["read_only_workspace_paths"], ["public"])
        self.assertEqual(l1["writable_workspace_paths"], ["poc"])

    def test_environment_configuration_is_fail_closed_and_records_no_values(
        self,
    ) -> None:
        experiment.configure_adapter("zsoft-detect")
        policy = experiment._pi_worker_sandbox_policy("CUSTOM_API_KEY")
        manifest = {
            "method": "goal-plus-pi",
            "goal_plus_config": {"worker_sandbox": policy},
        }
        environment = {
            "PATH": "/usr/bin",
            "CUSTOM_API_KEY": "secret-value",
        }
        with (
            mock.patch.object(
                experiment.shutil, "which", return_value="/usr/bin/bwrap"
            ),
            mock.patch.object(experiment, "_require_pi_worker_launcher_runtime"),
        ):
            experiment._configure_pi_worker_sandbox_environment(
                manifest,
                environment,
                Path("/runtime/bin"),
                "CUSTOM_API_KEY",
            )

        self.assertEqual(json.loads(environment[SANDBOX_POLICY_ENV]), policy)
        self.assertEqual(
            environment[GOAL_PLUS_WORKER_LAUNCHER_ENV],
            str(experiment.PI_WORKER_LAUNCHER),
        )
        self.assertFalse(manifest["pi_worker_sandbox"]["environment_values_persisted"])
        self.assertEqual(manifest["pi_worker_sandbox"]["owner"], "bench-goal-plus")
        self.assertNotIn("secret-value", json.dumps(manifest))

    def test_old_or_tampered_manifest_cannot_disable_sandbox(self) -> None:
        experiment.configure_adapter("zsoft-l1")
        with self.assertRaisesRegex(RuntimeError, "re-prepare"):
            experiment._configure_pi_worker_sandbox_environment(
                {"method": "goal-plus-pi", "goal_plus_config": {}},
                {"PATH": "/usr/bin"},
                Path("/runtime/bin"),
                "OPENAI_API_KEY",
            )

        with self.assertRaisesRegex(RuntimeError, "does not match"):
            experiment._configure_pi_worker_sandbox_environment(
                {
                    "method": "goal-plus-pi",
                    "goal_plus_config": {
                        "worker_sandbox": {
                            "engine": "bubblewrap",
                            "evaluation_mode": "blind",
                            "workspace_access": "read_only",
                            "read_only_workspace_paths": [],
                            "writable_workspace_paths": ["poc"],
                            "pass_env": ["OPENAI_API_KEY"],
                        }
                    },
                },
                {"PATH": "/usr/bin"},
                Path("/runtime/bin"),
                "OPENAI_API_KEY",
            )


if __name__ == "__main__":
    unittest.main()
