from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "edgebench_experiment",
    ROOT / "experiments" / "edgebench" / "experiment.py",
)
assert SPEC and SPEC.loader
EDGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EDGE
SPEC.loader.exec_module(EDGE)


class EdgeBenchExperimentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = (
            EDGE.ensure_temp_root("test-edgebench-experiment")
            / f"{self._testMethodName}-{time.time_ns()}"
        )
        self.temp.mkdir(parents=True)
        self.originals = {
            "TASKS_DIR": EDGE.TASKS_DIR,
            "RUNS_ROOT": EDGE.RUNS_ROOT,
            "EDGE_ROOT": EDGE.EDGE_ROOT,
            "GOAL_PLUS_ROOT": EDGE.GOAL_PLUS_ROOT,
        }
        EDGE.TASKS_DIR = self.temp / "edgebench" / "tasks"
        EDGE.RUNS_ROOT = self.temp / "runs"
        EDGE.EDGE_ROOT = self.temp / "edgebench"
        EDGE.GOAL_PLUS_ROOT = self.temp / "goal-plus"
        EDGE.TASKS_DIR.mkdir(parents=True)
        EDGE.GOAL_PLUS_ROOT.mkdir(parents=True)
        (EDGE.TASKS_DIR / "vliw_kernel_optimization.json").write_text(
            json.dumps(
                {
                    "task_id": "vliw_kernel_optimization",
                    "work": {
                        "agent_query": "Optimize solution.py.",
                        "image_tag": "work123",
                    },
                    "judge": {
                        "image_tag": "judge123",
                        "score_direction": "minimize",
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        for name, value in self.originals.items():
            setattr(EDGE, name, value)

    def profile(self) -> dict:
        _, profile = EDGE.load_profile("vliw-smoke")
        return profile

    def test_full_codex_profile_covers_all_public_tasks(self) -> None:
        _, profile = EDGE.load_profile("full-codex-2h")

        self.assertEqual(len(profile["task_ids"]), 51)
        self.assertEqual(len(set(profile["task_ids"])), 51)
        self.assertEqual(profile["methods"], ["plain-codex"])
        self.assertEqual(profile["model"], "gpt-5.6-sol")
        self.assertEqual(profile["reasoning_effort"], "medium")
        self.assertEqual(profile["wall_time_seconds"], 7200)
        self.assertEqual(profile["concurrency"], 1)
        self.assertEqual(profile["cell_concurrency"], 2)
        self.assertNotIn("work_cpu_limit", profile)
        self.assertNotIn("judge_cpu_limit", profile)

    def test_prepare_encodes_plain_outer_and_goal_plus_inner_concurrency(self) -> None:
        args = SimpleNamespace(
            method=None,
            wall_time_seconds=180,
            concurrency=3,
            model="gpt-test",
            reasoning_effort="high",
            campaign_id="unit-campaign",
        )

        destination = EDGE.prepare(args, self.profile())

        plain = json.loads(
            (
                destination
                / "cells"
                / "vliw_kernel_optimization--plain-codex"
                / "cell.json"
            ).read_text()
        )
        goal_plus = json.loads(
            (
                destination
                / "cells"
                / "vliw_kernel_optimization--goal-plus-codex"
                / "cell.json"
            ).read_text()
        )
        self.assertEqual(plain["outer_replicas"], 3)
        self.assertEqual(plain["inner_search_concurrency"], 0)
        self.assertEqual(goal_plus["outer_replicas"], 1)
        self.assertEqual(goal_plus["inner_search_concurrency"], 3)
        self.assertEqual(
            json.loads((destination / "profile.json").read_text())["cell_concurrency"],
            1,
        )
        self.assertFalse(any(path.name in {".gp", ".goal-plus"} for path in destination.rglob("*")))

    def test_cell_queue_limits_parallel_cells_and_continues_after_failure(self) -> None:
        destination = self.temp / "campaign"
        destination.mkdir()
        EDGE.write_json(destination / "controller.json", {"state": "running"})
        campaign = {
            "cells": [
                {"cell_id": cell_id, "task_id": cell_id}
                for cell_id in ("a", "b", "c")
            ]
        }
        started = []
        processes = []
        live = 0
        max_live = 0

        class FakeProcess:
            def __init__(self, pid):
                self.pid = pid
                self.done = False

            def poll(self):
                return 0 if self.done else None

        def fake_start(_destination, summary, **_kwargs):
            nonlocal live, max_live
            process = FakeProcess(100 + len(processes))
            processes.append(process)
            started.append(summary["cell_id"])
            live += 1
            max_live = max(max_live, live)
            return {
                "cell": {
                    "cell_id": summary["cell_id"],
                    "task_id": summary["task_id"],
                    "started_at": "now",
                },
                "process": process,
            }

        def fake_finish(_destination, running, *, stop_requested):
            nonlocal live
            self.assertFalse(stop_requested)
            live -= 1
            return 1 if running["cell"]["cell_id"] == "b" else 0

        sleeps = 0

        def fake_sleep(_seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 1:
                processes[0].done = True
            else:
                for process in processes:
                    process.done = True

        original_start = EDGE.start_campaign_cell
        original_finish = EDGE.finish_campaign_cell
        original_sleep = EDGE.time.sleep
        EDGE.start_campaign_cell = fake_start
        EDGE.finish_campaign_cell = fake_finish
        EDGE.time.sleep = fake_sleep
        try:
            returncode = EDGE.execute_cell_queue(
                destination,
                campaign,
                {"state": "running"},
                cell_concurrency=2,
                judge_container_url="http://judge",
                api_config={"api_key_source": None, "api_base_url_source": None},
                api_key=None,
                runtime_api_base_url=None,
                bridge_host=None,
                stop_requested=lambda: False,
            )
        finally:
            EDGE.start_campaign_cell = original_start
            EDGE.finish_campaign_cell = original_finish
            EDGE.time.sleep = original_sleep

        self.assertEqual(returncode, 1)
        self.assertEqual(started, ["a", "b", "c"])
        self.assertEqual(max_live, 2)
        self.assertEqual(
            json.loads((destination / "controller.json").read_text())[
                "active_children"
            ],
            {},
        )

    def test_cell_queue_stop_interrupts_active_cells_without_starting_more(self) -> None:
        destination = self.temp / "campaign"
        destination.mkdir()
        EDGE.write_json(destination / "controller.json", {"state": "running"})
        campaign = {
            "cells": [
                {"cell_id": cell_id, "task_id": cell_id}
                for cell_id in ("a", "b", "c")
            ]
        }
        started = []
        processes = []
        requested = False

        class FakeProcess:
            def __init__(self, pid):
                self.pid = pid
                self.done = False
                self.signals = []

            def poll(self):
                return 130 if self.done else None

            def send_signal(self, value):
                self.signals.append(value)
                self.done = True

        def fake_start(_destination, summary, **_kwargs):
            process = FakeProcess(200 + len(processes))
            processes.append(process)
            started.append(summary["cell_id"])
            return {
                "cell": {
                    "cell_id": summary["cell_id"],
                    "task_id": summary["task_id"],
                    "started_at": "now",
                },
                "process": process,
            }

        def fake_finish(_destination, _running, *, stop_requested):
            self.assertTrue(stop_requested)
            return 130

        def fake_sleep(_seconds):
            nonlocal requested
            requested = True

        original_start = EDGE.start_campaign_cell
        original_finish = EDGE.finish_campaign_cell
        original_sleep = EDGE.time.sleep
        EDGE.start_campaign_cell = fake_start
        EDGE.finish_campaign_cell = fake_finish
        EDGE.time.sleep = fake_sleep
        try:
            returncode = EDGE.execute_cell_queue(
                destination,
                campaign,
                {"state": "running"},
                cell_concurrency=2,
                judge_container_url="http://judge",
                api_config={"api_key_source": None, "api_base_url_source": None},
                api_key=None,
                runtime_api_base_url=None,
                bridge_host=None,
                stop_requested=lambda: requested,
            )
        finally:
            EDGE.start_campaign_cell = original_start
            EDGE.finish_campaign_cell = original_finish
            EDGE.time.sleep = original_sleep

        self.assertEqual(returncode, 130)
        self.assertEqual(started, ["a", "b"])
        self.assertEqual(
            [process.signals for process in processes],
            [[EDGE.signal.SIGINT], [EDGE.signal.SIGINT]],
        )

    def test_goal_plus_environment_uses_pinned_source_and_configured_k(self) -> None:
        cell = {
            "method": "goal-plus-codex",
            "reasoning_effort": "xhigh",
            "inner_search_concurrency": 4,
            "worker_runtime_seconds": 600,
        }

        env = EDGE.cell_environment(cell)

        self.assertEqual(env["SFORGE_GOAL_PLUS_SOURCE_DIR"], str(EDGE.GOAL_PLUS_ROOT))
        self.assertIn("SFORGE_GOAL_PLUS_MAX_PARALLEL=4", env["SFORGE_AGENT_EXTRA_ENV"])
        self.assertIn(
            "SFORGE_GOAL_PLUS_WORKER_RUNTIME_SECONDS=600",
            env["SFORGE_AGENT_EXTRA_ENV"],
        )
        for key in ("TMPDIR", "TMP", "TEMP"):
            self.assertTrue(Path(env[key]).is_relative_to(ROOT))

    def test_api_config_prefers_sforge_then_openai_then_codex(self) -> None:
        config = EDGE.resolve_agent_api_config(
            {
                "SFORGE_AGENT_API_KEY": "sforge-key",
                "SFORGE_AGENT_API_BASE_URL": "https://sforge.example/v1",
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_BASE_URL": "https://openai.example/v1",
                "CODEX_API_KEY": "codex-key",
            }
        )

        self.assertEqual(config["api_key"], "sforge-key")
        self.assertEqual(config["api_key_source"], "SFORGE_AGENT_API_KEY")
        self.assertEqual(config["api_base_url"], "https://sforge.example/v1")

        fallback = EDGE.resolve_agent_api_config(
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_BASE_URL": "http://127.0.0.1:3788/v1",
                "CODEX_API_KEY": "codex-key",
            }
        )
        self.assertEqual(fallback["api_key"], "openai-key")
        self.assertEqual(fallback["api_key_source"], "OPENAI_API_KEY")
        self.assertEqual(fallback["api_base_url_source"], "OPENAI_BASE_URL")

    def test_loopback_api_bridge_preserves_base_path(self) -> None:
        self.assertEqual(
            EDGE.loopback_api_target("http://127.0.0.1:3788/v1"),
            ("127.0.0.1", 3788),
        )
        self.assertEqual(
            EDGE.bridged_base_url(
                "http://127.0.0.1:3788/v1", "192.0.2.10", 45678
            ),
            "http://192.0.2.10:45678/v1",
        )
        self.assertIsNone(
            EDGE.loopback_api_target("https://api.example.com/v1")
        )

    def test_cell_environment_maps_api_key_and_bridge(self) -> None:
        env = EDGE.cell_environment(
            {
                "method": "plain-codex",
                "reasoning_effort": "medium",
            },
            api_key="runtime-key",
            api_base_url="http://192.0.2.10:45678/v1",
            bridge_host="192.0.2.10",
        )

        self.assertEqual(env["SFORGE_AGENT_API_KEY"], "runtime-key")
        self.assertEqual(
            env["SFORGE_AGENT_API_BASE_URL"],
            "http://192.0.2.10:45678/v1",
        )
        self.assertIn("192.0.2.10", env["SFORGE_NO_PROXY"].split(","))

    def test_judge_environment_uses_fixed_model_and_runtime_api(self) -> None:
        previous = EDGE.os.environ.pop("SFORGE_JUDGE_EXTRA_ENV", None)
        try:
            env = EDGE.judge_server_environment(
                api_key="judge-key",
                api_base_url="http://192.0.2.10:45678/v1",
                bridge_host="192.0.2.10",
            )
        finally:
            if previous is not None:
                EDGE.os.environ["SFORGE_JUDGE_EXTRA_ENV"] = previous

        values = dict(
            item.split("=", 1)
            for item in env["SFORGE_JUDGE_EXTRA_ENV"].split(",")
        )
        self.assertEqual(values["SFORGE_JUDGE_API_KEY"], "judge-key")
        self.assertEqual(
            values["SFORGE_JUDGE_API_BASE_URL"],
            "http://192.0.2.10:45678/v1",
        )
        self.assertEqual(values["SFORGE_JUDGE_MODEL"], "gpt-5.5")

    def test_child_proxy_is_rewritten_for_container_access(self) -> None:
        previous = {
            key: EDGE.os.environ.get(key)
            for key in ("SFORGE_HTTPS_PROXY", "HTTPS_PROXY")
        }
        EDGE.os.environ.pop("SFORGE_HTTPS_PROXY", None)
        EDGE.os.environ["HTTPS_PROXY"] = "http://127.0.0.1:3128"
        try:
            env = EDGE.cell_environment(
                {
                    "method": "plain-codex",
                    "reasoning_effort": "high",
                }
            )
        finally:
            for key, value in previous.items():
                if value is None:
                    EDGE.os.environ.pop(key, None)
                else:
                    EDGE.os.environ[key] = value

        self.assertEqual(
            env["SFORGE_HTTPS_PROXY"],
            "http://host.docker.internal:3128",
        )

    def test_rust_runtime_probe_preserves_image_environment(self) -> None:
        original = EDGE.run_capture
        captured = []

        def fake_run_capture(command, *, env=None):
            captured.append(command)
            return {"returncode": 0, "stdout": "rustc 1.88.0", "stderr": ""}

        EDGE.run_capture = fake_run_capture
        try:
            result = EDGE.rust_image_runtime_probe("example:rust", "1.88.0")
        finally:
            EDGE.run_capture = original

        self.assertEqual(result["returncode"], 0)
        self.assertIn("-c", captured[0])
        self.assertNotIn("-lc", captured[0])
        self.assertIn("command -v cargo", captured[0][-1])

    def test_codex_usage_reads_jsonl_agent_output(self) -> None:
        run = self.temp / "task-run"
        run.mkdir()
        (run / "agent_output.txt").write_text(
            "\n".join(
                [
                    '{"type":"thread.started","thread_id":"thread-1"}',
                    '{"type":"turn.completed","usage":{"input_tokens":11,"cached_input_tokens":3,"output_tokens":5}}',
                    "non-json status line",
                    '{"type":"turn.completed","usage":{"input_tokens":7,"output_tokens":2}}',
                ]
            ),
            encoding="utf-8",
        )

        usage = EDGE.codex_usage(run)

        self.assertEqual(usage["coverage"], "agent_output_only")
        self.assertEqual(usage["session_count"], 1)
        self.assertEqual(usage["tokens"]["input_tokens"], 18)
        self.assertEqual(usage["tokens"]["output_tokens"], 7)
        self.assertEqual(usage["tokens"]["cached_input_tokens"], 3)

    def test_codex_usage_reads_cumulative_rollout_tokens_once(self) -> None:
        run = self.temp / "task-run"
        run.mkdir()
        events = "\n".join(
            [
                '{"type":"session_meta","payload":{"id":"session-1"}}',
                '{"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":11,"cached_input_tokens":3,"output_tokens":5,"total_tokens":16}}}}',
                '{"type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":18,"cached_input_tokens":7,"output_tokens":9,"total_tokens":27}}}}',
            ]
        ).encode()
        member = tarfile.TarInfo("sessions/rollout.jsonl")
        member.size = len(events)
        with tarfile.open(run / "codex-sessions.tar", "w") as archive:
            archive.addfile(member, io.BytesIO(events))

        usage = EDGE.codex_usage(run)

        self.assertEqual(usage["coverage"], "all_collected_codex_sessions")
        self.assertEqual(usage["session_count"], 1)
        self.assertEqual(usage["tokens"]["input_tokens"], 18)
        self.assertEqual(usage["tokens"]["cached_input_tokens"], 7)
        self.assertEqual(usage["tokens"]["output_tokens"], 9)
        self.assertEqual(usage["tokens"]["total_tokens"], 27)

    def test_goal_plus_stats_counts_empty_search_run(self) -> None:
        run = self.temp / "task-run"
        run.mkdir()
        payload = b'{"run_id":"run-1","state":"running"}'
        member = tarfile.TarInfo(".goal-plus/runs/run-1/run.json")
        member.size = len(payload)
        with tarfile.open(run / "goal-plus-state.tar", "w") as archive:
            archive.addfile(member, io.BytesIO(payload))

        stats = EDGE.goal_plus_stats(run)

        self.assertIsNotNone(stats)
        assert stats is not None
        self.assertEqual(stats["search_runs"], 1)
        self.assertEqual(stats["candidates"], 0)
        self.assertEqual(stats["search_run_states"], {"running": 1})

    def test_provision_excludes_downloaded_tasks_from_git_status(self) -> None:
        exclude = EDGE.EDGE_ROOT / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True)
        exclude.write_text("# local excludes\n", encoding="utf-8")

        EDGE.ensure_local_task_exclude()
        EDGE.ensure_local_task_exclude()

        self.assertEqual(
            exclude.read_text(encoding="utf-8").splitlines().count("tasks/"),
            1,
        )

    def test_command_keeps_plain_replicas_distinct_from_goal_plus_workers(self) -> None:
        destination = self.temp / "campaign"
        plain = {
            "cell_id": "plain",
            "task_id": "vliw_kernel_optimization",
            "sforge_agent": "codex",
            "model": "gpt-test",
            "wall_time_seconds": 300,
            "eval_interval_seconds": 120,
            "sforge_run_id": "run-plain",
            "outer_replicas": 4,
            "outer_replica_concurrency": 4,
            "judge_concurrency": 1,
            "judge_port": 8080,
            "work_cpu_limit": None,
            "judge_cpu_limit": None,
            "internet": True,
        }

        command = EDGE.build_sforge_command(destination, plain)

        self.assertEqual(command[command.index("--replicas") + 1], "4")
        self.assertEqual(command[command.index("--replica-concurrency") + 1], "4")
        self.assertEqual(
            command[command.index("--judge-url") + 1],
            "http://host.docker.internal:8080",
        )
        self.assertIn("--enable-internet", command)


if __name__ == "__main__":
    unittest.main()
