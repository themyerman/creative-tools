# Releasing eye-of-sauron

## Version

1. Set the version in **`pyproject.toml`** (`[project].version`). That value is the release truth for wheels/sdists.
2. Optional: keep **`CHANGELOG.md`** `[Unreleased]` → new section with date.
3. From a git checkout without `pip install`, `eye_of_sauron.__version__` is **`0.0.0+local`** (not the released version).

## Tag (monorepo)

From the repo root (e.g. `python-stuff/`):

```bash
git tag -a eye-of-sauron-v0.1.1 -m "eye-of-sauron 0.1.1"
git push origin eye-of-sauron-v0.1.1
```

Adjust the tag pattern to match your org’s conventions.

## Verify before tagging

```bash
cd eye-of-sauron
python -m pip install -U pip setuptools wheel
pip install .
python3 -m unittest discover -s tests -p 'test_*.py' -v
eye-of-sauron --help
```

## Build artifacts (optional)

```bash
pip install build
python -m build
# dist/eye_of_sauron-*.whl and .tar.gz
```

## GitHub Code Scanning

The workflow uploads SARIF for the default branch and same-repo PRs. **Fork PRs** often cannot upload (token `security-events: read`); that is expected on GitHub.

## Clean local clutter

```bash
./scripts/clean_local.sh
```

Or see `.gitignore` for what is ignored (logs, punchlist, build outputs, CI SARIF filename).
