from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ale_materialize", ROOT / "adapters/ale/materialize.py")
assert SPEC and SPEC.loader
MATERIALIZE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MATERIALIZE)


class AleMaterializeTest(unittest.TestCase):
    def test_bounds_known_legacy_optional_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            results = Path(temp_dir) / "results.json"
            results.write_text(
                json.dumps(
                    {
                        "repeated_sampling": {
                            "code": "int main() { while (walk.size() - 1 < MAX_L) { break; } }"
                        }
                    }
                )
            )
            code, provenance = MATERIALIZE.load_starter(results)
            self.assertIn("while (false && walk.size() - 1 < MAX_L)", code)
            self.assertIn("unbounded-loop-disabled", provenance)


if __name__ == "__main__":
    unittest.main()
