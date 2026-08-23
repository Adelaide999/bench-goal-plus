from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.zsoft_l1 import adapter  # noqa: E402


class AdapterContractTest(unittest.TestCase):
    def test_declares_raw_metric_contract(self) -> None:
        self.assertIn(adapter.DIRECTION, {"minimize", "maximize"})
        self.assertTrue(adapter.PRIMARY_METRIC)
        self.assertTrue(adapter.ARTIFACT_NAME)
        self.assertEqual(
            adapter.UPSTREAM_SUBDIR,
            "benchmarks/vulnerability/zsoft-l1",
        )

    def test_task_catalog_is_pinned(self) -> None:
        task_ids = adapter.list_task_ids()
        self.assertIn("sample-asan-crash", task_ids)
        self.assertGreaterEqual(len(task_ids), 30)

    def test_configure_task_rejects_unknown_task(self) -> None:
        with self.assertRaises(adapter.AdapterError):
            adapter.configure_task("no-such-task")

    def test_materialize_and_placeholder_fails(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        workspace = tmp / "ws"
        materialized = adapter.materialize_workspace(
            adapter.ZSOFT_ROOT, workspace
        )
        self.assertEqual(materialized["task_id"], adapter.TASK_ID)
        self.assertTrue((workspace / "poc").is_file())
        self.assertTrue((workspace / "TASK.md").is_file())
        self.assertTrue((workspace / "evaluate.py").is_file())
        self.assertTrue(
            (workspace / ".goal-plus-verifiers" / "primary_metric.py").is_file()
        )
        metadata = json.loads((workspace / "task.json").read_text())
        self.assertEqual(metadata["source_revision"], metadata["upstream_commit"])
        report = adapter.evaluate_workspace(workspace, adapter.BENCHMARK_ROOT, "public")
        self.assertFalse(report["valid"])
        self.assertEqual(report[adapter.PRIMARY_METRIC], 0)
        self.assertEqual(report["budget"]["total_claimed"], 1)

    def test_git_commit_supports_shared_runtime_checkouts(self) -> None:
        self.assertRegex(
            adapter.git_commit(ROOT / "third_party" / "muyuan"),
            r"^[0-9a-f]{40}$",
        )
        self.assertRegex(adapter.git_commit(adapter.ZSOFT_ROOT), r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
