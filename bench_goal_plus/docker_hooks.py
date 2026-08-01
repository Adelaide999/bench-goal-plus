"""Optional adapter-owned Docker setup hooks for future benchmark integrations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from adapters.registry import load_adapter

from .catalog import Catalog, read_json
from .errors import ContractError
from .paths import ROOT, UPSTREAM_REGISTRY


HOOKS = {
    "inventory": "local_asset_inventory",
    "provision": "provision_environment",
    "doctor": "doctor_environment",
}


def upstream_root(upstream_key: str) -> Path:
    manifest = read_json(UPSTREAM_REGISTRY)
    entry = manifest.get("upstreams", {}).get(upstream_key)
    if not isinstance(entry, dict):
        raise ContractError(f"unknown upstream key: {upstream_key}")
    return ROOT / "third_party" / str(entry["checkout_dir"])


def invoke(
    action: str, target_id: str, *, profile: str | None = None
) -> dict[str, Any]:
    catalog = Catalog()
    try:
        target = catalog.targets[target_id]
    except KeyError as error:
        raise ContractError(f"unknown target: {target_id}") from error
    if target.docker.owner != "adapter" or target.adapter_id is None:
        raise ContractError(f"{target_id}: Docker is not adapter-owned")
    if action == "inventory" and not target.local_asset_inventory:
        raise ContractError(f"{target_id}: local asset inventory is not enabled")
    loaded = load_adapter(target.adapter_id)
    hook_name = HOOKS[action]
    hook = getattr(loaded.module, hook_name, None)
    if not callable(hook):
        raise ContractError(
            f"{target_id}: adapter Docker action {action} requires {hook_name}"
        )
    if action == "inventory" and not profile:
        raise ContractError(f"{target_id}: inventory requires --profile")
    key = str(loaded.module.UPSTREAM_KEY)
    result = (
        hook(upstream_root(key), profile)
        if action == "inventory"
        else hook(upstream_root(key))
    )
    if not isinstance(result, dict):
        raise ContractError(f"{target_id}: {hook_name} must return an object")
    return {"target": target_id, "action": action, **result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=tuple(HOOKS))
    parser.add_argument("--target", required=True)
    parser.add_argument("--profile")
    args = parser.parse_args(argv)
    print(
        json.dumps(
            invoke(args.action, args.target, profile=args.profile), indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
