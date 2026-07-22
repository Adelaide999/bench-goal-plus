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
    def test_cpu_portable_catalog_is_a_batch_without_special_resources(self) -> None:
        tasks = adapter.list_catalog_tasks("cpu_portable")
        self.assertEqual(len(tasks), 12)
        self.assertEqual(len({item["task_id"] for item in tasks}), 12)
        for item in tasks:
            profile = item["profile"]
            self.assertEqual(profile["class"], "cpu_portable")
            self.assertFalse(profile.get("gpu"))
            self.assertFalse(profile.get("npu"))
            self.assertFalse(profile.get("network"))
            self.assertFalse(profile.get("external_software"))
            self.assertFalse(profile.get("dataset"))
            self.assertTrue(
                set(profile.get("python_modules") or []).issubset(
                    {"numpy", "scipy"}
                )
            )

    def test_goal_plus_verifier_converts_full_evaluator_report_to_one_line_metric(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            (temp / "evaluate.py").write_text(
                "import json\n"
                "print(json.dumps({'valid': True, 'primary_metric': "
                "{'name': 'combined_score', 'value': 1.25}}, indent=2))\n"
            )
            verifier = temp / "primary_metric.py"
            verifier.write_text(adapter.render_goal_plus_verifier("combined_score"))
            completed = subprocess.run(
                [sys.executable, str(verifier)],
                cwd=temp,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(
                json.loads(completed.stdout),
                {"combined_score": 1.25, "valid": True},
            )

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
                profile={
                    "class": "cpu_portable",
                    "python_modules": [],
                },
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
            controller_runtime = temp / "controller-runtime"
            adapter.materialize_workspace(
                task,
                workspace,
                Path(sys.executable),
                max_evaluator_calls=2,
                reserved_final_calls=1,
                description=description,
                controller_runtime_dir=controller_runtime,
            )
            metadata = json.loads((workspace / "task.json").read_text())
            self.assertEqual(
                metadata["goal_plus_verifier"],
                ".goal-plus-verifiers/primary_metric.py",
            )
            self.assertTrue(
                (workspace / ".goal-plus-verifiers/primary_metric.py").is_file()
            )
            self.assertEqual(
                metadata["runtime_python"], str(Path(sys.executable).absolute())
            )
            self.assertEqual(
                metadata["controller_runtime_dir"],
                str(controller_runtime.absolute()),
            )
            self.assertFalse((workspace / ".bench-runtime").exists())
            self.assertEqual(metadata["execution_profile"]["class"], "cpu_portable")
            self.assertIn("portable CPU-only task", (workspace / "TASK.md").read_text())
            metadata["runtime_python"] = sys.executable
            (workspace / "task.json").write_text(json.dumps(metadata))
            subprocess.run(
                ["git", "clone", str(workspace), str(temp / "candidate-worktree")],
                check=True,
                capture_output=True,
            )
            candidate_workspace = temp / "candidate-worktree"
            candidate_metadata = json.loads(
                (candidate_workspace / "task.json").read_text()
            )
            candidate_metadata["runtime_python"] = sys.executable
            (candidate_workspace / "task.json").write_text(
                json.dumps(candidate_metadata)
            )

            original_worker = adapter.WORKER_PATH
            try:
                adapter.WORKER_PATH = fake_worker
                public = adapter.evaluate_workspace(candidate_workspace, "public")
                self.assertEqual(public["call_index"], 1)
                self.assertEqual(public["primary_metric"]["value"], 1.0)
                self.assertEqual(public["combined_score"], 1.0)
                with self.assertRaises(adapter.BudgetExhausted):
                    adapter.evaluate_workspace(workspace, "public")
                final = adapter.evaluate_workspace(workspace, "final")
                self.assertEqual(final["call_index"], 2)
            finally:
                adapter.WORKER_PATH = original_worker

            history = (controller_runtime / "history.jsonl").read_text().splitlines()
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

    def test_unlimited_public_budget_still_reserves_final(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir)
            (runtime / "budget.lock").touch()
            (runtime / "budget.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "max_evaluator_calls": None,
                        "reserved_final_calls": 1,
                        "total_claimed": 0,
                        "public_claimed": 0,
                        "final_claimed": 0,
                    }
                )
            )
            adapter.claim_ticket(runtime, "public")
            _, budget = adapter.claim_ticket(runtime, "public")
            self.assertEqual(budget["public_claimed"], 2)
            adapter.claim_ticket(runtime, "final")
            with self.assertRaises(adapter.BudgetExhausted):
                adapter.claim_ticket(runtime, "final")

    def test_sanitizes_home_from_evidence(self) -> None:
        text = f"path={Path.home()}/private/file"
        self.assertEqual(
            adapter.sanitize_evidence_text(text),
            "path=<USER_HOME>/private/file",
        )


if __name__ == "__main__":
    unittest.main()
