#!/usr/bin/env python3
"""
Seed demo-fragile, demo-mixed, demo-golden for the dashboard.

  ASCP_DATABASE_URL   same as API (e.g. sqlite:///./.ascp-dev.db)
  ASCP_ARTIFACT_ROOT  artifact dir

  PYTHONPATH=src python scripts/seed_demo_tenants.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ascp.config import Settings
from ascp.dev.demo_tenants import seed_demo_tenants
from ascp.storage.factory import create_backend


def main() -> int:
    settings = Settings()
    seed_demo_tenants(create_backend(settings))
    print("Seeded: demo-fragile (super weak), demo-mixed (partial), demo-golden (strong)")
    print(f"  DB: {settings.database_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
