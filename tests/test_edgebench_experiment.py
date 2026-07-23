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
        self.assertFalse(any(path.name in {".gp", ".goal-plus"} for path in destination.rglob("*")))

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
