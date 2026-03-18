"""Seed three dashboard demo tenants: fragile (weak), mixed (partial), golden (strong)."""

from __future__ import annotations

from typing import Any

from ascp.core.types import AuditEvent, AuditEventType, PolicyRef
from ascp.storage.ports import AssuranceRunRecord


def _create_run_idempotent(b: Any, record: AssuranceRunRecord) -> None:
    try:
        b.create_run(record)
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return
        raise


def seed_demo_tenants(b: Any) -> None:
    """
    Idempotent enough for dev: (re)writes policies and models for demo-* tenants;
    appends lockfiles and creates fixed-id assurance runs (may duplicate lockfile rows on re-run).
    """
    # --- demo-fragile: only RAG row → no policy/models/runs/supply audit ---
    b.rag_set_corpus(
        "demo-fragile",
        "seed-corpus",
        [{"chunk_id": "seed-1", "text": "placeholder chunk for tenant discovery", "is_poison": 0}],
    )

    tid_m = "demo-mixed"
    b.put_policy_document(
        PolicyRef(tenant_id=tid_m, policy_id="default", version="v1"),
        {
            "schema_version": "1",
            "tools": {
                "mode": "allowlist",
                "allowed": ["search", "read_file"],
                "deny": ["execute_shell"],
                "on_violation": "block",
            },
        },
    )
    b.register_model(tid_m, "gpt-4o", metadata=None)
    b.put_supply_lockfile(tid_m, "requirements.txt", b"demo-mixed==1.0\n")
    _create_run_idempotent(
        b,
        AssuranceRunRecord(
            run_id="demo-mixed-assurance-1",
            tenant_id=tid_m,
            status="completed",
            metadata={
                "suite": "builtin-v0",
                "runner": "assurance-live-v1",
                "mode": "live",
                "scoring": {
                    "score": 0.5,
                    "passed_count": 2,
                    "total": 4,
                    "ci_passed": False,
                },
            },
        ),
    )
    b.append(
        AuditEvent(
            event_type=AuditEventType.POLICY_EVALUATION,
            tenant_id=tid_m,
            payload={"outcome": "ALLOW", "policy_id": "default"},
        )
    )

    tid_g = "demo-golden"
    b.put_policy_document(
        PolicyRef(tenant_id=tid_g, policy_id="default", version="v1"),
        {
            "schema_version": "1",
            "tools": {
                "mode": "allowlist",
                "allowed": ["search", "read_file", "calculator"],
                "deny": ["bash", "execute_shell"],
                "on_violation": "block",
            },
        },
    )
    b.register_model(tid_g, "gpt-4o", metadata={"env": "prod"})
    b.register_model(tid_g, "gpt-4o-mini", metadata={"env": "staging"})
    b.put_supply_lockfile(tid_g, "poetry.lock", b"# demo-golden lockfile snapshot\n")
    b.put_supply_lockfile(tid_g, "package-lock.json", b'{"lockfileVersion": 3}\n')
    _create_run_idempotent(
        b,
        AssuranceRunRecord(
            run_id="demo-golden-assurance-1",
            tenant_id=tid_g,
            status="completed",
            metadata={
                "suite": "builtin-v0",
                "runner": "assurance-live-v1",
                "mode": "live",
                "scoring": {
                    "score": 1.0,
                    "passed_count": 4,
                    "total": 4,
                    "ci_passed": True,
                },
            },
        ),
    )
    for _ in range(2):
        b.append(
            AuditEvent(
                event_type=AuditEventType.GATEWAY_REQUEST,
                tenant_id=tid_g,
                payload={"outcome": "FORWARDED", "model_id": "gpt-4o"},
            )
        )
    b.append(
        AuditEvent(
            event_type=AuditEventType.ASSURANCE_RUN,
            tenant_id=tid_g,
            payload={"action": "execute_live", "scoring": {"score": 1.0, "ci_passed": True}},
        )
    )
