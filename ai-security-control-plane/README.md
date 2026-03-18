# AI Security Control Plane

Python-oriented control plane for **guarding LLM apps in production**, **continuous adversarial testing**, **RAG-focused attack lab**, and **supply-chain provenance**—with **pluggable storage** (SQL, NoSQL, object stores, log sinks).

Product intent and architecture live in **[prd.md](./prd.md)**.

---

## Next steps / Todo

### Foundations (done)

- **Core types** — `TenantId` / `WorkspaceId` / `RunId`, `PolicyRef`, `Decision` / `Violation`, `AuditEvent`, `PolicyEvaluationContext` (`ascp.core`).
- **Storage ports** — `PolicyRepository`, `TrustRegistry`, `AuditSink`, `ArtifactStore`, `AssuranceRunStore` + `AssuranceRunRecord` (`ascp.storage.ports`).
- **Reference backend** — `SqliteFsBackend`: SQLite + filesystem artifacts; see [ARCHITECTURE.md](./ARCHITECTURE.md).
- **Policy engines** — `AllowAllPolicyEngine`, `TrustRegistryPolicyEngine`, **`ChainedPolicyEngine`**, **`DocumentPolicyEngine`** (tool allowlist / deny from stored documents).
- **Policy documents (v1)** — `PolicyDocumentV1` / `ToolsPolicy`; YAML via `policy_document_from_yaml()`; block vs. warn on allowlist violations; denylist always blocks.
- **Operator HTTP API** — FastAPI app (`ascp.api`): `GET /health`, policy PUT/GET, model register/list, **`POST /v1/tenants/{id}/evaluate`**, assurance runs (create / list / get / patch / **`POST .../execute`** stub), **`GET /v1/assurance/suites`**. Optional **`ASCP_API_KEY`** → require `Authorization: Bearer …` or `X-ASCP-API-Key` (health stays open). Install `ascp[api]`, run **`ascp-serve`** (`ASCP_DATABASE_URL`, `ASCP_ARTIFACT_ROOT`, `ASCP_LOG_LEVEL`).
- **Assurance (red-team)** — Suite **`builtin-v0`**; **stub** (no `target_url`) or **live**: set run metadata **`target_url`** (+ optional **`target_model`**, **`target_payload_style`** `openai_chat`|`simple_json`, **`target_headers`**, **`target_body_extra`**). Server may set **`ASCP_ASSURANCE_TARGET_AUTHORIZATION`** for Bearer to staging. Report + audit **`assurance-live-v1`** / **`builtin-stub-v1`**.
- **Gateway proxy** — **`POST /v1/tenants/{id}/gateway/v1/chat/completions`**: same policy chain as evaluate (model + tool names from body), then forward to **`ASCP_UPSTREAM_BASE_URL`** + **`ASCP_UPSTREAM_API_KEY`** (OpenAI-compatible). **`stream: true`** rejected in v0. **403** policy block, **503** if upstream unset.
- **Config & logging** — `Settings` (`ASCP_*`), `configure_logging` / `bind_correlation_id` for correlation-aware logs.

Major decisions and work to line up (check off as we go):

- [ ] **Scope & phases** — Define v0 (e.g. 8–12 weeks): which pillar ships first vs. stub; single-tenant vs. multi-tenant later.
- [x] **Gateway (partial)** — OpenAI-style **`/chat/completions`** proxy path; sync only; policy query params; streaming TBD.
- [x] **Policy model (partial)** — Stored JSON/YAML v1 schema with tool allowlist/deny and block/warn; versioning via `PolicyRef`; trust registry separate; evaluation order = trust then document (chain).
- [ ] **Storage abstractions** — Interfaces for policy registry, audit sink, artifact store, test-run metadata; first reference implementation (e.g. Postgres + local blob dir).
- [ ] **Trust registry & scanner (pillar 4)** — What we fingerprint first (lockfiles, HF revision, container digest); CI integration (GitHub Action, generic CLI); SBOM format(s).
- [x] **Red-team runner (partial)** — Scenarios + stub + **live `target_url`** HTTP + heuristics; richer scoring / CI next.
- [ ] **RAG lab (pillar 3)** — Synthetic poison corpora; eval metrics; integration with same retrieval path as prod (or faithful stub).
- [ ] **Observability & compliance** — Audit log shape, retention, redaction; SIEM/OTLP forwarding; what we never store.
- [x] **Dashboard / API (minimal)** — Operator API; optional shared-secret API key.
- [ ] **Distribution** — PyPI package(s), Docker, Helm, or “library + service” split.
- [ ] **Licensing & safety** — Responsible use of attack scenarios; docs for customers running tests only on systems they own.
