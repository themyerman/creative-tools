"""OpenAI-style chat.completions body parsing and upstream forward."""

from __future__ import annotations

from typing import Any

import httpx

from ascp.core.types import Decision, PolicyEvaluationContext, PolicyRef
from ascp.policy import ChainedPolicyEngine, DocumentPolicyEngine, TrustRegistryPolicyEngine
from ascp.storage import SqliteFsBackend


def extract_tool_names_from_openai_body(body: dict[str, Any]) -> list[str]:
    """Collect ``function.name`` from OpenAI ``tools`` array."""
    tools = body.get("tools")
    if not isinstance(tools, list):
        return []
    names: list[str] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        fn = t.get("function")
        if isinstance(fn, dict):
            n = fn.get("name")
            if isinstance(n, str) and n.strip():
                names.append(n.strip())
    return names


def evaluate_chat_completions_request(
    backend: SqliteFsBackend,
    *,
    tenant_id: str,
    policy_id: str,
    policy_version: str,
    model_id: str,
    tool_names: list[str],
    workspace_id: str | None = None,
) -> Decision:
    ref = PolicyRef(tenant_id=tenant_id, policy_id=policy_id, version=policy_version)
    chain = ChainedPolicyEngine(
        TrustRegistryPolicyEngine(backend, require_registration=True),
        DocumentPolicyEngine(backend, policy_ref=ref),
    )
    extra: dict[str, Any] = {}
    if tool_names:
        extra["tools_invoked"] = tool_names
    ctx = PolicyEvaluationContext(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        model_id=model_id or None,
        extra=extra,
    )
    return chain.evaluate(ctx)


def forward_openai_chat_completions(
    *,
    base_url: str,
    api_key: str | None,
    body: dict[str, Any],
    timeout: float,
) -> tuple[int, bytes, str]:
    """
    POST ``{base_url}/chat/completions`` with JSON body.
    Returns ``(status_code, content_bytes, content_type)``.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=body, headers=headers)
    ct = r.headers.get("content-type") or "application/json"
    return r.status_code, r.content, ct


