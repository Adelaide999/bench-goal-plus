from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from adapters.registry import load_adapter
from adapters.torchbench import adapter


def make_upstream(root: Path) -> Path:
    source = root / "upstream"
    (source / "torchbenchmark/models/alexnet").mkdir(parents=True)
    (source / "torchbenchmark/models/BERT_pytorch").mkdir(parents=True)
    (source / "torchbenchmark/__init__.py").write_text("\n")
    (source / "torchbenchmark/models/alexnet/__init__.py").write_text("seed = 1\n")
    (source / "torchbenchmark/models/BERT_pytorch/__init__.py").write_text(
        "seed = 2\n"
    )
    (source / "run.py").write_text("trusted = True\n")
    subprocess.run(["git", "init", "-q", "-b", "main", source], check=True)
    subprocess.run(
        ["git", "-C", source, "config", "user.name", "Test Controller"], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            source,
            "config",
            "user.email",
            "test@example.invalid",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", source, "add", "."], check=True)
    subprocess.run(["git", "-C", source, "commit", "-q", "-m", "fixture"], check=True)
    return source


class TorchBenchAdapterTest(unittest.TestCase):
    def tearDown(self) -> None:
        adapter.configure_task(None)

    def test_model_catalog_selects_one_shared_adapter_contract(self) -> None:
        expected = {
            "alexnet",
            "BERT_pytorch",
            "mobilenet_v2",
            "resnet18",
            "squeezenet1_1",
        }
        self.assertEqual(set(adapter.list_task_ids()), expected)
        self.assertEqual(
            set(load_adapter("torchbench").manifest_contract()["task_ids"]),
            expected,
        )
        adapter.configure_task("BERT_pytorch")
        self.assertEqual(adapter.TASK_ID, "BERT_pytorch-eval-cuda")
        self.assertEqual(
            adapter.ARTIFACT_NAME,
            "torchbenchmark/models/BERT_pytorch",
        )
        with self.assertRaisesRegex(adapter.AdapterError, "unsupported TorchBench model"):
            adapter.configure_task("resnet-does-not-exist")

    def test_materialize_copies_tracked_checkout_without_touching_upstream(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = make_upstream(root)
            source_commit = adapter.git_commit(source)
            workspace = root / "workspace"

            result = adapter.materialize_workspace(source, workspace)

            self.assertEqual(adapter.git_commit(source), source_commit)
            self.assertFalse(
                subprocess.run(
                    ["git", "-C", source, "status", "--porcelain"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
            )
            self.assertEqual(result["model"], "alexnet")
            self.assertTrue((workspace / adapter.ARTIFACT_NAME).is_dir())
            self.assertTrue((workspace / "evaluate.py").is_file())
            self.assertTrue(
                (workspace / ".goal-plus-verifiers/primary_metric.py").is_file()
            )
            metadata = json.loads((workspace / "task.json").read_text())
            self.assertEqual(metadata["upstream_commit"], source_commit)
            self.assertFalse(metadata["official_benchmark_comparable"])

    def test_evaluation_tree_consumes_only_the_candidate_model_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = make_upstream(root)
            workspace = root / "workspace"
            adapter.materialize_workspace(source, workspace)
            (workspace / "run.py").write_text("trusted = False\n")
            (workspace / adapter.ARTIFACT_NAME / "__init__.py").write_text(
                "optimized = True\n"
            )

            evaluation = adapter.prepare_evaluation_tree(
                source,
                workspace / adapter.ARTIFACT_NAME,
                "alexnet",
                root / "evaluation",
            )

            self.assertEqual((evaluation / "run.py").read_text(), "trusted = True\n")
            self.assertEqual(
                (evaluation / adapter.ARTIFACT_NAME / "__init__.py").read_text(),
                "optimized = True\n",
            )

    def test_gpu_pool_maps_candidate_and_plain_lane_names(self) -> None:
        previous = os.environ.get("BENCH_GOAL_PLUS_TORCHBENCH_GPUS")
        os.environ["BENCH_GOAL_PLUS_TORCHBENCH_GPUS"] = "3,5"
        try:
            self.assertEqual(adapter.assigned_gpu(Path("/run/workspace/c001")), "3")
            self.assertEqual(adapter.assigned_gpu(Path("/run/workspace/c002")), "5")
            self.assertEqual(adapter.assigned_gpu(Path("/run/workspaces/lane-02")), "3")
        finally:
            if previous is None:
                os.environ.pop("BENCH_GOAL_PLUS_TORCHBENCH_GPUS", None)
            else:
                os.environ["BENCH_GOAL_PLUS_TORCHBENCH_GPUS"] = previous


if __name__ == "__main__":
    unittest.main()
