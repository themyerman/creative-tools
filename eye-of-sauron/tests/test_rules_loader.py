"""Tests for external YAML rule-pack loader."""

import json
import tempfile
import unittest
from pathlib import Path

from eye_of_sauron import rules_loader


class RuleLoaderTests(unittest.TestCase):
    """Validate YAML rule-pack loading and validation."""

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
            (d / "pack.yaml").write_text(json.dumps(pack), encoding="utf-8")
            loaded, errors = rules_loader.load_rule_packs(d)
            self.assertFalse(errors)
            self.assertIn(".py", loaded["extensions"])

    def test_load_invalid_pack_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "bad.yaml").write_text('extensions:\n  - .py\n', encoding="utf-8")
            loaded, errors = rules_loader.load_rule_packs(d)
            self.assertEqual(loaded, {})
            self.assertTrue(errors)

    def test_load_multiple_packs_merges_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            pack1 = {
                "extensions": [".py"],
                "rule_set": {".py": {"specific": {}, "general": {"high": [], "medium": [], "low": []}}},
            }
            pack2 = {
                "extensions": [".go"],
                "rule_set": {".go": {"specific": {}, "general": {"high": [], "medium": [], "low": []}}},
            }
            (d / "a.yaml").write_text(json.dumps(pack1), encoding="utf-8")
            (d / "b.yaml").write_text(json.dumps(pack2), encoding="utf-8")
            loaded, errors = rules_loader.load_rule_packs(d)
            self.assertFalse(errors)
            self.assertIn(".py", loaded["extensions"])
            self.assertIn(".go", loaded["extensions"])


if __name__ == "__main__":
    unittest.main()
