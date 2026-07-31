"""Validated catalog for benchmark datasets and experiment panels."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bench_artifacts import read_json


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "benchmarks/datasets.json"
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
DOMAINS = {"software", "security", "web", "optimization", "research"}
CLAIM_ROLES = {"primary", "confirmatory", "mechanism", "smoke_only", "audit_required"}
DOCKER_REQUIREMENTS = {"required", "not_required", "mixed", "unresolved"}
EXPERIMENT_STAGES = set(range(5))


class DatasetCatalogError(ValueError):
    pass


def load_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    try:
        catalog = read_json(path)
    except (OSError, ValueError) as error:
        raise DatasetCatalogError(f"cannot read dataset catalog {path}: {error}") from error
    if not isinstance(catalog, dict):
        raise DatasetCatalogError(f"dataset catalog must be a JSON object: {path}")
    return catalog


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if catalog.get("schema_version") != 1:
        errors.append("dataset catalog schema_version must be 1")
    panel_statuses = set(catalog.get("panel_status_values") or [])
    adapter_statuses = set(catalog.get("adapter_status_values") or [])
    if not panel_statuses:
        errors.append("dataset catalog must define panel_status_values")
    if not adapter_statuses:
        errors.append("dataset catalog must define adapter_status_values")

    datasets = catalog.get("datasets")
    if not isinstance(datasets, list):
        return [*errors, "dataset catalog datasets must be a list"]
    seen_dataset_ids: set[str] = set()
    for index, dataset in enumerate(datasets):
        if not isinstance(dataset, dict):
            errors.append(f"dataset entry {index} must be an object")
            continue
        dataset_id = dataset.get("id")
        label = dataset_id if isinstance(dataset_id, str) else f"entry {index}"
        if not isinstance(dataset_id, str) or SAFE_ID.fullmatch(dataset_id) is None:
            errors.append(f"{label}: invalid dataset id")
        elif dataset_id in seen_dataset_ids:
            errors.append(f"duplicate dataset id: {dataset_id}")
        else:
            seen_dataset_ids.add(dataset_id)
        if dataset.get("domain") not in DOMAINS:
            errors.append(f"{label}: invalid domain {dataset.get('domain')!r}")
        if dataset.get("claim_role") not in CLAIM_ROLES:
            errors.append(f"{label}: invalid claim_role {dataset.get('claim_role')!r}")
        task_count = dataset.get("task_count")
        if not isinstance(task_count, int) or isinstance(task_count, bool) or task_count < 1:
            errors.append(f"{label}: task_count must be a positive integer")

        stages = dataset.get("recommended_stages")
        if not isinstance(stages, list) or not stages:
            errors.append(f"{label}: recommended_stages must be a non-empty list")
        elif any(stage not in EXPERIMENT_STAGES for stage in stages):
            errors.append(f"{label}: recommended_stages must be within 0-4")
        elif len(stages) != len(set(stages)):
            errors.append(f"{label}: recommended_stages must be unique")

        source = dataset.get("source")
        if not isinstance(source, dict):
            errors.append(f"{label}: source must be an object")
            source = {}
        if not source.get("revision_policy"):
            errors.append(f"{label}: source.revision_policy is required")

        integration = dataset.get("integration")
        if not isinstance(integration, dict):
            errors.append(f"{label}: integration must be an object")
            integration = {}
        adapter_status = integration.get("adapter_status")
        if adapter_status not in adapter_statuses:
            errors.append(f"{label}: invalid adapter_status {adapter_status!r}")
        if adapter_status != "source_pending" and not (
            source.get("repository") or source.get("data")
        ):
            errors.append(f"{label}: cataloged datasets require a repository or data URL")

        environment = dataset.get("environment")
        if not isinstance(environment, dict):
            errors.append(f"{label}: environment must be an object")
            environment = {}
        if environment.get("docker_requirement") not in DOCKER_REQUIREMENTS:
            errors.append(
                f"{label}: invalid docker_requirement "
                f"{environment.get('docker_requirement')!r}"
            )

        panels = dataset.get("panels")
        if not isinstance(panels, list) or not panels:
            errors.append(f"{label}: panels must be a non-empty list")
            continue
        seen_panel_ids: set[str] = set()
        for panel_index, panel in enumerate(panels):
            if not isinstance(panel, dict):
                errors.append(f"{label}: panel {panel_index} must be an object")
                continue
            panel_id = panel.get("id")
            panel_label = f"{label}/{panel_id or panel_index}"
            if not isinstance(panel_id, str) or SAFE_ID.fullmatch(panel_id) is None:
                errors.append(f"{panel_label}: invalid panel id")
            elif panel_id in seen_panel_ids:
                errors.append(f"{label}: duplicate panel id {panel_id}")
            else:
                seen_panel_ids.add(panel_id)
            status = panel.get("status")
            if status not in panel_statuses:
                errors.append(f"{panel_label}: invalid panel status {status!r}")
            target_size = panel.get("target_size")
            if target_size is not None and (
                not isinstance(target_size, int)
                or isinstance(target_size, bool)
                or target_size < 1
                or (isinstance(task_count, int) and target_size > task_count)
            ):
                errors.append(f"{panel_label}: invalid target_size {target_size!r}")
            task_ids = panel.get("task_ids")
            if not isinstance(task_ids, list) or any(
                not isinstance(task_id, str) or not task_id for task_id in task_ids
            ):
                errors.append(f"{panel_label}: task_ids must be a list of strings")
                task_ids = []
            elif len(task_ids) != len(set(task_ids)):
                errors.append(f"{panel_label}: task_ids must be unique")
            if task_ids and target_size != len(task_ids):
                errors.append(
                    f"{panel_label}: target_size {target_size} does not match "
                    f"{len(task_ids)} task_ids"
                )
            if status == "frozen":
                if not isinstance(source.get("revision"), str) or not source["revision"]:
                    errors.append(f"{panel_label}: frozen panels require source.revision")
                if not task_ids:
                    errors.append(f"{panel_label}: frozen panels require explicit task_ids")
    return errors


def validated_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    catalog = load_catalog(path)
    errors = validate_catalog(catalog)
    if errors:
        raise DatasetCatalogError("; ".join(errors))
    return catalog


def list_datasets(
    *,
    domain: str | None = None,
    stage: int | None = None,
    adapter_status: str | None = None,
    path: Path = DEFAULT_CATALOG,
) -> list[dict[str, Any]]:
    datasets = validated_catalog(path)["datasets"]
    return [
        dataset
        for dataset in datasets
        if (domain is None or dataset["domain"] == domain)
        and (stage is None or stage in dataset["recommended_stages"])
        and (
            adapter_status is None
            or dataset["integration"]["adapter_status"] == adapter_status
        )
    ]


def resolve_dataset(dataset_id: str, path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    for dataset in list_datasets(path=path):
        if dataset["id"] == dataset_id:
            return dataset
    raise KeyError(f"unknown benchmark dataset: {dataset_id}")


def resolve_panel(
    dataset_id: str,
    panel_id: str,
    path: Path = DEFAULT_CATALOG,
) -> dict[str, Any]:
    dataset = resolve_dataset(dataset_id, path)
    for panel in dataset["panels"]:
        if panel["id"] == panel_id:
            return panel
    raise KeyError(f"unknown benchmark panel: {dataset_id}/{panel_id}")
