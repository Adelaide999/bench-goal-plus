from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "verify_legacy_smokes", ROOT / "scripts/verify_legacy_smokes.py"
)
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class LegacySmokeEvidenceTest(unittest.TestCase):
    def test_migrated_evidence_is_complete(self) -> None:
        report = VERIFY.verify_migrated()
        self.assertEqual(report["ale_bench_lite"]["private_cases"], 200)
        self.assertEqual(report["autolab"]["metric"], 2194)
        self.assertEqual(report["skydiscover_evox"]["programs"], 2)


if __name__ == "__main__":
    unittest.main()
