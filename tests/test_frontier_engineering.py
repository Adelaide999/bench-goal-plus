from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bench_goal_plus.application import BenchmarkAgent
from bench_goal_plus.catalog import Catalog
from bench_goal_plus.errors import ContractError
from bench_goal_plus.runners.factory import create_runner
from experiments.frontier_engineering import config
from experiments.frontier_engineering import environment
from experiments.frontier_engineering import reporting
from experiments.frontier_engineering import runtime
from experiments.frontier_engineering import task_adapter


ROOT = Path(__file__).resolve().parents[1]
PLAIN_CODEX_EVIDENCE = (
    ROOT
    / "evidence/runs/2026-08-07-frontier-engineering-energy-storage-plain-codex"
)
GOAL_PLUS_PI_EVIDENCE = (
    ROOT
    / "evidence/runs/2026-08-07-frontier-engineering-energy-storage-goal-plus-pi"
)
CPU_DEFAULT_EVIDENCE = (
    ROOT
    / "evidence/environment/2026-08-07-frontier-engineering-cpu-default-doctor.json"
)
EXPECTED_V1_LITE_TASKS = (
    "ComputerSystems/MallocLab",
    "QuantumComputing/task_01_routing_qftentangled",
    "JobShop/abz",
    "InventoryOptimization/disruption_eoqd",
    "EnergyStorage/BatteryFastChargingSPMe",
    "Robotics/RobotArmCycleTimeOptimization",
    "Optics/holographic_multiplane_focusing",
    "WirelessChannelSimulation/HighReliableSimulation",
    "ReactionOptimisation/snar_multiobjective",
    "StructuralOptimization/TopologyOptimization",
)
EXPECTED_V1_LITE_CPU_TASKS = tuple(
    task_id
    for task_id in EXPECTED_V1_LITE_TASKS
    if task_id != "Robotics/RobotArmCycleTimeOptimization"
)


def initialize_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test Controller"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "config",
            "user.email",
            "test-controller@example.invalid",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "fixture"],
        check=True,
    )


def make_upstream(root: Path, task_id: str, initial: str) -> Path:
    task_dir = root / "benchmarks" / task_id
    metadata = task_dir / "frontier_eval"
    metadata.mkdir(parents=True)
    candidate = task_dir / initial
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("score = 1\n", encoding="utf-8")
    (task_dir / "Task.md").write_text("Optimize the fixture.\n", encoding="utf-8")
    values = {
        "initial_program.txt": initial,
        "candidate_destination.txt": initial,
        "eval_command.txt": "{python} verification.py {candidate}\n",
        "copy_files.txt": ".\n",
        "readonly_files.txt": "Task.md\n",
    }
    for name, value in values.items():
        (metadata / name).write_text(value, encoding="utf-8")
    (metadata / "agent_files.txt").write_text("Task.md\n", encoding="utf-8")
    unified = root / "frontier_eval/tasks/unified"
    (unified / "evaluator").mkdir(parents=True)
    (unified / "evaluator/python.py").write_text("# evaluator\n", encoding="utf-8")
    (unified / "spec.py").write_text("# spec\n", encoding="utf-8")
    initialize_git(root)
    return candidate


