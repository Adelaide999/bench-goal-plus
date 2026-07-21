from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("status", ROOT / "scripts/status.py")
assert SPEC and SPEC.loader
STATUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATUS)


class RegistryTest(unittest.TestCase):
    def test_registry_is_valid(self) -> None:
        self.assertEqual(STATUS.validate(STATUS.load_registry()), [])


if __name__ == "__main__":
    unittest.main()

