from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("status", ROOT / "scripts/status.py")
assert SPEC and SPEC.loader
STATUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATUS)


class RegistryTest(unittest.TestCase):
    def test_registry_is_valid(self) -> None:
        self.assertEqual(STATUS.validate(STATUS.load_registry()), [])

    def test_dataset_catalog_is_valid(self) -> None:
        self.assertEqual(STATUS.validate_datasets(), [])

    def test_every_item_has_explicit_docker_requirement(self) -> None:
        data = STATUS.load_registry()
        requirements = {
            item["id"]: item["docker_requirement"] for item in data["items"]
        }
        self.assertEqual(requirements["ale-bench-lite"], "required")
        self.assertEqual(requirements["heurigym"], "not_required")
        self.assertEqual(requirements["autolab-cpu"], "mixed")
        self.assertEqual(requirements["edgebench"], "required")
        self.assertEqual(requirements["swe-bench-verified"], "required")
        self.assertEqual(requirements["openevolve"], "not_required")

    def test_swe_bench_readiness_keeps_methods_separate(self) -> None:
        data = STATUS.load_registry()
        item = next(
            item for item in data["items"] if item["id"] == "swe-bench-verified"
        )

        self.assertEqual(item["gate_set"], "benchmark_methods")
        self.assertEqual(
            set(item["stages"]), set(data["gate_sets"]["benchmark_methods"])
        )
        self.assertEqual(item["stages"]["plain_codex"], "partial")
        self.assertEqual(item["stages"]["plain_pi"], "partial")
        self.assertEqual(item["stages"]["goal_plus_codex"], "n/a")
        self.assertEqual(item["stages"]["goal_plus_pi"], "n/a")


if __name__ == "__main__":
    unittest.main()
