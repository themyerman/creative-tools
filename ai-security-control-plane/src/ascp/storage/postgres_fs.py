"""PostgreSQL metadata + local filesystem artifacts (same ports as SQLite backend)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from ascp.core.types import AuditEvent, PolicyRef, RunId, TenantId
from ascp.storage.ports import AssuranceRunRecord


def _safe_artifact_key(key: str) -> str:
    if not key or ".." in key or key.startswith("/"):
        raise ValueError("invalid artifact key")
    if not re.match(r"^[a-zA-Z0-9._/-]+$", key):
        raise ValueError("artifact key must be alphanumeric path segments")
    return key


class PostgresFsBackend:
    def __init__(self, database_url: str, artifact_root: str | Path) -> None:
        self._url = database_url
        self._artifact_root = Path(artifact_root)
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        return psycopg.connect(self._url, row_factory=dict_row)

    def _init_schema(self) -> None:
        stmts = [
            """CREATE TABLE IF NOT EXISTS policies (
            tenant_id TEXT NOT NULL, policy_id TEXT NOT NULL, version TEXT NOT NULL,
            document_json TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY (tenant_id, policy_id, version))""",
            """CREATE TABLE IF NOT EXISTS trust_registry (
            tenant_id TEXT NOT NULL, model_id TEXT NOT NULL,
            metadata_json TEXT NOT NULL, registered_at TEXT NOT NULL,
            PRIMARY KEY (tenant_id, model_id))""",
            """CREATE TABLE IF NOT EXISTS audit_events (
            id BIGSERIAL PRIMARY KEY, event_json TEXT NOT NULL, occurred_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS assurance_runs (
            run_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, workspace_id TEXT,
            status TEXT NOT NULL, metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS tenant_api_keys (
            key_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, name TEXT NOT NULL,
            key_hash TEXT NOT NULL, created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS supply_lockfiles (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, filename TEXT NOT NULL,
            sha256_hex TEXT NOT NULL, size_bytes BIGINT NOT NULL, created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS rag_chunks (
            tenant_id TEXT NOT NULL, corpus_id TEXT NOT NULL, chunk_id TEXT NOT NULL,
            body TEXT NOT NULL, is_poison INT NOT NULL DEFAULT 0,
            PRIMARY KEY (tenant_id, corpus_id, chunk_id))""",
            "CREATE INDEX IF NOT EXISTS idx_audit_occurred ON audit_events(occurred_at)",
            "CREATE INDEX IF NOT EXISTS idx_supply_tenant ON supply_lockfiles(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_rag_corpus ON rag_chunks(tenant_id, corpus_id)",
        ]
        with self._connect() as conn:
            for s in stmts:
                conn.execute(s)
            conn.commit()

    def get_policy_document(self, ref: PolicyRef) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT document_json FROM policies WHERE tenant_id=%s AND policy_id=%s AND version=%s",
                (ref.tenant_id, ref.policy_id, ref.version),
            ).fetchone()
        if not row:
            return None
        return json.loads(row["document_json"])

    def put_policy_document(self, ref: PolicyRef, document: dict[str, Any]) -> None:
        now = datetime.now(UTC).isoformat()
        payload = json.dumps(document, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO policies (tenant_id, policy_id, version, document_json, created_at)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id, policy_id, version) DO UPDATE SET document_json = EXCLUDED.document_json
                """,
                (ref.tenant_id, ref.policy_id, ref.version, payload, now),
            )
            conn.commit()

    def list_policy_versions(self, tenant_id: TenantId, policy_id: str) -> list[PolicyRef]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT version FROM policies WHERE tenant_id=%s AND policy_id=%s ORDER BY created_at",
                (tenant_id, policy_id),
            ).fetchall()
        return [PolicyRef(tenant_id=tenant_id, policy_id=policy_id, version=r["version"]) for r in rows]

    def register_model(
        self, tenant_id: TenantId, model_id: str, *, metadata: dict[str, Any] | None = None
    ) -> None:
        meta = metadata or {}
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trust_registry (tenant_id, model_id, metadata_json, registered_at)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (tenant_id, model_id) DO UPDATE SET
                  metadata_json = EXCLUDED.metadata_json, registered_at = EXCLUDED.registered_at
                """,
                (tenant_id, model_id, json.dumps(meta, default=str), now),
            )
            conn.commit()

    def is_model_allowed(self, tenant_id: TenantId, model_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM trust_registry WHERE tenant_id=%s AND model_id=%s",
                (tenant_id, model_id),
            ).fetchone()
        return row is not None

    def list_models(self, tenant_id: TenantId) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT model_id FROM trust_registry WHERE tenant_id=%s ORDER BY model_id",
                (tenant_id,),
            ).fetchall()
        return [r["model_id"] for r in rows]

    def append(self, event: AuditEvent) -> None:
        self.append_batch([event])

    def append_batch(self, events: list[AuditEvent]) -> None:
        if not events:
            return
        rows = [
            (
                e.model_dump_json(),
                e.occurred_at.isoformat()
                if e.occurred_at.tzinfo
                else e.occurred_at.replace(tzinfo=UTC).isoformat(),
            )
            for e in events
        ]
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO audit_events (event_json, occurred_at) VALUES (%s,%s)", rows
                )
            conn.commit()
        self._maybe_forward_audit_webhook(events)

    def _maybe_forward_audit_webhook(self, events: list[AuditEvent]) -> None:
        import os

        url = os.environ.get("ASCP_AUDIT_WEBHOOK_URL")
        if not url:
            return
        try:
            import httpx

            httpx.post(url, json=[e.model_dump(mode="json") for e in events], timeout=5.0)
        except Exception:
            pass

    def put_bytes(self, key: str, data: bytes) -> str:
        sk = _safe_artifact_key(key)
        path = self._artifact_root / sk
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return sk

    def get_bytes(self, key: str) -> bytes | None:
        sk = _safe_artifact_key(key)
        path = self._artifact_root / sk
        if not path.is_file():
            return None
        return path.read_bytes()

    def create_run(self, record: AssuranceRunRecord) -> RunId:
        now = datetime.now(UTC).isoformat()
        meta = json.dumps(record.metadata, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO assurance_runs
                (run_id, tenant_id, workspace_id, status, metadata_json, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    record.run_id,
                    record.tenant_id,
                    record.workspace_id,
                    record.status,
                    meta,
                    now,
                    now,
                ),
            )
            conn.commit()
        return record.run_id

    def update_run(
        self,
        run_id: RunId,
        *,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT metadata_json, status FROM assurance_runs WHERE run_id=%s", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown run_id: {run_id}")
            current_meta = json.loads(row["metadata_json"])
            if metadata:
                current_meta = {**current_meta, **metadata}
            new_status = status if status is not None else row["status"]
            conn.execute(
                """
                UPDATE assurance_runs SET status=%s, metadata_json=%s, updated_at=%s WHERE run_id=%s
                """,
                (new_status, json.dumps(current_meta, default=str), now, run_id),
            )
            conn.commit()

    def get_run(self, run_id: RunId) -> AssuranceRunRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM assurance_runs WHERE run_id=%s", (run_id,)).fetchone()
        if row is None:
            return None
        return AssuranceRunRecord(
            run_id=row["run_id"],
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            status=row["status"],
            metadata=json.loads(row["metadata_json"]),
        )

    def list_runs(self, tenant_id: TenantId, *, limit: int = 100) -> list[AssuranceRunRecord]:
        lim = max(1, min(limit, 500))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, tenant_id, workspace_id, status, metadata_json
                FROM assurance_runs WHERE tenant_id=%s ORDER BY updated_at DESC LIMIT %s
                """,
                (tenant_id, lim),
            ).fetchall()
        return [
            AssuranceRunRecord(
                run_id=r["run_id"],
                tenant_id=r["tenant_id"],
                workspace_id=r["workspace_id"],
                status=r["status"],
                metadata=json.loads(r["metadata_json"]),
            )
            for r in rows
        ]

    # --- tenant API keys ---
    def create_tenant_api_key(self, tenant_id: str, name: str) -> dict[str, str]:
        import hashlib
        import secrets

        token = "ascp_ten_" + secrets.token_urlsafe(32)
        h = hashlib.sha256(token.encode()).hexdigest()
        kid = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tenant_api_keys (key_id, tenant_id, name, key_hash, created_at)
                VALUES (%s,%s,%s,%s,%s)
                """,
                (kid, tenant_id, name, h, now),
            )
            conn.commit()
        return {"key_id": kid, "token": token, "tenant_id": tenant_id, "name": name}

    def verify_tenant_api_token(self, token: str) -> str | None:
        import hashlib

        if not token or not token.startswith("ascp_ten_"):
            return None
        h = hashlib.sha256(token.encode()).hexdigest()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT tenant_id FROM tenant_api_keys WHERE key_hash=%s", (h,)
            ).fetchone()
        return row["tenant_id"] if row else None

    def list_tenant_api_key_ids(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key_id, name, created_at FROM tenant_api_keys WHERE tenant_id=%s ORDER BY created_at",
                (tenant_id,),
            ).fetchall()
        return [{"key_id": r["key_id"], "name": r["name"], "created_at": r["created_at"]} for r in rows]

    # --- supply chain ---
    def put_supply_lockfile(self, tenant_id: str, filename: str, content: bytes) -> dict[str, Any]:
        import hashlib

        sid = str(uuid.uuid4())
        sha = hashlib.sha256(content).hexdigest()
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO supply_lockfiles (id, tenant_id, filename, sha256_hex, size_bytes, created_at)
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                (sid, tenant_id, filename, sha, len(content), now),
            )
            conn.commit()
        key = f"supply/{tenant_id}/{sid}/{filename}"
        self.put_bytes(key, content)
        return {"id": sid, "sha256": sha, "filename": filename, "artifact_key": key}

    def list_known_tenant_ids(self, *, limit: int = 200) -> list[str]:
        lim = max(1, min(limit, 500))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tenant_id FROM (
                    SELECT DISTINCT tenant_id FROM assurance_runs
                    UNION SELECT DISTINCT tenant_id FROM trust_registry
                    UNION SELECT DISTINCT tenant_id FROM policies
                    UNION SELECT DISTINCT tenant_id FROM tenant_api_keys
                    UNION SELECT DISTINCT tenant_id FROM supply_lockfiles
                    UNION SELECT DISTINCT tenant_id FROM rag_chunks
                ) AS u ORDER BY tenant_id LIMIT %s
                """,
                (lim,),
            ).fetchall()
        return [str(r["tenant_id"]) for r in rows]

    def list_supply_lockfiles(self, tenant_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, filename, sha256_hex, size_bytes, created_at
                FROM supply_lockfiles WHERE tenant_id=%s ORDER BY created_at DESC LIMIT %s
                """,
                (tenant_id, min(limit, 200)),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- RAG lab ---
    def rag_set_corpus(
        self, tenant_id: str, corpus_id: str, chunks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM rag_chunks WHERE tenant_id=%s AND corpus_id=%s",
                (tenant_id, corpus_id),
            )
            for c in chunks:
                cid = str(c.get("chunk_id") or uuid.uuid4())
                body = str(c.get("text") or c.get("body") or "")
                poison = 1 if c.get("is_poison") or c.get("poison") else 0
                conn.execute(
                    """
                    INSERT INTO rag_chunks (tenant_id, corpus_id, chunk_id, body, is_poison)
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    (tenant_id, corpus_id, cid, body, poison),
                )
            conn.commit()
        return {"tenant_id": tenant_id, "corpus_id": corpus_id, "chunk_count": len(chunks)}

    def rag_evaluate_query(
        self, tenant_id: str, corpus_id: str, query: str, *, top_k: int = 5
    ) -> dict[str, Any]:
        q = (query or "").lower().strip()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT chunk_id, body, is_poison FROM rag_chunks WHERE tenant_id=%s AND corpus_id=%s",
                (tenant_id, corpus_id),
            ).fetchall()
        scored: list[tuple[int, dict[str, Any]]] = []
        for r in rows:
            body = r["body"]
            low = body.lower()
            score = sum(1 for w in q.split() if len(w) > 2 and w in low)
            scored.append((score, dict(r)))
        scored.sort(key=lambda x: -x[0])
        top = [x[1] for x in scored[: max(1, top_k)]]
        poison_hit = any(x["is_poison"] for x in top if x.get("is_poison"))
        return {
            "query": query,
            "corpus_id": corpus_id,
            "retrieved": top,
            "poison_in_top_k": bool(poison_hit),
            "top_k": len(top),
        }

    def export_audit_events_jsonl(
        self, tenant_id: str | None, *, limit: int = 5000, since_iso: str | None = None
    ) -> bytes:
        lim = max(1, min(limit, 50_000))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT event_json, occurred_at FROM audit_events ORDER BY id DESC LIMIT %s",
                (lim * 2,),
            ).fetchall()
        lines: list[str] = []
        for r in rows:
            try:
                ev = json.loads(r["event_json"])
                if tenant_id and ev.get("tenant_id") != tenant_id:
                    continue
                if since_iso and (r["occurred_at"] or "") < since_iso:
                    continue
                lines.append(r["event_json"])
                if len(lines) >= lim:
                    break
            except Exception:
                continue
        return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
