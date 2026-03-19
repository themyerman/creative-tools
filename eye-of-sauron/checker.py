#!/usr/bin/env python3
"""Scan configured folders/files for risky patterns."""

import argparse
import copy
import datetime
import fnmatch
import importlib.util
import json
import re
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

try:
    from conf import rules as DEFAULT_RULES
except ModuleNotFoundError:
    conf_path = Path(__file__).resolve().parent / "conf.py"
    spec = importlib.util.spec_from_file_location("eye_conf_runtime", conf_path)
    conf_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conf_module)
    DEFAULT_RULES = conf_module.rules
try:
    from rules_loader import load_rule_packs
except ModuleNotFoundError:
    rules_loader_path = Path(__file__).resolve().parent / "rules_loader.py"
    loader_spec = importlib.util.spec_from_file_location("eye_rules_loader_runtime", rules_loader_path)
    loader_module = importlib.util.module_from_spec(loader_spec)
    loader_spec.loader.exec_module(loader_module)
    load_rule_packs = loader_module.load_rule_packs

VALID_SEVERITIES = ("high", "medium", "low", "specific")
DEFAULT_EXCLUDE_DIRS = {".git", ".hg", ".svn", "node_modules", "vendor", "__pycache__"}
COMMENT_PREFIXES = {
    ".py": ("#",),
    ".php": ("#", "//", "/*", "*"),
    ".module": ("#", "//", "/*", "*"),
    ".inc": ("#", "//", "/*", "*"),
    ".js": ("//", "/*", "*"),
    ".ts": ("//", "/*", "*"),
    ".tsx": ("//", "/*", "*"),
    ".java": ("//", "/*", "*"),
    ".go": ("//", "/*", "*"),
    ".rb": ("#",),
    ".sh": ("#",),
    ".yml": ("#",),
    ".yaml": ("#",),
    ".tf": ("#", "//", "/*", "*"),
    ".rs": ("//", "/*", "*"),
    ".cs": ("//", "/*", "*"),
    ".kt": ("//", "/*", "*"),
    ".swift": ("//", "/*", "*"),
    ".scala": ("//", "/*", "*"),
    ".sql": ("--", "/*", "*"),
    ".dockerfile": ("#",),
}
PROFILE_EXTENSIONS = {
    "default": None,
    "web": {".php", ".js", ".ts", ".tsx", ".module", ".inc"},
    "backend": {".py", ".go", ".java", ".rb", ".sh"},
    "platform": {".rs", ".cs", ".kt", ".swift", ".scala", ".sql", ".dockerfile"},
    "full": None,
}
SEMGREP_PROFILES = {
    "fast": ["p/secrets"],
    "balanced": ["auto"],
    "strict": ["p/secrets", "p/security-audit", "p/owasp-top-ten"],
}


@dataclass
class Finding:
    """Structured output for one rule match."""

    file: str
    line: int
    severity: str
    rule_id: str
    pattern: str
    snippet: str
    message: str = ""
    description: str = ""
    remediation: str = ""
    fix_recipe: str = ""
    safe_replacement: str = ""
    test_policy: str = "review"
    autofix: str = "review"
    docs_url: str = ""
    tags: Optional[List[str]] = None
    cwe: str = ""
    confidence: str = "medium"


@dataclass
class ScanResult:
    """Aggregate scan result."""

    files_scanned: int
    findings: list[Finding]
    compile_errors: list[str]


