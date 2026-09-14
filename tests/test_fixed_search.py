from __future__ import annotations

import contextlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from bench_goal_plus.application import BenchmarkAgent
from bench_goal_plus.catalog import Catalog
from bench_goal_plus.cli import build_parser
from bench_goal_plus.goal_plus_evidence import summarize_worker_concurrency
from bench_runtime_paths import ensure_temp_root
from experiments.edgebench.controller.evidence import goal_plus_stats
from experiments.edgebench.controller.profiles import load_profile as load_edgebench_profile
from experiments.frontier_engineering.config import validate_profile as validate_frontier_profile
from experiments.swe_bench_verified.config import validate_profile as validate_swe_profile


class FixedSearchContractTest(unittest.TestCase):
    def test_retired_profile_configuration_is_rejected_before_preparation(self) -> None:
        for configuration in (None, {}, {"max_candidates": 3}):
            profile = {"search_scheduler": configuration}
            for validate in (validate_frontier_profile, validate_swe_profile):
                with self.subTest(validate=validate, configuration=configuration):
                    with self.assertRaisesRegex(ValueError, "no longer supported"):
                        validate("retired", profile)
            with tempfile.TemporaryDirectory(dir=ensure_temp_root()) as temporary:
                path = Path(temporary) / "profile.json"
                path.write_text(json.dumps(profile))
                with self.assertRaisesRegex(ValueError, "no longer supported"):
                    load_edgebench_profile(path)

    def test_retired_cli_options_are_rejected(self) -> None:
        for option in ("--search-scheduler-model", "--search-scheduler-reasoning-effort",
                       "--search-scheduler-timeout-seconds", "--search-scheduler-reward",
                       "--search-scheduler-allocation", "--max-candidates",
                       "--search-scheduler-config-json"):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    build_parser().parse_args(["plan", option, "1"])

    def test_regular_plan_has_no_optional_scoring_configuration(self) -> None:
        spec = BenchmarkAgent(catalog=Catalog()).resolve_spec(
            target_ids=("local-vliw",), methods=("goal-plus-pi",),
            model="test-model", reasoning_effort="low", wall_time_seconds=180,
            live_search_concurrency=1,
        )
        self.assertNotIn("search_scheduler", spec.as_dict())
        self.assertNotIn("llm_verifier", spec.as_dict())
        self.assertEqual(spec.concurrency()["K"], 1)

    def test_regular_spec_uses_current_goal_plus_defaults(self) -> None:
        from goal_plus.models import SearchSpec

        spec = SearchSpec.model_validate({
            "objective": "Optimize score", "source_path": ".",
            "metric_name": "score", "metric_direction": "maximize",
            "edit_surface": {"allow": ["solution.py"]},
            "process_verifiers": [{"name": "score", "role": "ranking_signal",
                                   "command": ["python", "score.py"]}],
            "budget": {"max_parallel": 1}, "workspace": {"provider": "git_worktree"},
            "strategy": {"orchestration_mode": "parallel_loops"},
        })
        self.assertEqual(spec.strategy.orchestration_mode, "parallel_loops")
        self.assertFalse(spec.strategy.requires_llm_verifier)
        self.assertIsNone(spec.strategy.allocation)
        self.assertEqual(list(spec.strategy.selection.ranking_keys), ["hard_score"])

    def test_worker_concurrency_counts_replacements_without_false_overlap(self) -> None:
        summary = summarize_worker_concurrency(
            [
                {
                    "candidate_id": "c001",
                    "started_at": "2026-09-03T00:00:00Z",
                    "ended_at": "2026-09-03T00:01:00Z",
                },
                {
                    "candidate_id": "c002",
                    "started_at": "2026-09-03T00:00:00Z",
                    "ended_at": "2026-09-03T00:02:00Z",
                },
                {
                    "candidate_id": "c003",
                    "started_at": "2026-09-03T00:01:00Z",
                    "ended_at": "2026-09-03T00:03:00Z",
                },
            ]
        )

        self.assertEqual(summary["max_live_workers"], 2)
        self.assertEqual(summary["candidate_ids"], ["c001", "c002", "c003"])

    def test_missing_execution_intervals_remain_unavailable(self) -> None:
        summary = summarize_worker_concurrency([
            {"candidate_id": "c001", "started_at": "2026-09-03T00:00:00Z"},
            {"candidate_id": "c002", "started_at": "2026-09-03T00:00:00",
             "ended_at": "2026-09-03T00:01:00"},
        ])
        self.assertEqual(summary["invalid_interval_count"], 2)
        self.assertIsNone(summary["max_live_workers"])

    def test_edgebench_archive_reads_frozen_k_and_worker_peak(self) -> None:
        with tempfile.TemporaryDirectory(dir=ensure_temp_root()) as temporary:
            task_run = Path(temporary) / "task-run"
            state_root = Path(temporary) / "state" / ".gp"
            run_dir = state_root / "runs" / "run_0001"
            spec_dir = state_root / "specs" / "spec_0001"
            goal_dir = state_root / "goal-plus" / "gp_0001"
            job_dir = run_dir / "agent_sessions"
            for directory in (run_dir, spec_dir, goal_dir, job_dir, task_run):
                directory.mkdir(parents=True, exist_ok=True)
            (run_dir / "run.json").write_text(
                json.dumps(
                    {
                        "run_id": "run_0001",
                        "frozen_spec_id": "spec_0001",
                        "state": "promoted",
                    }
                ),
                encoding="utf-8",
            )
            (spec_dir / "frozen_spec.json").write_text(
                json.dumps(
                    {
                        "spec": {
                            "budget": {"max_parallel": 1, "max_candidates": None},
                            "strategy": {
                                "orchestration_mode": "parallel_loops",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            (goal_dir / "goal.json").write_text(
                json.dumps(
                    {
                        "goal_plus_id": "gp_0001",
                        "status": "complete",
                        "linked_search": {"run_id": "run_0001"},
                    }
                ),
                encoding="utf-8",
            )
            candidate_dir = run_dir / "candidates" / "c001"
            candidate_dir.mkdir(parents=True)
            (candidate_dir / "candidate.json").write_text(
                json.dumps(
                    {
                        "candidate_id": "c001",
                        "task": {"allocation_depth": 0},
                    }
                ),
                encoding="utf-8",
            )
            (job_dir / "agent_0001.json").write_text(
                json.dumps(
                    {
                        "run_id": "run_0001",
                        "candidate_id": "c001",
                        "agent_session_id": "agent_0001",
                        "agent_harness": "pi", "runtime_provider": "direct",
                        "session_handle": {
                            "agent_harness": "pi", "runtime_provider": "direct", "external_id": "native-1",
                            "metadata": {"dispatches": [{
                                "agent_harness": "pi", "runtime_provider": "direct",
                                "native_session_id": "native-1", "invocation_id": "turn-1",
                                "started_at": "2026-09-03T00:00:00Z",
                                "ended_at": "2026-09-03T00:01:00Z",
                            }]},
                        },
                    }
                ),
                encoding="utf-8",
            )
            with tarfile.open(task_run / "goal-plus-state.tar", "w") as archive:
                archive.add(state_root, arcname=".gp")

            stats = goal_plus_stats(task_run)

        assert stats is not None
        self.assertEqual(stats["search_run_contracts"][0]["max_parallel"], 1)
        self.assertEqual(
            stats["search_run_contracts"][0]["orchestration_mode"],
            "parallel_loops",
        )
        self.assertEqual(stats["worker_concurrency"]["max_live_workers"], 1)
