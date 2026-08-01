from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bench_goal_plus import docker_inventory
from experiments.skydiscover import environment


ROOT = Path(__file__).resolve().parents[1]
PROFILE = (
    ROOT
    / "experiments/skydiscover/profiles/cpu-no-torch-19.json"
)


class DockerInventoryTest(unittest.TestCase):
    def test_exact_inventory_uses_one_container_query_and_no_acquisition(self) -> None:
        containers = subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                {
                    "ID": "container-1",
                    "Image": "example/image:fixed",
                    "ImageID": "sha256:image",
                    "Names": "kept",
                    "State": "exited",
                    "Status": "Exited",
                }
            )
            + "\n",
            stderr="",
        )
        inspected = subprocess.CompletedProcess(
            [],
            0,
            stdout=json.dumps(
                [
                    {
                        "Id": "sha256:image",
                        "RepoTags": ["example/image:fixed"],
                        "RepoDigests": [],
                        "Size": 123,
                        "Architecture": "amd64",
                        "Os": "linux",
                        "Config": {"Labels": {"test": "yes"}},
                    }
                ]
            ),
            stderr="",
        )
        with mock.patch.object(
            docker_inventory, "_run", side_effect=[containers, inspected]
        ) as invoked:
            result = docker_inventory.inspect_exact_images(
                [{"reference": "example/image:fixed", "required": True}]
            )

        commands = [call.args[0] for call in invoked.call_args_list]
        self.assertEqual(commands[0][:3], ["docker", "ps", "-a"])
        self.assertEqual(
            commands[1],
            ["docker", "image", "inspect", "example/image:fixed"],
        )
        self.assertEqual(result["images"][0]["containers"][0]["name"], "kept")
        self.assertFalse(any("pull" in command or "build" in command for command in commands))


class SkyDiscoverAssetPackTest(unittest.TestCase):
    def test_torch_requirement_detection_handles_pep_508_forms(self) -> None:
        for requirement in (
            "torch",
            "Torch>=2.4",
            "torch[cuda] ~= 2.5",
            "torch @ https://example.invalid/torch.whl",
        ):
            with self.subTest(requirement=requirement):
                self.assertTrue(
                    environment.requirement_declared(requirement, "torch")
                )

        self.assertFalse(
            environment.requirement_declared(
                "# torch>=2\ntorchvision==0.20\n--extra-index-url https://example.invalid",
                "torch",
            )
        )

    def test_profile_freezes_the_reviewed_no_torch_pack(self) -> None:
        payload = json.loads(PROFILE.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["pip_index_url"],
            "https://pypi.tuna.tsinghua.edu.cn/simple",
        )
        base = payload["base_image"]
        self.assertEqual(base["reference"], "python:3.12-slim")
        self.assertEqual(base["architecture"], "amd64")
        self.assertRegex(base["manifest_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(base["expected_image_id"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            base["sources"][0], "docker.m.daocloud.io/library/python"
        )
        images = payload["images"]
        self.assertEqual(len(images), 19)
        self.assertEqual(len({item["reference"] for item in images}), 19)
        self.assertEqual(len({item["context"] for item in images}), 19)
        contexts = "\n".join(item["context"] for item in images)
        self.assertNotIn("second_autocorr_ineq", contexts)
        self.assertNotIn("ADRS/eplb", contexts)
        self.assertNotIn("kernelbench", contexts)
        self.assertTrue(
            all(len(item["source_tree"]) == 40 for item in images)
        )

    def test_generated_dockerfile_only_adds_pip_index_build_arg(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = root / "context"
            context.mkdir()
            original = "FROM python:3.12-slim\nWORKDIR /benchmark\nRUN pip install scipy\n"
            (context / "Dockerfile").write_text(original, encoding="utf-8")
            image = {
                "context_path": str(context),
                "expected_source_tree": "a" * 40,
            }
            with mock.patch.object(environment, "ROOT", root):
                generated = environment.build_dockerfile({}, image)

            self.assertEqual(
                generated.read_text(encoding="utf-8"),
                "FROM python:3.12-slim\n"
                "ARG PIP_INDEX_URL\n"
                "WORKDIR /benchmark\n"
                "RUN pip install scipy\n",
            )

    def test_provision_builds_missing_images_without_pull_refresh(self) -> None:
        profile = {
            "id": "test-pack",
            "asset_pack": "test-assets",
            "source_commit": "a" * 40,
            "pip_index_url": "https://pypi.tuna.tsinghua.edu.cn/simple",
            "base_image": {"reference": "python:3.12-slim"},
        }
        before = {
            "source": {"commit_matches": True, "dirty": False},
            "base_image": {
                "ready": True,
                "image_id": "sha256:base",
                "architecture": "amd64",
            },
            "images": [
                {
                    "reference": "example/evaluator:fixed",
                    "context": "benchmarks/example/evaluator",
                    "context_path": "/workspace/evaluator",
                    "context_present": True,
                    "dockerfile_present": True,
                    "base_image_matches": True,
                    "source_tree_matches": True,
                    "torch_dependency_declared": False,
                    "expected_source_tree": "b" * 40,
                    "present": False,
                    "ready": False,
                }
            ],
        }
        after = {"ready": True}
        with (
            mock.patch.object(environment, "inventory", side_effect=[before, after]),
            mock.patch.object(
                environment,
                "build_dockerfile",
                return_value=Path("/workspace/Dockerfile"),
            ),
            mock.patch.object(
                environment,
                "run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as invoked,
        ):
            result = environment.provision(profile)

        command = invoked.call_args.args[0]
        self.assertEqual(command[:3], ["docker", "build", "--pull=false"])
        self.assertIn("PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple", command)
        self.assertNotIn("pull", command[3:])
        self.assertEqual(result["built"], ["example/evaluator:fixed"])

    def test_doctor_runs_images_with_pull_never(self) -> None:
        checked = {
            "ready": True,
            "images": [{"reference": "example/evaluator:fixed"}],
        }
        with (
            mock.patch.object(environment, "inventory", return_value=checked),
            mock.patch.object(
                environment,
                "run",
                return_value=subprocess.CompletedProcess([], 0, "ok", ""),
            ) as invoked,
        ):
            result = environment.doctor({"asset_pack": "pack", "id": "profile"})

        command = invoked.call_args.args[0]
        self.assertIn("--pull", command)
        self.assertEqual(command[command.index("--pull") + 1], "never")
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