def _csv_list(value):
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def parse_args(argv):
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Scan source code for risky patterns.")
    parser.add_argument("-t", "--topdir", default=DEFAULT_RULES.get("topdir", "."))
    parser.add_argument(
        "-f",
        "--folders",
        default=",".join(DEFAULT_RULES.get("scan_folders", [])),
        help="Comma-separated folder names to include (match on path part).",
    )
    parser.add_argument(
        "-s",
        "--scan-levels",
        default=",".join(DEFAULT_RULES.get("scan_level", ["high"])),
        help="Comma-separated severities: high,medium,low",
    )
    parser.add_argument(
        "-i",
        "--ignore",
        default=",".join(DEFAULT_RULES.get("ignore", [])),
        help="Comma-separated rule patterns to ignore.",
    )
    parser.add_argument("-q", "--quick", action="store_true", help="Scan only HIGH checks.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Include pass summary.")
    parser.add_argument(
        "--format",
        choices=("text", "json", "sarif"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--fail-on",
        choices=VALID_SEVERITIES,
        default="high",
        help="Exit non-zero if findings at or above this severity exist.",
    )
    parser.add_argument("--max-findings", type=int, default=0, help="Stop after N findings (0=all).")
    parser.add_argument(
        "--exclude-dirs",
        default=",".join(sorted(DEFAULT_EXCLUDE_DIRS)),
        help="Comma-separated directory names to skip while walking.",
    )
    parser.add_argument(
        "--scan-comments",
        action="store_true",
        help="Also scan comment-only lines.",
    )
    parser.add_argument(
        "--profile",
        choices=tuple(PROFILE_EXTENSIONS.keys()),
        default="default",
        help="Language profile filter.",
    )
    parser.add_argument(
        "--suppressions",
        default="",
        help="Path to suppression file with `path_glob:rule_id` entries.",
    )
    parser.add_argument(
        "--baseline",
        default="",
        help="Path to JSON baseline file used to suppress known findings.",
    )
    parser.add_argument(
        "--write-baseline",
        default="",
        help="Write baseline JSON to this file after scanning.",
    )
    parser.add_argument(
        "--rule-packs-dir",
        default=str(Path(__file__).resolve().parent / "rules"),
        help="Directory containing JSON rule packs.",
    )
    parser.add_argument(
        "--use-semgrep",
        action="store_true",
        help="Run Semgrep and merge findings (if semgrep CLI is available).",
    )
    parser.add_argument(
        "--semgrep-profile",
        choices=tuple(SEMGREP_PROFILES.keys()),
        default="balanced",
        help="Predefined Semgrep ruleset profile.",
    )
    parser.add_argument(
        "--semgrep-config",
        default="",
        help="Override Semgrep config(s); comma-separated values.",
    )
    parser.add_argument(
        "--log-dir",
        default=str(Path(__file__).resolve().parent / "logs"),
        help="Directory for per-run scanner logs.",
    )
    parser.add_argument(
        "--punchlist",
        action="store_true",
        help="Write markdown + SARIF under ./punchlist/<run-id>/ for this run.",
    )
    return parser.parse_args(argv)


def is_comment_or_blank(line, extension):
    """Return True if line is blank or starts with a known comment prefix."""
    stripped = line.strip()
    if not stripped:
        return True
    prefixes = COMMENT_PREFIXES.get(extension, ("#", "//", "/*", "*"))
    return any(stripped.startswith(prefix) for prefix in prefixes)


def _rule_entry_to_payload(entry):
    """Normalize rule entry from legacy string or metadata dict."""
    if isinstance(entry, str):
        return {
            "id": entry,
            "pattern": entry,
            "description": "",
            "remediation": "",
            "fix_recipe": "",
            "safe_replacement": "",
            "test_policy": "review",
            "autofix": "review",
            "docs_url": "",
            "tags": [],
            "cwe": "",
            "confidence": "medium",
        }
    if isinstance(entry, dict):
        return {
            "id": entry.get("id", entry.get("pattern", "unnamed-rule")),
            "pattern": entry.get("pattern", ""),
            "description": entry.get("description", ""),
            "remediation": entry.get("remediation", ""),
            "fix_recipe": entry.get("fix_recipe", ""),
            "safe_replacement": entry.get("safe_replacement", ""),
            "test_policy": entry.get("test_policy", "review"),
            "autofix": entry.get("autofix", "review"),
            "docs_url": entry.get("docs_url", ""),
            "tags": entry.get("tags", []),
            "cwe": entry.get("cwe", ""),
            "confidence": entry.get("confidence", "medium"),
        }
    raise TypeError(f"Unsupported rule entry type: {type(entry)}")


def _compile_rules(rule_map, active_levels, ignored_patterns):
    """Compile generic/specific regex rules once."""
    generic = {}
    specific = {}
    errors = []
    for extension, ext_rules in rule_map.items():
        generic[extension] = []
        specific[extension] = {}

        for severity, patterns in ext_rules.get("general", {}).items():
            if severity not in active_levels:
                continue
            for entry in patterns:
                payload = _rule_entry_to_payload(entry)
                pattern = payload["pattern"]
                rule_id = payload["id"]
                if not pattern:
                    errors.append(f"[{extension}:{severity}] empty regex for rule `{rule_id}`")
                    continue
                if pattern in ignored_patterns or rule_id in ignored_patterns:
                    continue
                try:
                    compiled = re.compile(pattern, re.IGNORECASE)
                except re.error as exc:
                    errors.append(f"[{extension}:{severity}] invalid regex `{pattern}`: {exc}")
                    continue
                generic[extension].append((severity, payload, compiled))

        for filename, checks in ext_rules.get("specific", {}).items():
            compiled_checks = []
            for rule_id, rule_def in checks.items():
                for pattern, expected in rule_def.items():
                    try:
                        compiled = re.compile(pattern, re.IGNORECASE)
                    except re.error as exc:
                        errors.append(
                            f"[{extension}:{filename}:{rule_id}] invalid regex `{pattern}`: {exc}"
                        )
                        continue
                    compiled_checks.append((rule_id, pattern, expected, compiled))
            specific[extension][filename] = compiled_checks
    return generic, specific, errors


def _iter_target_files(topdir, include_folders, valid_extensions, exclude_dirs):
    """Yield file paths filtered by extension and included folder names."""
    base = Path(topdir).resolve()
    include_set = set(include_folders)
    exclude_set = set(exclude_dirs)

    for root, dirs, files in os_walk(base):
        dirs[:] = [d for d in dirs if d not in exclude_set]
        root_path = Path(root)
        if include_set:
            root_parts = set(root_path.parts)
            if not (include_set & root_parts):
                continue
        for filename in files:
            extension = _detect_file_key(filename)
            if extension in valid_extensions:
                yield root_path / filename


def _detect_file_key(filename):
    """Map file name to extension key used by rule config."""
    lower = filename.lower()
    if lower == "dockerfile":
        return ".dockerfile"
    return Path(filename).suffix.lower()


def os_walk(path):
    """Wrapper for os.walk to simplify testing/mocking."""
    import os

    return os.walk(path)


def merge_rule_configs(base_rules, modern_rules):
    """Merge legacy and modern rule sets."""
    merged = copy.deepcopy(base_rules)
    for ext in modern_rules.get("extensions", []):
        if ext not in merged["extensions"]:
            merged["extensions"].append(ext)
    for ext, ext_rules in modern_rules.get("rule_set", {}).items():
        if ext not in merged["rule_set"]:
            merged["rule_set"][ext] = {"specific": {}, "general": {"high": [], "medium": [], "low": []}}
        for severity in ("high", "medium", "low"):
            merged["rule_set"][ext]["general"].setdefault(severity, [])
            merged["rule_set"][ext]["general"][severity].extend(ext_rules.get("general", {}).get(severity, []))
        merged["rule_set"][ext]["specific"].update(ext_rules.get("specific", {}))
    return merged


def _finding_fingerprint(finding):
    return f"{finding.file}:{finding.line}:{finding.severity}:{finding.rule_id}"


def _finding_id(finding):
    """Stable short identifier for tracking a finding across runs."""
    import hashlib

    raw = _finding_fingerprint(finding).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def load_baseline(path):
    """Load baseline fingerprints from JSON file."""
    if not path:
        return set(), []
    p = Path(path)
    if not p.exists():
        return set(), [f"Baseline file not found: {p}"]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return set(), [f"Unable to parse baseline file {p}: {exc}"]
    fingerprints = set(data.get("fingerprints", []))
    return fingerprints, []


def write_baseline(path, findings):
    """Write baseline fingerprints JSON."""
    payload = {
        "fingerprints": sorted({_finding_fingerprint(item) for item in findings}),
        "count": len(findings),
        "version": 1,
    }
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_suppressions(path):
    """Load suppression file entries in `path_glob:rule_id` format."""
    if not path:
        return [], []
    p = Path(path)
    if not p.exists():
        return [], [f"Suppressions file not found: {p}"]
    suppressions = []
    errors = []
    for idx, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            errors.append(f"Invalid suppression entry at line {idx}: `{line}`")
            continue
        file_glob, rule_id = line.split(":", 1)
        suppressions.append((file_glob.strip(), rule_id.strip()))
    return suppressions, errors


def is_suppressed(finding, suppressions):
    """Return True if finding matches suppression rule."""
    for file_glob, rule_id in suppressions:
        if fnmatch.fnmatch(finding.file, file_glob) and (rule_id == "*" or rule_id == finding.rule_id):
            return True
    return False


def scan_with_rules(
    rule_config,
    topdir,
    include_folders,
    active_levels,
    ignored_patterns,
    exclude_dirs,
    scan_comments=False,
    max_findings=0,
    allowed_extensions=None,
):
    """Execute scanner and return structured findings."""
    rule_set = rule_config["rule_set"]
    extensions = set(rule_config["extensions"])
    compiled_generic, compiled_specific, compile_errors = _compile_rules(
        rule_set,
        set(active_levels),
        set(ignored_patterns),
    )

    findings = []
    files_scanned = 0
    if allowed_extensions:
        extensions = extensions & set(allowed_extensions)
    for file_path in _iter_target_files(topdir, include_folders, extensions, exclude_dirs):
        files_scanned += 1
        extension = _detect_file_key(file_path.name)
        file_specific = compiled_specific.get(extension, {}).get(file_path.name, [])
        file_generic = compiled_generic.get(extension, [])
        try:
            with file_path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not scan_comments and is_comment_or_blank(line, extension):
                        continue
                    for rule_id, pattern, expected, regex in file_specific:
                        if regex.search(line):
                            findings.append(
                                Finding(
                                    file=str(file_path),
                                    line=line_number,
                                    severity="specific",
                                    rule_id=rule_id,
                                    pattern=pattern,
                                    snippet=line[:140].strip(),
                                    message=f"FAIL! should be {expected}",
                                )
                            )
                    for severity, payload, regex in file_generic:
                        if regex.search(line):
                            findings.append(
                                Finding(
                                    file=str(file_path),
                                    line=line_number,
                                    severity=severity,
                                    rule_id=payload["id"],
                                    pattern=payload["pattern"],
                                    snippet=line[:140].strip(),
                                    description=payload["description"],
                                    remediation=payload["remediation"],
                                    fix_recipe=payload["fix_recipe"],
                                    safe_replacement=payload["safe_replacement"],
                                    test_policy=payload["test_policy"],
                                    autofix=payload["autofix"],
                                    docs_url=payload["docs_url"],
                                    tags=payload["tags"],
                                    cwe=payload["cwe"],
                                    confidence=payload["confidence"],
                                )
                            )
                    if max_findings and len(findings) >= max_findings:
                        return ScanResult(files_scanned, findings, compile_errors)
        except OSError as exc:
            compile_errors.append(f"Unable to read {file_path}: {exc}")
    return ScanResult(files_scanned, findings, compile_errors)


def severity_rank(severity):
    order = {"low": 1, "medium": 2, "high": 3, "specific": 4}
    return order.get(severity, 0)


def has_failing_findings(findings, fail_on):
    """Return True if any finding meets/exceeds fail_on severity."""
    threshold = severity_rank(fail_on)
    return any(severity_rank(item.severity) >= threshold for item in findings)


def render_text(result, show_ok=False):
    """Render text output compatible with terminal usage."""
    lines = [
        "=====================================================",
        "==         EYE OF SAURON                           ==",
        '==       "the eye sees all"                        ==',
        "=====================================================",
        "",
    ]
    if result.compile_errors:
        lines.append("CONFIG/RUNTIME ERRORS:")
        lines.extend(f"- {err}" for err in result.compile_errors)
        lines.append("")

    if not result.findings:
        lines.append("No findings.")
    else:
        for item in result.findings:
            if item.message:
                lines.append(
                    f"[{item.severity.upper()}]\t{item.file}:{item.line}\t{item.rule_id}\t{item.message}"
                )
            else:
                lines.append(
                    f"[{item.severity.upper()}]\t{item.file}:{item.line}\t{item.rule_id}\t{item.snippet}"
                )
    if show_ok:
        lines.append("")
        lines.append(f"Files scanned: {result.files_scanned}")
        lines.append(f"Findings: {len(result.findings)}")
    return "\n".join(lines)


def render_json(result):
    """Render machine-readable output."""
    payload = {
        "files_scanned": result.files_scanned,
        "findings_count": len(result.findings),
        "compile_errors": result.compile_errors,
        "findings": [asdict(item) for item in result.findings],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def render_sarif(result):
    """Render SARIF v2.1.0 output."""
    rules = {}
    sarif_results = []
    for item in result.findings:
        if item.rule_id not in rules:
            rules[item.rule_id] = {
                "id": item.rule_id,
                "name": item.rule_id,
                "shortDescription": {"text": item.description or item.rule_id},
                "fullDescription": {"text": item.remediation or item.description or item.rule_id},
            }
            if item.cwe:
                rules[item.rule_id]["properties"] = {"cwe": item.cwe, "tags": item.tags or []}
        sarif_results.append(
            {
                "ruleId": item.rule_id,
                "level": "error" if severity_rank(item.severity) >= 3 else "warning",
                "message": {"text": item.message or item.snippet or item.rule_id},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": item.file},
                            "region": {"startLine": item.line},
                        }
                    }
                ],
            }
        )
    payload = {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "eye-of-sauron",
                        "rules": list(rules.values()),
                    }
                },
                "results": sarif_results,
            }
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _sort_findings_for_punchlist(findings):
    """Sort findings by severity, file, then line."""
    return sorted(
        findings,
        key=lambda item: (-severity_rank(item.severity), item.file.lower(), item.line, item.rule_id),
    )


