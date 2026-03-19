# eye-of-sauron

Security-pattern scanner for legacy and modern codebases. It walks source files, matches YAML-defined (and legacy `conf`) rules, and reports in **text**, **JSON**, or **SARIF**. Optional **Semgrep** merges in as a second engine.

---

## Install

| How | Command |
|-----|---------|
| **Editable** (hack on code, get the CLI) | `pip install -e .` (from this directory; needs a recent **pip** / **setuptools**) |
| **Normal** | `pip install .` |
| **Dev deps file** | `pip install -r requirements-dev.txt` (PyYAML only; use with `python -m unittest` from checkout) |
| **No install** | `cd` here and use `python -m eye_of_sauron …` or `python checker.py …` |

After install, the CLI is **`eye-of-sauron`** (hyphen). Rule packs ship inside the **`eye_of_sauron`** package (`eye_of_sauron/rules/*.yaml`); override with `--rule-packs-dir` if you maintain a fork.

**Requirements:** Python **3.9+**, **PyYAML** (declared in `pyproject.toml`).

**Reliable installs:** upgrade packaging tools first (avoids old pip/`egg` issues):

```bash
python -m pip install -U pip setuptools wheel
pip install .          # or: pip install -e .
```

---

## Project layout

| Path | Role |
|------|------|
| `eye_of_sauron/checker.py` | CLI, scan engine, Semgrep hook, SARIF/punchlist |
| `eye_of_sauron/conf.py` | Legacy rule matrix (PHP/JS, etc.) merged with packs |
| `eye_of_sauron/rules_loader.py` | YAML pack loader + validation |
| `eye_of_sauron/rules/` | Shipped packs (`modern-core`, `secrets`, `tier2-languages`, `schema`) |
| `checker.py` (repo root) | Thin wrapper: `python checker.py` → same as the package CLI |
| `scripts/clean_local.sh` | Deletes `logs/`, `punchlist/`, build dirs, `eye-of-sauron-results.sarif`, `*.egg-info` |
| `tests/` | `unittest` suite |
| `LICENSE`, `CHANGELOG.md`, `RELEASING.md` | MIT license, release notes, release checklist |

---

## Quick start: scan any repository

From a checkout **or** after `pip install`, point **`-t`** at the repo root. By default the whole tree is scanned (empty `scan_folders` in `conf.py`).

```bash
# Examples (pick one entry style)
eye-of-sauron -t /path/to/repo -s high,medium
python3 -m eye_of_sauron -t /path/to/repo -s high,medium
python3 checker.py -t /path/to/repo -s high,medium   # only when cwd is this repo
```

**Useful knobs:**

| Goal | Flags |
|------|--------|
| Limit to subtrees whose path contains certain **folder names** (legacy) | `-f application,assets` |
| Broader built-in rules | `-s high,medium,low` |
| Machine-readable output | `--format json` or `--format sarif` |
| Write JSON/SARIF to a file (no stdout body for those formats) | `-o FILE` / `--output FILE` |
| CI pass/fail | `--fail-on high` (exit `1` if any finding ≥ that severity) |
| Markdown + SARIF bundle under the **target** repo | `--punchlist` → `TARGET/punchlist/scan-<ts>-<id>/` |
| Skip known noise | `--suppressions path/to.txt` |
| Known backlog | `--baseline baseline.json` / `--write-baseline` |
| Add Semgrep | `--use-semgrep` (+ install `semgrep` on PATH) |
| Logs | `--log-dir ./logs` (default **`logs`** relative to **current working directory**) |
| Full flag list | `-h` or **`--help`** (same for `python -m eye_of_sauron` / `python checker.py`) |

**Gotcha:** non-empty `-f` uses **path-part** matching (a directory segment must equal one of the names). If **zero files** are scanned, the tool prints a **warning** to stderr.

---

## CLI cheat sheet

