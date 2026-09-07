import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.edgebench.controller import environment as env
from experiments.edgebench.controller.profiles import load_profile


class Arm64VliwTest(unittest.TestCase):
    def test_docker_requires_selected_native_architecture(self):
        for actual, required, passed in (
            ("aarch64", "linux/arm64", True),
            ("aarch64", "linux/amd64", False),
            ("x86_64", "linux/amd64", True),
        ):
            with self.subTest(actual=actual, required=required):
                result = {"returncode": 0, "stderr": "", "stdout": json.dumps(
                    {"Architecture": actual, "OSType": "linux"})}
                report = env.DoctorReport("test")
                with patch.object(env.io, "run_capture", return_value=result):
                    env._docker_details(report, {"execution_platform": required})
                self.assertEqual(report.payload()["ok"], passed)

    def test_local_images_resolve_from_explicit_task_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "BENCHMARK.yaml").write_text("name: edgebench-arm64-local\n")
            (root / "vliw_kernel_optimization.json").write_text(json.dumps({
                "work": {"image_tag": "work"}, "judge": {"image_tag": "judge"}
            }))
            self.assertEqual(env.task_images("vliw_kernel_optimization", {
                "task_assets_dir": str(root)
            }), ("edgebench-arm64-local.work.vliw_kernel_optimization:work",
                 "edgebench-arm64-local.judge.vliw_kernel_optimization:judge"))

    def test_arm_profile_rejects_unsupported_codex(self):
        _, profile = load_profile("vliw-goal-plus-pi-sol-low-arm64-30m")
        profile["methods"] = ["goal-plus-codex"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(profile))
            with self.assertRaisesRegex(ValueError, "ARM64"):
                load_profile(path)

    def test_local_assets_cannot_be_replaced_by_provision(self):
        with self.assertRaisesRegex(ValueError, "skip-provision"):
            env.provision({"task_assets_dir": "/local/assets"})
