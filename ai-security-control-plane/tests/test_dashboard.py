"""Dashboard HTML routes."""

import re

from ascp.api.app import create_app
from ascp.api.dashboard_routes import compute_tenant_posture
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


def test_dashboard_home_shows_tenant_readiness_scores(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'dh.db'}",
        artifact_root=str(tmp_path / "ah"),
    )
    app = create_app(settings)
    with TestClient(app) as c:
        c.put(
            "/v1/tenants/weak/policies/default/versions/v1",
            json={"schema_version": "1", "tools": {"mode": "open"}},
        )
        c.put(
            "/v1/tenants/strong/policies/default/versions/v1",
            json={"schema_version": "1", "tools": {"mode": "open"}},
        )
        c.post("/v1/tenants/strong/models", json={"model_id": "gpt-4o"})
        c.post("/v1/tenants/strong/models", json={"model_id": "gpt-4o-mini"})
        r = c.get("/dashboard")
    assert r.status_code == 200
    assert b"/ 100" in r.content
    assert b"weak" in r.content and b"strong" in r.content
    m = re.search(rb'<ul class="tenants tenant-summary">(.*?)</ul>', r.content, re.DOTALL)
    assert m
    ul = m.group(1)
    tenants_order = re.findall(rb'<a href="/dashboard/tenant/[^"]+">([^<]+)</a>', ul)
    assert tenants_order == [b"weak", b"strong"]


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


def test_posture_scores_empty_vs_strong():
    empty = compute_tenant_posture(
        models=[],
        policy=None,
        runs=[],
        lockfile_count=0,
        audit_rows=[],
    )
    assert empty["overall_band"] == "gap"
    assert empty["overall"] < 55
    assert len(empty["dimensions"]) == 5

    strong = compute_tenant_posture(
        models=["gpt-4o"],
        policy={"tools": {"mode": "allowlist", "allowed": ["x"]}},
        runs=[{"status": "completed", "ci_passed": True, "score": 1.0}],
        lockfile_count=2,
        audit_rows=[{"summary": "FORWARDED model=gpt-4o"}],
    )
    assert strong["overall"] >= 78
    assert strong["overall_band"] == "strong"


def test_tenant_dashboard_includes_posture(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'dp.db'}",
        artifact_root=str(tmp_path / "ap"),
    )
    app = create_app(settings)
    with TestClient(app) as c:
        c.put(
            "/v1/tenants/z/policies/default/versions/v1",
            json={"schema_version": "1", "tools": {"mode": "open"}},
        )
        r = c.get("/dashboard/tenant/z")
    assert r.status_code == 200
    assert b"Pillar scores" in r.content
    assert b"/ 100" in r.content
