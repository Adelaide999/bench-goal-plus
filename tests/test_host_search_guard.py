#!/usr/bin/env python3
"""Keep host-wide find/grep from stalling Goal Plus main sessions."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from experiments.benchmark_compare.host_search_guard import (
    GUARD_BIN,
    blocked_path,
    prepend_to_path,
)


class HostSearchGuardTests(unittest.TestCase):
    def test_blocks_root_find_and_recursive_grep_outside_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cwd = str(Path(temporary).resolve())
            self.assertEqual(blocked_path("find", ["/", "-name", "*.py"], cwd), "/")
            self.assertEqual(
                blocked_path(
                    "grep",
                    ["-rn", "unknown selection ranking key", "/usr/lib/node_modules"],
                    cwd,
                ),
                "/usr/lib/node_modules",
            )
            self.assertIsNone(blocked_path("find", [".", "-name", "*.py"], cwd))
            self.assertIsNone(blocked_path("grep", ["-n", "foo", "file.py"], cwd))
            inside = str(Path(cwd) / "src")
            self.assertIsNone(blocked_path("find", [inside, "-name", "*.py"], cwd))

    def test_wrappers_are_on_path_before_system_find(self) -> None:
        environment = {"PATH": "/usr/bin:/bin"}
        prepend_to_path(environment)
        self.assertTrue(environment["PATH"].startswith(str(GUARD_BIN)))
        find_wrapper = GUARD_BIN / "find"
        grep_wrapper = GUARD_BIN / "grep"
        self.assertTrue(find_wrapper.is_file())
        self.assertTrue(grep_wrapper.is_file())
        self.assertTrue(os.stat(find_wrapper).st_mode & stat.S_IXUSR)
        self.assertTrue(os.stat(grep_wrapper).st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
