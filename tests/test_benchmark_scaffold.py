from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bench_goal_plus.errors import ContractError
from bench_goal_plus.scaffold import scaffold_benchmark
from bench_runtime_paths import ensure_temp_root


class BenchmarkScaffoldTest(unittest.TestCase):
    def test_common_scaffold_writes_contract_files_without_registrations(self) -> None:
        with tempfile.TemporaryDirectory(dir=ensure_temp_root("test-scaffold")) as temp:
            root = Path(temp)
            result = scaffold_benchmark(
                benchmark_id="example-bench",
                shape="common",
                root=root,
                write=True,
            )

            self.assertTrue(result["written"])
            self.assertTrue(
                (root / "adapters/example_bench/adapter.py").is_file()
            )
            self.assertTrue(
                (root / "tests/test_example_bench_adapter.py").is_file()
            )
            self.assertEqual(
                result["registration_fragment"]["task_adapter"]["module"],
                "adapters.example_bench.adapter",
            )
            with self.assertRaisesRegex(ContractError, "refuses to overwrite"):
                scaffold_benchmark(
                    benchmark_id="example-bench",
                    shape="common",
                    root=root,
                    write=True,
                )

    def test_native_scaffold_dry_run_lists_the_full_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory(dir=ensure_temp_root("test-scaffold")) as temp:
            root = Path(temp)
            result = scaffold_benchmark(
                benchmark_id="native-bench",
                shape="native",
                root=root,
                write=False,
            )

            self.assertFalse(result["written"])
            self.assertFalse((root / "experiments/native-bench").exists())
            self.assertEqual(
                result["acceptance"],
                [
                    "catalog schema and unsupported-method rejection",
                    "doctor",
                    "prepare",
                    "run",
                    "status",
                    "finalize with raw metric evidence",
                ],
            )


if __name__ == "__main__":
    unittest.main()
