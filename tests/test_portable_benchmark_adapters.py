from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch

from adapters.ale import adapter as ale
from adapters.autolab import adapter as autolab
from adapters.frontier_cs import adapter as frontier_cs
from adapters.frontier_engineering import adapter as frontier
from adapters.local_vliw import adapter as local_vliw
from adapters.portable import candidate_changed_paths
from experiments.heurigym_compare import experiment
from experiments.openevolve_compare import experiment as openevolve_experiment


ROOT = Path(__file__).resolve().parents[1]


class PortableBenchmarkAdapterTest(unittest.TestCase):
    def test_registry_exposes_all_standalone_adapters(self) -> None:
        self.assertEqual(
            set(experiment.BENCHMARK_ADAPTERS),
            {
                "ale-bench-lite",
                "autolab-toy-isa",
                "frontier-cs-problem-0",
                "frontier-engineering-malloclab",
                "heurigym",
                "local-vliw",
            },
        )

    def test_docker_backed_tasks_use_host_capable_codex_sandbox(self) -> None:
        experiment.configure_adapter("ale-bench-lite")
        self.assertEqual(experiment.CODEX_SANDBOX, "danger-full-access")
        experiment.configure_adapter("frontier-cs-problem-0")
        self.assertEqual(experiment.CODEX_SANDBOX, "danger-full-access")
        experiment.configure_adapter("autolab-toy-isa")
        self.assertEqual(experiment.CODEX_SANDBOX, "workspace-write")
        experiment.configure_adapter("local-vliw")
        self.assertEqual(experiment.CODEX_SANDBOX, "workspace-write")
        self.assertFalse(experiment.OFFICIAL_BENCHMARK_COMPARABLE)
        experiment.configure_adapter("heurigym")
        self.assertTrue(experiment.OFFICIAL_BENCHMARK_COMPARABLE)

    def test_goal_plus_codex_loads_project_hooks_from_an_isolated_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            run_dir.mkdir()
            environment = {"CODEX_HOME": "/personal/codex-home"}
            codex_home = openevolve_experiment.configure_isolated_codex_home(
                environment, run_dir
            )

            self.assertEqual(environment["CODEX_HOME"], str(codex_home))
            self.assertEqual(codex_home.parent, run_dir / "controller-runtime")
            self.assertEqual(list(codex_home.iterdir()), [])

            common = {
                "codex_bin": "codex",
                "workspace": Path("workspace"),
                "output_last_message": Path("final-message.txt"),
                "model": "gpt-5.6-terra",
                "reasoning_effort": "medium",
                "api_base": "http://proxy.example/v1",
                "sandbox": "workspace-write",
                "ephemeral": False,
            }
            goal_plus = experiment.codex_command(goal_plus=True, **common)
            plain = experiment.codex_command(goal_plus=False, **common)
            self.assertNotIn("--ignore-user-config", goal_plus)
            self.assertIn("--ignore-user-config", plain)
            self.assertIn('model_reasoning_effort="medium"', goal_plus)
            self.assertIn(
                "features.multi_agent_v2.max_concurrent_threads_per_session=5",
                goal_plus,
            )
            self.assertFalse(
                any("max_concurrent_threads_per_session" in arg for arg in plain)
            )

    def test_local_vliw_goal_plus_wires_annotator_provider_and_usage(self) -> None:
        experiment.configure_adapter("local-vliw")
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                run_dir = root / "run"
                workspace = run_dir / "workspace"
                workspace.mkdir(parents=True)
                (workspace / "TASK.md").write_text("optimize\n", encoding="utf-8")
                (workspace / experiment.ARTIFACT_NAME).write_text(
                    "# candidate\n", encoding="utf-8"
                )
                manifest = {
                    "workspace": str(workspace),
                    "reasoning_effort": "medium",
                    "environment": {"runtime_bin": str(root / "bin")},
                    "budget": {
                        "wall_time_seconds": 300,
                        "soft_closeout_seconds": 30,
                        "hard_kill_grace_seconds": 5,
                        "concurrency": 1,
                        "worker_runtime_seconds": 240,
                    },
                }
                args = SimpleNamespace(
                    model="gpt-test",
                    api_base="http://proxy.example/v1",
                    codex_bin="codex",
                )
                seed = {"budget": {"total_claimed": 1}}
                final = {"valid": True, "budget": {"total_claimed": 1}}
                annotator_usage = {
                    "input_tokens": 9,
                    "output_tokens": 3,
                    "tasks": 1,
                    "attempts": 1,
                    "states": {"completed": 1},
                }

                with (
                    patch.object(
                        experiment,
                        "evaluate_with_controller_runtime",
                        side_effect=[seed, final],
                    ),
                    patch.object(experiment, "configure_isolated_codex_home"),
                    patch.object(
                        experiment, "configure_evidence_annotator_environment"
                    ) as configure_annotator,
                    patch.object(experiment, "render_goal", return_value="prompt"),
                    patch.object(
                        experiment, "codex_command", return_value=["codex"]
                    ) as codex_command,
                    patch.object(
                        experiment,
                        "run_controlled",
                        return_value={"hard_killed": False},
                    ),
                    patch.object(
                        experiment,
                        "parse_codex_events",
                        return_value={"top_level_usage": {}},
                    ),
                    patch.object(
                        experiment,
                        "controller_subprocess_environment",
                        return_value=nullcontext(),
                    ),
                    patch.object(
                        experiment,
                        "finalize_goal_plus_search",
                        return_value={"completed": True},
                    ),
                    patch.object(
                        experiment,
                        "collect_goal_plus_state",
                        return_value={"runs": []},
                    ),
                    patch.object(
                        experiment,
                        "collect_evidence_annotator_usage",
                        return_value=annotator_usage,
                    ),
                    patch.object(
                        experiment, "goal_plus_incomplete_reason", return_value=None
                    ),
                ):
                    control = experiment.execute_goal_plus(
                        manifest, run_dir, args, {}
                    )

                configure_annotator.assert_called_once_with(
                    ANY,
                    model="gpt-test",
                    reasoning_effort="medium",
                    api_base="http://proxy.example/v1",
                )
                self.assertEqual(
                    codex_command.call_args.kwargs[
                        "max_concurrent_threads_per_session"
                    ],
                    2,
                )
                self.assertEqual(
                    control["evidence_annotator_usage"], annotator_usage
                )
        finally:
            experiment.configure_adapter("heurigym")

    def test_autolab_parser_requires_successful_verification(self) -> None:
        self.assertEqual(autolab.parse_result("cycles=1547 verify=ok"), (1547, True))
        self.assertEqual(
            autolab.parse_result("cycles=1547 verify=wrong"), (1547, False)
        )
        self.assertEqual(autolab.DIRECTION, "minimize")

    def test_frontier_cs_keeps_official_partial_score(self) -> None:
        output = (
            "points 0.9308993502 Ratio: 0.930899350 "
            "(cells=37532, W=19, H=2122, area=40318)"
        )
        self.assertEqual(frontier_cs.parse_checker_ratio(output), 0.93089935)
        self.assertEqual(frontier_cs.DIRECTION, "maximize")

    def test_frontier_portable_copy_omits_checked_in_linux_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            handout = (
                source
                / "benchmarks/ComputerSystems/MallocLab/malloclab-handout"
            )
            handout.mkdir(parents=True)
            (handout / "Makefile").write_text("all:\n\t@true\n")
            (handout / "mm.c").write_text("int x;\n")
            (handout / "mdriver.o").write_bytes(b"linux object")
            (handout / "mdriver").write_bytes(b"linux binary")
            target = root / "target"
            frontier.prepare_portable_repo(source, target)
            copied = (
                target
                / "benchmarks/ComputerSystems/MallocLab/malloclab-handout"
            )
            self.assertTrue((copied / "Makefile").is_file())
            self.assertTrue((copied / "mm.c").is_file())
            self.assertFalse((copied / "mdriver.o").exists())
            self.assertFalse((copied / "mdriver").exists())

    def test_score_order_respects_metric_direction(self) -> None:
        low = {"primary_metric": {"value": 1.0}}
        high = {"primary_metric": {"value": 2.0}}
        experiment.configure_adapter("autolab-toy-isa")
        self.assertLess(experiment.score_order_key(low), experiment.score_order_key(high))
        experiment.configure_adapter("frontier-engineering-malloclab")
        self.assertLess(experiment.score_order_key(high), experiment.score_order_key(low))
        experiment.configure_adapter("heurigym")

    def test_ale_contract_is_official_lite_and_single_artifact(self) -> None:
        self.assertEqual(ale.TASK_ID, "ahc027")
        self.assertEqual(ale.ARTIFACT_NAME, "solution.cpp")
        self.assertEqual(ale.DIRECTION, "minimize")
        self.assertIn("five public-lite seeds", ale.task_text("statement"))

    def test_local_vliw_materializes_only_public_inputs_and_scores_seed(self) -> None:
        source = ROOT / local_vliw.LOCAL_SOURCE_RELATIVE
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            metadata = local_vliw.materialize_workspace(source, workspace)
            self.assertEqual(metadata["classification"], "local_example")
            self.assertFalse(metadata["official_edgebench_comparable"])
            self.assertTrue((workspace / "solution.py").is_file())
            self.assertTrue((workspace / "test_cases/public_cases.json").is_file())
            self.assertFalse((workspace / "controller").exists())
            self.assertFalse((workspace / "test_cases/hidden_cases.json").exists())

            report = local_vliw.evaluate_workspace(workspace, source, "public")
            self.assertTrue(report["valid"])
            self.assertEqual(report["cycles"], local_vliw.BASELINE_CYCLES)
            self.assertEqual(report["classification"], "local_example")
            self.assertFalse(report["official_edgebench_comparable"])

    def test_codex_task_name_counts_as_a_bound_goal_plus_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            run_dir = workspace / ".gp/runs/run_test"
            (run_dir / "agent_sessions").mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps({"run_id": "run_test", "state": "running"})
            )
            (run_dir / "agent_sessions/agent_test.json").write_text(
                json.dumps(
                    {
                        "candidate_id": "c001",
                        "host": "codex",
                        "host_handle": {
                            "external_id": None,
                            "task_name": "/root/search_agent_test_001",
                        },
                    }
                )
            )
            (run_dir / "agent_sessions/agent_placeholder.json").write_text(
                json.dumps(
                    {
                        "candidate_id": "c001",
                        "host": "codex",
                        "host_handle": {
                            "external_id": None,
                            "task_name": "search_agent_test_001",
                        },
                    }
                )
            )
            state = openevolve_experiment.collect_goal_plus_state(workspace)
            self.assertEqual(state["runs"][0]["bound_agent_session_count"], 1)
            self.assertEqual(state["runs"][0]["bound_candidate_count"], 1)
            self.assertEqual(state["runs"][0]["unbound_agent_session_count"], 1)
            self.assertEqual(
                state["runs"][0]["bound_session_counts_by_candidate"],
                {"c001": 1},
            )

    def test_goal_plus_collector_uses_frozen_metric_direction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / ".gp"
            run_dir = root / "runs/run_test"
            candidate_dir = run_dir / "candidates/c001"
            spec_dir = root / "specs/spec_test"
            candidate_dir.mkdir(parents=True)
            spec_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps(
                    {
                        "run_id": "run_test",
                        "state": "promoted",
                        "frozen_spec_id": "spec_test",
                        "selected_score": 4.0,
                    }
                )
            )
            (spec_dir / "frozen_spec.json").write_text(
                json.dumps({"spec": {"metric_direction": "minimize"}})
            )
            (candidate_dir / "candidate.json").write_text(
                json.dumps(
                    {
                        "candidate_id": "c001",
                        "iterations": [{"score": 7.0}, {"score": 4.0}],
                    }
                )
            )
            run = openevolve_experiment.collect_goal_plus_state(workspace)["runs"][0]
            self.assertEqual(run["metric_direction"], "minimize")
            self.assertEqual(run["best_recorded_score"], 4.0)
            self.assertEqual(run["selected_score"], 4.0)

    def test_goal_plus_collector_exposes_frozen_budget_and_pi_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / ".gp"
            run_dir = root / "runs/run_test"
            spec_dir = root / "specs/spec_test"
            job_dir = root / "host-pools/pi/pool_test/jobs/job_test"
            run_dir.mkdir(parents=True)
            spec_dir.mkdir(parents=True)
            job_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps(
                    {
                        "run_id": "run_test",
                        "state": "promoted",
                        "frozen_spec_id": "spec_test",
                    }
                )
            )
            (spec_dir / "frozen_spec.json").write_text(
                json.dumps(
                    {
                        "spec": {
                            "metric_direction": "minimize",
                            "strategy": {
                                "worker_host": "pi-rpc",
                                "worker_budget": {
                                    "min_runtime_seconds": 150,
                                    "min_verifier_runs": 1,
                                    "max_runtime_seconds": 200,
                                },
                            },
                        }
                    }
                )
            )
            (job_dir / "job.json").write_text(
                json.dumps(
                    {
                        "job_id": "job_test",
                        "run_id": "run_test",
                        "candidate_id": "c001",
                        "status": "timed_out",
                    }
                )
            )
            (job_dir / "result.json").write_text(
                json.dumps({"lease": {"satisfied": False}})
            )

            run = openevolve_experiment.collect_goal_plus_state(workspace)["runs"][0]

            self.assertEqual(run["worker_host"], "pi-rpc")
            self.assertEqual(run["worker_budget"]["min_runtime_seconds"], 150)
            self.assertEqual(run["pi_pool_jobs"][0]["status"], "timed_out")
            self.assertFalse(run["pi_pool_jobs"][0]["lease"]["satisfied"])

    def test_goal_plus_collector_excludes_failed_iteration_scores(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / ".gp"
            run_dir = root / "runs/run_test"
            candidate_dir = run_dir / "candidates/c001"
            spec_dir = root / "specs/spec_test"
            candidate_dir.mkdir(parents=True)
            spec_dir.mkdir(parents=True)
            (run_dir / "run.json").write_text(
                json.dumps(
                    {
                        "run_id": "run_test",
                        "state": "promoted",
                        "frozen_spec_id": "spec_test",
                        "selected_score": 1461,
                    }
                )
            )
            (spec_dir / "frozen_spec.json").write_text(
                json.dumps({"spec": {"metric_direction": "minimize"}})
            )
            (candidate_dir / "candidate.json").write_text(
                json.dumps(
                    {
                        "candidate_id": "c001",
                        "iterations": [
                            {"score": 1461, "process_passed": True},
                            {"score": 0, "process_passed": False},
                        ],
                    }
                )
            )

            run = openevolve_experiment.collect_goal_plus_state(workspace)["runs"][0]

            self.assertEqual(run["best_recorded_score"], 1461)
            self.assertEqual(run["recorded_score_min"], 1461)
            self.assertEqual(run["recorded_score_max"], 1461)

    def test_controller_runtime_files_are_not_candidate_edits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / ".gitignore").write_text("\n")
            (workspace / "solution.cpp").write_text("int main() {}\n")
            subprocess.run(
                ["git", "init", "-q", str(workspace)], check=True
            )
            subprocess.run(
                ["git", "-C", str(workspace), "add", "."], check=True
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(workspace),
                    "-c",
                    "user.name=Benchmark Test",
                    "-c",
                    "user.email=benchmark-test@example.invalid",
                    "commit",
                    "-q",
                    "-m",
                    "seed",
                ],
                check=True,
            )
            (workspace / ".bench-runtime").mkdir()
            (workspace / ".bench-runtime/budget.json").write_text("{}\n")
            (workspace / ".tmp").mkdir()
            (workspace / ".tmp/handoff.json").write_text("{}\n")
            (workspace / ".tmp/peer.diff").write_text("scratch\n")
            (workspace / "results.tsv").write_text("commit\tscore\n")
            (workspace / "TASK.md").write_text("unauthorized\n")
            self.assertEqual(candidate_changed_paths(workspace), {"TASK.md"})

    def test_goal_seed_runtime_is_external_and_environment_is_restored(self) -> None:
        controller_runtime = ROOT / ".tmp/tests/controller-runtime-test"

        def fake_evaluate(workspace: Path, mode: str) -> dict[str, object]:
            self.assertEqual(workspace, Path("workspace"))
            self.assertEqual(mode, "public")
            self.assertEqual(
                os.environ["GOAL_PLUS_VERIFIER_TMPDIR"],
                str(controller_runtime),
            )
            return {"valid": True}

        with patch.dict(
            os.environ,
            {"GOAL_PLUS_VERIFIER_TMPDIR": "outer-runtime"},
        ):
            with patch.object(experiment, "evaluate", side_effect=fake_evaluate):
                result = experiment.evaluate_with_controller_runtime(
                    Path("workspace"), "public", controller_runtime
                )
            self.assertEqual(os.environ["GOAL_PLUS_VERIFIER_TMPDIR"], "outer-runtime")
        self.assertEqual(result, {"valid": True})

    def test_controller_closeout_uses_pinned_runtime_and_restores_environment(self) -> None:
        with patch.dict(
            os.environ,
            {"PATH": "/outer/bin", "GOAL_PLUS_VERIFIER_TMPDIR": "outer-runtime"},
            clear=False,
        ):
            runtime_bin = ROOT / ".tmp/tests/pinned-bin"
            verifier_runtime = ROOT / ".tmp/tests/controller-runtime"
            with experiment.controller_subprocess_environment(
                runtime_bin_dir=runtime_bin,
                verifier_tmpdir=verifier_runtime,
            ):
                self.assertEqual(
                    os.environ["PATH"],
                    f"{runtime_bin}:/outer/bin",
                )
                self.assertEqual(
                    os.environ["GOAL_PLUS_VERIFIER_TMPDIR"],
                    str(verifier_runtime),
                )
            self.assertEqual(os.environ["PATH"], "/outer/bin")
            self.assertEqual(os.environ["GOAL_PLUS_VERIFIER_TMPDIR"], "outer-runtime")


if __name__ == "__main__":
    unittest.main()
