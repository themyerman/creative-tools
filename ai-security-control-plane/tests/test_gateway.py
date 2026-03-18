"""OpenAI gateway policy + forward helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ascp.core.types import PolicyRef
from ascp.gateway.openai_proxy import (
    evaluate_chat_completions_request,
    extract_tool_names_from_openai_body,
    forward_openai_chat_completions,
)
from ascp.storage import SqliteFsBackend


@pytest.fixture
def backend(tmp_path):
    return SqliteFsBackend(
        f"sqlite:///{tmp_path / 'g.db'}",
        artifact_root=tmp_path / "a",
    )


def test_extract_tool_names():
    body = {
        "model": "gpt-4",
        "tools": [
            {"type": "function", "function": {"name": "search"}},
            {"type": "function", "function": {"name": "run_code"}},
        ],
    }
    assert extract_tool_names_from_openai_body(body) == ["search", "run_code"]


def test_evaluate_blocks_unregistered_model(backend):
    ref = PolicyRef(tenant_id="t1", policy_id="p1", version="v1")
    backend.put_policy_document(
        ref,
        {"schema_version": "1", "tools": {"mode": "open"}},
    )
    d = evaluate_chat_completions_request(
        backend,
        tenant_id="t1",
        policy_id="p1",
        policy_version="v1",
        model_id="gpt-4",
        tool_names=[],
    )
    assert d.outcome.value == "BLOCK"


def test_evaluate_allows_registered_with_open_tools(backend):
    backend.register_model("t1", "gpt-4")
    ref = PolicyRef(tenant_id="t1", policy_id="p1", version="v1")
    backend.put_policy_document(
        ref,
        {"schema_version": "1", "tools": {"mode": "open"}},
    )
    d = evaluate_chat_completions_request(
        backend,
        tenant_id="t1",
        policy_id="p1",
        policy_version="v1",
        model_id="gpt-4",
        tool_names=["bash"],
    )
    assert d.outcome.value == "ALLOW"


def test_forward_openai_chat_completions():
    with patch("ascp.gateway.openai_proxy.httpx.Client") as C:
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'{"ok":true}'
        resp.headers = {"content-type": "application/json"}
        C.return_value.__enter__.return_value.post.return_value = resp
        st, content, ct = forward_openai_chat_completions(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            body={"model": "gpt-4", "messages": []},
            timeout=10.0,
        )
    assert st == 200
    assert content == b'{"ok":true}'
    assert "json" in ct.lower()
