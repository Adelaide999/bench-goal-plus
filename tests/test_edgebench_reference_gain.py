from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from experiments.edgebench.reference_gain import (
    identify_gains,
    parse_reference_table,
    render_markdown,
)


FIXTURE = """\
# EdgeBench

<summary><b>Per-Task Scores by Time Budget (51 tasks)</b></summary>

| Task | Category | Opus 4.8 | GPT-5.5 |
|:-----|:---------|:---------|:--------|
| task_a | Optimization | 10/15/20/25/28/30 | 5/7/9/11/12/14 |
| task_b | Systems & SE | —/—/—/—/—/— | 20/22/25/28/30/35 |
| task_c | Games | 50/51/52/53/54/55 | 45/46/47/48/49/50 |

</details>
"""


class EdgeBenchReferenceGainTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.readme = Path(self.temporary.name) / "README.md"
        self.readme.write_text(FIXTURE, encoding="utf-8")
        self.reference = parse_reference_table(self.readme, expected_task_count=3)

    def test_parser_preserves_models_curves_and_missing_scores(self) -> None:
        self.assertEqual(self.reference["task_count"], 3)
        self.assertEqual(self.reference["models"], ["Opus 4.8", "GPT-5.5"])
        self.assertEqual(
            self.reference["tasks"]["task_a"]["models"]["Opus 4.8"]["12"],
            30.0,
        )
        self.assertIsNone(
            self.reference["tasks"]["task_b"]["models"]["Opus 4.8"]["2"]
        )

    def test_identify_gains_compares_only_same_task_and_model(self) -> None:
        report = identify_gains(self.reference, min_gain=10.0)

        self.assertEqual(report["summary"]["comparable_task_model_pairs"], 5)
        self.assertEqual(report["summary"]["missing_endpoint_pairs"], 1)
        self.assertEqual(report["summary"]["qualifying_pairs"], 2)
        self.assertEqual(report["summary"]["qualifying_tasks"], 2)
        self.assertEqual(
            [
                (row["task_id"], row["model"], row["gain_points"])
                for row in report["candidates"]
            ],
            [("task_a", "Opus 4.8", 20.0), ("task_b", "GPT-5.5", 15.0)],
        )

    def test_model_filter_threshold_and_top_are_configurable(self) -> None:
        report = identify_gains(
            self.reference,
            models=["gpt-5.5"],
            min_gain=5.0,
            top=1,
        )

        self.assertEqual(report["comparison"]["models"], ["GPT-5.5"])
        self.assertEqual(report["summary"]["qualifying_pairs"], 3)
        self.assertEqual(report["summary"]["reported_pairs"], 1)
        self.assertEqual(report["candidates"][0]["task_id"], "task_b")

    def test_task_filter_can_require_multiple_models_to_improve(self) -> None:
        report = identify_gains(
            self.reference,
            min_gain=5.0,
            min_model_count=2,
        )

        self.assertEqual(
            report["summary"]["threshold_matching_pairs_before_task_filter"], 5
        )
        self.assertEqual(report["summary"]["qualifying_tasks"], 2)
        self.assertEqual(report["summary"]["qualifying_pairs"], 4)
        self.assertEqual(
            {row["task_id"] for row in report["candidates"]},
            {"task_a", "task_c"},
        )
        self.assertTrue(
            all(row["qualifying_models_for_task"] == 2 for row in report["candidates"])
        )

    def test_markdown_reports_provenance_and_raw_endpoints(self) -> None:
        report = identify_gains(self.reference, models=["Opus 4.8"], min_gain=10.0)
        markdown = render_markdown(report)

        self.assertIn("same-model checkpoint gains", markdown)
        self.assertIn("Source SHA256", markdown)
        self.assertIn(
            "| `task_a` | Optimization | Opus 4.8 | 10.0 | 30.0 | +20.0 |",
            markdown,
        )

    def test_invalid_comparison_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "start hour must be earlier"):
            identify_gains(self.reference, start_hour=12, end_hour=2)
        with self.assertRaisesRegex(ValueError, "unknown model"):
            identify_gains(self.reference, models=["missing-model"])
        with self.assertRaisesRegex(ValueError, "model count"):
            identify_gains(self.reference, min_model_count=0)


if __name__ == "__main__":
    unittest.main()
