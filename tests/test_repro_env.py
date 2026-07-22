from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import repro_env  # noqa: E402


class ReproEnvironmentTest(unittest.TestCase):
    def test_manifest_pins_portable_upstreams(self) -> None:
        manifest = repro_env.load_manifest(ROOT / "environment/upstreams.json")
        self.assertEqual(manifest["python"], "3.12")
        self.assertEqual(manifest["pi_min_version"], "0.80.6")
        self.assertEqual(set(manifest["upstreams"]), {"openevolve", "goal_plus"})
        for upstream in manifest["upstreams"].values():
            self.assertRegex(upstream["pinned_commit"], r"^[0-9a-f]{40}$")
            self.assertTrue(upstream["repository"].startswith("https://github.com/"))
            self.assertNotIn("/Users/", upstream["checkout_dir"])
        task_catalog = json.loads(
            (ROOT / "adapters/openevolve_examples/tasks.json").read_text()
        )
        self.assertEqual(
            manifest["upstreams"]["openevolve"]["pinned_commit"],
            task_catalog["upstream"]["pinned_commit"],
        )

    def test_lock_and_manifests_do_not_contain_local_identity_or_keys(self) -> None:
        text = "\n".join(
            path.read_text()
            for path in (
                ROOT / "environment/upstreams.json",
                ROOT / "environment/requirements.in",
                ROOT / "environment/requirements.lock",
            )
        )
        self.assertNotRegex(text, r"/Users/[^/\s]+")
        self.assertNotRegex(text, r"\bsk-[A-Za-z0-9_-]{16,}\b")
        self.assertIn("fastmcp==", text)
        self.assertIn("openai==", text)

    def test_codex_version_parser(self) -> None:
        self.assertEqual(
            repro_env.parse_codex_version("codex-cli 0.144.6"), (0, 144, 6)
        )
        self.assertIsNone(repro_env.parse_codex_version("unknown"))

    def test_missing_git_checkout_is_reported_without_mutation(self) -> None:
        state = repro_env.git_state(ROOT / "does-not-exist")
        self.assertEqual(
            state,
            {"exists": False, "is_git": False, "head": None, "dirty": None},
        )


if __name__ == "__main__":
    unittest.main()
