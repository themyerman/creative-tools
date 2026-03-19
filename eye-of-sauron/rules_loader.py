"""Load and validate external JSON rule packs."""

import json
from pathlib import Path

VALID_SEVERITIES = ("high", "medium", "low")


def _validate_rule_entry(entry, context):
    errors = []
    if isinstance(entry, str):
        return errors
    if not isinstance(entry, dict):
        return [f"{context}: rule must be string or object"]
    if not entry.get("pattern"):
        errors.append(f"{context}: object rule missing `pattern`")
    if "id" in entry and not isinstance(entry["id"], str):
        errors.append(f"{context}: `id` must be string")
    return errors


def _validate_pack(data, file_name):
    errors = []
    if not isinstance(data, dict):
        return [f"{file_name}: pack must be a JSON object"]
    if "extensions" not in data or not isinstance(data["extensions"], list):
        errors.append(f"{file_name}: missing or invalid `extensions` list")
    if "rule_set" not in data or not isinstance(data["rule_set"], dict):
        errors.append(f"{file_name}: missing or invalid `rule_set` object")
        return errors
    for ext, ext_rules in data["rule_set"].items():
        if not isinstance(ext_rules, dict):
            errors.append(f"{file_name}:{ext}: rule set must be object")
            continue
        general = ext_rules.get("general", {})
        if not isinstance(general, dict):
            errors.append(f"{file_name}:{ext}: `general` must be object")
            continue
        for sev in VALID_SEVERITIES:
            entries = general.get(sev, [])
            if not isinstance(entries, list):
                errors.append(f"{file_name}:{ext}:{sev}: must be list")
                continue
            for idx, entry in enumerate(entries):
                errors.extend(_validate_rule_entry(entry, f"{file_name}:{ext}:{sev}[{idx}]"))
    return errors


def _merge_packs(packs):
    merged = {"extensions": [], "rule_set": {}}
    for pack in packs:
        for ext in pack.get("extensions", []):
            if ext not in merged["extensions"]:
                merged["extensions"].append(ext)
        for ext, ext_rules in pack.get("rule_set", {}).items():
            merged["rule_set"].setdefault(ext, {"specific": {}, "general": {"high": [], "medium": [], "low": []}})
            for sev in VALID_SEVERITIES:
                merged["rule_set"][ext]["general"][sev].extend(ext_rules.get("general", {}).get(sev, []))
            merged["rule_set"][ext]["specific"].update(ext_rules.get("specific", {}))
    return merged


def load_rule_packs(rule_packs_dir):
    """Load all JSON packs from a directory."""
    path = Path(rule_packs_dir)
    if not path.exists():
        return {}, [f"Rule packs directory not found: {path}"]
    json_files = sorted(file for file in path.glob("*.json") if file.name != "schema.json")
    if not json_files:
        return {}, []

    packs = []
    errors = []
    for file_path in json_files:
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{file_path.name}: JSON parse error: {exc}")
            continue
        errors.extend(_validate_pack(data, file_path.name))
        packs.append(data)
    if errors:
        return {}, errors
    return _merge_packs(packs), []