```text
eye-of-sauron -t TOPDIR [-f FOLDERS] [-s LEVELS] [-i IGNORE] [-q] [-v]
  [--format text|json|sarif] [--fail-on high|medium|low|specific]
  [--profile default|web|backend|platform|full] [--scan-comments]
  [--suppressions FILE] [--baseline FILE] [--write-baseline FILE] [--punchlist]
  [--use-semgrep] [--semgrep-profile fast|balanced|strict] [--semgrep-config a,b]
  [--output FILE] [--log-dir DIR] [--max-findings N] [--exclude-dirs a,b] [--rule-packs-dir DIR]
```

Concrete examples:

- `eye-of-sauron -t . -s high,medium,low --suppressions suppressions-ci.txt --fail-on high`
- `eye-of-sauron -t ../myapp --format sarif --output results.sarif --fail-on medium`
- `eye-of-sauron -t . --punchlist` (writes punchlist under **`-t`**, not the scanner repo)

---

## Local artifacts & cleanup

Ignored by git (see `.gitignore`): **`logs/`**, **`punchlist/`**, **`*.sarif`**, **`eye-of-sauron-results.sarif`**, Python/build dirs (`build/`, `dist/`, `.eggs/`, `*.egg-info`), caches.

Remove them locally:

```bash
./scripts/clean_local.sh
```

---

## Plain-English behavior

- **Specific** rules: named files (e.g. `Dockerfile`, `settings.py`) with stricter expectations.
- **General** rules: line/regex checks per language (e.g. `eval`, weak TLS, secrets).
- **Baseline** = accepted known findings; **suppressions** = disable a rule for matching paths (`fnmatch` on the **absolute** file path).
- **Semgrep** is optional; rule IDs are prefixed with `SEMGREP::` when merged.

Exit codes: **`0`** clean vs `--fail-on`, **`1`** failing findings, **`2`** config/runtime errors.

---

## Development

```bash
python -m pip install -U pip setuptools wheel   # recommended before install
pip install -r requirements-dev.txt             # PyYAML only; run tests without installing
# or install the tool:
pip install .                                    # or: pip install -e .

python3 -m unittest discover -s tests -p 'test_*.py' -v
```

**Releases:** see **`RELEASING.md`** and **`CHANGELOG.md`**.

### CI (GitHub)

Workflow **`.github/workflows/eye-of-sauron.yml`**: upgrades pip/setuptools, **`pip install .`**, unit tests, SARIF written with `--output eye-of-sauron-results.sarif`, **upload to GitHub Code Scanning** (`upload-sarif`; fork PRs may skip upload), then a gate step with `--fail-on high` and `suppressions-ci.txt`.

---

## Semgrep

- Profiles: `fast` → `p/secrets`; `balanced` → `auto`; `strict` adds security-audit + OWASP packs.
- Override with `--semgrep-config a,b,c`.
- If the binary is missing, you get guidance in compile errors (exit `2` if that path breaks your policy).

---

## Punch list (v2)

With `--punchlist`, each run creates:

- `…/punchlist/scan-<timestamp>-<id>/punchlist.md` (checklist + link to SARIF)
- `…/punchlist/scan-<timestamp>-<id>/results.sarif`

---

## LLM-friendly rule fields (YAML packs)

`fix_recipe`, `safe_replacement`, `test_policy`, `autofix`, `docs_url`, `cwe`, etc. Prefer `autofix: review` when automation is uncertain.

---

## Suppressions file

One entry per line: `path_glob:rule_id` or `path_glob:*`.

Examples:

```text
*/vendor/*:*
*/migrations/*.py:PY_EVAL_EXEC
```

---

## Roadmap (ideas)

- AST-native checks for Python/TypeScript to cut regex false positives.
- Rule-pack CI split (validation vs performance).
- Richer metadata (`owner`, `review_date`, `precision`) and stale-rule reports.
- Policy mode (`--enforce`) and baseline drift.