def render_punchlist_markdown(result, sarif_link_name=None):
    """Render findings as a developer-friendly markdown checklist (v2).

    If ``sarif_link_name`` is set (e.g. ``results.sarif``), a relative markdown
    link to that file is included in the header.
    """
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    severity_counts = {
        "high": sum(1 for x in result.findings if x.severity == "high"),
        "medium": sum(1 for x in result.findings if x.severity == "medium"),
        "low": sum(1 for x in result.findings if x.severity == "low"),
        "specific": sum(1 for x in result.findings if x.severity == "specific"),
    }
    autofix_counts = {
        "safe": sum(1 for x in result.findings if x.autofix == "safe"),
        "review": sum(1 for x in result.findings if x.autofix == "review"),
        "manual": sum(1 for x in result.findings if x.autofix == "manual"),
    }
    lines = [
        "# Eye of Sauron Punch List (v2)",
        "",
        f"Generated: `{ts}`",
        f"Files scanned: **{result.files_scanned}**",
        f"Findings: **{len(result.findings)}**",
    ]
    if sarif_link_name:
        lines.append(
            f"Machine-readable (SARIF): [{sarif_link_name}](./{sarif_link_name})"
        )
    lines.extend(
        [
            "",
            "## Summary",
            "",
        ]
    )
    lines.extend(
        [
            f"- Severity counts: high={severity_counts['high']}, medium={severity_counts['medium']}, low={severity_counts['low']}, specific={severity_counts['specific']}",
            f"- Autofix counts: safe={autofix_counts['safe']}, review={autofix_counts['review']}, manual={autofix_counts['manual']}",
            "- Suggested workflow: triage high -> assign owner -> open ticket -> track status",
            "",
        ]
    )
    if result.compile_errors:
        lines.extend(["## Scanner Warnings", ""])
        for err in result.compile_errors:
            lines.append(f"- {err}")
        lines.append("")

    if not result.findings:
        lines.extend(["## Action Items", "", "- [x] No findings."])
        return "\n".join(lines)

    buckets = {"high": [], "medium": [], "low": [], "specific": []}
    for item in _sort_findings_for_punchlist(result.findings):
        buckets.setdefault(item.severity, []).append(item)

    lines.append("## Action Items")
    lines.append("")
    for severity in ("high", "medium", "low", "specific"):
        group = buckets.get(severity, [])
        if not group:
            continue
        lines.append(f"### {severity.upper()} ({len(group)})")
        lines.append("")
        for item in group:
            finding_id = _finding_id(item)
            sla = "P1 (24h)" if item.severity in ("high", "specific") else "P2 (7d)" if item.severity == "medium" else "P3 (30d)"
            title = f"- [ ] `{item.file}:{item.line}` - `{item.rule_id}`"
            lines.append(title)
            lines.append(f"  - finding-id: `{finding_id}`")
            lines.append("  - status: `open`")
            lines.append("  - owner: `unassigned`")
            lines.append(f"  - sla: `{sla}`")
            if item.description:
                lines.append(f"  - why: {item.description}")
            if item.remediation:
                lines.append(f"  - fix: {item.remediation}")
            elif item.message:
                lines.append(f"  - fix: {item.message}")
            lines.append(f"  - autofix: {item.autofix}")
            lines.append(f"  - test-policy: {item.test_policy}")
            if item.fix_recipe:
                lines.append(f"  - recipe: {item.fix_recipe}")
            if item.safe_replacement:
                lines.append(f"  - safe-replacement: `{item.safe_replacement}`")
            if item.docs_url:
                lines.append(f"  - docs: {item.docs_url}")
            if item.cwe:
                lines.append(f"  - cwe: {item.cwe}")
            if item.snippet:
                lines.append(f"  - snippet: `{item.snippet}`")
            lines.append("")
    return "\n".join(lines)


