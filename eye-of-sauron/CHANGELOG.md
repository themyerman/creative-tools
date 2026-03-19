# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-03-19

### Added

- `-o` / `--output` to write JSON/SARIF reports to a file (CI-friendly body on stdout suppression for machine formats).
- `LICENSE` (MIT), `CHANGELOG.md`, `RELEASING.md`.
- GitHub Actions: upgrade pip/setuptools, generate SARIF, upload to Code Scanning, then enforce `--fail-on high`.
- `scripts/clean_local.sh` to remove local scanner/build artifacts.

### Changed

- `__version__` resolves from package metadata when installed; dev checkout uses `0.1.1.dev0`.
- Documentation: install/pip notes, CI SARIF, local cleanup.

