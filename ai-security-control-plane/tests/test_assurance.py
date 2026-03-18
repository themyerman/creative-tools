"""Built-in assurance scenarios and stub runner."""

from __future__ import annotations

import json

import pytest

from unittest.mock import MagicMock, patch

from ascp.assurance import execute_assurance_run, execute_builtin_stub_run, list_suite_ids, scenarios_for_suite
from ascp.core.types import new_run_id
from ascp.storage import AssuranceRunRecord, SqliteFsBackend


@pytest.fixture
def backend(tmp_path):
    return SqliteFsBackend(
        f"sqlite:///{tmp_path / 'd.db'}",
        artifact_root=tmp_path / "a",
    )


def test_list_suites():
    assert "builtin-v0" in list_suite_ids()


def test_scenarios_non_empty():
    assert len(scenarios_for_suite("builtin-v0")) >= 1


def test_stub_runner_writes_report(backend):
    tid = "tenant-x"
    rid = new_run_id()
    backend.create_run(
        AssuranceRunRecord(
            run_id=rid,
            tenant_id=tid,
            workspace_id="ws",
            status="created",
            metadata={"suite": "builtin-v0"},
        )
    )
    out = execute_builtin_stub_run(
        runs=backend,
        artifacts=backend,
        audit=backend,
        tenant_id=tid,
        run_id=rid,
    )
    assert out["status"] == "completed"
    assert out["scenario_count"] >= 1
    raw = backend.get_bytes(f"assurance/{rid}/report.json")
    assert raw is not None
    report = json.loads(raw.decode())
    assert report["run_id"] == rid
    assert len(report["results"]) == out["scenario_count"]

    rec = backend.get_run(rid)
    assert rec is not None
    assert rec.status == "completed"
    assert rec.metadata.get("runner") == "builtin-stub-v1"


def test_stub_runner_idempotent(backend):
    tid = "t1"
    rid = new_run_id()
    backend.create_run(
        AssuranceRunRecord(
            run_id=rid,
            tenant_id=tid,
            status="created",
            metadata={"suite": "builtin-v0"},
        )
    )
    execute_builtin_stub_run(
        runs=backend, artifacts=backend, audit=None, tenant_id=tid, run_id=rid
    )
    out2 = execute_builtin_stub_run(
        runs=backend, artifacts=backend, audit=None, tenant_id=tid, run_id=rid
    )
    assert out2.get("idempotent") is True


def test_unknown_suite_fails(backend):
    tid = "t1"
    rid = new_run_id()
    backend.create_run(
        AssuranceRunRecord(
            run_id=rid,
            tenant_id=tid,
            status="created",
            metadata={"suite": "no-such-suite"},
        )
    )
    with pytest.raises(ValueError, match="unknown or empty suite"):
        execute_builtin_stub_run(
            runs=backend, artifacts=backend, audit=None, tenant_id=tid, run_id=rid
        )
    rec = backend.get_run(rid)
    assert rec is not None
    assert rec.status == "failed"


def test_live_runner_posts_to_target(backend):
    tid = "t1"
    rid = new_run_id()
    backend.create_run(
        AssuranceRunRecord(
            run_id=rid,
            tenant_id=tid,
            status="created",
            metadata={
                "suite": "builtin-v0",
                "target_url": "https://staging.example/v1/chat",
            },
        )
    )
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "I'm sorry, I cannot help with that."
    resp.is_success = True
    with patch("ascp.assurance.runner.httpx.Client") as C:
        C.return_value.__enter__.return_value.post.return_value = resp
        out = execute_assurance_run(
            runs=backend,
            artifacts=backend,
            audit=None,
            tenant_id=tid,
            run_id=rid,
        )
    assert out["mode"] == "live"
    assert out["scenario_count"] >= 1
    rec = backend.get_run(rid)
    assert rec is not None
    assert rec.metadata.get("runner") == "assurance-live-v1"
    for row in rec.metadata["results"]:
        assert row.get("http_status") == 200
        assert row["heuristics"].get("possible_refusal") is True
