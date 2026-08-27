from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.zsoft_detect import adapter as detect  # noqa: E402
from adapters.zsoft_l1 import adapter as l1  # noqa: E402
from experiments.benchmark_compare import experiment  # noqa: E402
from experiments.openevolve_compare import experiment as goal_experiment  # noqa: E402
from experiments.openevolve_compare.experiment import render_goal  # noqa: E402


def _init_source_checkout(path: Path) -> str:
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
    )
    (path / "src").mkdir()
    (path / "src/audit.c").write_text("/* public fixture */\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-q", "-m", "fixture"], check=True
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _valid_finding() -> dict[str, object]:
    return {
        "location": {
            "path": "src/audit.c",
            "function": "parse_request",
            "start_line": 1,
            "end_line": 2,
        },
        "bug_type": "cwe_125",
        "root_cause": {
            "cause": "unchecked length",
            "trigger": "crafted request",
            "impact": "out-of-bounds read",
        },
    }


class ZSoftBlindEvaluationTest(unittest.TestCase):
    def tearDown(self) -> None:
        detect.configure_task(None)
        l1.configure_task(None)
        experiment.configure_adapter("heurigym")

    def test_detect_public_schema_check_never_calls_official_scorer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            submission = workspace / "submission"
            submission.mkdir(parents=True)
            (submission / "finding.json").write_text(
                json.dumps(_valid_finding()), encoding="utf-8"
            )
            (workspace / "task.json").write_text(
                json.dumps(
                    {
                        "task_id": detect.TASK_ID,
                        "project_id": detect.DEFAULT_PROJECT,
                        "commit": detect.project_commit(detect.DEFAULT_PROJECT),
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(detect, "_run") as official:
                report = detect.evaluate_workspace(
                    workspace, Path("/controller-path-must-not-be-read"), "public"
                )
            official.assert_not_called()
            self.assertTrue(report["valid"])
            self.assertEqual(report["format_valid"], 1.0)
            for key in ("f1", "precision", "recall", "tp", "fp", "fn", "zsoft_score"):
                self.assertNotIn(key, report)

            invalid = _valid_finding()
            invalid["unexpected"] = True
            (submission / "finding.json").write_text(
                json.dumps(invalid), encoding="utf-8"
            )
            with mock.patch.object(detect, "_run") as official:
                rejected = detect.evaluate_workspace(
                    workspace, Path("/controller-path-must-not-be-read"), "public"
                )
            official.assert_not_called()
            self.assertFalse(rejected["valid"])
            self.assertIn(
                "unexpected fields", json.dumps(rejected["public_diagnostics"])
            )

    def test_l1_public_check_never_calls_official_judge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            (workspace / "poc").write_text("print('poc')\n", encoding="utf-8")
            (workspace / "task.json").write_text(
                json.dumps(
                    {
                        "task_id": l1.TASK_ID,
                        "artifact_name": "poc",
                        "submission_max_bytes": 128,
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(l1, "_run_cli") as official:
                report = l1.evaluate_workspace(
                    workspace, Path("/controller-path-must-not-be-read"), "public"
                )
            official.assert_not_called()
            self.assertTrue(report["valid"])
            self.assertEqual(report["format_valid"], 1.0)
            self.assertNotIn("success", report)
            self.assertNotIn("zsoft_result", report)

            (workspace / "poc").write_text("def broken(:\n", encoding="utf-8")
            with mock.patch.object(l1, "_run_cli") as official:
                rejected = l1.evaluate_workspace(
                    workspace, Path("/controller-path-must-not-be-read"), "public"
                )
            official.assert_not_called()
            self.assertFalse(rejected["valid"])
            self.assertIn(
                "parseable Python", json.dumps(rejected["public_diagnostics"])
            )

    def test_final_mode_calls_each_official_boundary_once_and_preserves_raw(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            detect_workspace = root / "detect"
            detect_submission = detect_workspace / "submission"
            detect_submission.mkdir(parents=True)
            (detect_submission / "finding.json").write_text(
                json.dumps(_valid_finding()), encoding="utf-8"
            )
            (detect_workspace / "task.json").write_text(
                json.dumps(
                    {
                        "task_id": detect.TASK_ID,
                        "project_id": detect.DEFAULT_PROJECT,
                        "commit": detect.project_commit(detect.DEFAULT_PROJECT),
                    }
                ),
                encoding="utf-8",
            )
            detect_raw = {
                "f1": 0.75,
                "precision": 0.6,
                "recall": 1.0,
                "tp": 3,
                "fp": 2,
                "fn": 0,
            }
            detected = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(detect_raw), stderr=""
            )
            with mock.patch.object(detect, "_run", return_value=detected) as scorer:
                detect_report = detect.evaluate_workspace(
                    detect_workspace, detect.BENCHMARK_ROOT, "final"
                )
                with self.assertRaisesRegex(RuntimeError, "only be claimed once"):
                    detect.evaluate_workspace(
                        detect_workspace, detect.BENCHMARK_ROOT, "final"
                    )
                scorer.assert_called_once()
            self.assertEqual(detect_report["zsoft_score"], detect_raw)
            self.assertEqual(detect_report["f1"], 0.75)

            l1_workspace = root / "l1"
            l1_workspace.mkdir()
            (l1_workspace / "poc").write_text("print('poc')\n", encoding="utf-8")
            (l1_workspace / "task.json").write_text(
                json.dumps(
                    {
                        "task_id": l1.TASK_ID,
                        "artifact_name": "poc",
                        "submission_max_bytes": 128,
                    }
                ),
                encoding="utf-8",
            )
            l1_raw = {
                "result": {"success": True, "summary": "accepted"},
                "details": {"sentinel": "raw-preserved"},
            }
            judged = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(l1_raw), stderr=""
            )
            with mock.patch.object(l1, "_run_cli", return_value=judged) as judge:
                l1_report = l1.evaluate_workspace(
                    l1_workspace, l1.BENCHMARK_ROOT, "final"
                )
                with self.assertRaisesRegex(RuntimeError, "only be claimed once"):
                    l1.evaluate_workspace(
                        l1_workspace, l1.BENCHMARK_ROOT, "final"
                    )
                judge.assert_called_once()
            self.assertEqual(l1_report["zsoft_result"], l1_raw)
            self.assertEqual(l1_report["success"], 1)

    def test_oversized_l1_artifact_is_rejected_before_reading_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "poc"
            artifact.write_bytes(b"x" * 129)
            with mock.patch("adapters.zsoft_blind.os.fdopen") as opened:
                diagnostics = l1.validate_l1_artifact(artifact, 128)
            opened.assert_not_called()
            self.assertIn("exceeds", json.dumps(diagnostics))

    def test_materialized_workspaces_contain_no_official_paths_or_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source-cache"
            commit = _init_source_checkout(source)
            contract = detect.bench_contract("civetweb")
            detect_workspace = root / "detect-workspace"
            with (
                mock.patch.dict(
                    os.environ, {detect.SOURCE_CACHE_ENV: str(source)}, clear=False
                ),
                mock.patch.dict(detect.PROJECT_COMMITS, {"civetweb": commit}),
                mock.patch.object(detect, "bench_contract", return_value=contract),
            ):
                detect.materialize_workspace(detect.BENCHMARK_ROOT, detect_workspace)

            l1_workspace = root / "l1-workspace"
            l1.materialize_workspace(l1.BENCHMARK_ROOT, l1_workspace)
            for workspace, adapter, hidden_metric in (
                (detect_workspace, detect, "f1"),
                (l1_workspace, l1, "success"),
            ):
                self.assertFalse((workspace / "evaluate.py").exists())
                self.assertFalse((workspace / ".goal-plus-verifiers").exists())
                metadata = json.loads((workspace / "task.json").read_text())
                self.assertNotIn("upstream_root", metadata)
                self.assertEqual(metadata["primary_metric"], "format_valid")
                controls = "\n".join(
                    (workspace / name).read_text(encoding="utf-8")
                    for name in ("TASK.md", "AGENTS.md", "task.json", "public_check.py")
                ).lower()
                self.assertNotRegex(
                    controls,
                    rf"\b{re.escape(hidden_metric)}\b",
                )
                self.assertNotIn("score_submission.py", controls)
                self.assertNotIn("_run_cli", controls)
                forbidden = (
                    str(adapter.BENCHMARK_ROOT).encode(),
                    str(adapter.CONTROLLER_PATH).encode(),
                )
                for path in workspace.rglob("*"):
                    if not path.is_file() or path.is_symlink():
                        continue
                    payload = path.read_bytes()
                    for value in forbidden:
                        self.assertNotIn(value, payload, path)

                checked = subprocess.run(
                    [sys.executable, "public_check.py"],
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(checked.returncode, 0, checked.stderr)
                self.assertTrue(json.loads(checked.stdout)["valid"])

    def test_blind_prompt_freezes_format_only_selection_contract(self) -> None:
        prompt = render_goal(
            task_text="# Task\nProduce the artifact.",
            artifact_name="submission",
            artifact_is_directory=True,
            metric_name="format_valid",
            metric_direction="maximize",
            wall_seconds=300,
            closeout_seconds=60,
            concurrency=2,
            worker_host="pi-rpc",
            worker_model="provider/model",
            evaluation_mode="blind",
        )
        self.assertIn('evaluation_mode="blind"', prompt)
        self.assertIn("Metric: `format_valid`", prompt)
        self.assertEqual(prompt.count("feedback policy `final_only`"), 2)
        self.assertIn("lowest candidate ID", prompt)
        self.assertIn("latest such commit", prompt)
        self.assertIn("publicly compliant", prompt)
        self.assertIn("never disclosed to workers", prompt)
        self.assertIn("`results.tsv`", prompt)
        self.assertIn("Global Evidence are opaque", prompt)
        self.assertNotIn("summary_only", prompt)
        self.assertNotIn("evaluate.py", prompt)
        self.assertNotIn(".goal-plus-verifiers", prompt)
        for hidden_name in ("f1", "precision", "recall", "success"):
            self.assertNotIn(hidden_name, prompt.lower())

    def test_non_zsoft_visible_goal_rendering_is_unchanged(self) -> None:
        kwargs = {
            "task_text": "# Task\nImprove it.",
            "artifact_name": "candidate.py",
            "metric_name": "score",
            "metric_direction": "maximize",
            "wall_seconds": 300,
            "closeout_seconds": 60,
            "concurrency": 2,
            "worker_host": "codex",
            "worker_model": "test-model",
        }
        self.assertEqual(render_goal(**kwargs), render_goal(**kwargs, evaluation_mode="visible"))
        self.assertIn("feedback policy `summary_only`", render_goal(**kwargs))

    def test_existing_blind_promotion_must_match_lowest_latest_compliant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_path = Path(temporary) / "run" / "run.json"
            for candidate_id, iterations in (
                (
                    "c001",
                    [
                        {
                            "iteration": 1,
                            "process_passed": True,
                            "git_head": "1" * 40,
                            "git_artifact_clean": True,
                        },
                        {
                            "iteration": 2,
                            "process_passed": False,
                            "git_head": "2" * 40,
                            "git_artifact_clean": True,
                        },
                        {
                            "iteration": 3,
                            "process_passed": True,
                            "git_head": "3" * 40,
                            "git_artifact_clean": True,
                        },
                    ],
                ),
                (
                    "c002",
                    [
                        {
                            "iteration": 4,
                            "process_passed": True,
                            "git_head": "4" * 40,
                            "git_artifact_clean": True,
                        }
                    ],
                ),
            ):
                candidate_path = (
                    run_path.parent / "candidates" / candidate_id / "candidate.json"
                )
                candidate_path.parent.mkdir(parents=True)
                candidate_path.write_text(
                    json.dumps(
                        {"candidate_id": candidate_id, "iterations": iterations}
                    )
                )

            goal_experiment._validate_existing_blind_selection(
                run_path,
                {
                    "selected_candidate_id": "c001",
                    "selected_iteration": 3,
                    "selected_git_head": "3" * 40,
                },
            )
            with self.assertRaisesRegex(RuntimeError, "blind selection rule"):
                goal_experiment._validate_existing_blind_selection(
                    run_path,
                    {
                        "selected_candidate_id": "c002",
                        "selected_iteration": 4,
                        "selected_git_head": "4" * 40,
                    },
                )

    def test_zsoft_goal_plus_codex_is_rejected_before_prepare_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "must-not-exist"
            config = experiment.PrepareConfig(
                benchmark="zsoft-detect",
                method="goal-plus-codex",
                run_dir=run_dir,
            )
            with self.assertRaisesRegex(ValueError, "Bubblewrap worker boundary"):
                experiment.prepare(config.to_namespace())
            self.assertFalse(run_dir.exists())

    def test_controller_closes_search_before_one_final_evaluation(self) -> None:
        experiment.configure_adapter("zsoft-detect")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            workspace = run_dir / "workspace"
            (workspace / "submission").mkdir(parents=True)
            (workspace / "submission/.gitkeep").write_text("")
            (workspace / "TASK.md").write_text("Audit the source.\n")
            manifest = {
                "method": "goal-plus-pi",
                "workspace": str(workspace),
                "reasoning_effort": "medium",
                "task": {"evaluation_mode": "blind"},
                "environment": {
                    "runtime_bin": str(root / "bin"),
                    "benchmark_root": str(detect.BENCHMARK_ROOT),
                },
                "budget": {
                    "wall_time_seconds": 300,
                    "soft_closeout_seconds": 60,
                    "hard_kill_grace_seconds": 5,
                    "concurrency": 1,
                    "worker_runtime_seconds": 120,
                    "worker_min_runtime_seconds": None,
                },
                "goal_plus_config": {"shared_dir_enabled": False},
            }
            args = SimpleNamespace(
                model="test-model",
                api_base="http://provider.invalid/v1",
                pi_bin="pi",
            )
            order: list[str] = []

            def evaluated(
                _workspace: Path,
                mode: str,
                _runtime: Path,
                _upstream: Path | None = None,
            ) -> dict[str, object]:
                order.append(mode)
                return {
                    "valid": True,
                    "budget": {"total_claimed": 1},
                    "primary_metric": {"value": 1.0},
                }

            def finalized(
                _workspace: Path, evaluation_mode: str = "visible"
            ) -> dict[str, object]:
                self.assertEqual(evaluation_mode, "blind")
                order.append("closeout")
                return {
                    "completed": True,
                    "runs": [
                        {
                            "selection": {
                                "selected_candidate_id": "c001",
                                "selection_rule": experiment.BLIND_SELECTION_RULE,
                            },
                            "promotion": {"artifact_path": "/controller/c001.patch"},
                            "final_state": "promoted",
                            "goal_statuses": {"gp_001": "complete"},
                        }
                    ],
                }

            with (
                mock.patch.object(
                    experiment,
                    "evaluate_with_controller_runtime",
                    side_effect=evaluated,
                ),
                mock.patch.object(experiment, "configure_isolated_codex_home"),
                mock.patch.object(
                    experiment, "configure_evidence_annotator_environment"
                ),
                mock.patch.object(experiment, "write_pi_models_config"),
                mock.patch.object(
                    experiment,
                    "run_controlled",
                    return_value={"hard_killed": False},
                ),
                mock.patch.object(experiment, "close_pi_pools", return_value={}),
                mock.patch.object(
                    experiment,
                    "controller_subprocess_environment",
                    return_value=nullcontext(),
                ),
                mock.patch.object(
                    experiment, "finalize_goal_plus_search", side_effect=finalized
                ),
                mock.patch.object(experiment, "parse_pi_events", return_value={}),
                mock.patch.object(
                    experiment,
                    "collect_goal_plus_state",
                    return_value={"runs": []},
                ),
                mock.patch.object(
                    experiment, "collect_evidence_annotator_usage", return_value={}
                ),
                mock.patch.object(
                    experiment, "goal_plus_incomplete_reason", return_value=None
                ),
            ):
                experiment.execute_goal_plus(manifest, run_dir, args, {})

            self.assertEqual(order, ["public", "closeout", "final"])
            self.assertEqual(order.count("final"), 1)

    def test_blind_controller_withholds_official_evaluation_when_closeout_raises(
        self,
    ) -> None:
        experiment.configure_adapter("zsoft-detect")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            workspace = run_dir / "workspace"
            (workspace / "submission").mkdir(parents=True)
            (workspace / "submission/.gitkeep").write_text("")
            (workspace / "TASK.md").write_text("Audit the source.\n")
            manifest = {
                "method": "goal-plus-pi",
                "workspace": str(workspace),
                "reasoning_effort": "medium",
                "task": {"evaluation_mode": "blind"},
                "environment": {
                    "runtime_bin": str(root / "bin"),
                    "benchmark_root": str(detect.BENCHMARK_ROOT),
                },
                "budget": {
                    "wall_time_seconds": 300,
                    "soft_closeout_seconds": 60,
                    "hard_kill_grace_seconds": 5,
                    "concurrency": 1,
                    "worker_runtime_seconds": 120,
                    "worker_min_runtime_seconds": None,
                },
                "goal_plus_config": {"shared_dir_enabled": False},
            }
            args = SimpleNamespace(
                model="test-model",
                api_base="http://provider.invalid/v1",
                pi_bin="pi",
            )
            modes: list[str] = []

            def evaluated(
                _workspace: Path,
                mode: str,
                _runtime: Path,
                _upstream: Path | None = None,
            ) -> dict[str, object]:
                modes.append(mode)
                return {
                    "valid": True,
                    "budget": {"total_claimed": 1},
                    "primary_metric": {"value": 1.0},
                }

            with (
                mock.patch.object(
                    experiment,
                    "evaluate_with_controller_runtime",
                    side_effect=evaluated,
                ),
                mock.patch.object(experiment, "configure_isolated_codex_home"),
                mock.patch.object(
                    experiment, "configure_evidence_annotator_environment"
                ),
                mock.patch.object(experiment, "write_pi_models_config"),
                mock.patch.object(
                    experiment,
                    "run_controlled",
                    return_value={"hard_killed": False},
                ),
                mock.patch.object(experiment, "close_pi_pools", return_value={}),
                mock.patch.object(
                    experiment,
                    "controller_subprocess_environment",
                    return_value=nullcontext(),
                ),
                mock.patch.object(
                    experiment,
                    "finalize_goal_plus_search",
                    side_effect=RuntimeError("closeout failed"),
                ),
                mock.patch.object(experiment, "parse_pi_events", return_value={}),
                mock.patch.object(
                    experiment,
                    "collect_goal_plus_state",
                    return_value={"runs": []},
                ),
                mock.patch.object(
                    experiment, "collect_evidence_annotator_usage", return_value={}
                ),
                mock.patch.object(
                    experiment, "goal_plus_incomplete_reason", return_value=None
                ),
            ):
                control = experiment.execute_goal_plus(manifest, run_dir, args, {})

            self.assertEqual(modes, ["public"])
            self.assertTrue(control["official_evaluation_withheld"])
            self.assertEqual(control["evaluator_calls"]["controller_final_claimed"], 0)
            self.assertIn("closeout failed", control["result_incomplete_reason"])
            self.assertFalse((run_dir / "final-eval.json").exists())

    def test_blind_controller_withholds_official_evaluation_for_incomplete_closeout_evidence(
        self,
    ) -> None:
        experiment.configure_adapter("zsoft-detect")
        valid_selection = {
            "selected_candidate_id": "c001",
            "selection_rule": experiment.BLIND_SELECTION_RULE,
        }
        valid_promotion = {"artifact_path": "/controller/c001.patch"}
        cases = {
            "selection": {
                "promotion": valid_promotion,
                "final_state": "promoted",
                "goal_statuses": {"gp_001": "complete"},
            },
            "promotion": {
                "selection": valid_selection,
                "final_state": "promoted",
                "goal_statuses": {"gp_001": "complete"},
            },
            "goal_statuses": {
                "selection": valid_selection,
                "promotion": valid_promotion,
                "final_state": "promoted",
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for missing_field, run_evidence in cases.items():
                with self.subTest(missing_field=missing_field):
                    run_dir = root / missing_field / "run"
                    workspace = run_dir / "workspace"
                    (workspace / "submission").mkdir(parents=True)
                    (workspace / "submission/.gitkeep").write_text("")
                    (workspace / "TASK.md").write_text("Audit the source.\n")
                    manifest = {
                        "method": "goal-plus-pi",
                        "workspace": str(workspace),
                        "reasoning_effort": "medium",
                        "task": {"evaluation_mode": "blind"},
                        "environment": {
                            "runtime_bin": str(root / "bin"),
                            "benchmark_root": str(detect.BENCHMARK_ROOT),
                        },
                        "budget": {
                            "wall_time_seconds": 300,
                            "soft_closeout_seconds": 60,
                            "hard_kill_grace_seconds": 5,
                            "concurrency": 1,
                            "worker_runtime_seconds": 120,
                            "worker_min_runtime_seconds": None,
                        },
                        "goal_plus_config": {"shared_dir_enabled": False},
                    }
                    args = SimpleNamespace(
                        model="test-model",
                        api_base="http://provider.invalid/v1",
                        pi_bin="pi",
                    )
                    modes: list[str] = []

                    def evaluated(
                        _workspace: Path,
                        mode: str,
                        _runtime: Path,
                        _upstream: Path | None = None,
                    ) -> dict[str, object]:
                        modes.append(mode)
                        return {
                            "valid": True,
                            "budget": {"total_claimed": 1},
                            "primary_metric": {"value": 1.0},
                        }

                    closeout = {"completed": True, "runs": [run_evidence]}
                    with (
                        mock.patch.object(
                            experiment,
                            "evaluate_with_controller_runtime",
                            side_effect=evaluated,
                        ),
                        mock.patch.object(experiment, "configure_isolated_codex_home"),
                        mock.patch.object(
                            experiment, "configure_evidence_annotator_environment"
                        ),
                        mock.patch.object(experiment, "write_pi_models_config"),
                        mock.patch.object(
                            experiment,
                            "run_controlled",
                            return_value={"hard_killed": False},
                        ),
                        mock.patch.object(experiment, "close_pi_pools", return_value={}),
                        mock.patch.object(
                            experiment,
                            "controller_subprocess_environment",
                            return_value=nullcontext(),
                        ),
                        mock.patch.object(
                            experiment,
                            "finalize_goal_plus_search",
                            return_value=closeout,
                        ),
                        mock.patch.object(experiment, "parse_pi_events", return_value={}),
                        mock.patch.object(
                            experiment,
                            "collect_goal_plus_state",
                            return_value={"runs": []},
                        ),
                        mock.patch.object(
                            experiment,
                            "collect_evidence_annotator_usage",
                            return_value={},
                        ),
                        mock.patch.object(
                            experiment, "goal_plus_incomplete_reason", return_value=None
                        ),
                    ):
                        control = experiment.execute_goal_plus(
                            manifest, run_dir, args, {}
                        )

                    self.assertEqual(modes, ["public"])
                    self.assertTrue(control["official_evaluation_withheld"])
                    self.assertEqual(
                        control["evaluator_calls"]["controller_final_claimed"], 0
                    )
                    expected_reason = {
                        "selection": "selection",
                        "promotion": "promotion",
                        "goal_statuses": "terminal evidence",
                    }[missing_field]
                    self.assertIn(
                        expected_reason, control["result_incomplete_reason"]
                    )
                    self.assertFalse((run_dir / "final-eval.json").exists())


if __name__ == "__main__":
    unittest.main()
