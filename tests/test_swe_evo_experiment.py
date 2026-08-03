from __future__ import annotations

import argparse
import importlib
import json
import stat
import time
import unittest
from pathlib import Path
from unittest.mock import patch


SWE = importlib.import_module("experiments.swe_evo.experiment")
DATASET = importlib.import_module("experiments.swe_evo.dataset")


def record(index: int = 0) -> dict:
    return {
        "repo": "psf/requests",
        "instance_id": f"psf__requests_release_{index}",
        "base_commit": "a" * 40,
        "patch": "diff --git a/requests/api.py b/requests/api.py\n",
        "test_patch": "diff --git a/tests/test_hidden.py b/tests/test_hidden.py\n",
        "problem_statement": "Fix the release regression.",
        "FAIL_TO_PASS": ["tests/test_hidden.py::test_release"],
        "PASS_TO_PASS": ["tests/test_public.py::test_api"],
        "environment_setup_commit": "b" * 40,
        "image": "ghcr.io/example/requests-task",
        "version": "2.12",
        "start_version": "2.12.2",
        "end_version": "2.12.3",
        "test_cmds": "pytest",
        "log_parser": "parse_log_pytest",
        "all_patch": "hidden",
    }


class SweEvoExperimentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = (
            SWE.ensure_temp_root("test-swe-evo")
            / f"{self._testMethodName}-{time.time_ns()}"
        )
        self.temp.mkdir(parents=True)
        self.original_runs = SWE.RUNS_ROOT
        SWE.RUNS_ROOT = self.temp / "runs"

    def tearDown(self) -> None:
        SWE.RUNS_ROOT = self.original_runs

    def test_dataset_contract_requires_exact_upstream_cardinality(self) -> None:
        with self.assertRaisesRegex(DATASET.DatasetContractError, "expected 48"):
            DATASET.validate_records([record()])
        records = [record(index) for index in range(48)]
        DATASET.validate_records(records)

    def test_generated_worker_task_excludes_all_hidden_fields(self) -> None:
        task, contract = SWE.task_payload(record())
        serialized = json.dumps(task)
        for forbidden in DATASET.HIDDEN_FIELDS:
            self.assertNotIn(f'"{forbidden}"', serialized)
        self.assertNotIn("test_hidden.py", serialized)
        self.assertNotIn("test_release", serialized)
        self.assertIn("release regression", task["work"]["agent_query"])
        self.assertEqual(contract["work_tag"], task["work"]["image_tag"])
        self.assertEqual(contract["judge_tag"], task["judge"]["image_tag"])
        self.assertFalse(task["internet"])
        self.assertIn(".codex", task["submit_exclude"])
        self.assertIn(".goal-plus-verifiers", task["submit_exclude"])
        self.assertIn("results.tsv", task["submit_exclude"])

    def test_hidden_field_audit_fails_closed(self) -> None:
        with self.assertRaisesRegex(DATASET.DatasetContractError, "hidden fields"):
            DATASET.assert_worker_safe({"test_patch": "secret"})

    def test_prepare_preserves_k_semantics_and_private_evaluator_lock(self) -> None:
        profile = {
            "schema_version": 1,
            "id": "test",
            "benchmark_id": "swe-evo",
            "upstream_commit": "c" * 40,
            "dataset_sha256": "d" * 64,
            "task_ids": [record()["instance_id"]],
            "methods": ["plain-codex", "goal-plus-codex"],
            "model": "test-model",
            "reasoning_effort": "medium",
            "wall_time_seconds": 60,
            "concurrency": 2,
            "cell_concurrency": 1,
            "worker_runtime_seconds": 50,
            "eval_interval_seconds": 30,
            "judge_port": 18081,
            "work_cpu_limit": 2,
            "work_mem_limit": "4g",
            "judge_cpu_limit": 1,
            "judge_mem_limit": "2g",
            "official_evaluator_timeout_seconds": 120,
            "image_provision_concurrency": 1,
        }
        args = argparse.Namespace(
            campaign_id="test-campaign",
            method=None,
            model=None,
            reasoning_effort=None,
            wall_time_seconds=None,
            concurrency=None,
            cell_concurrency=None,
        )
        inspected = {"available": True, "image": "fixture", "id": "sha256:fixture"}
        with (
            patch.object(SWE, "selected_records", return_value=[record()]),
            patch.object(SWE, "docker_inspect", return_value=inspected),
            patch.object(SWE, "sha256_file", return_value=profile["dataset_sha256"]),
        ):
            destination = SWE.prepare(args, profile)
        evaluator = destination / "evaluator" / "instances.json"
        self.assertEqual(stat.S_IMODE(evaluator.stat().st_mode), 0o600)
        task_text = next((destination / "sforge_tasks").glob("*.json")).read_text()
        self.assertNotIn("FAIL_TO_PASS", task_text)
        self.assertNotIn("test_patch", task_text)
        campaign = SWE.read_json(destination / "campaign.json")
        cells = {
            item["method"]: SWE.read_json(
                destination / "cells" / item["cell_id"] / "cell.json"
            )
            for item in campaign["cells"]
        }
        self.assertEqual(cells["plain-codex"]["outer_replicas"], 2)
        self.assertEqual(cells["plain-codex"]["inner_search_concurrency"], 0)
        self.assertEqual(cells["goal-plus-codex"]["outer_replicas"], 1)
        self.assertEqual(cells["goal-plus-codex"]["inner_search_concurrency"], 2)
        self.assertEqual(campaign["T_K_C_R"], {"T": 60, "K": 2, "C": 1, "R": 1})

    def test_process_judge_is_explicitly_non_official(self) -> None:
        command = SWE._process_eval_command()
        self.assertIn("process-only", command)
        self.assertIn("'official':False", command)

    def test_smoke_profile_pins_source_image_digest(self) -> None:
        _, profile = SWE.load_profile("ghcr-smoke-1")
        task_id = profile["task_ids"][0]
        digest = profile["source_image_digests"][task_id]
        self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(profile["image_provision_concurrency"], 1)

    def test_mirror_transport_must_preserve_manifest_digest(self) -> None:
        item = record()
        expected = "sha256:" + "1" * 64
        with (
            patch.dict(SWE.os.environ, {"SWE_EVO_IMAGE_MIRROR": "mirror.example"}),
            patch.object(SWE, "docker_inspect", return_value={"available": False}),
            patch.object(SWE, "manifest_digest", return_value="sha256:" + "2" * 64),
            patch.object(SWE.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "mirror digest mismatch"):
                SWE.pull_source_image(item, expected)
        run.assert_not_called()

    def test_image_digest_matches_any_repository_name(self) -> None:
        expected = "sha256:" + "3" * 64
        details = {"repo_digests": [f"mirror.example/repo@{expected}"]}
        self.assertTrue(SWE.image_has_digest(details, expected))

    def test_goal_plus_trajectory_requires_a_completed_promotion(self) -> None:
        trajectory = self.temp / "trajectory"
        SWE.write_json(
            trajectory / "goal-plus-live-status.json",
            {
                "terminal_ready": True,
                "actual_worker_launch_count": 2,
                "worker_verifier_runs": 2,
                "candidate_ids": ["c001", "c002"],
                "promoted_candidate_ids": [],
                "goal_statuses": [{"goal_plus_id": "gp_0001", "status": "blocked"}],
            },
        )
        provenance = SWE._goal_plus_provenance(trajectory)
        self.assertFalse(provenance["valid"])
        self.assertEqual(provenance["actual_worker_launch_count"], 2)
        self.assertIn("no completed promoted candidate", provenance["reason"])

        payload = SWE.read_json(trajectory / "goal-plus-live-status.json")
        payload["promoted_candidate_ids"] = ["c001"]
        payload["goal_statuses"][0]["status"] = "complete"
        SWE.write_json(trajectory / "goal-plus-live-status.json", payload)
        self.assertTrue(SWE._goal_plus_provenance(trajectory)["valid"])


if __name__ == "__main__":
    unittest.main()
