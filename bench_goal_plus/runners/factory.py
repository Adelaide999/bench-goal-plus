"""Create typed runners from catalog definitions."""

from __future__ import annotations

from ..errors import ContractError
from ..models import RunnerDefinition
from .base import BenchmarkRunner
from .common_matrix import CommonMatrixRunner
from .native_profile import NativeProfileRunner
from .openevolve_batch import OpenEvolveBatchRunner


def create_runner(definition: RunnerDefinition) -> BenchmarkRunner:
    if definition.kind == "native-profile":
        return NativeProfileRunner(definition)
    if definition.kind == "common-matrix":
        return CommonMatrixRunner(definition)
    if definition.kind == "openevolve-batch":
        return OpenEvolveBatchRunner(definition)
    raise ContractError(f"unsupported runner kind: {definition.kind}")
