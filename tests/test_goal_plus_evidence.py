from __future__ import annotations

import unittest

from bench_goal_plus.goal_plus_evidence import frozen_worker_host


class FrozenHostEvidenceTests(unittest.TestCase):
    def test_local_driver_comes_from_frozen_main_identity(self) -> None:
        for native_host, expected in (("codex", "codex"), ("pi", "pi-rpc")):
            for backend in ("copy", "git_worktree"):
                with self.subTest(host=native_host, backend=backend):
                    self.assertEqual(frozen_worker_host({
                        "native_host": native_host,
                        "spec": {"workspace": {"backend": backend}},
                    }), expected)

    def test_missing_identity_or_unsupported_workspace_does_not_guess(self) -> None:
        for frozen in (
            {},
            {"spec": {"strategy": {"worker_host": "pi-rpc"}}},
            {"native_host": "pi", "spec": {"workspace": {"backend": "thinkthread"}}},
            {"native_host": "pi-rpc", "spec": {"workspace": {"backend": "copy"}}},
        ):
            with self.subTest(frozen=frozen):
                self.assertIsNone(frozen_worker_host(frozen))
