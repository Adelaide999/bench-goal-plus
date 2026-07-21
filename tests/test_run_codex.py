from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_codex.py"


class RunCodexTest(unittest.TestCase):
    def test_captures_jsonl_usage_without_real_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            workspace = temp / "workspace"
            workspace.mkdir()
            subprocess.run(["git", "init", "-b", "main", str(workspace)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(workspace), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(workspace), "config", "user.name", "Test"], check=True)
            (workspace / "README.md").write_text("fixture\n")
            subprocess.run(["git", "-C", str(workspace), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(workspace), "commit", "-m", "fixture"], check=True, capture_output=True)

            prompt = temp / "prompt.md"
            prompt.write_text("Improve the fixture.\n")
            fake_codex = temp / "fake-codex"
            fake_codex.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = \"--version\" ]; then echo 'codex-cli fixture'; exit 0; fi\n"
                "output=''\n"
                "while [ $# -gt 0 ]; do\n"
                "  if [ \"$1\" = \"--output-last-message\" ]; then output=$2; shift 2; else shift; fi\n"
                "done\n"
                "cat >/dev/null\n"
                "echo '{\"type\":\"thread.started\",\"thread_id\":\"thread-fixture\"}'\n"
                "echo '{\"type\":\"turn.started\"}'\n"
                "echo '{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":10,\"cached_input_tokens\":3,\"output_tokens\":4,\"reasoning_output_tokens\":2}}'\n"
                "echo 'done' > \"$output\"\n"
            )
            fake_codex.chmod(0o755)

            run_dir = temp / "run"
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--workspace",
                    str(workspace),
                    "--prompt-file",
                    str(prompt),
                    "--run-dir",
                    str(run_dir),
                    "--codex-bin",
                    str(fake_codex),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((run_dir / "run-manifest.json").read_text())
            self.assertEqual(manifest["thread_id"], "thread-fixture")
            self.assertEqual(manifest["usage"]["input_tokens"], 10)
            self.assertEqual(manifest["terminal_event"], "turn.completed")
            self.assertEqual((run_dir / "final-message.txt").read_text(), "done\n")
            self.assertFalse(manifest["load_user_config"])


if __name__ == "__main__":
    unittest.main()

