from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


from experiments.openevolve_compare import reporting


class OpenEvolveReportingTest(unittest.TestCase):
    def make_campaign(self, root: Path) -> tuple[Path, Path]:
        campaign = root / "campaign"
        run = campaign / "task-one" / "future-agent"
        pending = campaign / "task-two" / "another-agent"
        run.mkdir(parents=True)
        pending.mkdir(parents=True)
        (run / "experiment.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "finished",
                    "task_id": "task|one",
                    "method": "future-agent",
                    "model": "model-x",
                    "reasoning_effort": "medium",
                    "seed": 7,
                    "budget": {"wall_time_seconds": 100, "concurrency": 2},
                    "task": {
                        "primary_metric": "cost",
                        "direction": "minimize",
                        "upstream_commit": "abc123",
                        "evaluator_sha256": "def456",
                    },
                    "execution": {
                        "duration_seconds": 40.5,
                        "deadline_reached": False,
                        "returncode": 0,
                        "selected_lane": "lane-01",
                        "evaluator_calls": {
                            "total_claimed": 8,
                            "public_claimed": 6,
                            "final_claimed": 2,
                        },
                        "codex": {
                            "coverage": "all lanes",
                            "lanes": [
                                {
                                    "top_level_usage": {
                                        "input_tokens": 100,
                                        "output_tokens": 10,
                                    }
                                },
                                {
                                    "top_level_usage": {
                                        "input_tokens": 200,
                                        "output_tokens": 20,
                                    }
                                },
                            ],
                        },
                    },
                }
            )
        )
        (run / "seed-evals.json").write_text(
            json.dumps(
                {
                    "lanes": [
                        {"evaluation": {"primary_metric": {"value": 10.0}}},
                        {"evaluation": {"primary_metric": {"value": 8.0}}},
                    ]
                }
            )
        )
        (run / "final-eval.json").write_text(
            json.dumps(
                {
                    "valid": True,
                    "primary_metric": {
                        "name": "cost",
                        "value": 6.0,
                        "direction": "minimize",
                    },
                    "raw_metrics": {"cost": 6.0, "quality": 0.9},
                }
            )
        )
        (run / "final-candidate.py").write_text("result = 6\n")
        campaign_payload = {
            "schema_version": 1,
            "model": "model-x",
            "seed": 7,
            "budget": {"wall_time_seconds": 100, "concurrency": 2},
            "entries": [
                {
                    "task_id": "task|one",
                    "method": "future-agent",
                    "run_dir": str(run),
                    "prepared": True,
                    "error": None,
                },
                {
                    "task_id": "task-two",
                    "method": "another-agent",
                    "run_dir": str(pending),
                    "prepared": True,
                    "error": None,
                },
            ],
        }
        (campaign / "campaign.json").write_text(json.dumps(campaign_payload))
        (campaign / "campaign-results.json").write_text(
            json.dumps(
                {
                    "results": [
                        {
                            "task_id": "task|one",
                            "method": "future-agent",
                            "run_dir": str(run),
                            "status": "finished",
                            "returncode": 0,
                            "error": None,
                        }
                    ]
                }
            )
        )
        return campaign, run

    def test_collects_dynamic_methods_pending_cells_and_directional_gain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            campaign, run = self.make_campaign(Path(temp_dir))
            report = reporting.collect_sources([campaign, run])

            self.assertEqual(report["record_count"], 2)
            finished = next(
                item for item in report["records"] if item["method"] == "future-agent"
            )
            self.assertEqual(finished["score"]["seed_values"], [10.0, 8.0])
            self.assertEqual(finished["score"]["seed_best"], 8.0)
            self.assertEqual(finished["score"]["final"], 6.0)
            self.assertEqual(finished["score"]["directional_gain"], 2.0)
            self.assertEqual(finished["execution"]["usage"]["input_tokens"], 300)
            self.assertEqual(finished["execution"]["usage"]["output_tokens"], 30)
            pending = next(
                item for item in report["records"] if item["method"] == "another-agent"
            )
            self.assertEqual(pending["status"], "prepared")
            self.assertIsNone(pending["score"]["final"])

            standalone_source = reporting.collect_sources([run])
            self.assertEqual(
                standalone_source["records"][0]["campaign_id"], campaign.name
            )

    def test_writes_portable_json_and_markdown_with_evidence_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            campaign, _ = self.make_campaign(Path(temp_dir))
            report = reporting.write_campaign_report(campaign)

            markdown = (campaign / "campaign-summary.md").read_text()
            payload = json.loads((campaign / "campaign-summary.json").read_text())
            self.assertEqual(payload, report)
            self.assertIn("task\\|one", markdown)
            self.assertIn("future-agent", markdown)
            self.assertIn("8..10", markdown)
            self.assertIn("cost=6; quality=0.9", markdown)
            self.assertIn("| 6 | 2 | cost=6; quality=0.9 | true |", markdown)
            self.assertIn("[final]", markdown)
            self.assertIn("Scores are raw evaluator metrics", markdown)

    def test_missing_telemetry_is_not_reported_as_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run = Path(temp_dir) / "standalone"
            run.mkdir()
            (run / "experiment.json").write_text(
                json.dumps(
                    {
                        "status": "finished",
                        "task_id": "task",
                        "method": "agent",
                        "task": {
                            "primary_metric": "score",
                            "direction": "maximize",
                        },
                    }
                )
            )
            record = reporting.collect_run(run)
            self.assertIsNone(record["execution"]["usage"].get("input_tokens"))
            self.assertIn("missing", record["execution"]["evaluator_calls"]["coverage"])


if __name__ == "__main__":
    unittest.main()
