# eye-of-sauron

Security-pattern scanner for legacy and modern codebases.

## What is here

- `checker.py`: command-line scanner that walks configured folders and reports matching rule violations.
- `conf.py`: rule definitions grouped by extension and severity (`high`, `medium`, `low`), plus specific-file checks.
- `rules/`: external YAML rule packs (`modern-core.yaml`, `secrets.yaml`, `tier2-languages.yaml`) plus `schema.yaml`.
- `rules_loader.py`: YAML rule-pack loader with lightweight schema validation.

## Plain-English overview

- Think of `eye-of-sauron` as a spell-checker for risky code patterns.
- It scans your code files, looks for known bad/suspicious patterns, and prints a report.
- It does not change your code; it only reads files and reports what it finds.
- You can run it in simple text mode for humans or JSON/SARIF mode for tools and CI.
- You can tell it what to scan (folders, language profile) and how strict to be (`--fail-on`).
- It writes a run log into `logs/` with a unique file name every time.

### Specific vs General rules (simple version)

- `specific` rules are for known files (example: `settings.py`, `Dockerfile`) where you want strict policy checks.
- `general` rules are broad pattern checks for all files of a language (example: `eval(...)`, `verify=False`, hardcoded keys).
- Use `specific` when you care about one file's expected settings.
- Use `general` when you want broad coverage across the codebase.

### Baseline and suppressions (simple version)

- `baseline` = "known existing findings we accept for now."
- `suppressions` = "skip this rule for this path."
- This helps you adopt scanning without blocking everything on day one.
- Over time, reduce baseline/suppressions as code gets cleaner.

### Semgrep profiles (simple version)

- `fast`: quick pass, mostly secrets-focused.
- `balanced`: good default for day-to-day scans.
- `strict`: deeper scan, more findings, best for security-focused CI runs.
- You can override profile configs directly with `--semgrep-config`.

## CLI usage

- `python3 checker.py -t /path/to/repo -f application,assets -s high,medium`
- `python3 checker.py -t /path/to/repo --format json --fail-on medium`
- `python3 checker.py -t /path/to/repo --max-findings 50 --exclude-dirs .git,node_modules`
- `python3 checker.py -t /path/to/repo --profile backend --format sarif`
- `python3 checker.py -t /path/to/repo --profile platform --format sarif`
- `python3 checker.py -t /path/to/repo --suppressions suppressions.txt --baseline baseline.json`
- `python3 checker.py -t /path/to/repo --suppressions suppressions-python-stuff-tests.txt`
- `python3 checker.py -t /path/to/repo --write-baseline baseline.json`
- `python3 checker.py -t /path/to/repo --rule-packs-dir ./rules --use-semgrep --semgrep-config auto`
- `python3 checker.py -t /path/to/repo --use-semgrep --semgrep-profile fast`
- `python3 checker.py -t /path/to/repo --use-semgrep --semgrep-profile strict`
- `python3 checker.py -t /path/to/repo --log-dir ./logs`

## Notes

- `checker.py` now supports:
  - text, JSON, and SARIF output
  - rule metadata (`id`, `description`, `remediation`, `tags`, `cwe`, `confidence`)
  - baseline filtering and suppression files
  - external YAML rule packs (validated at load time)
  - optional Semgrep integration (`--use-semgrep`)
  - profile-based extension filtering (`default`, `web`, `backend`, `platform`, `full`)
- Regex rules are compiled once at startup with validation errors surfaced before scan completion.
- Path filtering uses path-part matching and supports explicit exclude directories.
- Modern languages covered in YAML rule packs include Python, TypeScript/TSX, Java, Go, Ruby, Shell, YAML, and Terraform.
- Additional tier-2 languages via rule packs include Rust, C#, Kotlin, Swift, Scala, SQL, and Dockerfile.
- New detection categories include hardcoded secrets, injection sinks, unsafe deserialization patterns, insecure TLS settings, and risky shell usage.
- Exit codes:
  - `0`: no findings at/above `--fail-on`
  - `1`: findings at/above `--fail-on`
  - `2`: config/runtime errors (invalid regex, unreadable files, etc.)
- Unit tests live in `tests/test_eye_conf.py` and `tests/test_checker.py`.

## Semgrep

- Semgrep is optional and additive; `eye-of-sauron` still works without it.
- When enabled, Semgrep findings are merged into output with `SEMGREP::` prefixed rule IDs.
- If Semgrep is not installed, scanner reports a config/runtime error with guidance.
- Built-in Semgrep profiles:
  - `fast`: `p/secrets`
  - `balanced`: `auto`
  - `strict`: `p/secrets`, `p/security-audit`, `p/owasp-top-ten`
- `--semgrep-config` overrides profile defaults; pass comma-separated config values.
- Every run writes a unique JSON log file to `logs/` by default (override with `--log-dir`).

## Next Steps

- Add AST-native checks for Python and TypeScript to reduce regex false positives on injection findings.
- Split rule-pack CI into validation + benchmark jobs (correctness and performance budgets).
- Add richer rule metadata governance (`owner`, `review_date`, `precision`) and stale-rule reporting.
- Add prebuilt Semgrep profiles (`strict`, `balanced`, `fast`) and map them to scanner profiles.
- Add GitHub Actions workflow to run scanner + Semgrep and upload SARIF automatically.
- Add policy mode (`--enforce`) with per-severity quality gates and baseline drift alerts.

## Suppressions file format

Plain text file with one rule per line:

- `path_glob:rule_id`
- `path_glob:*` (suppress all rules for matching files)

Example:

- `*/vendor/*:*`
- `*/migrations/*.py:PY_EVAL_EXEC`
