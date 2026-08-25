#!/usr/bin/env python3
"""Run one TorchBench workload in a fresh benchmark Python process."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
import statistics
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def load_workload(repository: Path, model_name: str, batch_size: int):
    sys.path.insert(0, str(repository))
    from torchbenchmark.util.experiment.instantiator import (  # noqa: PLC0415
        TorchBenchModelConfig,
        load_model,
    )

    return load_model(
        TorchBenchModelConfig(
            name=model_name,
            test="eval",
            device="cuda",
            batch_size=batch_size,
            extra_args=[],
        )
    )


def environment_fingerprint(torch) -> dict[str, Any]:
    try:
        torchvision_version = importlib.metadata.version("torchvision")
    except importlib.metadata.PackageNotFoundError:
        torchvision_version = None
    return {
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "torchvision": torchvision_version,
        "torch_cuda": str(torch.version.cuda) if torch.version.cuda else None,
        "cudnn": torch.backends.cudnn.version(),
        "gpu": torch.cuda.get_device_name(0),
        "compute_capability": list(torch.cuda.get_device_capability(0)),
    }


def normalize_output(value: Any, tensors: list[Any]) -> Any:
    import torch

    if isinstance(value, torch.Tensor):
        tensor = value.detach().cpu().clone()
        index = len(tensors)
        tensors.append(tensor)
        return {
            "type": "tensor",
            "index": index,
            "shape": list(tensor.shape),
            "dtype": str(tensor.dtype),
        }
    if isinstance(value, Mapping):
        items = []
        for key in sorted(value, key=lambda item: repr(item)):
            if not isinstance(key, (str, int, float, bool)):
                raise TypeError(f"unsupported output mapping key: {type(key).__name__}")
            items.append([key, normalize_output(value[key], tensors)])
        return {"type": "mapping", "items": items}
    if isinstance(value, tuple):
        return {
            "type": "tuple",
            "items": [normalize_output(item, tensors) for item in value],
        }
    if isinstance(value, list):
        return {
            "type": "list",
            "items": [normalize_output(item, tensors) for item in value],
        }
    if value is None or isinstance(value, (str, int, float, bool)):
        return {"type": "scalar", "value": value}
    raise TypeError(f"unsupported output value: {type(value).__name__}")


def capture_output(workload) -> dict[str, Any]:
    tensors: list[Any] = []
    structure = normalize_output(workload.invoke(), tensors)
    return {"structure": structure, "tensors": tensors}


def compare_outputs(actual: dict[str, Any], expected: dict[str, Any], *, atol: float, rtol: float):
    import torch

    if actual["structure"] != expected["structure"]:
        raise RuntimeError("output structure, shape, or dtype changed")
    if len(actual["tensors"]) != len(expected["tensors"]):
        raise RuntimeError("output tensor count changed")

    maximum_absolute_error = 0.0
    maximum_relative_error = 0.0
    for index, (observed, reference) in enumerate(
        zip(actual["tensors"], expected["tensors"])
    ):
        if observed.is_floating_point() or observed.is_complex():
            if not torch.isfinite(observed).all().item():
                raise RuntimeError(f"output tensor {index} contains non-finite values")
            if observed.numel():
                difference = (observed - reference).abs()
                absolute_error = float(difference.max().item())
                relative_error = float(
                    (difference / reference.abs().clamp_min(1.0e-12)).max().item()
                )
                maximum_absolute_error = max(maximum_absolute_error, absolute_error)
                maximum_relative_error = max(maximum_relative_error, relative_error)
            if not torch.allclose(observed, reference, atol=atol, rtol=rtol):
                raise RuntimeError(
                    f"output tensor {index} differs from reference: "
                    f"max_abs={absolute_error}, max_rel={relative_error}"
                )
        elif not torch.equal(observed, reference):
            raise RuntimeError(f"output tensor {index} differs from reference")
    return {
        "tensor_count": len(actual["tensors"]),
        "max_abs_error": maximum_absolute_error,
        "max_rel_error": maximum_relative_error,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("reference", "evaluate"))
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--batch-size", type=int, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--atol", type=float, default=0.0)
    parser.add_argument("--rtol", type=float, default=0.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("the evaluator requires exactly one visible CUDA device")
    workload = load_workload(args.repository.resolve(), args.model, args.batch_size)
    environment = environment_fingerprint(torch)
    output = capture_output(workload)
    torch.cuda.synchronize()

    if args.action == "reference":
        args.reference.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {"environment": environment, "output": output},
            args.reference,
        )
        result = {
            "valid": True,
            "model": args.model,
            "batch_size": args.batch_size,
            "environment": environment,
        }
    else:
        reference = torch.load(
            args.reference,
            map_location="cpu",
            weights_only=True,
        )
        if environment != reference["environment"]:
            raise RuntimeError("runtime environment differs from the frozen reference")
        correctness = compare_outputs(
            output,
            reference["output"],
            atol=args.atol,
            rtol=args.rtol,
        )
        from torchbenchmark.util.experiment.metrics import get_latencies  # noqa: PLC0415

        samples = get_latencies(
            workload.invoke,
            "cuda",
            nwarmup=args.warmups,
            num_iter=args.samples,
        )
        median = float(statistics.median(samples))
        if not math.isfinite(median):
            raise RuntimeError("median latency is not finite")
        result = {
            "valid": True,
            "model": args.model,
            "batch_size": args.batch_size,
            "median_latency_ms": median,
            "latency_samples_ms": samples,
            "correctness": correctness,
            "environment": environment,
        }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            json.dumps(
                {"valid": False, "error": f"{type(error).__name__}: {error}"},
                sort_keys=True,
            )
        )
        raise SystemExit(2)
