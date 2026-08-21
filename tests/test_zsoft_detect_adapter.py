from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.zsoft_detect import adapter  # noqa: E402


class AdapterContractTest(unittest.TestCase):
    def test_declares_raw_metric_contract(self) -> None:
        self.assertIn(adapter.DIRECTION, {"minimize", "maximize"})
        self.assertTrue(adapter.PRIMARY_METRIC)
        self.assertTrue(adapter.ARTIFACT_NAME)
        self.assertLess(adapter.VERIFIER_TIMEOUT_SECONDS, 1800)
        self.assertEqual(
            adapter.UPSTREAM_SUBDIR,
            "benchmarks/vulnerability/zsoft-detect",
        )

    def test_project_catalog_is_pinned(self) -> None:
        self.assertEqual(
            set(adapter.list_projects()),
            set(adapter.PROJECT_COMMITS),
        )

    def test_configure_task_rejects_unknown_project(self) -> None:
        with self.assertRaises(adapter.AdapterError):
            adapter.configure_task("no-such-project")

    def test_configure_task_updates_persisted_task_id(self) -> None:
        self.addCleanup(adapter.configure_task, None)
        adapter.configure_task("libxml2-detect")

        self.assertEqual(adapter.ACTIVE_PROJECT, "libxml2")
        self.assertEqual(adapter.TASK_ID, "libxml2-detect")

    def test_bench_contract_is_public_only(self) -> None:
        contract = adapter.bench_contract("civetweb")
        self.assertEqual(contract["project_id"], "civetweb")
        self.assertTrue(contract["scan_roots"])
        self.assertNotIn("applicability", json.dumps(contract))
        self.assertNotIn("cases", contract)

    def test_materialize_tracks_source_and_empty_submission(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        workspace = tmp / "workspace"
        source_checkout = tmp / "workspace-source"
        (source_checkout / ".git").mkdir(parents=True)
        (source_checkout / ".git" / "HEAD").write_text("nested metadata")
        (source_checkout / "src").mkdir()
        (source_checkout / "src" / "civetweb.c").write_text("/* fixture */\n")

        adapter.configure_task(None)
        adapter.materialize_workspace(adapter.ZSOFT_ROOT, workspace)

        tracked = subprocess.run(
            ["git", "-C", str(workspace), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        self.assertIn("source/src/civetweb.c", tracked)
        self.assertIn("submission/.gitkeep", tracked)
        self.assertFalse((workspace / "source" / ".git").exists())
        metadata = json.loads((workspace / "task.json").read_text())
        self.assertEqual(metadata["source_revision"], adapter.PROJECT_COMMITS["civetweb"])

    def test_evaluate_scores_candidate_submission_without_agent_api(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        workspace = tmp / "workspace"
        (workspace / adapter.ARTIFACT_NAME).mkdir(parents=True)
        (workspace / "task.json").write_text(
            json.dumps(
                {
                    "task_id": adapter.TASK_ID,
                    "project_id": adapter.DEFAULT_PROJECT,
                    "commit": adapter.project_commit(adapter.DEFAULT_PROJECT),
                }
            )
        )

        report = adapter.evaluate_workspace(
            workspace, adapter.BENCHMARK_ROOT, "public"
        )

        self.assertTrue(report["valid"])
        self.assertEqual(report[adapter.PRIMARY_METRIC], 0.0)
        self.assertEqual(report["message"], "ok")
        self.assertIsNotNone(report["zsoft_score"])
        self.assertEqual(report["budget"]["total_claimed"], 1)

    def test_adapter_cli_evaluates_candidate_submission(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        workspace = tmp / "workspace"
        (workspace / adapter.ARTIFACT_NAME).mkdir(parents=True)
        (workspace / "task.json").write_text(
            json.dumps(
                {
                    "task_id": adapter.TASK_ID,
                    "project_id": adapter.DEFAULT_PROJECT,
                    "commit": adapter.project_commit(adapter.DEFAULT_PROJECT),
                }
            )
        )

        completed = subprocess.run(
            [
                sys.executable,
                str(adapter.CONTROLLER_PATH),
                "evaluate",
                "--workspace",
                str(workspace),
                "--upstream-root",
                str(adapter.BENCHMARK_ROOT),
                "--mode",
                "public",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        report = json.loads(completed.stdout)
        self.assertTrue(report["valid"])
        self.assertEqual(report[adapter.PRIMARY_METRIC], 0.0)

    def test_git_commit_supports_shared_runtime_checkouts(self) -> None:
        self.assertRegex(
            adapter.git_commit(ROOT / "third_party" / "goal-plus"),
            r"^[0-9a-f]{40}$",
        )
        self.assertRegex(adapter.git_commit(adapter.ZSOFT_ROOT), r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
