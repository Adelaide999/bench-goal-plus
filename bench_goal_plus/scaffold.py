"""Generate a no-overwrite benchmark integration skeleton."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import ContractError
from .paths import ROOT


SAFE_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
SAFE_MODULE = re.compile(r"[a-z_][a-z0-9_]*")
TEMPLATE_ROOT = ROOT / "benchmarks" / "templates"


def _render(template: str, *, benchmark_id: str, module: str) -> str:
    return template.replace("__BENCHMARK_ID__", benchmark_id).replace(
        "__MODULE__", module
    )


def scaffold_plan(
    *,
    benchmark_id: str,
    shape: str,
    module: str | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    if SAFE_ID.fullmatch(benchmark_id) is None:
        raise ContractError(f"unsafe benchmark id: {benchmark_id!r}")
    module = module or benchmark_id.replace("-", "_")
    if SAFE_MODULE.fullmatch(module) is None:
        raise ContractError(f"unsafe Python module name: {module!r}")
    if shape not in {"common", "native"}:
        raise ContractError("shape must be common or native")
    if shape == "common":
        files = {
            root / "adapters" / module / "__init__.py": "empty.py.tmpl",
            root / "adapters" / module / "adapter.py": "common-adapter.py.tmpl",
            root / "adapters" / module / "README.md": "common-README.md.tmpl",
            root / "tests" / f"test_{module}_adapter.py": "common-test.py.tmpl",
        }
        registration = {
            "task_adapter": {
                "id": benchmark_id,
                "module": f"adapters.{module}.adapter",
            },
            "runner": "common-matrix",
        }
    else:
        files = {
            root / "experiments" / benchmark_id / "experiment.py": (
                "native-experiment.py.tmpl"
            ),
            root / "experiments" / benchmark_id / "README.md": (
                "native-README.md.tmpl"
            ),
            root / "experiments" / benchmark_id / "profiles" / "smoke.json": (
                "native-profile.json.tmpl"
            ),
            root / "tests" / f"test_{module}_experiment.py": (
                "native-test.py.tmpl"
            ),
        }
        registration = {
            "runner": {
                "id": f"{benchmark_id}-native",
                "kind": "native-profile",
                "controller": f"experiments/{benchmark_id}/experiment.py",
                "evidence_filename": "campaign-summary.json",
                "supported_methods": ["plain-codex"],
            }
        }
    return {
        "benchmark_id": benchmark_id,
        "shape": shape,
        "module": module,
        "files": [
            {
                "path": str(path.relative_to(root)),
                "template": template,
            }
            for path, template in files.items()
        ],
        "registration_fragment": registration,
        "acceptance": [
            "catalog schema and unsupported-method rejection",
            "doctor",
            "prepare",
            "run",
            "status",
            "finalize with raw metric evidence",
        ],
        "_files": files,
    }


def scaffold_benchmark(
    *,
    benchmark_id: str,
    shape: str,
    module: str | None = None,
    root: Path = ROOT,
    write: bool = False,
) -> dict[str, Any]:
    plan = scaffold_plan(
        benchmark_id=benchmark_id,
        shape=shape,
        module=module,
        root=root,
    )
    files: dict[Path, str] = plan.pop("_files")
    conflicts = [path for path in files if path.exists()]
    if conflicts:
        rendered = ", ".join(str(path.relative_to(root)) for path in conflicts)
        raise ContractError(f"scaffold refuses to overwrite existing paths: {rendered}")
    if write:
        for path, template_name in files.items():
            template_path = TEMPLATE_ROOT / template_name
            if not template_path.is_file():
                raise ContractError(f"missing scaffold template: {template_path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                _render(
                    template_path.read_text(encoding="utf-8"),
                    benchmark_id=plan["benchmark_id"],
                    module=plan["module"],
                ),
                encoding="utf-8",
            )
    plan["written"] = write
    return plan
