from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/environment/2026-07-21-mac-representative-smokes.json"
TEMP_AUDIT = ROOT / "evidence/environment/2026-07-23-repository-local-temp-audit.json"
SKYDISCOVER_DOCKER_AUDIT = (
    ROOT / "evidence/environment/2026-07-25-skydiscover-cpu-docker-images.json"
)


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

    def test_repository_local_temp_audit_is_complete_and_sanitized(self) -> None:
        raw = TEMP_AUDIT.read_text()
        payload = json.loads(raw)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["policy"]["repository_temp_root"], ".tmp")
        self.assertFalse(payload["policy"]["system_host_temp_dependency"])
        self.assertTrue(payload["doctor"]["repository_local_temp_check"])
        self.assertEqual(payload["doctor"]["managed_checkouts"], 10)
        self.assertEqual(len(payload["seed_smokes"]), 5)
        self.assertTrue(all(item["valid"] for item in payload["seed_smokes"]))
        self.assertTrue(
            all(
                item["temp_namespace"].startswith(".tmp/")
                for item in payload["seed_smokes"]
            )
        )
        self.assertNotIn("/Users/", raw)
        self.assertNotRegex(raw, r"sk-[A-Za-z0-9]{12,}")

    def test_skydiscover_docker_space_audit_is_complete_and_sanitized(
        self,
    ) -> None:
        raw = SKYDISCOVER_DOCKER_AUDIT.read_text()
        payload = json.loads(raw)

        images = payload["images"]
        self.assertEqual(len(images), 19)
        self.assertEqual(
            sum(item["size_bytes"] for item in images),
            payload["measurement"]["logical_image_size_bytes"],
        )
        self.assertEqual(payload["validation"]["missing_images"], 0)
        self.assertEqual(payload["validation"]["pip_check_failures"], 0)
        self.assertEqual(payload["validation"]["torch_present_images"], 0)
        self.assertEqual(payload["measurement"]["recommended_free_space_gb"], 10)
        self.assertNotIn("/Users/", raw)
        self.assertNotRegex(raw, r"sk-[A-Za-z0-9]{12,}")


if __name__ == "__main__":
    unittest.main()
