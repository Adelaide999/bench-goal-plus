from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/environment/2026-07-21-mac-representative-smokes.json"


class EnvironmentEvidenceTest(unittest.TestCase):
    def test_representative_pack_is_complete_and_sanitized(self) -> None:
        raw = EVIDENCE.read_text()
        payload = json.loads(raw)

        expected = {
            "ale-bench-lite",
            "heurigym",
            "frontier-engineering-lite",
            "autolab-cpu",
            "swarmresearch-15",
            "frontier-cs",
            "perfopt-bench",
        }
        self.assertEqual({item["id"] for item in payload["benchmarks"]}, expected)
        self.assertGreater(payload["host"]["disk_free_bytes_after_builds"], 100_000_000_000)
        self.assertNotIn("/Users/", raw)
        self.assertNotRegex(raw, r"sk-[A-Za-z0-9]{12,}")


if __name__ == "__main__":
    unittest.main()
