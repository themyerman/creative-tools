"""FastAPI operator API: policies, trust registry, evaluate, assurance runs."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from ascp.assurance import execute_assurance_run as run_assurance_pipeline, list_suite_ids
from ascp.config import Settings
from ascp.core.types import (
    AuditEvent,
    AuditEventType,
    DecisionOutcome,
    PolicyEvaluationContext,
    PolicyRef,
    new_run_id,
)
from ascp.gateway.openai_proxy import (
    evaluate_chat_completions_request,
    extract_tool_names_from_openai_body,
    forward_openai_chat_completions,
)
from ascp.policy import (
    ChainedPolicyEngine,
    DocumentPolicyEngine,
    TrustRegistryPolicyEngine,
)
from ascp.storage import AssuranceRunRecord
from ascp.api.dashboard_routes import register_dashboard
from ascp.storage.factory import create_backend


class EvaluateBody(BaseModel):
    policy_id: str = "default"
    policy_version: str = "v1"
    model_id: str | None = None
    tools_invoked: list[str] = Field(default_factory=list)
    workspace_id: str | None = None
    audit: bool = True


class RegisterModelBody(BaseModel):
    model_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateAssuranceRunBody(BaseModel):
    suite: str = "builtin-v0"
    workspace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PatchAssuranceRunBody(BaseModel):
    status: str | None = None
    metadata: dict[str, Any] | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.backend = create_backend(settings)
        app.state.settings = settings
        yield

    app = FastAPI(
        title="ASCP Operator API",
        description="AI Security Control Plane — policies, trust registry, evaluation, assurance",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next):
        import re

        path = (request.url.path.rstrip("/") or "/")
        if path == "/health":
            return await call_next(request)
        if path == "/dashboard" or path.startswith("/dashboard/"):
            return await call_next(request)
        st = request.app.state.settings
        admin_key = getattr(st, "api_key", None)
        b = request.app.state.backend
        auth = request.headers.get("authorization") or ""
        token: str | None = None
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        if not token:
            token = request.headers.get("x-ascp-api-key") or request.headers.get(
                "x-ascp-tenant-token"
            )

        if path.startswith("/v1/admin"):
            if not admin_key or token != admin_key:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Admin requires ASCP_API_KEY (Bearer or X-ASCP-API-Key)"},
                )
            request.state.ascp_admin = True
            return await call_next(request)

        if admin_key:
            if token == admin_key:
                request.state.ascp_admin = True
                return await call_next(request)
            tid = b.verify_tenant_api_token(token or "")
            if not tid:
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            m = re.match(r"/v1/tenants/([^/]+)/", request.url.path)
            if m and m.group(1) != tid:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Tenant API token is not valid for this tenant path"},
                )
            request.state.ascp_tenant_token_tid = tid
            return await call_next(request)

        if token and hasattr(b, "verify_tenant_api_token"):
            tid = b.verify_tenant_api_token(token)
            if tid:
                m = re.match(r"/v1/tenants/([^/]+)/", request.url.path)
                if m and m.group(1) != tid:
                    return JSONResponse(status_code=403, content={"detail": "Tenant mismatch"})
        return await call_next(request)

    def backend(request: Request) -> Any:
        return request.app.state.backend

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/assurance/suites")
    def assurance_suites() -> dict[str, list[str]]:
        return {"suites": list_suite_ids()}

    @app.put(
        "/v1/tenants/{tenant_id}/policies/{policy_id}/versions/{version}",
        status_code=204,
    )
    def put_policy(
        tenant_id: str,
        policy_id: str,
        version: str,
        document: dict[str, Any],
        request: Request,
    ) -> None:
        b = backend(request)
        ref = PolicyRef(tenant_id=tenant_id, policy_id=policy_id, version=version)
        b.put_policy_document(ref, document)

    @app.get("/v1/tenants/{tenant_id}/policies/{policy_id}/versions/{version}")
    def get_policy(
        tenant_id: str,
        policy_id: str,
        version: str,
        request: Request,
    ) -> dict[str, Any] | None:
        b = backend(request)
        ref = PolicyRef(tenant_id=tenant_id, policy_id=policy_id, version=version)
        doc = b.get_policy_document(ref)
        if doc is None:
            raise HTTPException(status_code=404, detail="policy version not found")
        return doc

    @app.post("/v1/tenants/{tenant_id}/models", status_code=204)
    def register_model(
        tenant_id: str,
        body: RegisterModelBody,
        request: Request,
    ) -> None:
        b = backend(request)
        b.register_model(tenant_id, body.model_id, metadata=body.metadata or None)

    @app.get("/v1/tenants/{tenant_id}/models")
    def list_models(tenant_id: str, request: Request) -> dict[str, list[str]]:
        b = backend(request)
        return {"models": b.list_models(tenant_id)}

    @app.post("/v1/tenants/{tenant_id}/evaluate")
    def evaluate(
        tenant_id: str,
        body: EvaluateBody,
        request: Request,
    ) -> dict[str, Any]:
        b = backend(request)
        ref = PolicyRef(
            tenant_id=tenant_id,
            policy_id=body.policy_id,
            version=body.policy_version,
        )
        chain = ChainedPolicyEngine(
            TrustRegistryPolicyEngine(b, require_registration=True),
            DocumentPolicyEngine(b, policy_ref=ref),
        )
        extra: dict[str, Any] = {}
        if body.tools_invoked:
            extra["tools_invoked"] = body.tools_invoked
        ctx = PolicyEvaluationContext(
            tenant_id=tenant_id,
            workspace_id=body.workspace_id,
            model_id=body.model_id,
            extra=extra,
        )
        decision = chain.evaluate(ctx)

        if body.audit:
            b.append(
                AuditEvent(
                    event_type=AuditEventType.POLICY_EVALUATION,
                    tenant_id=tenant_id,
                    workspace_id=body.workspace_id,
                    correlation_id=decision.correlation_id,
                    payload={
                        "outcome": decision.outcome.value,
                        "violations": [v.model_dump() for v in decision.violations],
                        "policy_id": body.policy_id,
                        "policy_version": body.policy_version,
                        "model_id": body.model_id,
                        "tools_invoked": body.tools_invoked,
                    },
                )
            )

        return {
            "outcome": decision.outcome.value,
            "violations": [v.model_dump() for v in decision.violations],
            "correlation_id": decision.correlation_id,
        }

    @app.post("/v1/tenants/{tenant_id}/gateway/v1/chat/completions")
    async def gateway_openai_chat_completions(
        tenant_id: str,
        request: Request,
        policy_id: str = "default",
        policy_version: str = "v1",
        workspace_id: str | None = None,
        audit: bool = True,
    ) -> Response:
        """Policy check then forward to OpenAI-compatible ``ASCP_UPSTREAM_BASE_URL``."""
        st = request.app.state.settings
        b = backend(request)
        body_any = await request.json()
        if not isinstance(body_any, dict):
            raise HTTPException(status_code=400, detail="JSON object body required")
        body: dict[str, Any] = body_any
        is_stream = body.get("stream") is True
        model_id = str(body.get("model") or "").strip()
        if not model_id:
            raise HTTPException(status_code=400, detail="model is required")
        tool_names = extract_tool_names_from_openai_body(body)
        decision = evaluate_chat_completions_request(
            b,
            tenant_id=tenant_id,
            policy_id=policy_id,
            policy_version=policy_version,
            model_id=model_id,
            tool_names=tool_names,
            workspace_id=workspace_id,
        )

        def audit_blocked() -> None:
            if audit:
                b.append(
                    AuditEvent(
                        event_type=AuditEventType.GATEWAY_REQUEST,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        correlation_id=decision.correlation_id,
                        payload={
                            "path": "chat/completions",
                            "outcome": "BLOCKED",
                            "model_id": model_id,
                            "violations": [v.model_dump() for v in decision.violations],
                        },
                    )
                )

        if decision.outcome == DecisionOutcome.BLOCK:
            audit_blocked()
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "type": "policy_blocked",
                        "message": "Request blocked by ASCP policy",
                        "violations": [v.model_dump() for v in decision.violations],
                        "correlation_id": decision.correlation_id,
                    }
                },
            )

        base = (st.upstream_base_url or "").strip()
        if not base:
            if audit:
                b.append(
                    AuditEvent(
                        event_type=AuditEventType.GATEWAY_REQUEST,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        correlation_id=decision.correlation_id,
                        payload={
                            "path": "chat/completions",
                            "outcome": "UPSTREAM_NOT_CONFIGURED",
                            "model_id": model_id,
                        },
                    )
                )
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "type": "upstream_not_configured",
                        "message": "Set ASCP_UPSTREAM_BASE_URL (e.g. https://api.openai.com/v1)",
                        "correlation_id": decision.correlation_id,
                    }
                },
            )

        if is_stream:
            url = base.rstrip("/") + "/chat/completions"
            hdrs: dict[str, str] = {
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            }
            if st.upstream_api_key:
                hdrs["Authorization"] = f"Bearer {st.upstream_api_key}"
            client = httpx.AsyncClient(timeout=float(st.gateway_timeout_seconds))
            req = client.build_request("POST", url, json=body, headers=hdrs)
            resp = await client.send(req, stream=True)
            if resp.status_code != 200:
                err_b = await resp.aread()
                await resp.aclose()
                await client.aclose()
                if audit:
                    b.append(
                        AuditEvent(
                            event_type=AuditEventType.GATEWAY_REQUEST,
                            tenant_id=tenant_id,
                            workspace_id=workspace_id,
                            correlation_id=decision.correlation_id,
                            payload={
                                "path": "chat/completions",
                                "outcome": "UPSTREAM_ERROR_STREAM",
                                "status": resp.status_code,
                                "model_id": model_id,
                            },
                        )
                    )
                return Response(
                    content=err_b,
                    status_code=resp.status_code,
                    media_type=resp.headers.get("content-type", "application/json"),
                )

            async def stream_body():
                try:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
                finally:
                    await resp.aclose()
                    await client.aclose()

            if audit:
                b.append(
                    AuditEvent(
                        event_type=AuditEventType.GATEWAY_REQUEST,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        correlation_id=decision.correlation_id,
                        payload={
                            "path": "chat/completions",
                            "outcome": "FORWARDED_STREAM",
                            "model_id": model_id,
                        },
                    )
                )
            return StreamingResponse(
                stream_body(),
                media_type="text/event-stream",
                status_code=200,
            )

        try:
            status, content, ct = forward_openai_chat_completions(
                base_url=base,
                api_key=st.upstream_api_key,
                body=body,
                timeout=float(st.gateway_timeout_seconds),
            )
        except httpx.RequestError as e:
            if audit:
                b.append(
                    AuditEvent(
                        event_type=AuditEventType.GATEWAY_REQUEST,
                        tenant_id=tenant_id,
                        workspace_id=workspace_id,
                        correlation_id=decision.correlation_id,
                        payload={
                            "path": "chat/completions",
                            "outcome": "UPSTREAM_ERROR",
                            "model_id": model_id,
                            "detail": str(e)[:500],
                        },
                    )
                )
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "type": "upstream_error",
                        "message": str(e)[:500],
                        "correlation_id": decision.correlation_id,
                    }
                },
            )

        if audit:
            b.append(
                AuditEvent(
                    event_type=AuditEventType.GATEWAY_REQUEST,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    correlation_id=decision.correlation_id,
                    payload={
                        "path": "chat/completions",
                        "outcome": "FORWARDED",
                        "upstream_status": status,
                        "model_id": model_id,
                    },
                )
            )
        return Response(content=content, status_code=status, media_type=ct)

    @app.post("/v1/tenants/{tenant_id}/assurance-runs")
    def create_assurance_run(
        tenant_id: str,
        body: CreateAssuranceRunBody,
        request: Request,
    ) -> dict[str, str]:
        b = backend(request)
        rid = new_run_id()
        meta = {**body.metadata, "suite": body.suite}
        replay_id = (body.metadata or {}).get("replay_from_run_id")
        if replay_id:
            prev = b.get_run(str(replay_id))
            if prev and prev.tenant_id == tenant_id:
                pm = dict(prev.metadata)
                for k in (
                    "target_url",
                    "target_model",
                    "target_payload_style",
                    "target_headers",
                    "target_body_extra",
                    "min_pass_rate",
                ):
                    if k in pm and k not in (body.metadata or {}):
                        meta[k] = pm[k]
                if "suite" not in (body.metadata or {}):
                    meta["suite"] = pm.get("suite") or body.suite
        rec = AssuranceRunRecord(
            run_id=rid,
            tenant_id=tenant_id,
            workspace_id=body.workspace_id,
            status="created",
            metadata=meta,
        )
        b.create_run(rec)
        return {"run_id": rid}

    @app.get("/v1/tenants/{tenant_id}/assurance-runs")
    def list_assurance_runs(
        tenant_id: str,
        request: Request,
        limit: int = 50,
    ) -> dict[str, Any]:
        b = backend(request)
        runs = b.list_runs(tenant_id, limit=limit)
        return {"runs": [r.model_dump() for r in runs]}

    @app.get("/v1/tenants/{tenant_id}/assurance-runs/{run_id}")
    def get_assurance_run(
        tenant_id: str,
        run_id: str,
        request: Request,
    ) -> dict[str, Any]:
        b = backend(request)
        rec = b.get_run(run_id)
        if rec is None or rec.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="run not found")
        return rec.model_dump()

    @app.patch("/v1/tenants/{tenant_id}/assurance-runs/{run_id}")
    def patch_assurance_run(
        tenant_id: str,
        run_id: str,
        body: PatchAssuranceRunBody,
        request: Request,
    ) -> dict[str, Any]:
        b = backend(request)
        rec = b.get_run(run_id)
        if rec is None or rec.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="run not found")
        try:
            b.update_run(
                run_id,
                status=body.status,
                metadata=body.metadata,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found") from None
        out = b.get_run(run_id)
        assert out is not None
        return out.model_dump()

    @app.post("/v1/tenants/{tenant_id}/assurance-runs/{run_id}/execute")
    def post_assurance_run_execute(
        tenant_id: str,
        run_id: str,
        request: Request,
        fail_ci: bool = False,
    ) -> dict[str, Any]:
        b = backend(request)
        st = request.app.state.settings
        try:
            out = run_assurance_pipeline(
                runs=b,
                artifacts=b,
                audit=b,
                tenant_id=tenant_id,
                run_id=run_id,
                default_target_authorization=st.assurance_target_default_authorization,
                http_timeout=float(st.assurance_http_timeout_seconds),
            )
        except ValueError as e:
            msg = str(e)
            if "not found" in msg.lower():
                raise HTTPException(status_code=404, detail=msg) from e
            raise HTTPException(status_code=400, detail=msg) from e
        if fail_ci and not out.get("ci_passed", True):
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Assurance run did not meet min_pass_rate",
                    "scoring": {
                        k: out.get(k)
                        for k in ("score", "passed_count", "total", "ci_passed")
                        if k in out
                    },
                },
            )
        return out

    @app.post("/v1/admin/tenants/{tenant_id}/api-keys")
    def admin_create_tenant_api_key(
        tenant_id: str,
        request: Request,
        body: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        b = backend(request)
        name = str(body.get("name") or "default")
        return b.create_tenant_api_key(tenant_id, name)

    @app.get("/v1/admin/tenants/{tenant_id}/api-keys")
    def admin_list_tenant_api_keys(tenant_id: str, request: Request) -> dict[str, Any]:
        b = backend(request)
        return {"keys": b.list_tenant_api_key_ids(tenant_id)}

    @app.post("/v1/tenants/{tenant_id}/supply-chain/lockfile")
    async def upload_supply_lockfile(
        tenant_id: str,
        request: Request,
        filename: str = "requirements.txt",
    ) -> dict[str, Any]:
        b = backend(request)
        data = await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="empty body")
        return b.put_supply_lockfile(tenant_id, filename, data)

    @app.get("/v1/tenants/{tenant_id}/supply-chain/lockfiles")
    def list_supply_lockfiles(
        tenant_id: str,
        request: Request,
        limit: int = 50,
    ) -> dict[str, Any]:
        b = backend(request)
        return {"lockfiles": b.list_supply_lockfiles(tenant_id, limit=limit)}

    @app.post("/v1/tenants/{tenant_id}/supply-chain/cyclonedx")
    async def upload_cyclonedx(tenant_id: str, request: Request) -> dict[str, Any]:
        import uuid

        b = backend(request)
        raw = await request.body()
        if not raw:
            raise HTTPException(status_code=400, detail="empty body")
        sid = str(uuid.uuid4())
        key = f"supply/{tenant_id}/cyclonedx/{sid}.json"
        b.put_bytes(key, raw)
        return {"id": sid, "artifact_key": key}

    @app.put("/v1/tenants/{tenant_id}/rag/corpora/{corpus_id}")
    def rag_put_corpus(
        tenant_id: str,
        corpus_id: str,
        body: dict[str, Any],
        request: Request,
    ) -> dict[str, Any]:
        b = backend(request)
        chunks = body.get("chunks") or []
        if not isinstance(chunks, list):
            raise HTTPException(status_code=400, detail="chunks must be a list")
        return b.rag_set_corpus(tenant_id, corpus_id, chunks)

    @app.post("/v1/tenants/{tenant_id}/rag/corpora/{corpus_id}/evaluate")
    def rag_evaluate(
        tenant_id: str,
        corpus_id: str,
        body: dict[str, Any],
        request: Request,
    ) -> dict[str, Any]:
        b = backend(request)
        q = str(body.get("query") or "")
        top_k = int(body.get("top_k") or 5)
        return b.rag_evaluate_query(tenant_id, corpus_id, q, top_k=top_k)

    @app.get("/v1/tenants/{tenant_id}/audit/export.jsonl")
    def audit_export_jsonl(
        tenant_id: str,
        request: Request,
        limit: int = 5000,
        since: str | None = None,
    ) -> Response:
        b = backend(request)
        raw = b.export_audit_events_jsonl(tenant_id, limit=limit, since_iso=since)
        return Response(
            content=raw,
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="audit-{tenant_id}.jsonl"'},
        )

    register_dashboard(app)
    return app


app = create_app()
