"""Assurance (red-team) scenarios and stub runner."""

from ascp.assurance.runner import execute_assurance_run, execute_builtin_stub_run
from ascp.assurance.scenarios import SCENARIOS_BY_SUITE, list_suite_ids, scenarios_for_suite

__all__ = [
    "SCENARIOS_BY_SUITE",
    "execute_assurance_run",
    "execute_builtin_stub_run",
    "list_suite_ids",
    "scenarios_for_suite",
]
