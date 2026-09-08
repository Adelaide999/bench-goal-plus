"""Invoke the official single-instance evaluator with an explicit architecture."""

import argparse
import json
from pathlib import Path


def evaluate(instances: Path, predictions: Path, *, image: str, architecture: str,
             run_id: str, timeout: int) -> None:
    import docker
    from swebench.harness.run_evaluation import run_instance
    from swebench.harness.test_spec.test_spec import make_test_spec

    rows = json.loads(instances.read_text())
    outputs = json.loads(predictions.read_text())
    if len(rows) != 1 or len(outputs) != 1 or rows[0]["instance_id"] != outputs[0]["instance_id"]:
        raise ValueError("official single-instance evaluation requires matching task and prediction")
    spec = make_test_spec(rows[0], namespace="swebench", arch=architecture)
    if spec.instance_image_key != image:
        raise ValueError("official image differs from the frozen task image")
    client = docker.from_env()
    try:
        client.images.get(image)
        result = run_instance(spec, outputs[0], False, False, client, run_id, timeout)
        if result is None:
            raise RuntimeError("official evaluator did not return an instance report")
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--instances", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--architecture", choices=("x86_64", "arm64"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout", type=int, required=True)
    args = parser.parse_args()
    evaluate(args.instances, args.predictions, image=args.image,
             architecture=args.architecture, run_id=args.run_id, timeout=args.timeout)
