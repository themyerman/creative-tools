"""Tests for eye-of-sauron checker scan engine and CLI behavior."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CHECKER_PATH = BASE_DIR / "checker.py"

spec = importlib.util.spec_from_file_location("eye_of_sauron_checker_mod", CHECKER_PATH)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def build_test_rules():
    """Create a minimal ruleset for deterministic tests."""
    return {
        "extensions": [".php"],
        "topdir": ".",
        "scan_level": ["high", "medium", "low"],
        "ignore": [],
        "scan_folders": ["application"],
        "print_ok": False,
        "rule_set": {
            ".php": {
                "specific": {
                    "config.php": {
                        "CHECK_TOKEN": {"token\\s*=\\s*'[^']*'": "TOKEN"}
                    }
                },
                "general": {
                    "high": [r"\$_GET"],
                    "medium": [r"mkdir\("],
                    "low": [],
                },
            }
        },
    }


class CheckerTests(unittest.TestCase):
    """Validate scanning and rendering behavior."""

    def test_scan_detects_general_and_specific(self):
        rules = build_test_rules()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "application"
            root.mkdir(parents=True)
            (root / "index.php").write_text("<?php\n $x = $_GET['id'];\n", encoding="utf-8")
            (root / "config.php").write_text("<?php\n $token = 'abc';\n", encoding="utf-8")

            result = checker.scan_with_rules(
                rule_config=rules,
                topdir=tmp,
                include_folders=["application"],
                active_levels=["high", "medium"],
                ignored_patterns=[],
                exclude_dirs=[],
                scan_comments=False,
                max_findings=0,
            )

            self.assertGreaterEqual(result.files_scanned, 2)
            severities = {f.severity for f in result.findings}
            self.assertIn("high", severities)
            self.assertIn("specific", severities)

    def test_ignore_pattern_suppresses_finding(self):
        rules = build_test_rules()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "application"
            root.mkdir(parents=True)
            (root / "index.php").write_text("<?php\n $x = $_GET['id'];\n", encoding="utf-8")

            result = checker.scan_with_rules(
                rule_config=rules,
                topdir=tmp,
                include_folders=["application"],
                active_levels=["high"],
                ignored_patterns=[r"\$_GET"],
                exclude_dirs=[],
                scan_comments=False,
                max_findings=0,
            )
            self.assertEqual(len(result.findings), 0)

    def test_json_output_shape(self):
        empty = checker.ScanResult(files_scanned=1, findings=[], compile_errors=[])
        payload = json.loads(checker.render_json(empty))
        self.assertEqual(payload["files_scanned"], 1)
        self.assertEqual(payload["findings_count"], 0)

    def test_exit_code_threshold(self):
        finding = checker.Finding(
            file="a.php",
            line=1,
            severity="medium",
            rule_id="mkdir\\(",
            pattern="mkdir\\(",
            snippet="mkdir($x);",
        )
        self.assertFalse(checker.has_failing_findings([finding], "high"))
        self.assertTrue(checker.has_failing_findings([finding], "medium"))

    def test_metadata_rule_entry_supported(self):
        rules = {
            "extensions": [".py"],
            "topdir": ".",
            "scan_level": ["high"],
            "ignore": [],
            "scan_folders": ["src"],
            "print_ok": False,
            "rule_set": {
                ".py": {
                    "specific": {},
                    "general": {
                        "high": [
                            {
                                "id": "PY_EVAL",
                                "pattern": r"\beval\(",
                                "description": "Avoid eval",
                                "remediation": "Use safer parsing",
                            }
                        ],
                        "medium": [],
                        "low": [],
                    },
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "src"
            root.mkdir(parents=True)
            (root / "app.py").write_text("result = eval('1+1')\n", encoding="utf-8")
            result = checker.scan_with_rules(
                rule_config=rules,
                topdir=tmp,
                include_folders=["src"],
                active_levels=["high"],
                ignored_patterns=[],
                exclude_dirs=[],
                scan_comments=False,
                max_findings=0,
            )
            self.assertEqual(len(result.findings), 1)
            self.assertEqual(result.findings[0].rule_id, "PY_EVAL")
            self.assertEqual(result.findings[0].description, "Avoid eval")

    def test_suppressions_and_baseline_helpers(self):
        finding = checker.Finding(
            file="/tmp/src/app.py",
            line=3,
            severity="high",
            rule_id="PY_EVAL",
            pattern=r"\beval\(",
            snippet="eval(user_input)",
        )
        suppressions = [("/tmp/src/*.py", "PY_EVAL")]
        self.assertTrue(checker.is_suppressed(finding, suppressions))

        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "baseline.json"
            checker.write_baseline(baseline, [finding])
            fingerprints, errors = checker.load_baseline(baseline)
            self.assertFalse(errors)
            self.assertIn(checker._finding_fingerprint(finding), fingerprints)

    def test_parse_semgrep_payload(self):
        payload = json.dumps(
            {
                "results": [
                    {
                        "check_id": "python.lang.security.audit.eval",
                        "path": "/tmp/src/app.py",
                        "start": {"line": 5},
                        "extra": {
                            "severity": "ERROR",
                            "message": "Avoid eval",
                            "lines": "eval(user_input)",
                            "metadata": {"tags": ["security"], "cwe": "CWE-95"},
                        },
                    }
                ]
            }
        )
        findings, errors = checker.parse_semgrep_json_payload(payload)
        self.assertFalse(errors)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "high")
        self.assertTrue(findings[0].rule_id.startswith("SEMGREP::"))


if __name__ == "__main__":
    unittest.main()
