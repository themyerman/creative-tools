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
- **Filesystem** under **`artifact_root`**: one file per artifact key (safe relative paths only).

Use this for local dev, tests, and small deployments; scale-out paths replace individual ports with cloud-native implementations.

## Policy engines (`ascp.policy.engine`, `ascp.policy.document_engine`)

- **`PolicyEngine`**: `evaluate(PolicyEvaluationContext) -> Decision`.
- **`AllowAllPolicyEngine`**: always `ALLOW`.
- **`TrustRegistryPolicyEngine`**: when `require_registration=True`, blocks with `TRUST_MODEL_NOT_ALLOWED` if `model_id` is present and not in the tenant’s trust registry.
- **`DocumentPolicyEngine`**: loads **`PolicyDocumentV1`** from `PolicyRepository` for a fixed `PolicyRef`; enforces **tools** (`mode`: `open` | `allowlist`, `allowed`, `deny`, `on_violation`: `block` | `warn`). Context: `extra["tools_invoked"]` or `extra["tools"]`.
- **`ChainedPolicyEngine`**: runs multiple engines; first `BLOCK` wins; else aggregates `WARN`.

## Policy documents v1 (`ascp.policy.document`)

YAML/JSON mapping validated by Pydantic; **`policy_document_from_yaml(text)`**. Stored like any policy document via `PolicyRepository`.

## Operator API (`ascp.api`)

FastAPI: health, policy CRUD, models, **`POST .../evaluate`**, **`POST .../gateway/v1/chat/completions`** (policy then upstream forward), assurance runs + execute (stub or live via **`target_url`**), suites. Env: **`ASCP_UPSTREAM_BASE_URL`**, **`ASCP_UPSTREAM_API_KEY`**, **`ASCP_ASSURANCE_TARGET_AUTHORIZATION`**, timeouts. **`ASCP_API_KEY`** locks API except **`/health`**. **`ascp[api]`**, **`ascp-serve`**.

## Assurance (`ascp.assurance`)

**`execute_assurance_run`**: if run metadata has **`target_url`**, POSTs each scenario (default OpenAI-shaped **`{model, messages}`**); else stub rows. Report JSON + **`ASSURANCE_RUN`** audit.

## Gateway (`ascp.gateway`)

**`evaluate_chat_completions_request`** + **`forward_openai_chat_completions`** — tool names from OpenAI **`tools[].function.name`**.

## Core types (`ascp.core.types`)

IDs, `PolicyRef`, `Decision` / `Violation`, `AuditEvent`, and `PolicyEvaluationContext` are Pydantic models shared across ports and engines.
