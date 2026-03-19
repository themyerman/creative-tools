"""Unit tests for eye-of-sauron rule configuration."""

import importlib.util
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CONF_PATH = BASE_DIR / "eye_of_sauron" / "conf.py"

spec = importlib.util.spec_from_file_location("eye_of_sauron_conf_mod", CONF_PATH)
eye_conf_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eye_conf_mod)


class EyeConfigTests(unittest.TestCase):
    """Validate baseline config structure for scanner rules."""

    def test_extensions_exist(self):
        self.assertIn(".php", eye_conf_mod.rules["extensions"])
        self.assertIn(".js", eye_conf_mod.rules["extensions"])

    def test_rule_set_matches_extensions(self):
        for ext in eye_conf_mod.rules["extensions"]:
            self.assertIn(ext, eye_conf_mod.rules["rule_set"])

    def test_scan_levels_non_empty(self):
        self.assertTrue(eye_conf_mod.rules["scan_level"])


if __name__ == "__main__":
    unittest.main()
