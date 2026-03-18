"""Operator API (requires fastapi)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")

from starlette.testclient import TestClient

from ascp.api.app import create_app
from ascp.config import Settings


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "api.db"
    art = tmp_path / "art"
    settings = Settings(
        database_url=f"sqlite:///{db}",
        artifact_root=str(art),
    )
    app = create_app(settings)
    with TestClient(app) as tc:
        yield tc


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_evaluate_flow(client):
    tid = "tenant-a"
    client.put(
        f"/v1/tenants/{tid}/policies/default/versions/v1",
        json={
            "schema_version": "1",
            "tools": {
                "mode": "allowlist",
                "allowed": ["search"],
                "deny": [],
                "on_violation": "block",
            },
        },
    )
    client.post(
        f"/v1/tenants/{tid}/models",
        json={"model_id": "gpt-4"},
    )

    ok = client.post(
        f"/v1/tenants/{tid}/evaluate",
        json={
            "policy_id": "default",
            "policy_version": "v1",
            "model_id": "gpt-4",
            "tools_invoked": ["search"],
            "audit": False,
        },
    )
    assert ok.status_code == 200
    assert ok.json()["outcome"] == "ALLOW"

    bad = client.post(
        f"/v1/tenants/{tid}/evaluate",
        json={
            "policy_id": "default",
            "policy_version": "v1",
            "model_id": "gpt-4",
            "tools_invoked": ["bash"],
            "audit": False,
        },
    )
    assert bad.json()["outcome"] == "BLOCK"

    unreg = client.post(
        f"/v1/tenants/{tid}/evaluate",
        json={
            "policy_id": "default",
            "policy_version": "v1",
            "model_id": "unknown",
            "tools_invoked": [],
            "audit": False,
        },
    )
    assert unreg.json()["outcome"] == "BLOCK"


@pytest.fixture
def client_authed(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'k.db'}",
        artifact_root=str(tmp_path / "ka"),
        api_key="test-secret-key",
    )
    app = create_app(settings)
    with TestClient(app) as tc:
        yield tc


def test_api_key_unauthorized(client_authed):
    r = client_authed.get("/v1/assurance/suites")
    assert r.status_code == 401
    ok = client_authed.get(
        "/v1/assurance/suites",
        headers={"Authorization": "Bearer test-secret-key"},
    )
    assert ok.status_code == 200
    ok2 = client_authed.get(
        "/v1/assurance/suites",
        headers={"X-ASCP-API-Key": "test-secret-key"},
    )
    assert ok2.status_code == 200


def test_api_key_health_unauthenticated(client_authed):
    assert client_authed.get("/health").status_code == 200


def test_assurance_runs_api(client):
    suites = client.get("/v1/assurance/suites").json()["suites"]
    assert "builtin-v0" in suites
    tid = "tenant-ar"
    cr = client.post(
        f"/v1/tenants/{tid}/assurance-runs",
        json={"suite": "builtin-v0", "workspace_id": "w1"},
    )
    assert cr.status_code == 200
    rid = cr.json()["run_id"]
    ex = client.post(f"/v1/tenants/{tid}/assurance-runs/{rid}/execute")
    assert ex.status_code == 200
    assert ex.json()["status"] == "completed"
    got = client.get(f"/v1/tenants/{tid}/assurance-runs/{rid}")
    assert got.json()["status"] == "completed"
    listed = client.get(f"/v1/tenants/{tid}/assurance-runs")
    assert any(r["run_id"] == rid for r in listed.json()["runs"])


@pytest.fixture
def client_upstream(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'up.db'}",
        artifact_root=str(tmp_path / "ua"),
        upstream_base_url="https://api.fake-openai.com/v1",
        upstream_api_key="sk-upstream",
    )
    app = create_app(settings)
    with TestClient(app) as tc:
        yield tc


def test_gateway_blocks_unregistered_model(client_upstream):
    tid = "tg1"
    client_upstream.put(
        f"/v1/tenants/{tid}/policies/default/versions/v1",
        json={"schema_version": "1", "tools": {"mode": "open"}},
    )
    r = client_upstream.post(
        f"/v1/tenants/{tid}/gateway/v1/chat/completions",
        json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 403
    assert r.json()["error"]["type"] == "policy_blocked"


def test_gateway_503_without_upstream(client):
    tid = "tg2"
    client.put(
        f"/v1/tenants/{tid}/policies/default/versions/v1",
        json={"schema_version": "1", "tools": {"mode": "open"}},
    )
    client.post(f"/v1/tenants/{tid}/models", json={"model_id": "gpt-4"})
    r = client.post(
        f"/v1/tenants/{tid}/gateway/v1/chat/completions",
        json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 503
    assert r.json()["error"]["type"] == "upstream_not_configured"


def test_gateway_forwards_when_upstream_configured(client_upstream):
    tid = "tg3"
    client_upstream.put(
        f"/v1/tenants/{tid}/policies/default/versions/v1",
        json={"schema_version": "1", "tools": {"mode": "open"}},
    )
    client_upstream.post(f"/v1/tenants/{tid}/models", json={"model_id": "gpt-4"})
    fake = (200, b'{"id":"x","choices":[]}', "application/json")
    with patch("ascp.api.app.forward_openai_chat_completions", return_value=fake):
        r = client_upstream.post(
            f"/v1/tenants/{tid}/gateway/v1/chat/completions?audit=false",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
    assert r.status_code == 200
    assert r.json()["choices"] == []


def test_assurance_live_via_api(client):
    tid = "live-t"
    cr = client.post(
        f"/v1/tenants/{tid}/assurance-runs",
        json={
            "suite": "builtin-v0",
            "metadata": {
                "target_url": "https://target.example/chat",
            },
        },
    )
    rid = cr.json()["run_id"]
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "ok"
    resp.is_success = True
    with patch("ascp.assurance.runner.httpx.Client") as C:
        C.return_value.__enter__.return_value.post.return_value = resp
        ex = client.post(f"/v1/tenants/{tid}/assurance-runs/{rid}/execute")
    assert ex.status_code == 200
    assert ex.json()["mode"] == "live"
