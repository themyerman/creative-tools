"""Tests for external rule-pack loader."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
LOADER_PATH = BASE_DIR / "rules_loader.py"

spec = importlib.util.spec_from_file_location("eye_rules_loader_mod", LOADER_PATH)
rules_loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules_loader)


class RuleLoaderTests(unittest.TestCase):
    """Validate JSON rule-pack loading and validation."""

    def test_load_valid_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            pack = {
                "extensions": [".py"],
                "rule_set": {
                    ".py": {
                        "specific": {},
                        "general": {
                            "high": [{"id": "PY_EVAL", "pattern": r"\beval\("}],
                            "medium": [],
                            "low": []
                        }
                    }
                }
            }
            (d / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
            loaded, errors = rules_loader.load_rule_packs(d)
            self.assertFalse(errors)
            self.assertIn(".py", loaded["extensions"])

    def test_load_invalid_pack_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "bad.json").write_text('{"extensions": [".py"]}', encoding="utf-8")
            loaded, errors = rules_loader.load_rule_packs(d)
            self.assertEqual(loaded, {})
            self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
