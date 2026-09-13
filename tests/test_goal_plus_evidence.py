from __future__ import annotations

import unittest

from bench_goal_plus.goal_plus_evidence import frozen_agent_harness, session_worker_intervals


class FrozenHostEvidenceTests(unittest.TestCase):
    def test_local_driver_comes_from_frozen_main_identity(self) -> None:
        for native_host, expected in (("codex", "codex"), ("pi", "pi")):
            for backend in ("copy", "git_worktree"):
                with self.subTest(host=native_host, backend=backend):
                    self.assertEqual(frozen_agent_harness({
                        "agent_harness": native_host,
                        "runtime_provider": "direct",
                        "spec": {"workspace": {"provider": backend}},
                    }), expected)

    def test_missing_identity_or_unsupported_workspace_does_not_guess(self) -> None:
        for frozen in (
            {},
            {"spec": {"strategy": {"agent_harness": "pi"}}},
            {"native_host": "pi", "spec": {"workspace": {"backend": "thinkthread"}}},
            {"native_host": "pi", "spec": {"workspace": {"backend": "copy"}}},
            {"agent_harness": "pi", "spec": {"workspace": {"provider": "copy"}}},
            {"agent_harness": "pi", "runtime_provider": "thinkthread", "spec": {"workspace": {"provider": "copy"}}},
            {"agent_harness": "pi-rpc", "runtime_provider": "direct", "spec": {"workspace": {"provider": "copy"}}},
        ):
            with self.subTest(frozen=frozen):
                self.assertIsNone(frozen_agent_harness(frozen))

    def test_dispatches_require_matching_native_execution_and_do_not_duplicate(self) -> None:
        receipt = {
            "agent_harness": "pi", "runtime_provider": "direct",
            "native_session_id": "native-1", "invocation_id": "turn-1",
            "started_at": "2026-09-13T00:00:00Z", "ended_at": "2026-09-13T00:01:00Z",
        }
        session = {
            "agent_harness": "pi", "runtime_provider": "direct",
            "run_id": "run-1", "candidate_id": "c001", "execution_generation": 2,
            "session_handle": {
                "agent_harness": "pi", "runtime_provider": "direct", "external_id": "native-1",
                "metadata": {"dispatches": [receipt, dict(receipt)]},
            },
        }
        intervals = session_worker_intervals(session)
        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals[0]["execution_generation"], 2)
        for field, value in (("agent_harness", "codex"), ("runtime_provider", "thinkthread"), ("native_session_id", "other")):
            with self.subTest(field=field):
                changed = {**receipt, field: value}
                session["session_handle"]["metadata"]["dispatches"] = [changed]
                self.assertEqual(session_worker_intervals(session), [])
