from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.zsoft_detect import adapter


class AdapterContractTest(unittest.TestCase):
    def test_declares_raw_metric_contract(self) -> None:
        self.assertIn(adapter.DIRECTION, {"minimize", "maximize"})
        self.assertTrue(adapter.PRIMARY_METRIC)
        self.assertTrue(adapter.ARTIFACT_NAME)
        self.assertEqual(adapter.EVALUATION_MODE, "blind")
        self.assertEqual(adapter.PRIMARY_METRIC, "f1")
        self.assertEqual(adapter.GOAL_PLUS_PROCESS_METRIC, "format_valid")
        self.assertLess(adapter.VERIFIER_TIMEOUT_SECONDS, 1800)
        self.assertEqual(
            adapter.UPSTREAM_SUBDIR,
            "benchmarks/vulnerability/zsoft-detect",
        )
        self.assertEqual(adapter.PI_WORKER_SANDBOX["engine"], "bubblewrap")
        self.assertEqual(
            adapter.PI_WORKER_SANDBOX["evaluation_mode"], "blind"
        )
        self.assertEqual(adapter.PI_WORKER_SANDBOX["workspace_access"], "read_only")
        self.assertEqual(
            adapter.PI_WORKER_SANDBOX["read_only_workspace_paths"],
            ["source", "schemas"],
        )
        self.assertEqual(
            adapter.PI_WORKER_SANDBOX["writable_workspace_paths"], ["submission"]
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
        source_checkout.mkdir()
        subprocess.run(["git", "init", "-q", str(source_checkout)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(source_checkout),
                "config",
                "user.email",
                "test@example.com",
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(source_checkout), "config", "user.name", "Test"],
            check=True,
        )
        (source_checkout / "src").mkdir()
        (source_checkout / "src" / "civetweb.c").write_text("/* fixture */\n")
        subprocess.run(["git", "-C", str(source_checkout), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(source_checkout), "commit", "-q", "-m", "fixture"],
            check=True,
        )
        commit = subprocess.run(
            ["git", "-C", str(source_checkout), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        contract = adapter.bench_contract("civetweb")
        previous_commit = adapter.PROJECT_COMMITS["civetweb"]
        adapter.PROJECT_COMMITS["civetweb"] = commit
        self.addCleanup(
            adapter.PROJECT_COMMITS.__setitem__, "civetweb", previous_commit
        )

        adapter.configure_task(None)
        with mock.patch.object(adapter, "bench_contract", return_value=contract):
            adapter.materialize_workspace(adapter.ZSOFT_ROOT, workspace)

        tracked = subprocess.run(
            ["git", "-C", str(workspace), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        self.assertIn("source/src/civetweb.c", tracked)
        self.assertIn("submission/.gitkeep", tracked)
        self.assertIn("schemas/finding.schema.json", tracked)
        self.assertFalse((workspace / "source" / ".git").exists())
        metadata = json.loads((workspace / "task.json").read_text())
        self.assertEqual(metadata["source_revision"], commit)
        self.assertNotIn("upstream_root", metadata)
        self.assertEqual(metadata["primary_metric"], "format_valid")
        self.assertTrue((workspace / "public_check.py").is_file())
        self.assertFalse((workspace / "evaluate.py").exists())
        self.assertFalse((workspace / ".goal-plus-verifiers").exists())

    def test_materialize_copies_an_explicit_validated_source_cache(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        contract = adapter.bench_contract("civetweb")
        source = tmp / "source-cache"
        source.mkdir()
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(
            ["git", "-C", str(source), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(source), "config", "user.name", "Test"], check=True
        )
        (source / "sample.c").write_text("/* fixture */\n")
        subprocess.run(["git", "-C", str(source), "add", "sample.c"], check=True)
        subprocess.run(
            ["git", "-C", str(source), "commit", "-q", "-m", "fixture"],
            check=True,
        )
        commit = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        previous_commit = adapter.PROJECT_COMMITS["civetweb"]
        adapter.PROJECT_COMMITS["civetweb"] = commit
        self.addCleanup(
            adapter.PROJECT_COMMITS.__setitem__, "civetweb", previous_commit
        )

        workspace = tmp / "workspace"
        adapter.configure_task(None)
        with (
            mock.patch.dict(os.environ, {adapter.SOURCE_CACHE_ENV: str(source)}),
            mock.patch.object(adapter, "bench_contract", return_value=contract),
        ):
            adapter.materialize_workspace(adapter.ZSOFT_ROOT, workspace)

        self.assertTrue((workspace / "source").is_dir())
        self.assertFalse((workspace / "source").is_symlink())
        self.assertTrue((workspace / "source" / "sample.c").is_file())
        self.assertFalse((workspace / "source" / ".git").exists())
        self.assertEqual(
            json.loads((workspace / "schemas" / "finding.schema.json").read_text()),
            json.loads(
                (adapter.BENCHMARK_ROOT / "schemas" / "finding.schema.json").read_text()
            ),
        )
        metadata = json.loads((workspace / "task.json").read_text())
        self.assertEqual(
            metadata["source_materialization"], "validated_local_cache_copy"
        )

    def test_campaign_local_checkout_must_be_exact_and_clean(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        source = tmp / "workspace-source"
        source.mkdir()
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        (source / "partial.c").write_text("untracked\n")

        adapter.configure_task(None)
        with self.assertRaisesRegex(adapter.AdapterError, "Git top level|wrong commit"):
            adapter.materialize_workspace(adapter.ZSOFT_ROOT, tmp / "workspace")
        self.assertTrue((source / "partial.c").is_file())
        self.assertFalse((tmp / "workspace").exists())

    def test_source_copy_preserves_internal_symlinks_and_rejects_escape(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        source = tmp / "source"
        source.mkdir()
        (source / "target.h").write_text("fixture\n")
        (source / "internal.h").symlink_to("target.h")
        destination = tmp / "destination"

        from adapters.portable import copytree_confined

        copytree_confined(source, destination, label="fixture")
        self.assertTrue((destination / "internal.h").is_symlink())
        self.assertEqual(os.readlink(destination / "internal.h"), "target.h")

        (source / "escape").symlink_to("../private")
        with self.assertRaisesRegex(RuntimeError, "symlink escapes"):
            copytree_confined(source, tmp / "rejected", label="fixture")

    def test_materialization_paths_must_be_disjoint(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        source = root / "source"
        source.mkdir()
        with self.assertRaisesRegex(adapter.AdapterError, "paths overlap"):
            adapter._require_disjoint_paths(
                workspace=source / "workspace",
                source_checkout=source,
                benchmark_root=adapter.BENCHMARK_ROOT,
            )

    def test_public_evaluate_checks_format_without_official_scorer(self) -> None:
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

        with mock.patch.object(adapter, "_run") as scorer:
            report = adapter.evaluate_workspace(
                workspace, Path("/not-visible-to-public-check"), "public"
            )

        scorer.assert_not_called()
        self.assertTrue(report["valid"])
        self.assertEqual(report[adapter.GOAL_PLUS_PROCESS_METRIC], 1.0)
        self.assertNotIn(adapter.PRIMARY_METRIC, report)
        self.assertNotIn("zsoft_score", report)
        self.assertEqual(report["budget"]["total_claimed"], 1)

    def test_evaluate_rejects_submission_symlinks_before_scoring(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        workspace = tmp / "workspace"
        submission = workspace / adapter.ARTIFACT_NAME
        submission.mkdir(parents=True)
        (submission / "finding.json").symlink_to(
            adapter.BENCHMARK_ROOT / "schemas" / "finding.schema.json"
        )
        (workspace / "task.json").write_text(
            json.dumps(
                {
                    "task_id": adapter.TASK_ID,
                    "project_id": adapter.DEFAULT_PROJECT,
                    "commit": adapter.project_commit(adapter.DEFAULT_PROJECT),
                }
            )
        )

        with mock.patch.object(adapter, "_run") as scorer:
            report = adapter.evaluate_workspace(
                workspace, adapter.BENCHMARK_ROOT, "public"
            )

        scorer.assert_not_called()
        self.assertFalse(report["valid"])
        self.assertEqual(report[adapter.GOAL_PLUS_PROCESS_METRIC], 0.0)
        self.assertNotIn(adapter.PRIMARY_METRIC, report)
        self.assertIn("symlink", json.dumps(report["public_diagnostics"]))

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
        self.assertEqual(report[adapter.GOAL_PLUS_PROCESS_METRIC], 1.0)
        self.assertNotIn(adapter.PRIMARY_METRIC, report)

    def test_git_commit_supports_shared_runtime_checkouts(self) -> None:
        self.assertRegex(
            adapter.git_commit(adapter.ZSOFT_ROOT.parent / "muyuan"),
            r"^[0-9a-f]{40}$",
        )
        self.assertRegex(adapter.git_commit(adapter.ZSOFT_ROOT), r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