def write_run_log(log_dir, args, result, rendered_output, output_format):
    """Write a per-run log file to disk with a unique name."""
    target_dir = Path(log_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    run_id = uuid.uuid4().hex[:12]
    log_path = target_dir / f"scan-{timestamp}-{run_id}.log"
    payload = {
        "timestamp_utc": timestamp,
        "run_id": run_id,
        "args": vars(args),
        "files_scanned": result.files_scanned,
        "findings_count": len(result.findings),
        "compile_errors_count": len(result.compile_errors),
        "output_format": output_format,
        "output": rendered_output,
    }
    log_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return log_path


PUNCHLIST_MD_NAME = "punchlist.md"
PUNCHLIST_SARIF_NAME = "results.sarif"


def write_punchlist_bundle(punchlist_dir, result):
    """Write markdown + SARIF punch list bundle under a per-run subfolder."""
    target_dir = Path(punchlist_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    run_id = uuid.uuid4().hex[:12]
    run_dir = target_dir / f"scan-{timestamp}-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    punchlist_path = run_dir / PUNCHLIST_MD_NAME
    sarif_path = run_dir / PUNCHLIST_SARIF_NAME
    markdown = render_punchlist_markdown(result, sarif_link_name=PUNCHLIST_SARIF_NAME)
    punchlist_path.write_text(markdown, encoding="utf-8")
    sarif_path.write_text(render_sarif(result), encoding="utf-8")
    return punchlist_path, sarif_path


def parse_semgrep_json_payload(payload_text):
    """Parse semgrep JSON output and convert to local findings."""
    try:
        payload = json.loads(payload_text)
    except Exception as exc:
        return [], [f"Unable to parse Semgrep output: {exc}"]
    results = payload.get("results", [])
    findings = []
    for item in results:
        path = item.get("path", "")
        start = item.get("start", {}) or {}
        extra = item.get("extra", {}) or {}
        severity = (extra.get("severity") or "WARNING").upper()
        mapped = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}.get(severity, "medium")
        rule_id = item.get("check_id", "SEMGREP_RULE")
        message = extra.get("message", "")
        lines = extra.get("lines", "") or ""
        metadata = extra.get("metadata", {}) or {}
        finding = Finding(
            file=str(path),
            line=int(start.get("line") or 1),
            severity=mapped,
            rule_id=f"SEMGREP::{rule_id}",
            pattern=rule_id,
            snippet=(lines.splitlines()[0] if lines else message)[:140],
            message=message,
            description=metadata.get("short_description", ""),
            remediation=metadata.get("fix", ""),
            tags=metadata.get("tags", []),
            cwe=str(metadata.get("cwe", "")),
            confidence="high",
        )
        findings.append(finding)
    return findings, []


def run_semgrep_scan(topdir, semgrep_config):
    """Run semgrep scan and return findings plus errors."""
    cmd = ["semgrep", "scan"]
    for conf in semgrep_config:
        cmd.extend(["--config", conf])
    cmd.extend(["--json", str(topdir)])
    try:
        result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    except FileNotFoundError:
        return [], ["Semgrep not found in PATH; install semgrep or run without --use-semgrep."]
    if result.returncode not in (0, 1):
        err = result.stderr.strip() or result.stdout.strip() or "Unknown semgrep failure"
        return [], [f"Semgrep scan failed: {err}"]
    findings, parse_errors = parse_semgrep_json_payload(result.stdout)
    return findings, parse_errors


def resolve_semgrep_configs(profile, semgrep_config):
    """Resolve effective Semgrep config list from profile/override."""
    if semgrep_config:
        return [item.strip() for item in semgrep_config.split(",") if item.strip()]
    return list(SEMGREP_PROFILES.get(profile, SEMGREP_PROFILES["balanced"]))


def main(argv=None):
    """CLI entrypoint."""
    args = parse_args(argv or sys.argv[1:])
    runtime_rules = copy.deepcopy(DEFAULT_RULES)
    pack_rules, pack_errors = load_rule_packs(args.rule_packs_dir)
    if pack_rules:
        runtime_rules = merge_rule_configs(runtime_rules, pack_rules)

    if args.quick:
        active_levels = ["high"]
    else:
        active_levels = [level.lower() for level in _csv_list(args.scan_levels)]
    active_levels = [level for level in active_levels if level in ("high", "medium", "low")]
    if not active_levels:
        active_levels = ["high"]

    include_folders = _csv_list(args.folders)
    ignored_patterns = _csv_list(args.ignore)
    exclude_dirs = _csv_list(args.exclude_dirs)
    allowed_extensions = PROFILE_EXTENSIONS.get(args.profile)
    suppressions, suppression_errors = load_suppressions(args.suppressions)
    baseline_fingerprints, baseline_errors = load_baseline(args.baseline)

    result = scan_with_rules(
        rule_config=runtime_rules,
        topdir=args.topdir,
        include_folders=include_folders,
        active_levels=active_levels,
        ignored_patterns=ignored_patterns,
        exclude_dirs=exclude_dirs,
        scan_comments=args.scan_comments,
        max_findings=max(0, args.max_findings),
        allowed_extensions=allowed_extensions,
    )
    if include_folders and result.files_scanned == 0:
        print(
            "Warning: no files were scanned. Non-empty --folders limits paths to directories "
            "whose path contains one of those folder names (path-part match). "
            "Use --folders \"\" to scan the whole tree, or adjust folder names.",
            file=sys.stderr,
        )
    result.compile_errors.extend(pack_errors + suppression_errors + baseline_errors)
    filtered_findings = []
    for finding in result.findings:
        if is_suppressed(finding, suppressions):
            continue
        if _finding_fingerprint(finding) in baseline_fingerprints:
            continue
        filtered_findings.append(finding)
    result.findings = filtered_findings

    if args.use_semgrep:
        semgrep_configs = resolve_semgrep_configs(args.semgrep_profile, args.semgrep_config)
        semgrep_findings, semgrep_errors = run_semgrep_scan(args.topdir, semgrep_configs)
        result.findings.extend(semgrep_findings)
        result.compile_errors.extend(semgrep_errors)

    if args.write_baseline:
        write_baseline(args.write_baseline, result.findings)

    if args.format == "json":
        rendered = render_json(result)
    elif args.format == "sarif":
        rendered = render_sarif(result)
    else:
        rendered = render_text(result, show_ok=args.verbose)
    print(rendered)

    log_path = write_run_log(args.log_dir, args, result, rendered, args.format)
    if args.punchlist:
        punchlist_path, punchlist_sarif_path = write_punchlist_bundle(
            Path(args.topdir).resolve() / "punchlist",
            result,
        )
    if args.format == "text":
        print(f"\nLog written: {log_path}")
        if args.punchlist:
            print(f"Punch list written: {punchlist_path}")
            print(f"Punch list SARIF: {punchlist_sarif_path}")

    if result.compile_errors:
        return 2
    if has_failing_findings(result.findings, args.fail_on):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
