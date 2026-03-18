"""Demo tenant seed for dashboard posture spread."""

from ascp.api.dashboard_routes import _gather_tenant_dashboard_snapshot
from ascp.config import Settings
from ascp.dev.demo_tenants import seed_demo_tenants
from ascp.storage.factory import create_backend


def test_demo_tenants_fragile_mixed_golden_posture_order(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        artifact_root=str(tmp_path / "art"),
    )
    b = create_backend(settings)
    seed_demo_tenants(b)

    assert "demo-fragile" in b.list_known_tenant_ids()
    fragile = _gather_tenant_dashboard_snapshot(b, "demo-fragile")["posture"]["overall"]
    mixed = _gather_tenant_dashboard_snapshot(b, "demo-mixed")["posture"]["overall"]
    golden = _gather_tenant_dashboard_snapshot(b, "demo-golden")["posture"]["overall"]

    assert fragile < mixed < golden
    assert fragile < 35
    assert golden >= 78

    seed_demo_tenants(b)
