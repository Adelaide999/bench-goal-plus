"""Validated registry for standalone benchmark task adapters."""

from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, Protocol


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "benchmarks/task-adapters.json"
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
SAFE_MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
REQUIRED_CONSTANTS = (
    "ARTIFACT_NAME",
    "BENCHMARK_NAME",
    "CASE_SET_DESCRIPTION",
    "CODEX_SANDBOX",
    "DIRECTION",
    "PRIMARY_METRIC",
    "TASK_ID",
    "UPSTREAM_KEY",
    "VERIFIER_TIMEOUT_SECONDS",
)
REQUIRED_CALLABLES = (
    "evaluate_workspace",
    "git_commit",
    "materialize_workspace",
)


class BenchmarkAdapterModule(Protocol):
    """Runtime contract implemented by one standalone benchmark adapter."""

    ARTIFACT_NAME: str
    BENCHMARK_NAME: str
    CASE_SET_DESCRIPTION: str
    CODEX_SANDBOX: str
    DIRECTION: Literal["minimize", "maximize"]
    PRIMARY_METRIC: str
    TASK_ID: str
    UPSTREAM_KEY: str
    VERIFIER_TIMEOUT_SECONDS: int

    def materialize_workspace(
        self, source_root: Path, workspace: Path
    ) -> dict[str, Any]: ...

    def evaluate_workspace(
        self, workspace: Path, source_root: Path, mode: str
    ) -> dict[str, Any]: ...

    def git_commit(self, path: Path) -> str: ...


class AdapterContractError(ValueError):
    pass


@dataclass(frozen=True)
class AdapterDefinition:
    adapter_id: str
    module_name: str


@dataclass(frozen=True)
class LoadedAdapter:
    definition: AdapterDefinition
    module: ModuleType

    @property
    def adapter_id(self) -> str:
        return self.definition.adapter_id

    @property
    def module_name(self) -> str:
        return self.definition.module_name

    def manifest_contract(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "module": self.module_name,
            "benchmark_name": self.module.BENCHMARK_NAME,
            "task_id": self.module.TASK_ID,
            "artifact_name": self.module.ARTIFACT_NAME,
            "primary_metric": self.module.PRIMARY_METRIC,
            "direction": self.module.DIRECTION,
            "workspace_isolation": "one Git workspace per long-lived lane",
            "verification_owner": "benchmark controller",
        }


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise AdapterContractError(f"cannot read adapter registry {path}: {error}") from error
    if not isinstance(payload, dict):
        raise AdapterContractError("adapter registry must be a JSON object")
    return payload


def load_definitions(path: Path = DEFAULT_REGISTRY) -> dict[str, AdapterDefinition]:
    payload = _load_payload(path)
    if payload.get("schema_version") != 1:
        raise AdapterContractError("adapter registry schema_version must be 1")
    definitions: dict[str, AdapterDefinition] = {}
    entries = payload.get("adapters")
    if not isinstance(entries, list):
        raise AdapterContractError("adapter registry adapters must be a list")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise AdapterContractError(f"adapter entry {index} must be an object")
        adapter_id = entry.get("id")
        module_name = entry.get("module")
        if not isinstance(adapter_id, str) or SAFE_ID.fullmatch(adapter_id) is None:
            raise AdapterContractError(f"adapter entry {index} has unsafe id {adapter_id!r}")
        if not isinstance(module_name, str) or SAFE_MODULE.fullmatch(module_name) is None:
            raise AdapterContractError(
                f"adapter {adapter_id} has unsafe module {module_name!r}"
            )
        if adapter_id in definitions:
            raise AdapterContractError(f"duplicate adapter id: {adapter_id}")
        definitions[adapter_id] = AdapterDefinition(adapter_id, module_name)
    return definitions


def _validate_module(definition: AdapterDefinition, module: ModuleType) -> None:
    missing = [name for name in REQUIRED_CONSTANTS if not hasattr(module, name)]
    missing.extend(
        name
        for name in REQUIRED_CALLABLES
        if not callable(getattr(module, name, None))
    )
    if missing:
        raise AdapterContractError(
            f"adapter {definition.adapter_id} is missing: {', '.join(sorted(missing))}"
        )
    if module.DIRECTION not in {"minimize", "maximize"}:
        raise AdapterContractError(
            f"adapter {definition.adapter_id} has invalid direction {module.DIRECTION!r}"
        )
    if module.CODEX_SANDBOX not in {
        "read-only",
        "workspace-write",
        "danger-full-access",
    }:
        raise AdapterContractError(
            f"adapter {definition.adapter_id} has invalid Codex sandbox "
            f"{module.CODEX_SANDBOX!r}"
        )
    if not isinstance(module.VERIFIER_TIMEOUT_SECONDS, int) or module.VERIFIER_TIMEOUT_SECONDS < 1:
        raise AdapterContractError(
            f"adapter {definition.adapter_id} verifier timeout must be positive"
        )


def load_adapter(
    adapter_id: str,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
) -> LoadedAdapter:
    definitions = load_definitions(registry_path)
    try:
        definition = definitions[adapter_id]
    except KeyError as error:
        raise KeyError(
            f"unknown benchmark adapter {adapter_id!r}; "
            f"choose one of {', '.join(sorted(definitions))}"
        ) from error
    module = importlib.import_module(definition.module_name)
    _validate_module(definition, module)
    return LoadedAdapter(definition, module)


def adapter_modules(path: Path = DEFAULT_REGISTRY) -> dict[str, str]:
    return {
        adapter_id: definition.module_name
        for adapter_id, definition in load_definitions(path).items()
    }
