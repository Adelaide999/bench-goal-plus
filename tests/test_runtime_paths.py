from __future__ import annotations

import os
import unittest
from pathlib import Path

import bench_runtime_paths


ROOT = Path(__file__).resolve().parents[1]


class RuntimePathTest(unittest.TestCase):
    def test_temp_root_is_inside_the_relocatable_repository(self) -> None:
        self.assertEqual(bench_runtime_paths.ROOT, ROOT)
        self.assertEqual(bench_runtime_paths.DEFAULT_TEMP_ROOT, ROOT / ".tmp")
        self.assertTrue(bench_runtime_paths.DEFAULT_TEMP_ROOT.is_dir())
        for key in bench_runtime_paths.TEMP_ENVIRONMENT_KEYS:
            self.assertEqual(
                os.environ[key],
                str(ROOT / ".tmp"),
            )

    def test_child_environment_uses_only_repository_local_temp(self) -> None:
        environment: dict[str, str] = {}
        configured = bench_runtime_paths.configure_temp_environment(environment)
        for key in bench_runtime_paths.TEMP_ENVIRONMENT_KEYS:
            self.assertEqual(configured[key], str(ROOT / ".tmp"))

    def test_temporary_directory_is_created_below_repository(self) -> None:
        with bench_runtime_paths.temporary_directory(
            prefix="path-contract-",
            namespace="tests",
        ) as temporary:
            self.assertTrue(temporary.is_relative_to(ROOT / ".tmp/tests"))

    def test_production_does_not_fall_back_to_system_temp_paths(self) -> None:
        roots = (
            ROOT / "adapters",
            ROOT / "experiments",
            ROOT / "scripts",
            ROOT / "environment",
        )
        for root in roots:
            for path in root.rglob("*"):
                if path.suffix not in {".py", ".json", ".yaml", ".yml", ".toml", ".sh"}:
                    continue
                text = path.read_text()
                with self.subTest(path=path.relative_to(ROOT)):
                    self.assertNotIn("/private/tmp", text)
                    self.assertNotIn("/var/tmp", text)
                    self.assertNotIn('Path("/tmp', text)
                    self.assertNotIn("Path('/tmp", text)
                    if path.name != "bench_runtime_paths.py":
                        self.assertNotIn("tempfile.TemporaryDirectory", text)
                        self.assertNotIn("tempfile.mkdtemp", text)


if __name__ == "__main__":
    unittest.main()
