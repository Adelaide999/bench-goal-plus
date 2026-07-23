from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import repro_env  # noqa: E402


class ReproEnvironmentTest(unittest.TestCase):
    def test_manifest_tracks_portable_upstream_branches(self) -> None:
        manifest = repro_env.load_manifest(ROOT / "environment/upstreams.json")
        self.assertEqual(repro_env.DEFAULT_CHECKOUT_ROOT, ROOT / "third_party")
        self.assertEqual(manifest["python"], "3.12")
        self.assertEqual(manifest["pi_min_version"], "0.80.6")
        self.assertTrue(
            {
                "openevolve",
                "goal_plus",
                "edgebench",
                "heurigym",
                "ale_bench",
                "autolab",
            }
            <= set(manifest["upstreams"])
        )
        for upstream in manifest["upstreams"].values():
            self.assertRegex(
                upstream["tracking_branch"], r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"
            )
            self.assertNotIn("pinned_commit", upstream)
            self.assertTrue(upstream["repository"].startswith("https://github.com/"))
            self.assertNotIn("/Users/", upstream["checkout_dir"])
            self.assertEqual(Path(upstream["checkout_dir"]).parent, Path("."))
        selected = repro_env.selected_upstreams(manifest, ["heurigym"])
        self.assertEqual(set(selected), {"openevolve", "goal_plus", "heurigym"})
        selected_edgebench = repro_env.selected_upstreams(manifest, ["edgebench"])
        self.assertEqual(
            set(selected_edgebench), {"openevolve", "goal_plus", "edgebench"}
        )
        self.assertTrue(selected_edgebench["edgebench"]["editable"])
        task_catalog = json.loads(
            (ROOT / "adapters/openevolve_examples/tasks.json").read_text()
        )
        self.assertEqual(
            manifest["upstreams"]["openevolve"]["tracking_branch"],
            task_catalog["upstream"]["tracking_branch"],
        )

    def test_checkout_follows_branch_and_fast_forwards(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "source"
            remote = temp / "remote.git"
            checkout = temp / "checkout"
            subprocess.run(["git", "init", "-q", "-b", "main", source], check=True)
            subprocess.run(
                ["git", "-C", source, "config", "user.name", "Test Controller"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    source,
                    "config",
                    "user.email",
                    "test@example.invalid",
                ],
                check=True,
            )
            (source / "README.md").write_text("one\n")
            subprocess.run(["git", "-C", source, "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", source, "commit", "-q", "-m", "initial"], check=True
            )
            subprocess.run(["git", "init", "-q", "--bare", remote], check=True)
            subprocess.run(
                ["git", "-C", source, "remote", "add", "origin", str(remote)],
                check=True,
            )
            subprocess.run(
                ["git", "-C", source, "push", "-q", "-u", "origin", "main"],
                check=True,
            )
            entry = {
                "repository": str(remote),
                "tracking_branch": "main",
            }

            repro_env.ensure_checkout(checkout, entry)
            first = repro_env.git_state(checkout, "main")
            self.assertEqual(first["branch"], "main")
            self.assertEqual(first["upstream"], "origin/main")
            self.assertEqual(first["head"], first["remote_head"])

            subprocess.run(
                ["git", "-C", checkout, "remote", "add", "upstream", str(remote)],
                check=True,
            )
            subprocess.run(
                ["git", "-C", checkout, "fetch", "-q", "upstream", "main"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    checkout,
                    "branch",
                    "--set-upstream-to",
                    "upstream/main",
                    "main",
                ],
                check=True,
                capture_output=True,
            )
            repro_env.ensure_checkout(checkout, entry)
            repaired = repro_env.git_state(checkout, "main")
            self.assertEqual(repaired["upstream"], "origin/main")

            (source / "README.md").write_text("two\n")
            subprocess.run(["git", "-C", source, "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", source, "commit", "-q", "-m", "second"], check=True
            )
            subprocess.run(
                ["git", "-C", source, "push", "-q", "origin", "main"], check=True
            )
            expected = subprocess.run(
                ["git", "-C", source, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            repro_env.ensure_checkout(checkout, entry)
            second = repro_env.git_state(checkout, "main")
            self.assertEqual(second["head"], expected)
            self.assertNotEqual(first["head"], second["head"])

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
            {
                "exists": False,
                "is_git": False,
                "head": None,
                "branch": None,
                "upstream": None,
                "remote_head": None,
                "origin_url": None,
                "dirty": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
