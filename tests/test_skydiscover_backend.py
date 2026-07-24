from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "evidence" / "runs"
sys.path.insert(0, str(ROOT))

from adapters import skydiscover_bridge  # noqa: E402
from experiments.backends import skydiscover  # noqa: E402
from experiments.openevolve_compare import experiment, reporting  # noqa: E402


class SkyDiscoverBackendTest(unittest.TestCase):
    def test_methods_are_registered_with_explicit_reasoning_effort(self) -> None:
        parser = experiment.build_parser()
        for method, algorithm in (
            ("skydiscover-best-of-n", "best_of_n"),
            ("skydiscover-evox", "evox"),
            ("skydiscover-adaevolve", "adaevolve"),
        ):
            with self.subTest(method=method):
                args = parser.parse_args(
                    [
                        "prepare",
                        "--method",
                        method,
                        "--reasoning-effort",
                        "medium",
                    ]
                )
                self.assertEqual(args.reasoning_effort, "medium")
                self.assertEqual(
                    skydiscover.algorithm_for_method(args.method),
                    algorithm,
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

    def test_each_algorithm_gets_its_native_database_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            payloads = {}
            for algorithm in skydiscover.SUPPORTED_ALGORITHMS:
                payloads[algorithm] = skydiscover.write_config(
                    temp / f"{algorithm}.yaml",
                    algorithm=algorithm,
                    task_prompt="Improve the candidate.",
                    file_suffix=".py",
                    evaluator_timeout_seconds=30,
                    concurrency=1,
                    iterations_ceiling=1,
                    seed=7,
                    reasoning_effort="medium",
                )

            best_of_n = payloads["best_of_n"]["search"]
            self.assertEqual(best_of_n["database"]["best_of_n"], 5)
            self.assertNotIn(
                "auto_generate_variation_operators",
                best_of_n["database"],
            )

            evox = payloads["evox"]["search"]
            self.assertTrue(evox["share_llm"])
            self.assertTrue(
                evox["database"]["auto_generate_variation_operators"]
            )
            self.assertNotIn("best_of_n", evox["database"])

            adaevolve = payloads["adaevolve"]["search"]
            self.assertEqual(adaevolve["database"]["num_islands"], 2)
            self.assertTrue(adaevolve["database"]["use_adaptive_search"])
            self.assertTrue(adaevolve["database"]["use_dynamic_islands"])
            self.assertNotIn("best_of_n", adaevolve["database"])

            for payload in payloads.values():
                self.assertEqual(payload["search"]["database"]["random_seed"], 7)

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

    def test_evox_and_adaevolve_real_smoke_evidence_is_complete(self) -> None:
        cases = {
            "evox": {
                "evidence": EVIDENCE_ROOT
                / "2026-07-24-skydiscover-evox-function-minimization-smoke.json",
                "candidate_key": "candidate",
                "sha_key": "candidate_sha256",
            },
            "adaevolve": {
                "evidence": EVIDENCE_ROOT
                / "2026-07-24-skydiscover-adaevolve-function-minimization-smoke.json",
                "candidate_key": "generated_candidate",
                "sha_key": "generated_candidate_sha256",
            },
        }
        for algorithm, case in cases.items():
            with self.subTest(algorithm=algorithm):
                raw = case["evidence"].read_text()
                payload = json.loads(raw)
                self.assertEqual(payload["status"], "finished")
                self.assertEqual(payload["method"]["algorithm"], algorithm)
                self.assertEqual(payload["execution"]["returncode"], 0)
                self.assertEqual(payload["execution"]["completed_iterations"], 1)
                self.assertNotIn("/Users/", raw)
                self.assertIsNone(
                    re.search(
                        r"(?i)authorization\s*:|bearer\s+[A-Za-z0-9._-]{16,}",
                        raw,
                    )
                )

                candidate = ROOT / payload["evidence"][case["candidate_key"]]
                self.assertTrue(candidate.is_file())
                self.assertEqual(
                    hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    payload["result"][case["sha_key"]],
                )

        evox = json.loads(cases["evox"]["evidence"].read_text())
        self.assertGreater(
            evox["result"]["controller_final_primary_metric"],
            evox["result"]["seed_primary_metric"],
        )
        self.assertTrue(evox["method"]["variation_operator_labels_generated"])
        self.assertEqual(evox["execution"]["invalid_candidate_attempts"], 1)

        adaevolve = json.loads(cases["adaevolve"]["evidence"].read_text())
        self.assertTrue(adaevolve["execution"]["generated_candidate_valid"])
        self.assertFalse(adaevolve["execution"]["generated_candidate_selected"])
        self.assertLess(
            adaevolve["execution"]["generated_candidate_primary_metric"],
            adaevolve["result"]["seed_primary_metric"],
        )
        self.assertEqual(
            adaevolve["result"]["controller_final_primary_metric"],
            adaevolve["result"]["seed_primary_metric"],
        )


if __name__ == "__main__":
    unittest.main()