class FrontierEngineeringTest(unittest.TestCase):
    def tearDown(self) -> None:
        task_adapter.configure_task("ComputerSystems/MallocLab")

    def test_v1_lite_profile_preserves_upstream_task_and_runtime_matrix(self) -> None:
        _, profile = config.load_profile("v1-lite-codex-1h")
        _, cpu_profile = config.load_profile("v1-lite-cpu-codex-1h")

        self.assertEqual(tuple(profile["task_ids"]), EXPECTED_V1_LITE_TASKS)
        self.assertEqual(profile["accelerator_policy"], "nvidia-cuda-opt-in")
        self.assertEqual(tuple(cpu_profile["task_ids"]), EXPECTED_V1_LITE_CPU_TASKS)
        self.assertEqual(cpu_profile["accelerator_policy"], "cpu-only")
        self.assertEqual(tuple(config.V1_LITE_TASKS), EXPECTED_V1_LITE_TASKS)
        self.assertEqual(config.V1_LITE_CPU_TASKS, EXPECTED_V1_LITE_CPU_TASKS)
        self.assertEqual(
            config.V1_LITE_TASKS["JobShop/abz"].runtime_env,
            "frontier-eval-driver",
        )
        self.assertEqual(
            config.V1_LITE_TASKS["JobShop/abz"].runtime_python_env,
            "frontier-v1-main",
        )
        reaction = config.V1_LITE_TASKS[
            "ReactionOptimisation/snar_multiobjective"
        ]
        self.assertEqual(reaction.runtime_env, "frontier-eval-driver")
        self.assertEqual(reaction.runtime_python_env, "frontier-v1-summit")
        self.assertEqual(
            config.V1_LITE_TASKS[
                "EnergyStorage/BatteryFastChargingSPMe"
            ].evaluator_timeout_seconds,
            300,
        )
        self.assertEqual(
            config.V1_LITE_TASKS[
                "Robotics/RobotArmCycleTimeOptimization"
            ].evaluator_timeout_seconds,
            600,
        )
        self.assertEqual(
            config.V1_LITE_TASKS[
                "Robotics/RobotArmCycleTimeOptimization"
            ].accelerator,
            "nvidia-cuda",
        )

    def test_cpu_policy_rejects_known_cuda_tasks(self) -> None:
        _, profile = config.load_profile("v1-lite-cpu-codex-1h")
        for task_id in (
            "Robotics/RobotArmCycleTimeOptimization",
            "Aerodynamics/CarAerodynamicsSensing",
            "KernelEngineering/MLA",
        ):
            invalid = json.loads(json.dumps(profile))
            invalid["task_ids"].append(task_id)
            with self.subTest(task_id=task_id), self.assertRaisesRegex(
                config.FrontierEngineeringContractError,
                "NVIDIA CUDA tasks are excluded by cpu-only policy",
            ):
                config.validate_profile(str(invalid["id"]), invalid)

    def test_profile_rejects_unproven_c_and_invalid_worker_minimum(self) -> None:
        _, profile = config.load_profile("jobshop-codex-smoke")
        with self.assertRaisesRegex(config.FrontierEngineeringContractError, "C=1"):
            config.resolve_profile(profile, cell_concurrency=2)
        with self.assertRaisesRegex(
            config.FrontierEngineeringContractError, "require K=1"
        ):
            config.resolve_profile(profile, concurrency=2)
        invalid = json.loads(json.dumps(profile))
        invalid["worker_min_runtime_seconds"] = invalid["worker_runtime_seconds"] + 1
        with self.assertRaisesRegex(
            config.FrontierEngineeringContractError, "worker minimum"
        ):
            config.validate_profile(str(invalid["id"]), invalid)

    def test_task_bridge_materializes_selected_artifact_and_official_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upstream = root / "upstream"
            workspace = root / "workspace"
            make_upstream(
                upstream,
                "Robotics/RobotArmCycleTimeOptimization",
                "baseline/solution.py",
            )
            task_adapter.configure_task("Robotics/RobotArmCycleTimeOptimization")

            result = task_adapter.materialize_workspace(upstream, workspace)
            metadata = json.loads((workspace / "task.json").read_text())

            self.assertEqual(result["task_id"], "Robotics/RobotArmCycleTimeOptimization")
            self.assertEqual(metadata["artifact_source_relative"], "baseline/solution.py")
            self.assertEqual(metadata["artifact_name"], "solution.py")
            self.assertEqual(metadata["evaluator_timeout_seconds"], 600)
            self.assertTrue((workspace / "solution.py").is_file())
            self.assertIn("Optimize the fixture", (workspace / "TASK.md").read_text())
            self.assertFalse((workspace / ".gp").exists())

    def test_task_bridge_preserves_raw_metric_and_runtime_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upstream = root / "upstream"
            workspace = root / "workspace"
            make_upstream(
                upstream,
                "Robotics/RobotArmCycleTimeOptimization",
                "baseline/solution.py",
            )
            task_adapter.configure_task("Robotics/RobotArmCycleTimeOptimization")
            task_adapter.materialize_workspace(upstream, workspace)
            (workspace / "solution.py").write_text("score = 2\n", encoding="utf-8")
            observed: dict[str, object] = {}

            def run_bridge(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                observed["command"] = command
                observed["environment"] = kwargs["env"]
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(
                        {
                            "metrics": {
                                "valid": 1.0,
                                "combined_score": 12.5,
                                "feasible": 1.0,
                            },
                            "artifacts": {"native": "kept"},
                            "diagnostics": "official output",
                        }
                    ),
                    "",
                )

            metadata = json.loads((workspace / "task.json").read_text())
            with (
                mock.patch.object(
                    task_adapter, "candidate_changed_paths", return_value={"solution.py"}
                ),
                mock.patch.object(
                    task_adapter, "git_commit", return_value=metadata["upstream_commit"]
                ),
                mock.patch.object(task_adapter.subprocess, "run", side_effect=run_bridge),
            ):
                report = task_adapter.evaluate_workspace(workspace, upstream, "final")

            self.assertTrue(report["valid"])
            self.assertEqual(report["combined_score"], 12.5)
            self.assertEqual(report["raw_metrics"]["feasible"], 1.0)
            self.assertEqual(report["artifacts"]["native"], "kept")
            environment_values = observed["environment"]
            self.assertIsInstance(environment_values, dict)
            self.assertEqual(
                environment_values["FRONTIER_EVAL_EVALUATOR_TIMEOUT_S"], "600"
            )
            command = observed["command"]
            self.assertIn("frontier-v1-main", command)

    def test_inventory_is_read_only_and_does_not_duplicate_missing_seed(self) -> None:
        _, profile = config.load_profile("jobshop-codex-smoke")
        with tempfile.TemporaryDirectory() as temporary:
            upstream = Path(temporary) / "missing-upstream"
            with mock.patch.object(environment, "UPSTREAM_ROOT", upstream):
                inventory = environment.local_inventory(profile)

        self.assertTrue(inventory["read_only"])
        self.assertFalse(inventory["acquisition_attempted"])
        accelerator = next(
            item for item in inventory["checks"] if item["kind"] == "accelerator-policy"
        )
        self.assertEqual(accelerator["policy"], "cpu-only")
        self.assertEqual(accelerator["selected_cuda_tasks"], [])
        self.assertEqual(accelerator["gpu_probe_stage"], "not-required")
        task = next(item for item in inventory["checks"] if item["kind"] == "task")
        self.assertEqual(len(task["missing"]), len(set(task["missing"])))
        self.assertFalse(inventory["passed"])

    def test_seed_probe_uses_the_registered_evaluator_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            upstream = Path(temporary) / "upstream"
            make_upstream(
                upstream,
                "EnergyStorage/BatteryFastChargingSPMe",
                "init.py",
            )
            observed: dict[str, object] = {}

            def run_bridge(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                observed["environment"] = kwargs["env"]
                observed["timeout"] = kwargs["timeout"]
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(
                        {
                            "metrics": {
                                "valid": 1.0,
                                "combined_score": 12.5,
                                "timeout_budget_s": 300.0,
                            }
                        }
                    ),
                    "",
                )

            with (
                mock.patch.object(environment, "UPSTREAM_ROOT", upstream),
                mock.patch.object(
                    environment.subprocess, "run", side_effect=run_bridge
                ),
            ):
                result = environment._seed_probe(
                    "EnergyStorage/BatteryFastChargingSPMe"
                )

        probe_environment = observed["environment"]
        self.assertIsInstance(probe_environment, dict)
        self.assertEqual(
            probe_environment["FRONTIER_EVAL_EVALUATOR_TIMEOUT_S"], "300"
        )
        self.assertEqual(observed["timeout"], 300)
        self.assertTrue(result["passed"])
        self.assertEqual(result["metrics"]["timeout_budget_s"], 300.0)

    def test_accelerator_doctor_probes_only_explicit_gpu_profile(self) -> None:
        _, cpu_profile = config.load_profile("v1-lite-cpu-codex-1h")
        _, gpu_profile = config.load_profile("v1-lite-codex-1h")

        self.assertEqual(environment._accelerator_checks(cpu_profile), [])
        with (
            mock.patch.object(
                environment,
                "_nvidia_driver_probe",
                return_value={"kind": "host-accelerator", "passed": True},
            ) as driver_probe,
            mock.patch.object(
                environment,
                "_cuda_runtime_probe",
                return_value={"kind": "runtime-accelerator", "passed": True},
            ) as runtime_probe,
        ):
            checks = environment._accelerator_checks(gpu_profile)

        driver_probe.assert_called_once_with()
        runtime_probe.assert_called_once_with("frontier-v1-main")
        self.assertEqual(
            [item["kind"] for item in checks],
            ["host-accelerator", "runtime-accelerator"],
        )

    def test_catalog_and_preset_select_native_runner(self) -> None:
        catalog = Catalog()
        agent = BenchmarkAgent(catalog=catalog)
        target = catalog.targets["frontier-engineering"]
        runner = catalog.runners[target.runner_id]

        self.assertEqual(target.runner_id, "frontier-engineering-native")
        self.assertIsNone(target.adapter_id)
        self.assertTrue(target.local_asset_inventory)
        self.assertEqual(target.default_inventory_profile, "v1-lite-cpu-codex-1h")
        self.assertEqual(
            runner.supported_methods,
            ("plain-codex", "plain-pi", "goal-plus-codex", "goal-plus-pi"),
        )
        energy_spec = agent.resolve_spec(
            preset_id="frontier-engineering-energy-storage-codex-smoke"
        )
        self.assertEqual(energy_spec.profile, "energy-storage-codex-smoke")
        self.assertEqual(
            energy_spec.concurrency(), {"T": 300, "K": 1, "C": 1, "R": 1}
        )
        _, energy_profile = config.load_profile(energy_spec.profile)
        self.assertEqual(
            energy_profile["task_ids"], ["EnergyStorage/BatteryFastChargingSPMe"]
        )
        for preset_id, method in (
            ("frontier-engineering-energy-storage-pi-smoke", "plain-pi"),
            (
                "frontier-engineering-energy-storage-goal-plus-pi-smoke",
                "goal-plus-pi",
            ),
        ):
            pi_spec = agent.resolve_spec(preset_id=preset_id)
            self.assertEqual(pi_spec.methods, (method,))
            self.assertEqual(
                pi_spec.concurrency(),
                {
                    "T": 600 if method == "goal-plus-pi" else 300,
                    "K": 1,
                    "C": 1,
                    "R": 1,
                },
            )
            _, pi_profile = config.load_profile(pi_spec.profile)
            self.assertEqual(
                pi_profile["task_ids"], ["EnergyStorage/BatteryFastChargingSPMe"]
            )
        spec = agent.resolve_spec(
            preset_id="frontier-engineering-jobshop-codex-smoke"
        )
        self.assertEqual(spec.concurrency(), {"T": 300, "K": 1, "C": 1, "R": 1})
        commands, campaign = create_runner(spec.runner).prepare_commands(spec)
        self.assertIn("experiments/frontier_engineering/experiment.py", commands[0])
        self.assertIn("--method", commands[0])
        self.assertIn("--seeds", commands[0])
        self.assertEqual(
            campaign.path,
            ROOT / "runs/frontier-engineering" / spec.campaign_id,
        )
        with self.assertRaisesRegex(ContractError, "use C=1"):
            agent.resolve_spec(
                target_ids=("frontier-engineering",),
                profile="jobshop-codex-smoke",
                methods=("plain-codex",),
                model="gpt-5.6-sol",
                reasoning_effort="medium",
                wall_time_seconds=300,
                live_search_concurrency=1,
                cell_concurrency=2,
            )

    def test_native_runner_forwards_repeat_seeds_to_frontier_prepare(self) -> None:
        spec = BenchmarkAgent(catalog=Catalog()).resolve_spec(
            target_ids=("frontier-engineering",),
            profile="v1-lite-cpu-codex-1h",
            methods=("plain-pi",),
            seeds=(1, 2, 3, 4),
            model="gpt-5.6-sol",
            reasoning_effort="medium",
            wall_time_seconds=3600,
            live_search_concurrency=1,
            cell_concurrency=1,
        )

        command = create_runner(spec.runner).prepare_commands(spec)[0][0]

        seed_flag = command.index("--seeds")
        self.assertEqual(command[seed_flag + 1 : seed_flag + 5], ["1", "2", "3", "4"])
        _, profile = config.load_profile(spec.profile)
        resolved = config.resolve_profile(profile, seeds=list(spec.seeds))
        self.assertEqual(resolved["seeds"], [1, 2, 3, 4])

    def test_pi_doctor_checks_exact_model_without_persisting_credentials(self) -> None:
        _, profile = config.load_profile("energy-storage-pi-smoke")
        with (
            mock.patch.dict(
                environment.os.environ,
                {
                    "OPENAI_BASE_URL": "https://provider.example/v1",
                    "OPENAI_API_KEY": "secret-value",
                },
            ),
            mock.patch.object(environment.shutil, "which", return_value="/bin/pi"),
            mock.patch.object(
                environment,
                "command_output",
                side_effect=[
                    (True, "0.83.0"),
                    (
                        True,
                        "provider model context\n"
                        "bench-openai gpt-5.6-sol 272K",
                    ),
                ],
            ),
            mock.patch(
                "experiments.openevolve_compare.experiment.write_pi_models_config"
            ) as write_models,
        ):
            checks = environment._pi_agent_checks(profile)

        self.assertTrue(all(item["passed"] for item in checks))
        provider = checks[1]
        self.assertEqual(provider["model"], "bench-openai/gpt-5.6-sol")
        self.assertEqual(provider["api_key_env"], "OPENAI_API_KEY")
        serialized = json.dumps(checks)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("https://provider.example/v1", serialized)
        write_models.assert_called_once()

    def test_plain_codex_stage_is_backed_by_archived_native_evidence(self) -> None:
        registry = json.loads((ROOT / "benchmarks/registry.json").read_text())
        benchmark = next(
            item
            for item in registry["items"]
            if item["id"] == "frontier-engineering-lite"
        )
        summary_path = PLAIN_CODEX_EVIDENCE / "summary.json"
        official_path = PLAIN_CODEX_EVIDENCE / "official-report.json"
        candidate_path = PLAIN_CODEX_EVIDENCE / "candidate.py"
        summary = json.loads(summary_path.read_text())
        official = json.loads(official_path.read_text())

        self.assertEqual(benchmark["stages"]["plain_codex"], "pass")
        self.assertIn(
            str(summary_path.relative_to(ROOT)),
            benchmark["stage_evidence"]["plain_codex"],
        )
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["budget"], {
            "T": 300,
            "K": 1,
            "C": 1,
            "R": 1,
            "soft_closeout_seconds": 60,
            "hard_kill_grace_seconds": 30,
        })
        self.assertTrue(official["valid"])
        self.assertEqual(official["primary_metric"]["direction"], "maximize")
        self.assertEqual(official["primary_metric"]["value"], 121.2063096578825)
        self.assertEqual(summary["result"]["final_score"], 121.2063096578825)
        self.assertGreater(
            summary["result"]["final_score"], summary["result"]["seed_score"]
        )
        self.assertTrue(candidate_path.is_file())

    def test_goal_plus_pi_stage_is_backed_by_archived_native_evidence(self) -> None:
        registry = json.loads((ROOT / "benchmarks/registry.json").read_text())
        benchmark = next(
            item
            for item in registry["items"]
            if item["id"] == "frontier-engineering-lite"
        )
        summary_path = GOAL_PLUS_PI_EVIDENCE / "summary.json"
        official_path = GOAL_PLUS_PI_EVIDENCE / "official-report.json"
        candidate_path = GOAL_PLUS_PI_EVIDENCE / "candidate.py"
        summary = json.loads(summary_path.read_text())
        official = json.loads(official_path.read_text())

        self.assertEqual(benchmark["stages"]["goal_plus_pi"], "pass")
        for path in (summary_path, official_path, candidate_path):
            self.assertIn(
                str(path.relative_to(ROOT)),
                benchmark["stage_evidence"]["goal_plus_pi"],
            )
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(
            {key: summary["budget"][key] for key in ("T", "K", "C", "R")},
            {"T": 600, "K": 1, "C": 1, "R": 1},
        )
        self.assertEqual(summary["goal_plus"]["actual_subagent_count"], 1)
        self.assertTrue(summary["goal_plus"]["subagent_count_matches_K"])
        self.assertEqual(summary["execution"]["selected_iteration"], 5)
        self.assertEqual(
            summary["execution"]["selected_git_revision"],
            "a8fef7a9f76aedc99e25029874a1a81791865121",
        )
        self.assertTrue(official["valid"])
        self.assertEqual(official["primary_metric"]["direction"], "maximize")
        self.assertEqual(
            official["primary_metric"]["value"], summary["result"]["final_score"]
        )
        self.assertGreater(
            summary["result"]["final_score"], summary["result"]["seed_score"]
        )
        self.assertTrue(candidate_path.is_file())

    def test_default_cpu_doctor_evidence_excludes_gpu_tasks(self) -> None:
        payload = json.loads(CPU_DEFAULT_EVIDENCE.read_text())

        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["profile"], "v1-lite-cpu-codex-1h")
        self.assertEqual(payload["accelerator_policy"]["mode"], "cpu-only")
        self.assertEqual(payload["accelerator_policy"]["selected_cuda_tasks"], [])
        self.assertFalse(payload["accelerator_policy"]["gpu_checks_executed"])
        task_ids = tuple(item["task_id"] for item in payload["seed_evaluations"])
        self.assertEqual(task_ids, EXPECTED_V1_LITE_CPU_TASKS)
        self.assertTrue(
            all(
                item["valid"] == 1.0 and item["timeout"] == 0.0
                for item in payload["seed_evaluations"]
            )
        )

    def test_prepare_passes_dynamic_task_to_standalone_runner(self) -> None:
        _, profile = config.load_profile("jobshop-codex-smoke")
        with tempfile.TemporaryDirectory() as temporary:
            runs_root = Path(temporary) / "runs"
            with (
                mock.patch.object(config, "RUNS_ROOT", runs_root),
                mock.patch.object(runtime.standalone, "prepare", return_value=0) as prepare,
            ):
                destination = runtime.prepare("native-test", profile, Path("profile.json"))

            prepared = prepare.call_args.args[0]
            self.assertEqual(prepared.task_id, "JobShop/abz")
            self.assertEqual(prepared.adapter_module, runtime.ADAPTER_MODULE)
            campaign = json.loads((destination / "campaign.json").read_text())
            self.assertEqual(campaign["state"], "prepared")
            self.assertEqual(campaign["budget"]["live_search_concurrency"], 1)

    def test_execute_and_finalize_require_valid_official_score(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "campaign"
            run_dir = destination / "cell"
            run_dir.mkdir(parents=True)
            campaign = {
                "schema_version": 1,
                "campaign_id": "native-test",
                "benchmark": "frontier-engineering",
                "suite": "v1-lite",
                "state": "prepared",
                "model": "test-model",
                "reasoning_effort": "medium",
                "budget": {
                    "wall_time_seconds": 10,
                    "live_search_concurrency": 1,
                    "cell_concurrency": 1,
                    "attempts": 1,
                },
                "cells": [
                    {
                        "cell_id": "jobshop",
                        "task_id": "JobShop/abz",
                        "method": "plain-codex",
                        "seed": 1,
                        "run_dir": str(run_dir),
                        "state": "prepared",
                        "error": None,
                    }
                ],
            }
            config.write_json(destination / "campaign.json", campaign)

            def invalid_run(_args: object) -> int:
                config.write_json(
                    run_dir / "experiment.json",
                    {
                        "status": "finished",
                        "task_id": "JobShop/abz",
                        "method": "plain-codex",
                        "task": {
                            "artifact_name": "init.py",
                            "primary_metric": "combined_score",
                            "direction": "maximize",
                        },
                        "budget": {"wall_time_seconds": 10, "concurrency": 1},
                        "execution": {},
                    },
                )
                config.write_json(
                    run_dir / "final-eval.json",
                    {
                        "valid": False,
                        "primary_metric": {
                            "name": "combined_score",
                            "value": -1e18,
                            "direction": "maximize",
                        },
                        "raw_metrics": {"combined_score": -1e18, "valid": 0.0},
                    },
                )
                return 0

            with mock.patch.object(runtime.standalone, "execute", side_effect=invalid_run):
                self.assertEqual(runtime.execute_campaign(destination), 2)

            final_campaign = json.loads((destination / "campaign.json").read_text())
            self.assertEqual(final_campaign["state"], "partial")
            summary = reporting.finalize_campaign(destination)
            self.assertEqual(summary["state"], "partial")
            self.assertEqual(summary["records"][0]["score"]["final"], -1e18)
            self.assertFalse(summary["records"][0]["score"]["valid"])


if __name__ == "__main__":
    unittest.main()
