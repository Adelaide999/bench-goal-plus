from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from adapters.registry import load_adapter_module
from bench_goal_plus.catalog import Catalog
from bench_goal_plus.search_scheduler import (
    GoalPlusSearchScheduler,
    search_scheduler_from_namespace,
)
from bench_runtime_paths import ensure_temp_root
from experiments.aibench_coding import bridge, reporting, runtime, sandbox, task_adapter
from experiments.aibench_coding.cli import build_parser
from experiments.aibench_coding.config import (
    AIBenchContractError,
    load_profile,
    pi_api,
    resolve_profile,
    split_model,
)
from experiments.benchmark_compare import experiment as benchmark_compare
from experiments.benchmark_compare import pi_worker_launcher


ROOT = Path(__file__).resolve().parents[1]


class AIBenchCodingContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="aibench-coding-test-", dir=ensure_temp_root("tests")
        )
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _sandbox_command(
        self, role: str, method: str, arguments: list[str]
    ) -> tuple[list[str], Path, Path, Path, Path]:
        cell = self.root / "campaign" / "cells" / "cell-1"
        workspace = (
            cell / "workspace"
            if method.startswith("goal-plus-")
            else cell / "workspaces" / "lane-00"
        )
        hidden = self.root / "aibench-checkout"
        binary = self.root / role
        workspace.mkdir(parents=True)
        hidden.mkdir()
        binary.write_text("", encoding="utf-8")
        environment = {
            "AIBENCH_AGENT_ROLE": role,
            "AIBENCH_METHOD": method,
            f"AIBENCH_REAL_{role.upper()}_BIN": str(binary),
            "AIBENCH_HIDDEN_CHECKOUT": str(hidden),
            "AIBENCH_CELL_ROOT": str(cell),
        }
        previous = Path.cwd()
        try:
            os.chdir(workspace)
            with (
                mock.patch.dict(os.environ, environment, clear=False),
                mock.patch.object(
                    sandbox.shutil, "which", return_value="/usr/bin/bwrap"
                ),
            ):
                command = sandbox.build_command(arguments)
        finally:
            os.chdir(previous)
        return command, cell, workspace, hidden, binary

    def test_bwrap_option_detection_supports_old_and_new_versions(self) -> None:
        for help_output, expected in (
            ("--unshare-user --disable-userns --cap-drop", True),
            ("--unshare-user --cap-drop", False),
        ):
            with self.subTest(help_output=help_output), mock.patch.object(
                pi_worker_launcher.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    ["/usr/bin/bwrap", "--help"],
                    0,
                    stdout=help_output,
                    stderr="",
                ),
            ):
                self.assertEqual(
                    pi_worker_launcher._bwrap_supports_option(
                        "/usr/bin/bwrap", "--disable-userns", {}
                    ),
                    expected,
                )

    def test_bwrap_option_detection_fails_closed(self) -> None:
        with mock.patch.object(
            pi_worker_launcher.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(
                ["/usr/bin/bwrap", "--help"],
                1,
                stdout="",
                stderr="broken",
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "failed to inspect Bubblewrap options"
            ):
                pi_worker_launcher._bwrap_supports_option(
                    "/usr/bin/bwrap", "--disable-userns", {}
                )

    def test_pi_runtime_root_preserves_npm_bin_symlink(self) -> None:
        runtime_root = self.root / "pi-runtime"
        executable = runtime_root / "node_modules" / ".bin" / "pi"
        target = (
            runtime_root
            / "node_modules"
            / "@earendil-works"
            / "pi-coding-agent"
            / "dist"
            / "cli.js"
        )
        target.parent.mkdir(parents=True)
        executable.parent.mkdir(parents=True)
        target.write_text("#!/usr/bin/env node\n", encoding="utf-8")
        executable.symlink_to(
            Path("..") / "@earendil-works" / "pi-coding-agent" / "dist" / "cli.js"
        )

        self.assertEqual(
            pi_worker_launcher._executable_runtime_root(executable),
            runtime_root.resolve(),
        )
        self.assertEqual(
            pi_worker_launcher._executable_entrypoint(executable),
            target.resolve(strict=True),
        )

    def _zai_profile(self, methods: list[str]) -> dict[str, object]:
        _path, profile = load_profile("smoke")
        profile["methods"] = methods
        profile["model"] = (
            "zai/glm-5.2"
            if any("pi" in method for method in methods)
            else "glm-5.2"
        )
        profile["agent_provider"] = {
            "id": "zai",
            "name": "Z.AI Anthropic-compatible API",
            "auth_mode": "anthropic-compatible",
            "base_url_env": "ZAI_BASE_URL",
            "api_key_env": "ZAI_API_KEY",
            "wire_api": "anthropic-messages",
        }
        return profile

    def test_catalog_exposes_four_methods_and_native_capabilities(self) -> None:
        catalog = Catalog()
        runner = catalog.runners["aibench-coding-native"]
        self.assertEqual(
            set(runner.supported_methods),
            {
                "plain-codex",
                "plain-pi",
                "goal-plus-codex",
                "goal-plus-pi",
            },
        )
        self.assertTrue(runner.capabilities.cell_concurrency)
        self.assertTrue(runner.capabilities.official_evaluator)
        self.assertFalse(runner.capabilities.detach)
        target = catalog.targets["aibench-coding"]
        self.assertTrue(target.local_asset_inventory)
        self.assertEqual(target.docker.requirement, "not_required")

    def test_registry_promotes_only_the_evidenced_goal_plus_codex_method(self) -> None:
        registry = json.loads(
            (ROOT / "benchmarks" / "registry.json").read_text(encoding="utf-8")
        )
        item = next(
            entry for entry in registry["items"] if entry["id"] == "aibench-coding"
        )
        evidence_path = item["stage_evidence"]["goal_plus_codex"][0]
        summary = json.loads((ROOT / evidence_path).read_text(encoding="utf-8"))

        self.assertEqual(item["stages"]["goal_plus_codex"], "pass")
        self.assertEqual(item["stages"]["plain_codex"], "partial")
        self.assertEqual(item["stages"]["plain_pi"], "partial")
        self.assertEqual(item["stages"]["goal_plus_pi"], "partial")
        self.assertEqual(item["stages"]["campaign_ready"], "partial")
        self.assertEqual(summary["method"]["id"], "goal-plus-codex")
        self.assertEqual(summary["status"], "completed")
        self.assertTrue(summary["result"]["score_valid"])
        self.assertTrue(summary["execution"]["topology"]["matches_k"])

    def test_profile_and_provider_model_route_are_frozen(self) -> None:
        _path, profile = load_profile("smoke")
        self.assertEqual(profile["expected_case_set_fingerprint"], "9149d02169845dc5")
        self.assertEqual(profile["agent_provider"]["auth_mode"], "openai-compatible")
        self.assertEqual(
            split_model(profile),
            ("bench-openai", "gpt-5.6-sol"),
        )
        with self.assertRaises(AIBenchContractError):
            resolve_profile(profile, methods=["plain-pi"], model="gpt-5.6-sol")
        oauth = json.loads(json.dumps(profile))
        oauth["methods"] = ["goal-plus-codex"]
        oauth["model"] = "gpt-5.6-sol"
        oauth["agent_provider"] = {
            "id": "openai-codex",
            "name": "Codex ChatGPT OAuth",
            "auth_mode": "codex-oauth",
            "base_url_env": None,
            "api_key_env": None,
            "wire_api": "codex-chatgpt",
        }
        with self.assertRaisesRegex(AIBenchContractError, "openai-compatible"):
            resolve_profile(oauth)

    def test_pi_accepts_anthropic_messages_provider(self) -> None:
        profile = self._zai_profile(["goal-plus-pi"])

        resolved = resolve_profile(profile)

        self.assertEqual(split_model(resolved), ("zai", "glm-5.2"))
        self.assertEqual(pi_api(resolved), "anthropic-messages")

    def test_cli_accepts_shared_search_scheduler_contract(self) -> None:
        scheduler = GoalPlusSearchScheduler(
            host="pi-rpc",
            model="zai/glm-5.2",
            reasoning_effort="low",
            timeout_seconds=180,
            reward="evidence_llm_value/v3",
            allocation="value_guided_replace/v2",
        )
        args = build_parser().parse_args(
            [
                "prepare",
                "--profile",
                "smoke",
                "--campaign-id",
                "scheduler-smoke",
                "--search-scheduler-config-json",
                scheduler.to_json(),
            ]
        )

        self.assertEqual(search_scheduler_from_namespace(args), scheduler)

    def test_codex_rejects_anthropic_messages_provider(self) -> None:
        profile = self._zai_profile(["goal-plus-codex"])

        with self.assertRaisesRegex(
            AIBenchContractError, "Codex methods require openai-compatible responses"
        ):
            resolve_profile(profile)

    def test_runtime_passes_anthropic_messages_to_pi(self) -> None:
        profile = self._zai_profile(["goal-plus-pi"])
        run_dir = self.root / "cell"
        run_dir.mkdir()
        captured_command: list[str] = []

        def fake_run(command: list[str], **kwargs: object) -> object:
            del kwargs
            captured_command.extend(command)
            (run_dir / "experiment.json").write_text(
                json.dumps({"status": "finished"}), encoding="utf-8"
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with (
            mock.patch.dict(
                os.environ,
                {"ZAI_BASE_URL": "https://example.invalid", "ZAI_API_KEY": "key"},
                clear=False,
            ),
            mock.patch.object(
                runtime,
                "_sandbox_binaries",
                return_value=(Path("/codex"), Path("/pi")),
            ),
            mock.patch.object(runtime.subprocess, "run", side_effect=fake_run),
            mock.patch.object(
                runtime.shutil, "which", side_effect=lambda name: f"/bin/{name}"
            ),
        ):
            result = runtime._run_cell(
                profile,
                {"run_dir": str(run_dir), "method": "goal-plus-pi"},
            )

        self.assertEqual(
            captured_command[captured_command.index("--pi-api") + 1],
            "anthropic-messages",
        )
        self.assertEqual(
            captured_command[captured_command.index("--pi-provider-id") + 1],
            "zai",
        )
        self.assertEqual(result["state"], "completed")

    def test_cli_accepts_native_runner_override_contract(self) -> None:
        args = build_parser().parse_args(
            [
                "doctor",
                "--profile",
                "smoke",
                "--method",
                "goal-plus-pi",
                "--model",
                "bench-openai/gpt-5.6-sol",
                "--reasoning-effort",
                "high",
            ]
        )
        self.assertEqual(args.method, ["goal-plus-pi"])
        self.assertEqual(args.reasoning_effort, "high")

    def test_all_four_methods_use_controller_only_hidden_evaluation(self) -> None:
        self.assertEqual(task_adapter.EVALUATION_MODE, "visible")
        loaded = load_adapter_module(
            "aibench-coding-native", "experiments.aibench_coding.task_adapter"
        )
        self.assertTrue(
            loaded.manifest_contract()["controller_only_official_evaluation"]
        )
        self.assertTrue(
            {
                "plain-codex",
                "plain-pi",
                "goal-plus-codex",
                "goal-plus-pi",
            }.issubset(benchmark_compare.CONTROLLER_ONLY_METHODS)
        )
        self.assertEqual(
            task_adapter.PI_WORKER_SANDBOX["writable_workspace_paths"],
            ["submission"],
        )
        self.assertEqual(
            task_adapter.PI_WORKER_SANDBOX["evaluation_mode"], "visible"
        )

    def test_goal_plus_pi_worker_uses_unwrapped_binary_inside_worker_sandbox(
        self,
    ) -> None:
        policy = task_adapter.PI_WORKER_SANDBOX
        expected = {
            **policy,
            "pass_env": [
                *policy["pass_env"],
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                "OPENAI_API_BASE_URL",
            ],
        }
        environment = {
            "PATH": "/usr/bin",
            benchmark_compare.REAL_PI_BIN_ENV: "/host/bin/pi",
        }
        with (
            mock.patch.object(benchmark_compare, "PI_WORKER_SANDBOX", policy),
            mock.patch.object(
                benchmark_compare,
                "_resolve_real_pi_binary",
                return_value=Path("/host/bin/pi"),
            ) as resolve,
            mock.patch.object(
                benchmark_compare.shutil, "which", return_value="/usr/bin/bwrap"
            ),
        ):
            benchmark_compare._configure_pi_worker_sandbox_environment(
                {
                    "method": "goal-plus-pi",
                    "goal_plus_config": {"worker_sandbox": expected},
                },
                environment,
                "OPENAI_API_KEY",
                "/cell/pi-sandbox",
            )
        self.assertEqual(resolve.call_args.args[0], "/host/bin/pi")
        self.assertEqual(
            environment[benchmark_compare.REAL_PI_BIN_ENV], "/host/bin/pi"
        )

    def _metadata(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "case_id": "rev-09f7740f614d3ea9",
            "case_set": "_clean2026",
            "case_set_fingerprint": "9149d02169845dc5",
            "case_fingerprint": "v3:test",
            "task_type": "bugfix",
            "language": "python",
            "prompt": "Repair build.py.",
            "grader_command": "true",
            "protected_files": [],
            "validity_ok": True,
        }

    def test_model_free_materialize_and_public_evaluation(self) -> None:
        source = self.root / "checkout" / "benchmarks" / "coding"
        source.mkdir(parents=True)
        workspace = self.root / "workspace"

        def fake_bridge(_command: list[str], _source: Path, timeout: int = 300) -> dict:
            del timeout
            submission = workspace / "submission"
            submission.mkdir()
            (submission / "build.py").write_text("value = 1\n", encoding="utf-8")
            return self._metadata()

        with (
            mock.patch.object(task_adapter, "_bridge", side_effect=fake_bridge),
            mock.patch.object(task_adapter, "git_commit", return_value="a" * 40),
        ):
            prepared = task_adapter.materialize_workspace(source, workspace)
            report = task_adapter.evaluate_workspace(workspace, source, "public")
        self.assertEqual(prepared["source_revision"], "a" * 40)
        self.assertTrue(report["valid"])
        self.assertEqual(report["primary_metric"]["value"], 1.0)
        self.assertEqual(
            (workspace / "public_check.py").read_text(encoding="utf-8"),
            (workspace / ".goal-plus-verifiers" / "primary_metric.py").read_text(
                encoding="utf-8"
            ),
        )
        self.assertFalse((workspace / ".gp").exists())

    def test_public_evaluation_rejects_protected_path_before_tests(self) -> None:
        source = self.root / "checkout" / "benchmarks" / "coding"
        source.mkdir(parents=True)
        workspace = self.root / "workspace"

        original_test = "def test_build(): pass\n"

        def fake_bridge(_command: list[str], _source: Path, timeout: int = 300) -> dict:
            del timeout
            submission = workspace / "submission"
            submission.mkdir()
            (submission / "build.py").write_text("value = 1\n", encoding="utf-8")
            (submission / "test_build.py").write_text(original_test, encoding="utf-8")
            metadata = self._metadata()
            metadata["protected_files"] = [
                {
                    "path": "test_build.py",
                    "sha256": hashlib.sha256(original_test.encode()).hexdigest(),
                }
            ]
            return metadata

        with (
            mock.patch.object(task_adapter, "_bridge", side_effect=fake_bridge),
            mock.patch.object(task_adapter, "git_commit", return_value="b" * 40),
        ):
            task_adapter.materialize_workspace(source, workspace)
            (workspace / "submission" / "test_build.py").write_text(
                "def test_build(): assert True\n", encoding="utf-8"
            )
            with mock.patch.object(task_adapter, "_visible_ratio") as visible_ratio:
                report = task_adapter.evaluate_workspace(workspace, source, "public")

        visible_ratio.assert_not_called()
        self.assertFalse(report["valid"])
        self.assertIsNone(report["primary_metric"]["value"])
        self.assertEqual(
            report["integrity_violation"],
            "protected_path_modified: test_build.py",
        )

    def test_bridge_environment_prefers_locked_runtime(self) -> None:
        source = self.root / "source"
        environment = task_adapter._bridge_environment(source)
        self.assertEqual(
            environment["PATH"].split(os.pathsep)[0],
            str(task_adapter.RUNTIME_PYTHON.parent),
        )
        self.assertEqual(environment["PYTHONPATH"], str(source / "src"))

    def test_upstream_python_version_is_an_exact_minor(self) -> None:
        source = self.root / "source"
        source.mkdir()
        (source / ".python-version").write_text("3.13\n", encoding="utf-8")
        self.assertEqual(runtime._pinned_python_version(source), "3.13")
        (source / ".python-version").write_text(">=3.11\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "MAJOR.MINOR"):
            runtime._pinned_python_version(source)

    def test_public_evaluation_rejects_controller_file_changes(self) -> None:
        source = self.root / "checkout" / "benchmarks" / "coding"
        source.mkdir(parents=True)
        workspace = self.root / "workspace"

        def fake_bridge(_command: list[str], _source: Path, timeout: int = 300) -> dict:
            del timeout
            submission = workspace / "submission"
            submission.mkdir()
            (submission / "build.py").write_text("value = 1\n", encoding="utf-8")
            return self._metadata()

        with (
            mock.patch.object(task_adapter, "_bridge", side_effect=fake_bridge),
            mock.patch.object(task_adapter, "git_commit", return_value="b" * 40),
        ):
            task_adapter.materialize_workspace(source, workspace)
        (workspace / "TASK.md").write_text("tampered\n", encoding="utf-8")
        report = task_adapter.evaluate_workspace(workspace, source, "public")
        self.assertFalse(report["valid"])
        self.assertIn("TASK.md", report["unauthorized_changes"])

    def test_official_collection_error_is_not_a_valid_failure_score(self) -> None:
        workspace = self.root / "workspace"
        source = self.root / "source"
        workspace.mkdir()
        (workspace / "submission").mkdir()
        metadata = self._metadata()
        with mock.patch.object(
            task_adapter,
            "_bridge",
            return_value={
                "grade": {
                    "passed": False,
                    "infra_error": False,
                    "collection_error": True,
                    "detail": "pytest could not collect",
                }
            },
        ):
            report = task_adapter._official_evaluation(workspace, source, metadata)
        self.assertFalse(report["valid"])
        self.assertIsNone(report["value"])

    def test_official_bridge_rejects_symlinked_submission_root(self) -> None:
        hidden = self.root / "hidden"
        hidden.mkdir()
        submission = self.root / "submission"
        submission.symlink_to(hidden, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "real directory"):
            bridge._submission_root(submission)

    def test_bubblewrap_masks_hidden_checkout_and_other_cells(self) -> None:
        command, cell, workspace, hidden, binary = self._sandbox_command(
            "codex", "plain-codex", ["exec", "--json"]
        )
        pairs = list(zip(command, command[1:]))
        self.assertIn(("--tmpfs", str(hidden)), pairs)
        self.assertIn(("--tmpfs", str(cell.parent)), pairs)
        self.assertIn(("--bind", str(workspace)), pairs)
        self.assertEqual(command[-3:], [str(binary), "exec", "--json"])

    def test_bubblewrap_masks_symlinked_hidden_checkout_target(self) -> None:
        cell = self.root / "campaign" / "cells" / "cell-1"
        workspace = cell / "workspace"
        hidden = self.root / "hidden-real"
        hidden_link = self.root / "hidden-link"
        binary = self.root / "pi"
        workspace.mkdir(parents=True)
        hidden.mkdir()
        hidden_link.symlink_to(hidden, target_is_directory=True)
        binary.write_text("", encoding="utf-8")
        environment = {
            "AIBENCH_AGENT_ROLE": "pi",
            "AIBENCH_METHOD": "goal-plus-pi",
            "AIBENCH_REAL_PI_BIN": str(binary),
            "AIBENCH_HIDDEN_CHECKOUT": str(hidden_link),
            "AIBENCH_CELL_ROOT": str(cell),
        }
        previous = Path.cwd()
        try:
            os.chdir(workspace)
            with (
                mock.patch.dict(os.environ, environment, clear=False),
                mock.patch.object(sandbox.shutil, "which", return_value="/usr/bin/bwrap"),
            ):
                command = sandbox.build_command([])
        finally:
            os.chdir(previous)

        tmpfs_targets = [
            command[index + 1]
            for index, value in enumerate(command[:-1])
            if value == "--tmpfs"
        ]
        self.assertIn(str(hidden.resolve()), tmpfs_targets)
        self.assertNotIn(str(hidden_link.absolute()), tmpfs_targets)

    def test_goal_plus_pi_binds_private_short_xdg_runtime(self) -> None:
        command, cell, *_ = self._sandbox_command(
            "pi", "goal-plus-pi", ["--mode", "rpc"]
        )

        source = cell / "controller-runtime" / "agent-home" / "xdg-runtime"
        destination = str(sandbox.XDG_RUNTIME_DESTINATION)
        triples = [command[index : index + 3] for index in range(len(command) - 2)]
        self.assertIn(["--bind", str(source), destination], triples)
        self.assertIn(["--setenv", "XDG_RUNTIME_DIR", destination], triples)
        self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o700)

    def _write_cell(
        self,
        campaign: Path,
        method: str,
        *,
        success: bool,
        actual: int = 1,
    ) -> dict[str, object]:
        run_dir = campaign / "cells" / method
        run_dir.mkdir(parents=True)
        (run_dir / "submission").mkdir()
        if method.startswith("plain-"):
            agent = "pi" if method == "plain-pi" else "codex"
            execution = {
                agent: {
                    "lanes": [
                        {"lane": f"lane-{index:02d}"} for index in range(actual)
                    ]
                }
            }
        elif method == "goal-plus-codex":
            execution = {"codex": {"spawned_agent_thread_count": actual}}
        else:
            execution = {
                "goal_plus": {"runs": [{"bound_candidate_count": actual}]},
                "pi": {},
            }
        execution["evaluator_calls"] = {
            "total_claimed": 3,
            "controller_final_claimed": 1,
            "coverage": "complete",
        }
        manifest = {"status": "finished", "execution": execution}
        if method == "goal-plus-pi":
            manifest["pi_worker_sandbox"] = {
                "engine": "bubblewrap",
                "launch_interception": "bench-owned-pi-path-shim",
            }
        (run_dir / "experiment.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (run_dir / "final-eval.json").write_text(
            json.dumps(
                {
                    "valid": True,
                    "primary_metric": {
                        "name": "task_success",
                        "value": success,
                        "direction": "maximize",
                    },
                    "grade": {
                        "passed": success,
                        "test_pass_ratio": 1.0 if success else 0.5,
                        "infra_error": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        return {
            "cell_id": method,
            "task_id": "rev-09f7740f614d3ea9",
            "method": method,
            "seed": 1,
            "run_dir": str(run_dir),
            "state": "completed",
            "sandbox": {
                "kind": "bubblewrap",
                "hidden_checkout_masked": True,
            },
        }

    def _campaign(self, destination: Path, cells: list[dict], k: int) -> None:
        payload = {
            "schema_version": 1,
            "campaign_id": destination.name,
            "benchmark": "aibench-coding",
            "state": "completed",
            "model": "bench-openai/gpt-5.6-sol",
            "reasoning_effort": "medium",
            "budget": {
                "wall_time_seconds": 300,
                "live_search_concurrency": k,
                "cell_concurrency": 1,
                "repeats": 1,
            },
            "source": {
                "case_set": "_clean2026",
                "case_set_fingerprint": "9149d02169845dc5",
                "commit": "c" * 40,
                "goal_plus_commit": "d" * 40,
            },
            "cells": cells,
        }
        (destination / "campaign.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_finalize_preserves_false_score_and_topology_evidence(self) -> None:
        campaign = self.root / "campaign"
        campaign.mkdir()
        methods = ["plain-codex", "plain-pi", "goal-plus-codex", "goal-plus-pi"]
        cells = [
            self._write_cell(campaign, method, success=method != "plain-pi")
            for method in methods
        ]
        self._campaign(campaign, cells, 1)
        summary = reporting.finalize_campaign(campaign)
        self.assertEqual(summary["state"], "completed")
        plain_pi = next(
            item for item in summary["records"] if item["method"] == "plain-pi"
        )
        self.assertTrue(plain_pi["score"]["valid"])
        self.assertEqual(plain_pi["score"]["final"], 0)
        self.assertTrue(
            all(
                item["protocol"]["topology"]["matches_k"]
                for item in summary["records"]
            )
        )
        self.assertEqual(summary["aggregates"]["official_evaluator_calls"], 4)

    def test_finalize_marks_k_mismatch_partial_without_dropping_score(self) -> None:
        campaign = self.root / "campaign"
        campaign.mkdir()
        cell = self._write_cell(campaign, "goal-plus-pi", success=True, actual=1)
        self._campaign(campaign, [cell], 2)
        summary = reporting.finalize_campaign(campaign)
        self.assertEqual(summary["state"], "partial")
        record = summary["records"][0]
        self.assertEqual(record["score"]["final"], 1)
        self.assertFalse(record["protocol"]["matched_comparison_eligible"])
        self.assertIsNone(
            summary["aggregates"]["by_method"]["goal-plus-pi"]["pass_at_k"]
        )

    def test_finalize_requires_goal_plus_pi_worker_sandbox_evidence(self) -> None:
        campaign = self.root / "campaign"
        campaign.mkdir()
        cell = self._write_cell(campaign, "goal-plus-pi", success=True)
        manifest_path = Path(cell["run_dir"]) / "experiment.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.pop("pi_worker_sandbox")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self._campaign(campaign, [cell], 1)
        summary = reporting.finalize_campaign(campaign)
        self.assertEqual(summary["state"], "partial")
        self.assertIn(
            "worker Bubblewrap isolation",
            summary["records"][0]["incomplete_reason"],
        )


if __name__ == "__main__":
    unittest.main()
