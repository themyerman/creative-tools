"""Dashboard HTML routes."""

from ascp.api.app import create_app
from ascp.config import Settings
from fastapi.testclient import TestClient


def test_dashboard_open_when_no_api_key(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'd.db'}",
        artifact_root=str(tmp_path / "a"),
    )
    app = create_app(settings)
    with TestClient(app) as c:
        r = c.get("/dashboard")
    assert r.status_code == 200
    assert b"Tenants" in r.content


def test_dashboard_requires_basic_when_api_key_set(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'd2.db'}",
        artifact_root=str(tmp_path / "a2"),
        api_key="secret-dashboard-key",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        r = c.get("/dashboard")
    assert r.status_code == 401
    assert "Basic" in r.headers.get("www-authenticate", "")


def test_dashboard_basic_auth_ok(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'd3.db'}",
        artifact_root=str(tmp_path / "a3"),
        api_key="pw-dash",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        r = c.get("/dashboard", auth=("any", "pw-dash"))
    assert r.status_code == 200


def test_dashboard_tenant_page_lists_models(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'd4.db'}",
        artifact_root=str(tmp_path / "a4"),
    )
    app = create_app(settings)
    with TestClient(app) as c:
        c.put(
            "/v1/tenants/acme/policies/default/versions/v1",
            json={"schema_version": "1", "tools": {"mode": "open"}},
        )
        c.post("/v1/tenants/acme/models", json={"model_id": "gpt-4o"})
        r = c.get("/dashboard/tenant/acme")
    assert r.status_code == 200
    assert b"gpt-4o" in r.content
    assert b"open" in r.content
