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


def compute_tenant_posture(
    *,
    models: list[str],
    policy: dict[str, Any] | None,
    runs: list[dict[str, Any]],
    lockfile_count: int,
    audit_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Heuristic 0–100 scores per pillar + overall (mean). Not a formal risk score—explains
    gaps vs “safe to run” + “known bits” (PRD narrative).
    """
    dims: list[dict[str, Any]] = []

    # 1) Trust: registered models
    if len(models) >= 1:
        m_score, m_detail = 92, f"{len(models)} model(s) in trust registry"
    else:
        m_score, m_detail = 22, "No models registered — gateway can’t enforce allowlist"
    dims.append(
        _dim(
            "trust",
            "Known models (trust)",
            m_score,
            m_detail,
            "Are the LLM IDs you run explicitly allowlisted?",
        )
    )

    # 2) Policy: tool rules
    if policy and isinstance(policy.get("tools"), dict) and policy["tools"].get("mode"):
        p_score, p_detail = 94, f"Tools mode: {policy['tools'].get('mode')}"
    elif policy:
        p_score, p_detail = 52, "Policy exists but tool rules are thin or missing mode"
    else:
        p_score, p_detail = 18, "No default@v1 policy — tool allow/deny not configured"
    dims.append(
        _dim(
            "policy",
            "Enforceable rules",
            p_score,
            p_detail,
            "Can ASCP block disallowed tools on this tenant?",
        )
    )

    # 3) Assurance: latest run signal
    a_score, a_detail = 18, "No assurance runs yet — red-team posture unknown"
    if runs:
        r0 = runs[0]
        st = (r0.get("status") or "").lower()
        ci = r0.get("ci_passed")
        sc = r0.get("score")
        if st == "completed":
            if ci is True:
                a_score, a_detail = 96, "Latest run passed your CI threshold (min_pass_rate)"
            elif ci is False:
                a_score, a_detail = 34, "Latest run failed CI — jailbreak/leak heuristics or score below threshold"
            elif sc is not None:
                try:
                    sf = float(sc)
                    a_score = int(40 + min(1.0, max(0.0, sf)) * 45)
                    a_detail = f"Latest score {sf:.0%} (set fail_ci in CI to hard-gate)"
                except (TypeError, ValueError):
                    a_score, a_detail = 55, "Latest run completed; scoring incomplete in UI"
            else:
                a_score, a_detail = 48, "Latest run completed (stub or unscored)"
        elif st == "created":
            a_score, a_detail = 28, "Run created but not executed"
    dims.append(
        _dim(
            "assurance",
            "Tested (assurance)",
            a_score,
            a_detail,
            "Have automated adversarial prompts been run against staging recently?",
        )
    )

    # 4) Supply: lockfiles on record
    if lockfile_count >= 1:
        s_score, s_detail = 90, f"{lockfile_count} lockfile record(s) — provenance snapshot on file"
    else:
        s_score, s_detail = 26, "No lockfiles uploaded — “known dependencies” not recorded here"
    dims.append(
        _dim(
            "supply",
            "Known dependencies",
            s_score,
            s_detail,
            "Is there a hashed dependency record (CI upload)?",
        )
    )

    # 5) Visibility: audit trail shows real use
    has_gw = any(
        "FORWARD" in str(row.get("summary") or "") or "BLOCKED" in str(row.get("summary") or "")
        for row in audit_rows
    )
    has_eval = any("ALLOW" in str(row.get("summary") or "") for row in audit_rows)
    if has_gw or has_eval:
        v_score, v_detail = 82, "Audit shows gateway or policy evaluations — operational signal"
    elif audit_rows:
        v_score, v_detail = 58, "Some audit events; limited gateway/eval visibility"
    else:
        v_score, v_detail = 32, "No recent audit rows — hard to verify live enforcement"
    dims.append(
        _dim(
            "visibility",
            "Operational visibility",
            v_score,
            v_detail,
            "Do logs show this tenant’s AI path is actually exercised?",
        )
    )

    overall = round(sum(d["score"] for d in dims) / len(dims))
    if overall >= 78:
        headline = (
            "Strong posture: trust, policy, and evidence are mostly in place — "
            "closer to “safe to run” and “built from known bits.”"
        )
        overall_band = "strong"
    elif overall >= 52:
        headline = (
            "Mixed: some pillars are strong; others drag confidence. "
            "Close assurance, supply, or visibility gaps before claiming full safety."
        )
        overall_band = "partial"
    else:
        headline = (
            "Major gaps: this tenant doesn’t yet support a clear story that the AI is "
            "both gated and traced to known models/deps."
        )
        overall_band = "gap"

    return {
        "overall": overall,
        "overall_band": overall_band,
        "headline": headline,
        "tagline": "Is this AI safe to run — and built from known bits? (heuristic view)",
        "dimensions": dims,
    }


def _dim(
    key: str,
    title: str,
    score: int,
    detail: str,
    question: str,
) -> dict[str, Any]:
    score = max(0, min(100, int(score)))
    if score >= 72:
        band, band_class = "Strong", "strong"
    elif score >= 42:
        band, band_class = "Partial", "partial"
    else:
        band, band_class = "Gap", "gap"
    return {
        "key": key,
        "title": title,
        "score": score,
        "band": band,
        "band_class": band_class,
        "detail": detail,
        "question": question,
    }


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


def _gather_tenant_dashboard_snapshot(b: Any, tenant_id: str) -> dict[str, Any]:
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
    audit_rows = _audit_preview(b, tenant_id, limit=80)
    posture = compute_tenant_posture(
        models=models,
        policy=policy,
        runs=runs,
        lockfile_count=len(lockfiles),
        audit_rows=audit_rows[:40],
    )
    return {
        "tenant_id": tenant_id,
        "tenant_q": quote(tenant_id, safe=""),
        "models": models,
        "policy": policy,
        "policy_json": policy_json,
        "runs": runs,
        "lockfiles": lockfiles,
        "audit_rows": audit_rows[:18],
        "posture": posture,
    }


def register_dashboard(app: Any) -> None:
    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard_home(
        request: Request, _auth: None = Depends(_require_dashboard)
    ) -> Any:
        b = request.app.state.backend
        list_fn = getattr(b, "list_known_tenant_ids", None)
        tenants: list[str] = list_fn(limit=200) if callable(list_fn) else []
        tenant_rows: list[dict[str, Any]] = []
        for tid in tenants:
            snap = _gather_tenant_dashboard_snapshot(b, tid)
            p = snap["posture"]
            tenant_rows.append(
                {
                    "id": tid,
                    "path": quote(tid, safe=""),
                    "overall": p["overall"],
                    "overall_band": p["overall_band"],
                }
            )
        tenant_rows.sort(key=lambda x: (x["overall"], x["id"]))
        return _TEMPLATES.TemplateResponse(
            request,
            "dashboard/home.html",
            {"tenant_rows": tenant_rows},
        )

    @app.get("/dashboard/tenant/{tenant_id}", response_class=HTMLResponse)
    def dashboard_tenant(
        request: Request,
        tenant_id: str,
        _auth: None = Depends(_require_dashboard),
    ) -> Any:
        b = request.app.state.backend
        snap = _gather_tenant_dashboard_snapshot(b, tenant_id)
        return _TEMPLATES.TemplateResponse(request, "dashboard/tenant.html", snap)
