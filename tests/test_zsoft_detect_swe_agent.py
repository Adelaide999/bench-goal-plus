from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bench_goal_plus.application import BenchmarkAgent
from bench_goal_plus.catalog import Catalog
from bench_goal_plus.errors import ContractError
from bench_goal_plus.runners.factory import create_runner
from experiments.zsoft_detect_swe_agent import config, environment, reporting, runtime
from scripts import benchmark_report


ROOT = Path(__file__).resolve().parents[1]


def ready_inventory() -> dict[str, object]:
    return {
        "ok": True,
        "read_only": True,
        "acquisition_attempted": False,
        "framework": {"ok": True, "missing": False},
        "swe_agent": {"ok": True, "missing": False},
        "sources": [{"ok": True, "missing": False}],
    }


def bench_contract() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "project_id": "civetweb",
        "display_name": "CivetWeb",
        "commit": "d7ba35bbb649209c66e582d5a0244ba988a15159",
        "version_label": "fixture",
        "scan_roots": ["src"],
        "submission_path_prefixes": ["src"],
        "tracks": ["tp"],
        "project_bug_types": [{"id": "cwe_787", "title": "OOB write"}],
        "targets": [
            {"id": "src", "include": ["src"], "bug_types": ["cwe_787"]}
        ],
        "submission_schema": {},
    }


