from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest import mock

from bench_goal_plus.candidate_judge import (
    ANNOTATOR_DISABLED_ENV,
    judge_candidates,
    normalize_endpoint,
    normalize_mode,
    scrub_controller_judge_environment,
)
from experiments.benchmark_compare import experiment as benchmark_compare
from experiments.openevolve_compare import experiment as openevolve_compare


def _candidates() -> list[dict[str, object]]:
    return [
        {
            "candidate_id": "c001",
            "hard_valid": True,
            "hard_score": 1.0,
            "summary": "focused fix",
            "trajectory": "focused fix",
        },
        {
            "candidate_id": "c002",
            "hard_valid": True,
            "hard_score": 1.0,
            "summary": "larger fix",
            "trajectory": "larger fix",
        },
        {
            "candidate_id": "bad",
            "hard_valid": False,
            "hard_score": 1.0,
            "summary": "must not be sent",
        },
    ]


class CandidateJudgeTest(unittest.TestCase):
    def test_controller_subprocess_fence_restores_judge_secrets(self) -> None:
        values = {
            "OPENROUTER_API_KEY": "judge-secret",
            "GOAL_PLUS_JEV_MODEL": "typesafe/jev-1.13",
            "OPENAI_API_KEY": "fallback-secret",
            ANNOTATOR_DISABLED_ENV: "previous",
            "ZAI_API_KEY": "worker-secret",
        }
        with mock.patch.dict(os.environ, values, clear=False):
            with scrub_controller_judge_environment("jev"):
                self.assertNotIn("OPENROUTER_API_KEY", os.environ)
                self.assertNotIn("GOAL_PLUS_JEV_MODEL", os.environ)
                self.assertNotIn("OPENAI_API_KEY", os.environ)
                self.assertEqual(os.environ[ANNOTATOR_DISABLED_ENV], "1")
                self.assertEqual(os.environ["ZAI_API_KEY"], "worker-secret")
            for name, value in values.items():
                self.assertEqual(os.environ[name], value)

    def test_controller_evaluation_fences_judge_secrets(self) -> None:
        observed: dict[str, str | None] = {}

        def fake_evaluate(*_args: object) -> dict[str, object]:
            observed["judge_key"] = os.environ.get("OPENROUTER_API_KEY")
            observed["agent_key"] = os.environ.get("ZAI_API_KEY")
            observed["annotator_disabled"] = os.environ.get(
                ANNOTATOR_DISABLED_ENV
            )
            return {"valid": True}

        with (
            mock.patch.dict(
                os.environ,
                {
                    "OPENROUTER_API_KEY": "judge-secret",
                    "ZAI_API_KEY": "worker-secret",
                },
                clear=False,
            ),
            mock.patch.object(
                benchmark_compare, "evaluate", side_effect=fake_evaluate
            ),
        ):
            result = benchmark_compare.evaluate_with_controller_runtime(
                Path("workspace"),
                "public",
                Path("controller-runtime"),
                candidate_judge_mode="jev",
            )
            self.assertEqual(os.environ["OPENROUTER_API_KEY"], "judge-secret")
        self.assertTrue(result["valid"])
        self.assertIsNone(observed["judge_key"])
        self.assertEqual(observed["agent_key"], "worker-secret")
        self.assertEqual(observed["annotator_disabled"], "1")

    def test_off_is_side_effect_free_and_filters_nothing(self) -> None:
        opener = mock.Mock(side_effect=AssertionError("network must not run"))
        result = judge_candidates(
            "task",
            _candidates(),
            mode="off",
            opener=opener,
        )
        self.assertEqual(result["status"], "disabled")
        self.assertIsNone(result["selected_candidate_id"])
        opener.assert_not_called()

    def test_explicit_empty_environment_does_not_fall_back_to_process_keys(self) -> None:
        opener = mock.Mock(side_effect=AssertionError("network must not run"))
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "ambient"}, clear=False):
            result = judge_candidates(
                "task",
                _candidates(),
                mode="jev",
                environment={},
                opener=opener,
            )
        self.assertEqual(result["status"], "error")
        self.assertIn("OPENROUTER_API_KEY", result["error"])
        opener.assert_not_called()

    def test_jev_choice_is_parsed_without_putting_key_in_body(self) -> None:
        observed: dict[str, object] = {}

        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "answers": {
                            "best_candidate": {
                                "choice": "c002",
                                "probabilities": {"c001": 0.2, "c002": 0.8},
                            },
                        }
                    }
                ).encode()

        def opener(request: object, timeout: int) -> Response:
            del timeout
            observed["body"] = json.loads(request.data.decode())  # type: ignore[attr-defined]
            observed["authorization"] = request.headers.get("Authorization")  # type: ignore[attr-defined]
            return Response()

        result = judge_candidates(
            "public task",
            _candidates(),
            mode="jev",
            environment={
                "OPENROUTER_API_KEY": "secret-key",
                "GOAL_PLUS_JEV_ENDPOINT": "https://example.invalid/decisions",
            },
            opener=opener,
        )
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected_candidate_id"], "c002")
        self.assertEqual(result["scores"], {"c001": 0.2, "c002": 0.8})
        self.assertEqual(observed["authorization"], "Bearer secret-key")
        self.assertNotIn("secret-key", json.dumps(observed["body"]))
        self.assertEqual(
            [item["id"] for item in observed["body"]["state"]["candidates"]],
            ["c001", "c002"],
        )
        self.assertEqual(observed["body"]["model"], "typesafe/jev-1.13")
        choices = observed["body"]["questions"]["best_candidate"]["criteria"]
        self.assertEqual(set(choices), {"c001", "c002"})
        self.assertNotIn("bad", choices)

    def test_jev_request_uses_openrouter_attribution_header(self) -> None:
        observed: dict[str, str | None] = {}

        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"answers":{"best_candidate":{"choice":"c001"}}}'

        def opener(request: object, timeout: int) -> Response:
            del timeout
            headers = {str(key).lower(): value for key, value in request.headers.items()}  # type: ignore[attr-defined]
            observed["referer"] = headers.get("http-referer")
            observed["title"] = headers.get("x-title")
            return Response()

        result = judge_candidates(
            "task",
            _candidates(),
            mode="jev",
            environment={"OPENROUTER_API_KEY": "key"},
            opener=opener,
        )
        self.assertEqual(result["status"], "selected")
        self.assertEqual(
            observed,
            {
                "referer": "https://github.com/ck0123/bench-goal-plus",
                "title": "bench-goal-plus candidate judge",
            },
        )

    def test_jev_blank_model_falls_back_to_default(self) -> None:
        observed: dict[str, object] = {}

        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"answers":{"best_candidate":{"choice":"c001"}}}'

        def opener(request: object, timeout: int) -> Response:
            del timeout
            observed["body"] = json.loads(request.data.decode())  # type: ignore[attr-defined]
            return Response()

        result = judge_candidates(
            "task",
            _candidates(),
            mode="jev",
            environment={"OPENROUTER_API_KEY": "key", "GOAL_PLUS_JEV_MODEL": "  "},
            opener=opener,
        )
        self.assertEqual(result["status"], "selected")
        self.assertEqual(observed["body"]["model"], "typesafe/jev-1.13")  # type: ignore[index]

    def test_jev_provider_error_is_sanitized(self) -> None:
        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"error":{"code":402,"message":"credits unavailable"}}'

        result = judge_candidates(
            "task",
            _candidates(),
            mode="jev",
            environment={"OPENROUTER_API_KEY": "key"},
            opener=lambda *_args, **_kwargs: Response(),
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("OpenRouter error 402", result["error"])
        self.assertNotIn("credits unavailable", result["error"])

    def test_jev_http_error_does_not_persist_response_body(self) -> None:
        def opener(*_args: object, **_kwargs: object) -> object:
            raise urllib.error.HTTPError(
                "https://example.invalid/decisions",
                413,
                "payload too large",
                {},
                BytesIO(b"candidate summary and secret-token=should-not-leak"),
            )

        result = judge_candidates(
            "task",
            _candidates(),
            mode="jev",
            environment={"OPENROUTER_API_KEY": "key"},
            opener=opener,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "OpenRouter HTTP 413")
        self.assertNotIn("should-not-leak", result["error"])

    def test_jev_unknown_choice_is_not_accepted(self) -> None:
        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"answers":{"best_candidate":{"choice":"unknown"}}}'

        result = judge_candidates(
            "task",
            _candidates(),
            mode="jev",
            environment={"OPENROUTER_API_KEY": "key"},
            opener=lambda *_args, **_kwargs: Response(),
        )
        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["selected_candidate_id"])

    def test_llm_verifier_index_and_comparison_count_are_mapped(self) -> None:
        module = types.ModuleType("llm_verifier")

        class Result:
            index = 1
            scores = [0.25, 0.9]
            n_comparisons = 3

        module.select = mock.Mock(return_value=Result())  # type: ignore[attr-defined]
        with mock.patch.dict(
            sys.modules, {"llm_verifier": module}
        ), mock.patch.dict(
            "os.environ", {"OPENAI_API_KEY": "judge-key"}, clear=False
        ):
            result = judge_candidates(
                "task",
                _candidates(),
                mode="llm-as-a-verifier",
                environment={
                    "OPENAI_API_KEY": "judge-key",
                    "GOAL_PLUS_LLM_VERIFIER_BASE_URL": "https://judge.example/v1",
                },
            )
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["selected_candidate_id"], "c002")
        self.assertEqual(result["comparisons"], 3)
        self.assertEqual(result["calls"], 1)
        module.select.assert_called_once()
        self.assertIsInstance(module.select.call_args.kwargs["criteria"], dict)
        self.assertIn("correctness", module.select.call_args.kwargs["criteria"])
        self.assertEqual(module.select.call_args.kwargs["on_error"], "raise")

    def test_llm_verifier_accepts_deepseek_backend_without_openai_url(self) -> None:
        module = types.ModuleType("llm_verifier")

        class Result:
            index = 0
            scores = [1.0, 0.0]
            n_comparisons = 1

        observed: dict[str, str | None] = {}

        def select(*_args: object, **_kwargs: object) -> Result:
            observed["key"] = os.environ.get("DEEPSEEK_API_KEY")
            observed["base"] = os.environ.get("OPENAI_BASE_URL")
            return Result()

        module.select = select  # type: ignore[attr-defined]
        with mock.patch.dict(sys.modules, {"llm_verifier": module}):
            result = judge_candidates(
                "task",
                _candidates(),
                mode="llm-as-a-verifier",
                environment={"DEEPSEEK_API_KEY": "deepseek-key"},
            )
        self.assertEqual(result["selected_candidate_id"], "c001")
        self.assertEqual(observed, {"key": "deepseek-key", "base": None})

    def test_llm_verifier_prefers_explicit_base_url_when_native_keys_coexist(self) -> None:
        module = types.ModuleType("llm_verifier")

        class Result:
            index = 0
            scores = [1.0, 0.0]
            n_comparisons = 1

        observed: dict[str, str | None] = {}

        def select(*_args: object, **_kwargs: object) -> Result:
            observed["key"] = os.environ.get("OPENAI_API_KEY")
            observed["base"] = os.environ.get("OPENAI_BASE_URL")
            observed["deepseek"] = os.environ.get("DEEPSEEK_API_KEY")
            return Result()

        module.select = select  # type: ignore[attr-defined]
        with mock.patch.dict(sys.modules, {"llm_verifier": module}):
            result = judge_candidates(
                "task",
                _candidates(),
                mode="llm-as-a-verifier",
                environment={
                    "OPENAI_API_KEY": "openai-key",
                    "OPENAI_BASE_URL": "https://judge.example/v1",
                    "DEEPSEEK_API_KEY": "deepseek-key",
                },
            )
        self.assertEqual(result["selected_candidate_id"], "c001")
        self.assertEqual(
            observed,
            {
                "key": "openai-key",
                "base": "https://judge.example/v1",
                "deepseek": None,
            },
        )

    def test_mode_aliases(self) -> None:
        self.assertEqual(normalize_mode("llm_verifier"), "llm-as-a-verifier")
        self.assertEqual(normalize_mode("disabled"), "off")
        with self.assertRaises(ValueError):
            normalize_mode("other")

    def test_endpoint_rejects_embedded_credentials(self) -> None:
        self.assertEqual(
            normalize_endpoint("https://judge.example/v1"),
            "https://judge.example/v1",
        )
        with self.assertRaises(ValueError):
            normalize_endpoint("https://judge.example/v1?token=secret")

    def test_controller_contract_freezes_mode_without_key(self) -> None:
        contract = benchmark_compare._candidate_judge_contract(
            {
                "GOAL_PLUS_JUDGE": "jev",
                "GOAL_PLUS_JEV_ENDPOINT": "https://judge.example/decisions",
                "GOAL_PLUS_JEV_MODEL": "typesafe/jev-1.13",
                "OPENROUTER_API_KEY": "must-not-be-recorded",
            }
        )
        self.assertEqual(contract["mode"], "jev")
        self.assertEqual(contract["endpoint"], "https://judge.example/decisions")
        self.assertNotIn("OPENROUTER_API_KEY", contract)
        self.assertEqual(contract["native_annotation"], "disabled")

    def test_controller_contract_uses_default_for_blank_jev_model(self) -> None:
        contract = benchmark_compare._candidate_judge_contract(
            {
                "GOAL_PLUS_JUDGE": "jev",
                "GOAL_PLUS_JEV_MODEL": "  ",
            }
        )
        self.assertEqual(contract["model"], "typesafe/jev-1.13")

    def test_off_contract_ignores_stale_provider_configuration(self) -> None:
        contract = benchmark_compare._candidate_judge_contract(
            {
                "GOAL_PLUS_JUDGE": "off",
                "GOAL_PLUS_JEV_ENDPOINT": "not-a-url",
                "GOAL_PLUS_JEV_MODEL": "stale-model",
            }
        )
        self.assertEqual(contract["endpoint"], "")
        self.assertEqual(contract["model"], "")
        self.assertEqual(contract["native_annotation"], "unchanged")

    def test_off_worker_scrub_can_preserve_native_annotation_settings(self) -> None:
        environment = {
            "GOAL_PLUS_EVIDENCE_ANNOTATOR_DISABLED": "0",
            "GOAL_PLUS_EVIDENCE_ANNOTATOR_MODEL": "native-model",
            "OPENAI_BASE_URL": "https://native.example/v1",
            "DEEPSEEK_API_KEY": "native-deepseek-key",
        }
        benchmark_compare._hide_candidate_judge_from_workers(
            environment,
            preserve={
                "GOAL_PLUS_EVIDENCE_ANNOTATOR_DISABLED",
                "GOAL_PLUS_EVIDENCE_ANNOTATOR_MODEL",
                "OPENAI_BASE_URL",
                "DEEPSEEK_API_KEY",
            },
        )
        self.assertEqual(environment["GOAL_PLUS_EVIDENCE_ANNOTATOR_MODEL"], "native-model")
        self.assertEqual(environment["OPENAI_BASE_URL"], "https://native.example/v1")
        self.assertEqual(environment["DEEPSEEK_API_KEY"], "native-deepseek-key")

    def test_enabled_mode_requires_a_matching_selection_receipt(self) -> None:
        self.assertIn(
            "no selection receipt",
            benchmark_compare._candidate_judge_incomplete_reason(
                {"completed": True, "runs": [{"selection": {}}]},
                "jev",
            ),
        )
        self.assertIsNone(
            benchmark_compare._candidate_judge_incomplete_reason(
                {
                    "completed": True,
                    "runs": [
                        {
                            "selection": {"selected_candidate_id": "c001"},
                            "candidate_judge": {
                                "mode": "jev",
                                "status": "selected",
                                "selected_candidate_id": "c001",
                            },
                        }
                    ],
                },
                "jev",
            )
        )

    def test_enabled_prompt_removes_native_annotator(self) -> None:
        prompt = openevolve_compare.render_goal(
            task_text="Improve it.",
            artifact_name="candidate.py",
            metric_name="score",
            metric_direction="maximize",
            wall_seconds=60,
            closeout_seconds=10,
            concurrency=2,
            agent_harness="codex",
            worker_model="gpt-5.6-luna",
            candidate_judge_mode="jev",
        )
        self.assertNotIn(" annotator=", prompt.splitlines()[0])
        self.assertIn("Native Evidence Annotation is disabled", prompt)
        self.assertIn("host controller owns selection, promotion", prompt)
        self.assertNotIn("- Promotion rule:", prompt)
        self.assertIn("do not call selection or promotion tools", prompt)

    def test_native_selection_hook_is_compatible_with_old_runtime_signature(self) -> None:
        class Record:
            candidate_id = "c001"

        class Runtime:
            def _selection_options(self, run, records, direction):
                del run, records, direction
                return [(1.0, Record(), 1, "a" * 40)]

        class Tools:
            def __init__(self) -> None:
                self.runtime = Runtime()

            def search_select(self, run_id: str) -> dict[str, object]:
                options = self.runtime._selection_options(None, [], "maximize")
                return {
                    "selected_candidate_id": options[0][1].candidate_id,
                    "selected_iteration": options[0][2],
                    "selected_git_head": options[0][3],
                }

        result = openevolve_compare._select_with_candidate(
            Tools(), "run", "c001", iteration=1, git_head="a" * 40
        )
        self.assertEqual(result["selected_candidate_id"], "c001")

    def test_native_selection_hook_supports_current_nested_selection(self) -> None:
        class Record:
            candidate_id = "c001"

        class Iteration:
            iteration = 2
            git_head = "b" * 40

        class Option:
            record = Record()
            iteration = Iteration()

        class Selection:
            def _selection_options(self, run, records, frozen):
                del run, records, frozen
                return [Option()]

        class Runtime:
            selection = Selection()

        class Tools:
            runtime = Runtime()

            def search_select(self, run_id: str) -> dict[str, object]:
                options = self.runtime.selection._selection_options(None, [], None)
                return {
                    "selected_candidate_id": options[0].record.candidate_id,
                    "selected_iteration": options[0].iteration.iteration,
                    "selected_git_head": options[0].iteration.git_head,
                }

        result = openevolve_compare._select_with_candidate(
            Tools(), "run", "c001", iteration=2, git_head="b" * 40
        )
        self.assertEqual(result["selected_candidate_id"], "c001")

    def test_native_selection_tool_supports_current_goal_plus_name(self) -> None:
        class Record:
            candidate_id = "c001"

        class Iteration:
            iteration = 1
            git_head = "c" * 40

        class Option:
            record = Record()
            iteration = Iteration()

        class Selection:
            def _selection_options(self, run, records, frozen):
                del run, records, frozen
                return [Option()]

        class Runtime:
            selection = Selection()

        class Tools:
            runtime = Runtime()

            def goal_plus_search_select(self, run_id: str) -> dict[str, object]:
                options = self.runtime.selection._selection_options(None, [], None)
                return {
                    "selected_candidate_id": options[0].record.candidate_id,
                    "selected_iteration": options[0].iteration.iteration,
                    "selected_git_head": options[0].iteration.git_head,
                }

        result = openevolve_compare._select_with_candidate(
            Tools(), "run", "c001", iteration=1, git_head="c" * 40
        )
        self.assertEqual(result["selected_candidate_id"], "c001")

    def test_candidate_inputs_use_global_best_public_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "c001"
            second = root / "c002"
            first.mkdir()
            second.mkdir()

            def write(
                path: Path,
                candidate_id: str,
                scores: list[float],
                disposition: str = "keep",
            ) -> None:
                iterations = [
                    {
                        "iteration": index,
                        "score": score,
                        "process_passed": True,
                        "git_head": f"{index:040d}",
                        "settlement_id": f"settlement-{candidate_id}-{index}",
                        "artifact_hash": f"artifact-{candidate_id}-{index}",
                        "git_artifact_clean": True,
                        "touched_denied_files": False,
                        "changed_outside_allowed": False,
                        "disposition": disposition,
                    }
                    for index, score in enumerate(scores, start=1)
                ]
                (path / "candidate.json").write_text(
                    json.dumps({"candidate_id": candidate_id, "iterations": iterations})
                )

            write(first, "c001", [1.0, 0.5])
            write(second, "c002", [1.0], disposition="superseded")
            result = openevolve_compare._candidate_judge_inputs(
                [first / "candidate.json", second / "candidate.json"]
            )

        self.assertEqual(
            [item["candidate_id"] for item in result], ["c001", "c002"]
        )
        self.assertEqual(result[0]["hard_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
