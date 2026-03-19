#!/usr/bin/env bash
# Remove local scanner output and Python build artifacts (this repo).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

rm -rf logs punchlist build dist .eggs pip-wheel-metadata
rm -f eye-of-sauron-results.sarif

# Remove any *.egg-info at repo root (eye-of-sauron/)
find . -maxdepth 1 -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

echo "Cleaned under $ROOT (logs, punchlist, build outputs, egg-info, CI SARIF stub)."
