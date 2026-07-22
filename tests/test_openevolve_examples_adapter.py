from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.openevolve_examples import adapter  # noqa: E402


SEED = """# EVOLVE-BLOCK-START
def solve():
    return 1
# EVOLVE-BLOCK-END

def fixed():
    return 2
"""


class OpenEvolveExamplesAdapterTest(unittest.TestCase):
    def test_split_evolve_block_requires_exactly_one_block(self) -> None:
        prefix, block, suffix = adapter.split_evolve_block(SEED)
        self.assertIn("EVOLVE-BLOCK-START", prefix)
        self.assertIn("def solve", block)
        self.assertIn("def fixed", suffix)
        with self.assertRaises(ValueError):
            adapter.split_evolve_block("def solve(): pass\n")

    def test_materialize_and_budgeted_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            upstream = temp / "upstream"
            source = upstream / "examples/function_minimization"
            source.mkdir(parents=True)
            initial = source / "initial_program.py"
            initial.write_text(SEED)
            evaluator = source / "evaluator.py"
            evaluator.write_text("def evaluate(path): return {'combined_score': 1.0}\n")
            config = source / "config.yaml"
            config.write_text("prompt: {}\n")
            requirements = source / "requirements.txt"
            requirements.write_text("\n")

            fake_worker = temp / "fake_worker.py"
            fake_worker.write_text(
                "import json,sys\n"
                "from pathlib import Path\n"
                "out=Path(sys.argv[sys.argv.index('--output')+1])\n"
                "out.write_text(json.dumps({'schema_version':1,'valid':True,"
                "'primary_metric':{'name':'combined_score','value':1.0,'direction':'maximize'},"
                "'raw_metrics':{'combined_score':1.0},'artifacts':{},'elapsed_seconds':0.01}))\n"
            )

            task = adapter.ResolvedTask(
                task_id="function_minimization",
                upstream_root=upstream,
                upstream_commit="a" * 40,
                source_dir=source,
                initial_program=initial,
                evaluator=evaluator,
                config=config,
                requirements=requirements,
                artifact_name="candidate.py",
            )
            description = {
                "prompt": {"system_message": "Improve solve()."},
                "evaluation": {
                    "primary_metric": "combined_score",
                    "direction": "maximize",
                    "timeout_seconds": 10,
                    "cascade_evaluation": False,
                    "parallel_evaluations": 1,
                },
            }
            workspace = temp / "workspace"
            adapter.materialize_workspace(
                task,
                workspace,
                Path(sys.executable),
                max_evaluator_calls=2,
                reserved_final_calls=1,
                description=description,
            )
            metadata = json.loads((workspace / "task.json").read_text())
            self.assertEqual(metadata["runtime_python"], str(Path(sys.executable).absolute()))
            metadata["runtime_python"] = sys.executable
            (workspace / "task.json").write_text(json.dumps(metadata))

            original_worker = adapter.WORKER_PATH
            try:
                adapter.WORKER_PATH = fake_worker
                public = adapter.evaluate_workspace(workspace, "public")
                self.assertEqual(public["call_index"], 1)
                self.assertEqual(public["primary_metric"]["value"], 1.0)
                with self.assertRaises(adapter.BudgetExhausted):
                    adapter.evaluate_workspace(workspace, "public")
                final = adapter.evaluate_workspace(workspace, "final")
                self.assertEqual(final["call_index"], 2)
            finally:
                adapter.WORKER_PATH = original_worker

            history = (workspace / ".bench-runtime/history.jsonl").read_text().splitlines()
            self.assertEqual(len(history), 2)

            run_dir = temp / "run"
            run_dir.mkdir()
            (run_dir / "run-manifest.json").write_text(
                json.dumps(
                    {
                        "workspace_commit": "test-commit",
                        "codex_version": "codex-cli test",
                        "model": None,
                        "duration_seconds": 1.5,
                        "usage": {"input_tokens": 10, "output_tokens": 2},
                    }
                )
            )
            summary = adapter.archive_workspace(workspace, run_dir)
            self.assertEqual(summary["final_score"], 1.0)
            self.assertEqual(summary["evaluator_calls"]["total_claimed"], 2)
            self.assertEqual(summary["codex"]["model_identity_coverage"], "missing")
            self.assertTrue((run_dir / "candidate.py").is_file())
            self.assertTrue((run_dir / "evaluation-history.jsonl").is_file())

    def test_rejects_changes_outside_evolve_block(self) -> None:
        prefix, _, suffix = adapter.split_evolve_block(SEED)
        metadata = {
            "fixed_prefix_sha256": adapter.sha256_text(prefix),
            "fixed_suffix_sha256": adapter.sha256_text(suffix),
        }
        changed = SEED.replace("return 2", "return 3")
        self.assertEqual(
            adapter.validate_candidate(changed, metadata),
            "content after EVOLVE-BLOCK changed",
        )

    def test_sanitizes_home_from_evidence(self) -> None:
        text = f"path={Path.home()}/private/file"
        self.assertEqual(
            adapter.sanitize_evidence_text(text),
            "path=<USER_HOME>/private/file",
        )


if __name__ == "__main__":
    unittest.main()
