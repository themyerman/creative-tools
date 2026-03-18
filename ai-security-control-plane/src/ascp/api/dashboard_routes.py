"""Server-rendered operator dashboard (Jinja2 + FastAPI)."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.templating import Jinja2Templates

from ascp.core.types import PolicyRef

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
_BASIC = HTTPBasic(auto_error=False)


def _require_dashboard(
    request: Request, credentials: HTTPBasicCredentials | None = Depends(_BASIC)
) -> None:
    key = (getattr(request.app.state.settings, "api_key", None) or "").strip()
    if not key:
        return
    if credentials is None or not secrets.compare_digest(credentials.password, key):
        raise HTTPException(
            status_code=401,
            detail="Dashboard requires HTTP Basic auth (password = ASCP_API_KEY)",
            headers={"WWW-Authenticate": 'Basic realm="ASCP Dashboard"'},
        )


def _audit_preview(b: Any, tenant_id: str, limit: int = 20) -> list[dict[str, Any]]:
    raw = b.export_audit_events_jsonl(tenant_id, limit=limit * 3)
    rows: list[dict[str, Any]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("tenant_id") != tenant_id:
            continue
        payload = ev.get("payload") or {}
        kind = str(ev.get("event_type") or "")
        if kind == "GATEWAY_REQUEST":
            summ = str(payload.get("outcome") or "")
            mid = payload.get("model_id")
            if mid:
                summ += f" model={mid}"
        elif kind == "POLICY_EVALUATION":
            summ = f"{payload.get('outcome')} policy={payload.get('policy_id')}"
        elif kind == "ASSURANCE_RUN":
            summ = str(payload.get("action") or "")
            sc = payload.get("scoring") or {}
            if sc.get("score") is not None:
                summ += f" score={sc.get('score')}"
        else:
            summ = json.dumps(payload, default=str)[:120]
        rows.append(
            {
                "at": str(ev.get("occurred_at") or "")[:19],
                "kind": kind.split(".")[-1] if "." in kind else kind,
                "summary": summ[:200],
            }
        )
        if len(rows) >= limit:
            break
    return rows


def register_dashboard(app: Any) -> None:
    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_home(
        request: Request, _auth: None = Depends(_require_dashboard)
    ) -> Any:
        b = request.app.state.backend
        list_fn = getattr(b, "list_known_tenant_ids", None)
        tenants: list[str] = list_fn(limit=200) if callable(list_fn) else []
        tenant_links = [{"id": t, "path": quote(t, safe="")} for t in tenants]
        return _TEMPLATES.TemplateResponse(
            request,
            "dashboard/home.html",
            {"tenant_links": tenant_links},
        )

    @app.get("/dashboard/tenant/{tenant_id}", response_class=HTMLResponse)
    def dashboard_tenant(
        request: Request,
        tenant_id: str,
        _auth: None = Depends(_require_dashboard),
    ) -> Any:
        b = request.app.state.backend
        ref = PolicyRef(tenant_id=tenant_id, policy_id="default", version="v1")
        policy = b.get_policy_document(ref)
        policy_json = json.dumps(policy, indent=2, default=str) if policy else ""
        models = b.list_models(tenant_id)
        runs_raw = b.list_runs(tenant_id, limit=25)
        runs: list[dict[str, Any]] = []
        for r in runs_raw:
            md = dict(r.metadata)
            sc = md.get("scoring") or {}
            runs.append(
                {
                    "run_id": r.run_id,
                    "status": r.status,
                    "suite": md.get("suite", "—"),
                    "score": sc.get("score"),
                    "ci_passed": sc.get("ci_passed"),
                }
            )
        lockfiles = getattr(b, "list_supply_lockfiles", lambda *_a, **_k: [])(tenant_id, limit=10)
        audit_rows = _audit_preview(b, tenant_id, limit=18)
        return _TEMPLATES.TemplateResponse(
            request,
            "dashboard/tenant.html",
            {
                "tenant_id": tenant_id,
                "tenant_q": quote(tenant_id, safe=""),
                "models": models,
                "policy": policy,
                "policy_json": policy_json,
                "runs": runs,
                "lockfiles": lockfiles,
                "audit_rows": audit_rows,
            },
        )
