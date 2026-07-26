from __future__ import annotations

import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path

from bench_runtime_paths import ensure_temp_root


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "edgebench_timecurve",
    ROOT / "experiments" / "edgebench" / "timecurve.py",
)
assert SPEC and SPEC.loader
TIMECURVE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TIMECURVE
SPEC.loader.exec_module(TIMECURVE)


class EdgeBenchTimecurveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = (
            ensure_temp_root("test-edgebench-timecurve")
            / f"{self._testMethodName}-{time.time_ns()}"
        )
        self.campaign = self.temp / "campaign"
        self.tasks = self.temp / "tasks"
        self.output = self.campaign / "timecurve"
        self.campaign.mkdir(parents=True)
        self.tasks.mkdir(parents=True)
        self.original_tasks = TIMECURVE.TASKS_DIR
        TIMECURVE.TASKS_DIR = self.tasks

    def tearDown(self) -> None:
        TIMECURVE.TASKS_DIR = self.original_tasks

    @staticmethod
    def write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def make_campaign(self, task_id: str, *, state: str = "completed") -> tuple[dict, Path]:
        cell_id = f"{task_id}--plain-codex"
        run_id = f"campaign-{task_id}-plain-codex"
        self.write_json(
            self.campaign / "campaign.json",
            {
                "campaign_id": "campaign",
                "state": "running",
                "edgebench_commit": "edge123",
                "model": "gpt-test",
                "reasoning_effort": "medium",
                "cells": [
                    {
                        "cell_id": cell_id,
                        "task_id": task_id,
                        "method": "plain-codex",
                        "state": state,
                    }
                ],
            },
        )
        cell = {
            "cell_id": cell_id,
            "task_id": task_id,
            "method": "plain-codex",
            "model": "gpt-test",
            "state": state,
            "sforge_run_id": run_id,
            "wall_time_seconds": 7200,
            "eval_interval_seconds": 1800,
            "outer_replicas": 1,
        }
        self.write_json(self.campaign / "cells" / cell_id / "cell.json", cell)
        task_run = (
            self.campaign
            / "cells"
            / cell_id
            / "sforge"
            / "runs"
            / run_id
            / task_id
        )
        task_run.mkdir(parents=True)
        (task_run / "started_at").write_text("1000\n", encoding="utf-8")
        return cell, task_run

    def test_one_hour_uses_auto_two_prefix_and_joins_late_report(self) -> None:
        task_id = "score_task"
        self.write_json(
            self.tasks / f"{task_id}.json",
            {
                "task_id": task_id,
                "judge": {
                    "selection": "score_first",
                    "score_direction": "minimize",
                    "rescale": {"kind": "min_linear", "baseline": 100, "expert": 0},
                },
            },
        )
        cell, task_run = self.make_campaign(task_id)
        entries = [
            {
                "type": "submission",
                "round": "agent-1",
                "submission_id": "agent1",
                "status": "completed",
                "valid": True,
                "pass_rate": 1.0,
                "score": 90,
                "score_0_100": 10,
            },
            {
                "type": "submission",
                "round": "auto-1",
                "submission_id": "auto1",
                "status": "completed",
                "valid": True,
                "pass_rate": 1.0,
                "score": 80,
                "score_0_100": 20,
            },
            {
                "type": "submission",
                "round": "agent-2",
                "submission_id": "late",
                "status": "queued",
                "valid": None,
                "score": None,
            },
            {
                "type": "submission",
                "round": "auto-2",
                "submission_id": "anchor",
                "status": "completed",
                "valid": True,
                "pass_rate": 1.0,
                "score": 75,
                "score_0_100": 25,
            },
            {
                "type": "submission",
                "round": "agent-3",
                "submission_id": "after",
                "status": "completed",
                "valid": True,
                "pass_rate": 1.0,
                "score": 60,
                "score_0_100": 40,
            },
        ]
        self.write_json(task_run / "run_history.json", {"entries": entries})
        (task_run / "auto_eval_ticks.log").write_text(
            "[1970-01-01T00:30:00] submitted 10 bytes -> auto1 round=auto-1\n"
            "[1970-01-01T01:00:00] submitted 10 bytes -> anchor round=auto-2\n",
            encoding="utf-8",
        )
        late_report = (
            self.campaign
            / "judge"
            / "runs"
            / cell["sforge_run_id"]
            / task_id
            / "submissions"
            / "agent-2"
            / "report.json"
        )
        self.write_json(
            late_report,
            {
                "task_id": task_id,
                "submission_id": "late",
                "valid": True,
                "pass_rate": 1.0,
                "score": 70,
                "score_0_100": 30,
                "score_0_100_extended": 30,
            },
        )

        payload = TIMECURVE.build_timecurve(self.campaign, [1.0], self.output)
        row = payload["rows"][0]

        self.assertEqual(row["status"], "available")
        self.assertTrue(row["strict_checkpoint"])
        self.assertEqual(row["best_round"], "agent-2")
        self.assertEqual(row["raw_score"], 70)
        self.assertEqual(row["score_0_100"], 30)
        self.assertEqual(row["candidate_count"], 4)
        self.assertEqual(row["scored_candidate_count"], 4)
        self.assertEqual(payload["aggregates"][0]["available_count"], 1)
        self.assertEqual(payload["aggregates"][0]["mean_score_0_100"], 30)

    def test_full_budget_uses_final_closeout_without_auto_four(self) -> None:
        task_id = "final_closeout_task"
        self.write_json(
            self.tasks / f"{task_id}.json",
            {
                "task_id": task_id,
                "judge": {
                    "selection": "score_first",
                    "score_direction": "maximize",
                    "rescale": {"kind": "linear", "lower": 0, "upper": 100},
                },
            },
        )
        _cell, task_run = self.make_campaign(task_id)
        self.write_json(
            task_run / "run_history.json",
            {
                "entries": [
                    {
                        "type": "submission",
                        "round": "auto-3",
                        "submission_id": "auto3",
                        "status": "completed",
                        "valid": True,
                        "score": 40,
                    },
                    {
                        "type": "submission",
                        "round": "agent-9",
                        "submission_id": "last-agent",
                        "status": "completed",
                        "valid": True,
                        "score": 55,
                    },
                ]
            },
        )
        self.write_json(task_run / "final_result.json", {"runtime_seconds": 7200.1})

        payload = TIMECURVE.build_timecurve(self.campaign, [2.0], self.output)
        row = payload["rows"][0]

        self.assertEqual(row["status"], "available")
        self.assertTrue(row["strict_checkpoint"])
        self.assertEqual(row["anchor_round"], "final-closeout")
        self.assertEqual(row["best_round"], "agent-9")
        self.assertEqual(row["score_0_100"], 55)

    def test_native_zero_to_one_hundred_task_uses_identity_mapping(self) -> None:
        task_id = "borden_source_inversion"
        self.write_json(
            self.tasks / f"{task_id}.json",
            {
                "task_id": task_id,
                "judge": {
                    "selection": "score_first",
                    "score_direction": "maximize",
                },
            },
        )
        _cell, task_run = self.make_campaign(task_id)
        self.write_json(
            task_run / "run_history.json",
            {
                "entries": [
                    {
                        "type": "submission",
                        "round": "auto-2",
                        "submission_id": "auto2",
                        "status": "completed",
                        "valid": True,
                        "score": 73.5,
                    }
                ]
            },
        )
        (task_run / "auto_eval_ticks.log").write_text(
            "[1970-01-01T01:00:00] submitted 10 bytes -> auto2 round=auto-2\n",
            encoding="utf-8",
        )

        payload = TIMECURVE.build_timecurve(self.campaign, [1.0], self.output)
        row = payload["rows"][0]

        self.assertEqual(row["status"], "available")
        self.assertEqual(row["score_0_100"], 73.5)
        self.assertEqual(row["normalization_source"], "identity_native_0_100")

    def test_game_snapshot_selects_best_session(self) -> None:
        task_id = "game_task"
        self.write_json(
            self.tasks / f"{task_id}.json",
            {
                "task_id": task_id,
                "game_mode": True,
                "judge": {
                    "selection": "score_first",
                    "score_direction": "maximize",
                    "rescale": {"kind": "linear", "lower": 0, "upper": 100},
                },
            },
        )
        cell, _task_run = self.make_campaign(task_id, state="running")
        submissions = (
            self.campaign
            / "judge"
            / "runs"
            / cell["sforge_run_id"]
            / task_id
            / "submissions"
        )
        (submissions / "game-1").mkdir(parents=True)
        (submissions / "game-1" / "steps.jsonl").write_text(
            json.dumps({"move": 1, "score": 40, "peak_score": 40, "max_score": 100})
            + "\n",
            encoding="utf-8",
        )
        self.write_json(
            submissions / "game-2" / "game_result.json",
            {
                "round": "game-2",
                "score": 60,
                "final_score": 60,
                "peak_score": 65,
                "max_score": 100,
                "moves": 10,
            },
        )

        snapshot = TIMECURVE.capture_game_snapshot(
            self.campaign,
            cell,
            3600,
            self.output,
            observed_at=4604,
            poll_seconds=5,
        )
        payload = TIMECURVE.build_timecurve(self.campaign, [1.0], self.output)
        row = payload["rows"][0]

        self.assertTrue(snapshot["strict_checkpoint"])
        self.assertEqual(len(snapshot["sessions"]), 2)
        self.assertEqual(row["status"], "available")
        self.assertTrue(row["strict_checkpoint"])
        self.assertEqual(row["best_round"], "game-2")
        self.assertEqual(row["raw_score"], 60)
        self.assertEqual(row["score_0_100"], 60)

    def test_missing_game_snapshot_is_explicit(self) -> None:
        task_id = "missing_game"
        self.write_json(
            self.tasks / f"{task_id}.json",
            {
                "task_id": task_id,
                "game_mode": True,
                "judge": {
                    "selection": "score_first",
                    "score_direction": "maximize",
                    "rescale": {"kind": "linear", "lower": 0, "upper": 100},
                },
            },
        )
        self.make_campaign(task_id, state="completed")

        payload = TIMECURVE.build_timecurve(self.campaign, [1.0], self.output)
        row = payload["rows"][0]

        self.assertEqual(row["status"], "missing_game_snapshot")
        self.assertFalse(row["strict_checkpoint"])
        self.assertIsNone(row["score_0_100"])
        self.assertEqual(payload["aggregates"][0]["available_count"], 0)

    def test_unavailable_game_snapshot_is_not_a_zero_score(self) -> None:
        task_id = "unavailable_game"
        self.write_json(
            self.tasks / f"{task_id}.json",
            {
                "task_id": task_id,
                "game_mode": True,
                "judge": {
                    "selection": "score_first",
                    "score_direction": "maximize",
                    "rescale": {"kind": "linear", "lower": 0, "upper": 100},
                },
            },
        )
        cell, _task_run = self.make_campaign(task_id, state="completed")
        TIMECURVE.unavailable_game_snapshot(
            self.campaign,
            cell,
            3600,
            self.output,
            "campaign ended before capture",
        )

        payload = TIMECURVE.build_timecurve(self.campaign, [1.0], self.output)
        row = payload["rows"][0]

        self.assertEqual(row["status"], "missing_game_snapshot")
        self.assertIsNone(row["raw_score"])
        self.assertIsNone(row["score_0_100"])
        self.assertEqual(payload["aggregates"][0]["available_count"], 0)

    def test_writer_emits_json_and_csv(self) -> None:
        payload = {
            "schema_version": 1,
            "rows": [{"campaign_id": "c", "task_id": "t", "checkpoint_hours": 1}],
        }

        json_path, csv_path = TIMECURVE.write_timecurve(self.output, payload)

        self.assertTrue(json_path.is_file())
        self.assertTrue(csv_path.is_file())
        self.assertEqual(json.loads(json_path.read_text())["schema_version"], 1)
        self.assertIn("campaign_id", csv_path.read_text())


if __name__ == "__main__":
    unittest.main()
