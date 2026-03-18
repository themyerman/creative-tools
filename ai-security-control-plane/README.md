# AI Security Control Plane

Python-oriented control plane for **guarding LLM apps in production**, **continuous adversarial testing**, **RAG-focused attack lab**, and **supply-chain provenance**—with **pluggable storage** (SQL, NoSQL, object stores, log sinks).

Product intent and architecture live in **[prd.md](./prd.md)**.

---

## Next steps / Todo

Major decisions and work to line up (check off as we go):

- [ ] **Scope & phases** — Define v0 (e.g. 8–12 weeks): which pillar ships first vs. stub; single-tenant vs. multi-tenant later.
- [ ] **Gateway (pillar 2)** — Protocol surface (OpenAI-compatible proxy? sidecar? SDK hooks?); sync vs. streaming; where session/context IDs live.
- [ ] **Policy model** — How policies are authored (YAML, UI, API); versioning; tool allowlists, PII rules, model allowlists; evaluation order and failures (block vs. warn).
- [ ] **Storage abstractions** — Interfaces for policy registry, audit sink, artifact store, test-run metadata; first reference implementation (e.g. Postgres + local blob dir).
- [ ] **Trust registry & scanner (pillar 4)** — What we fingerprint first (lockfiles, HF revision, container digest); CI integration (GitHub Action, generic CLI); SBOM format(s).
- [ ] **Red-team runner (pillar 1)** — How tests target customer apps (staging URL, recorded fixtures); prompt/scenario library; scoring and tickets/export.
- [ ] **RAG lab (pillar 3)** — Synthetic poison corpora; eval metrics; integration with same retrieval path as prod (or faithful stub).
- [ ] **Observability & compliance** — Audit log shape, retention, redaction; SIEM/OTLP forwarding; what we never store.
- [ ] **Dashboard / API** — Minimal UI vs. API-only for v0; authn/z for operators.
- [ ] **Distribution** — PyPI package(s), Docker, Helm, or “library + service” split.
- [ ] **Licensing & safety** — Responsible use of attack scenarios; docs for customers running tests only on systems they own.
