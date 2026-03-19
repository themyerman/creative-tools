#!/usr/bin/env python3
"""
Backward-compatible entrypoint: ``python checker.py`` from this repo root.

Prefer:

- ``python -m eye_of_sauron`` (no install)
- ``eye-of-sauron`` after ``pip install -e .`` or ``pip install .``
"""

from eye_of_sauron.checker import main

if __name__ == "__main__":
    raise SystemExit(main())
