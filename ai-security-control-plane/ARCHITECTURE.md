# ASCP architecture — ports and reference backend

## Ports (`ascp.storage.ports`)

Storage and side effects are defined as **`typing.Protocol`** interfaces so production can swap Postgres, S3, Kafka, etc. without changing policy or gateway code.

| Port | Role |
|------|------|
| **PolicyRepository** | Versioned policy documents as `dict` (JSON-serializable). `get_policy_document`, `put_policy_document`, `list_policy_versions`. |
| **TrustRegistry** | Tenant-scoped model allowlist. `register_model`, `is_model_allowed`, `list_models`. |
| **AuditSink** | Append-only audit trail. `append`, `append_batch` with `AuditEvent`. |
| **ArtifactStore** | Binary blobs (reports, captures). `put_bytes`, `get_bytes` keyed by path-like string. |
| **AssuranceRunStore** | Assurance run metadata via `AssuranceRunRecord`. `create_run`, `update_run`, `get_run`, `list_runs(tenant_id, limit=...)`. |

## Reference backend: `SqliteFsBackend` (`ascp.storage.sqlite_fs`)

Single class implementing **all** ports above:

- **SQLite** (`database_url`, e.g. `sqlite:///./ascp.db`) with tables:
  - `policies` — tenant, policy_id, version, JSON document
  - `trust_registry` — tenant, model_id, metadata JSON
  - `audit_events` — full `AuditEvent` JSON per row
  - `assurance_runs` — run metadata + status + JSON metadata
  - `tenant_api_keys`, `supply_lockfiles`, `rag_chunks` — operator features (see README)
- **Filesystem** under **`artifact_root`**: one file per artifact key (safe relative paths only).

**`PostgresFsBackend`** (`ascp.storage.postgres_fs`): same tables + behavior when **`ASCP_DATABASE_URL`** is `postgresql://...` (requires **`pip install ascp[postgres]`**). **`create_backend(settings)`** in **`ascp.storage.factory`** picks SQLite vs Postgres.

Use SQLite/Postgres + FS for dev and small deployments; scale-out paths can replace individual ports with cloud-native implementations.

## Policy engines (`ascp.policy.engine`, `ascp.policy.document_engine`)

- **`PolicyEngine`**: `evaluate(PolicyEvaluationContext) -> Decision`.
- **`AllowAllPolicyEngine`**: always `ALLOW`.
- **`TrustRegistryPolicyEngine`**: when `require_registration=True`, blocks with `TRUST_MODEL_NOT_ALLOWED` if `model_id` is present and not in the tenant’s trust registry.
- **`DocumentPolicyEngine`**: loads **`PolicyDocumentV1`** from `PolicyRepository` for a fixed `PolicyRef`; enforces **tools** (`mode`: `open` | `allowlist`, `allowed`, `deny`, `on_violation`: `block` | `warn`). Context: `extra["tools_invoked"]` or `extra["tools"]`.
- **`ChainedPolicyEngine`**: runs multiple engines; first `BLOCK` wins; else aggregates `WARN`.

## Policy documents v1 (`ascp.policy.document`)

YAML/JSON mapping validated by Pydantic; **`policy_document_from_yaml(text)`**. Stored like any policy document via `PolicyRepository`.

## Operator API (`ascp.api`)

FastAPI: admin tenant API keys, supply-chain uploads, RAG corpora/eval, **audit NDJSON export**, gateway **sync + streaming**, assurance **scoring / fail_ci / replay**, **HTML dashboard** at **`/dashboard`** (Jinja2; HTTP Basic = **`ASCP_API_KEY`** when set), etc. Admin or per-tenant **`ascp_ten_*`** tokens for JSON API. **`ASCP_AUDIT_WEBHOOK_URL`**. See README + **`docs/OBSERVABILITY.md`**.

## Assurance (`ascp.assurance`)

**`execute_assurance_run`**: if run metadata has **`target_url`**, POSTs each scenario (default OpenAI-shaped **`{model, messages}`**); else stub rows. Report JSON + **`ASSURANCE_RUN`** audit.

## Gateway (`ascp.gateway`)

**`evaluate_chat_completions_request`** + **`forward_openai_chat_completions`** — tool names from OpenAI **`tools[].function.name`**.

## Core types (`ascp.core.types`)

IDs, `PolicyRef`, `Decision` / `Violation`, `AuditEvent`, and `PolicyEvaluationContext` are Pydantic models shared across ports and engines.
