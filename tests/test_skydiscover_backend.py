from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters import skydiscover_bridge  # noqa: E402
from experiments.backends import skydiscover  # noqa: E402
from experiments.openevolve_compare import experiment, reporting  # noqa: E402


class SkyDiscoverBackendTest(unittest.TestCase):
    def test_method_is_registered_with_explicit_reasoning_effort(self) -> None:
        parser = experiment.build_parser()
        args = parser.parse_args(
            [
                "prepare",
                "--method",
                "skydiscover-best-of-n",
                "--reasoning-effort",
                "medium",
            ]
        )
        self.assertEqual(args.reasoning_effort, "medium")
        self.assertEqual(
            skydiscover.algorithm_for_method(args.method),
            "best_of_n",
        )

    def test_config_is_secret_free_and_preserves_native_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "skydiscover.yaml"
            payload = skydiscover.write_config(
                target,
                algorithm="best_of_n",
                task_prompt="# Objective\nImprove the candidate.",
                file_suffix=".py",
                evaluator_timeout_seconds=30,
                concurrency=2,
                iterations_ceiling=99,
                seed=7,
                reasoning_effort="medium",
            )
            raw = target.read_text()
            self.assertNotRegex(raw, r"\bsk-[A-Za-z0-9_-]{16,}\b")
            self.assertEqual(payload["search"]["type"], "best_of_n")
            self.assertEqual(payload["max_parallel_iterations"], 2)
            self.assertEqual(payload["max_iterations"], 99)
            self.assertEqual(payload["llm"]["reasoning_effort"], "medium")
            self.assertFalse(payload["monitor"]["enabled"])

    def test_bridge_preserves_candidate_workspace_and_maps_minimize_metric(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            template = temp / "template"
            template.mkdir()
            (template / "task.json").write_text(
                json.dumps(
                    {
                        "artifact_name": "candidate.py",
                        "primary_metric": "cost",
                        "direction": "minimize",
                    }
                )
            )
            (template / "candidate.py").write_text("seed\n")
            candidate = temp / "proposed.py"
            candidate.write_text("improved\n")
            evaluation_root = temp / "evaluations"
            evaluation_root.mkdir()
            report = {
                "valid": True,
                "primary_metric": {
                    "name": "cost",
                    "value": 12.5,
                    "direction": "minimize",
                },
                "raw_metrics": {"cost": 12.5},
            }
            environment = {
                skydiscover_bridge.TEMPLATE_ENV: str(template),
                skydiscover_bridge.EVALUATION_ROOT_ENV: str(evaluation_root),
            }
            with (
                mock.patch.dict(os.environ, environment, clear=False),
                mock.patch.object(
                    skydiscover_bridge,
                    "evaluate_workspace",
                    return_value=report,
                ) as evaluate,
            ):
                metrics = skydiscover_bridge.evaluate(str(candidate))

            self.assertEqual(
                metrics,
                {"cost": 12.5, "combined_score": -12.5, "validity": 1.0},
            )
            evaluate.assert_called_once()
            call_workspace = evaluate.call_args.args[0]
            self.assertEqual((call_workspace / "candidate.py").read_text(), "improved\n")
            self.assertTrue((call_workspace / "skydiscover-eval.json").is_file())
            self.assertTrue(call_workspace.is_dir())

    def test_invalid_report_maps_only_to_finite_search_sentinel(self) -> None:
        metrics = skydiscover_bridge.metrics_from_report(
            {
                "valid": False,
                "primary_metric": {"name": "score", "value": None},
                "raw_metrics": {"error": "invalid"},
            },
            metric_name="score",
            direction="maximize",
        )
        self.assertEqual(metrics, {"combined_score": -1e300, "validity": 0.0})

    def test_reporting_accepts_common_backend_usage_contract(self) -> None:
        usage = reporting.collect_usage(
            {
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "coverage": "native response usage",
                }
            }
        )
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 2)
        self.assertEqual(usage["coverage"], "native response usage")


if __name__ == "__main__":
    unittest.main()
