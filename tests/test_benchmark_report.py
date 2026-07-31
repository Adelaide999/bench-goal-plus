from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from scripts import benchmark_report


class BenchmarkReportTest(unittest.TestCase):
    def temporary_campaign(self) -> tempfile.TemporaryDirectory[str]:
        temp_root = Path.cwd() / ".tmp" / "test-benchmark-report"
        temp_root.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=temp_root)

    def test_edgebench_export_preserves_missing_telemetry(self) -> None:
        with self.temporary_campaign() as temporary:
            campaign = Path(temporary)
            campaign_id = (
                "edgebench-51-codex-gpt-5-6-sol-medium-2h-k1-c2-20260724-1811"
            )
            payload = {
                "campaign_id": campaign_id,
                "live_search_concurrency": 2,
                "cell_concurrency": 2,
                "paper_reference": {"tasks": {"task-a": {"mean": 40.0}}},
                "cells": [
                    {
                        "task_id": "task-a",
                        "method": "goal-plus-codex",
                        "model": "gpt-5.6-sol",
                        "reasoning_effort": "medium",
                        "metric_direction": "maximize",
                        "wall_time_seconds": 7200,
                        "live_search_concurrency": 2,
                        "outer_replicas": 1,
                        "completed_trajectories": 1,
                        "valid_trajectories": 1,
                        "completion_evidence": {
                            "passed": True,
                            "checks": {
                                "actual_worker_launches": {
                                    "expected": 2,
                                    "actual": 2,
                                },
                                "candidates": {"expected": 2, "actual": 2},
                                "agent_sessions": {"expected": 2, "actual": 2},
                                "worker_verifier_runs": {
                                    "expected": 2,
                                    "actual": 3,
                                },
                            },
                        },
                        "best": {"raw_score": 0, "edgebench_score": 50.0},
                        "observations": [
                            {
                                "evaluator_calls": 3,
                                "runtime_seconds": 7000.0,
                                "codex_usage": {
                                    "coverage": "agent_output_only",
                                    "tokens": {"output_tokens": 25},
                                },
                            }
                        ],
                    }
                ],
            }
            (campaign / "comparison.json").write_text(json.dumps(payload))
            (campaign / "comparison.md").write_text("# Native comparison\n")

            rows = benchmark_report.edgebench_rows(payload)
            self.assertEqual(rows[0]["actual_goal_plus_subagents"], 2)
            self.assertEqual(rows[0]["goal_plus_candidates"], 2)
            self.assertEqual(rows[0]["goal_plus_worker_sessions"], 2)
            self.assertEqual(rows[0]["goal_plus_verifier_runs"], 3)
            self.assertTrue(rows[0]["completion_evidence_passed"])

            outputs = benchmark_report.export(campaign, None, None)

            self.assertEqual(Path(outputs["markdown"]).name, "report.md")
            workbook = Path(outputs["xlsx"])
            self.assertEqual(workbook.name, campaign_id + ".xlsx")
            self.assertEqual(
                (campaign / "report.md").read_text(), "# Native comparison\n"
            )
            with zipfile.ZipFile(workbook) as archive:
                self.assertEqual(archive.testzip(), None)
                results_xml = archive.read("xl/worksheets/sheet2.xml")
                summary_xml = archive.read("xl/worksheets/sheet1.xml").decode()
                ElementTree.fromstring(results_xml)
                rendered = results_xml.decode()
                self.assertIn("live_search_concurrency_k", summary_xml)
                self.assertIn("cell_concurrency_c", summary_xml)
                self.assertIn('<v>2</v>', summary_xml)
                self.assertIn("input_tokens", rendered)
                self.assertIn("agent_output_only", rendered)
                self.assertIn("raw_metric_direction", rendered)
                self.assertIn("actual_goal_plus_subagents", rendered)
                self.assertIn("goal_plus_worker_sessions", rendered)
                self.assertIn("completion_evidence_passed", rendered)
                self.assertIn('r="R2" s="2"/', rendered)

    def test_generic_export_keeps_raw_directional_fields(self) -> None:
        with self.temporary_campaign() as temporary:
            campaign = Path(temporary)
            payload = {
                "campaign_id": "generic-one",
                "state": "finished",
                "budget": {
                    "wall_time_seconds": 300,
                    "requested_live_concurrency": 2,
                    "cell_concurrency": 1,
                    "attempts": 3,
                },
                "records": [
                    {
                        "benchmark_id": "local-vliw",
                        "task_id": "vliw",
                        "cell_id": "cell-1",
                        "method": "plain-codex",
                        "status": "incomplete",
                        "incomplete_reason": "Codex completed 0 spawn_agent calls",
                        "protocol": {
                            "metric_name": "cycles",
                            "direction": "minimize",
                        },
                        "score": {
                            "final": 42,
                            "raw_metrics": {"cycles": 42, "validity": 1},
                            "directional_gain": 8,
                            "valid": True,
                        },
                        "execution": {
                            "evaluator_calls": {
                                "total_claimed": 4,
                                "coverage": "complete",
                            },
                            "usage": {
                                "input_tokens": 100,
                                "output_tokens": 20,
                                "coverage": "complete",
                            },
                        },
                    }
                ],
            }
            (campaign / "campaign-summary.json").write_text(json.dumps(payload))

            outputs = benchmark_report.export(campaign, None, None)

            with zipfile.ZipFile(outputs["xlsx"]) as archive:
                summary = archive.read("xl/worksheets/sheet1.xml").decode()
                rendered = archive.read("xl/worksheets/sheet2.xml").decode()
            self.assertIn("live_search_concurrency_k", summary)
            self.assertIn("cell_concurrency_c", summary)
            self.assertIn("independent_attempts_r", summary)
            self.assertIn('<v>3</v>', summary)
            self.assertIn("raw_final_metric", rendered)
            self.assertIn("raw_metrics", rendered)
            self.assertIn("directional_gain", rendered)
            self.assertIn("minimize", rendered)
            self.assertIn("incomplete_reason", rendered)
            self.assertIn("Codex completed 0 spawn_agent calls", rendered)

    def test_campaign_id_cannot_escape_output_directory(self) -> None:
        with self.temporary_campaign() as temporary:
            campaign = Path(temporary)
            payload = {"campaign_id": "../../outside", "records": []}
            (campaign / "campaign-summary.json").write_text(json.dumps(payload))

            outputs = benchmark_report.export(campaign, None, None)

            self.assertEqual(Path(outputs["xlsx"]).parent, campaign)
            self.assertEqual(Path(outputs["xlsx"]).name, "outside.xlsx")


if __name__ == "__main__":
    unittest.main()
