"""Project exact host Pi model metadata into isolated benchmark runtimes."""

import json
import os
from pathlib import Path
from typing import Any


def native_catalog_model(provider: str, model: str, api: str) -> dict[str, Any]:
    agent_dir = Path(os.environ.get("PI_CODING_AGENT_DIR", str(Path.home() / ".pi/agent")))
    catalog_path = agent_dir / "models-store.json"
    catalog = json.loads(catalog_path.read_text()) if catalog_path.is_file() else {}
    native = next((item for item in (catalog.get(provider) or {}).get("models", [])
                   if item.get("id") == model and item.get("api") == api), None)
    if native is None:
        raise ValueError(f"{provider} model {model!r} is absent from the host Pi catalog; refresh Pi models before launch")
    fields = {"id", "name", "reasoning", "input", "cost", "contextWindow",
              "maxTokens", "thinkingLevelMap", "compat"}
    return {key: value for key, value in native.items() if key in fields}