class ZSoftDetectSWEAgentTest(unittest.TestCase):
    def test_catalog_exposes_dedicated_method_without_common_runner_leakage(self) -> None:
        catalog = Catalog()
        target = catalog.targets["zsoft-detect-swe-agent"]
        runner = catalog.runners[target.runner_id]

        self.assertEqual(target.runner_id, "zsoft-detect-native")
        self.assertIsNone(target.adapter_id)
        self.assertTrue(target.local_asset_inventory)
        self.assertEqual(runner.supported_methods, ("zsoft-swe-agent",))
        self.assertNotIn(
            "zsoft-swe-agent", catalog.runners["common-matrix"].supported_methods
        )
        self.assertFalse(runner.capabilities.detach)
        self.assertFalse(runner.capabilities.resume)
        self.assertTrue(runner.capabilities.official_evaluator)

        spec = BenchmarkAgent(catalog=catalog).resolve_spec(
            preset_id="zsoft-detect-civetweb-swe-agent-smoke"
        )
        self.assertEqual(spec.methods, ("zsoft-swe-agent",))
        self.assertEqual(spec.concurrency(), {"T": 300, "K": 1, "C": 1, "R": 1})
        commands, campaign = create_runner(spec.runner).prepare_commands(spec)
        self.assertEqual(campaign.target_id, "zsoft-detect-swe-agent")
        self.assertIn("--seeds", commands[0])
        self.assertIn("zsoft-swe-agent", commands[0])

        with self.assertRaisesRegex(ContractError, "require K=1"):
            BenchmarkAgent(catalog=catalog).resolve_spec(
                target_ids=("zsoft-detect-swe-agent",),
                profile="civetweb-swe-agent-smoke",
                methods=("zsoft-swe-agent",),
                model="gpt-5.6-sol",
                wall_time_seconds=300,
                live_search_concurrency=2,
                cell_concurrency=1,
            )

    def test_profile_rejects_non_native_method_and_parallel_topology(self) -> None:
        _, profile = config.load_profile("civetweb-swe-agent-smoke")
        with self.assertRaisesRegex(config.ZSoftSWEAgentContractError, "methods must"):
            config.resolve_profile(profile, methods=["plain-codex"])
        with self.assertRaisesRegex(config.ZSoftSWEAgentContractError, "requires K=1"):
            config.resolve_profile(profile, concurrency=2)
        with self.assertRaisesRegex(config.ZSoftSWEAgentContractError, "requires C=1"):
            config.resolve_profile(profile, cell_concurrency=2)

    def test_local_pin_matches_the_upstream_swe_agent_contract(self) -> None:
        launcher = config.UPSTREAM_RUNNER.read_text(encoding="utf-8")
        requirements = (
            config.BENCHMARK_ROOT
            / "runners"
            / "swe-agent"
            / "requirements-runner.txt"
        ).read_text(encoding="utf-8")

        self.assertIn(config.PINNED_SWE_AGENT_COMMIT, launcher)
        self.assertIn(f"swe-rex=={config.PINNED_SWE_REX_VERSION}", requirements)
        self.assertIn(f"litellm=={config.PINNED_LITELLM_VERSION}", requirements)
        self.assertIn('"name": "swe-agent"', launcher)
        self.assertIn('"version": "1.0.1"', launcher)

    def test_profiled_inventory_never_checks_auth_or_acquires_assets(self) -> None:
        _, profile = config.load_profile("civetweb-swe-agent-smoke")
        missing = {
            "ok": False,
            "read_only": True,
            "acquisition_attempted": False,
            "framework": {"ok": True, "missing": False},
            "swe_agent": {"ok": False, "missing": True},
            "sources": [{"ok": False, "missing": True}],
        }
        with mock.patch.object(environment, "asset_inventory", return_value=missing):
            failed = environment.doctor_payload(
                profile,
                local_assets_only=True,
                allow_missing_local_assets=False,
            )
            allowed = environment.doctor_payload(
                profile,
                local_assets_only=True,
                allow_missing_local_assets=True,
            )

        self.assertFalse(failed["ok"])
        self.assertTrue(allowed["ok"])
        self.assertIsNone(failed["auth"])
        self.assertIsNone(failed["host"])
        self.assertTrue(failed["inventory"]["read_only"])
        self.assertFalse(failed["inventory"]["acquisition_attempted"])

    def test_full_doctor_rejects_macos_even_with_api_environment(self) -> None:
        _, profile = config.load_profile("civetweb-swe-agent-smoke")
        with (
            mock.patch.object(environment, "asset_inventory", return_value=ready_inventory()),
            mock.patch.object(environment.platform, "system", return_value="Darwin"),
            mock.patch.object(environment.platform, "machine", return_value="arm64"),
            mock.patch.object(environment.shutil, "which", return_value=None),
            mock.patch.dict(
                os.environ,
                {
                    "OPENAI_COMPAT_BASE_URL": "https://example.invalid/v1",
                    "OPENAI_COMPAT_API_KEY": "never-persist-this",
                },
                clear=False,
            ),
        ):
            payload = environment.doctor_payload(
                profile,
                local_assets_only=False,
                allow_missing_local_assets=False,
            )

        self.assertFalse(payload["ok"])
        self.assertFalse(payload["host"]["ok"])
        self.assertTrue(payload["auth"]["ok"])
        self.assertNotIn("never-persist-this", json.dumps(payload))

    def test_provision_rejects_macos_before_any_acquisition(self) -> None:
        _, profile = config.load_profile("civetweb-swe-agent-smoke")
        with (
            mock.patch.object(environment.platform, "system", return_value="Darwin"),
            mock.patch.object(environment.shutil, "which", return_value=None),
            mock.patch.object(environment.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, r"Linux\+bwrap"):
                environment.provision(profile)
        run.assert_not_called()

    def _prepared_campaign(self, root: Path) -> Path:
        _, profile = config.load_profile("civetweb-swe-agent-smoke")
        destination = root / "campaign"
        source = root / "source"
        source.mkdir()
        with (
            mock.patch.object(runtime, "campaign_dir", return_value=destination),
            mock.patch.object(runtime, "asset_inventory", return_value=ready_inventory()),
            mock.patch.object(runtime, "source_checkout", return_value=source),
            mock.patch.object(
                runtime.zsoft_adapter, "bench_contract", return_value=bench_contract()
            ),
        ):
            runtime.prepare("fixture-campaign", profile, Path("fixture-profile.json"))
        return destination

    @staticmethod
    def _fake_run(*, complete_usage: bool):
        def invoke(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if any(str(item).endswith("score_submission.py") for item in command):
                score = {
                    "project_id": "civetweb",
                    "commit": "d7ba35bbb649209c66e582d5a0244ba988a15159",
                    "tp": 2,
                    "fp": 1,
                    "fn": 3,
                    "precision": 2 / 3,
                    "recall": 0.4,
                    "f1": 0.5,
                }
                return subprocess.CompletedProcess(command, 0, json.dumps(score), "")
            run_dir = Path(command[command.index("--run-dir") + 1])
            (run_dir / "submission").mkdir(parents=True)
            metrics = {
                "status": "complete" if complete_usage else "failed",
                "runner": "swe-agent",
                "model": "gpt-5.6-sol",
                "bench": {
                    "project_id": "civetweb",
                    "commit": "d7ba35bbb649209c66e582d5a0244ba988a15159",
                },
                "runner_tool": {"git_commit": config.PINNED_SWE_AGENT_COMMIT},
                "sandbox": {"engine": "bubblewrap"},
                "timing": {"elapsed_ms": 1250},
                "tokens": {
                    "measurement_complete": complete_usage,
                    "exact": complete_usage,
                    "source": "upstream_openai_compatible_usage",
                    "input_tokens": 100 if complete_usage else None,
                    "cached_input_tokens": 25 if complete_usage else None,
                    "fresh_input_tokens": 75 if complete_usage else None,
                    "output_tokens": 10 if complete_usage else None,
                    "inference_requests": 2 if complete_usage else 0,
                },
            }
            (run_dir / "run-metrics.json").write_text(json.dumps(metrics))
            return subprocess.CompletedProcess(command, 0 if complete_usage else 3)

        return invoke

    def test_model_free_lifecycle_preserves_native_usage_and_raw_score(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as temporary:
            destination = self._prepared_campaign(Path(temporary))
            with (
                mock.patch.object(
                    runtime.subprocess,
                    "run",
                    side_effect=self._fake_run(complete_usage=True),
                ),
                mock.patch.dict(os.environ, {"OPENAI_COMPAT_API_KEY": "never-persist-this"}),
            ):
                self.assertEqual(runtime.execute_campaign(destination), 0)

            status = runtime.status_payload(destination)
            self.assertEqual(status["state"], "completed")
            self.assertEqual(status["counts"], {"completed": 1})
            summary = reporting.finalize_campaign(destination)
            record = summary["records"][0]
            self.assertEqual(summary["state"], "completed")
            self.assertEqual(record["score"]["final"], 0.5)
            self.assertEqual(record["score"]["raw_metrics"]["tp"], 2)
            self.assertEqual(record["execution"]["usage"]["input_tokens"], 100)
            self.assertEqual(record["execution"]["usage"]["cached_input_tokens"], 25)
            self.assertEqual(record["execution"]["evaluator_calls"]["total_claimed"], 1)
            self.assertFalse(record["protocol"]["matched_comparison_eligible"])
            self.assertIn("reasoning-effort", record["protocol"]["known_protocol_issue"])
            self.assertNotIn(
                "never-persist-this", (destination / "campaign.json").read_text()
            )
            outputs = benchmark_report.export(destination, None, None)
            self.assertTrue(Path(outputs["markdown"]).is_file())
            self.assertTrue(Path(outputs["xlsx"]).is_file())

    def test_incomplete_usage_keeps_score_but_marks_partial(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as temporary:
            destination = self._prepared_campaign(Path(temporary))
            with mock.patch.object(
                runtime.subprocess,
                "run",
                side_effect=self._fake_run(complete_usage=False),
            ):
                self.assertEqual(runtime.execute_campaign(destination), 2)

            summary = reporting.finalize_campaign(destination)
            record = summary["records"][0]
            self.assertEqual(summary["state"], "partial")
            self.assertEqual(record["score"]["final"], 0.5)
            self.assertEqual(record["execution"]["usage"]["coverage"], "incomplete")
            self.assertIn("provider token usage is incomplete", record["incomplete_reason"])


if __name__ == "__main__":
    unittest.main()
