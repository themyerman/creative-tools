# AI Security Control Plane (ASCP)

**ASCP** is a Python **control plane** for teams shipping LLM-powered apps. It helps you **enforce policies** (which models and tools are allowed), **audit** decisions, **proxy** OpenAI-style chat traffic through those policies, and run **assurance** (red-team style) scenarios against a **staging endpoint**—with everything stored in a **pluggable** layer (today: **SQLite + local files**; designed so you can swap in Postgres, S3, etc.).

Longer product vision (four pillars: gateway, red-team, RAG lab, supply chain) is in **[prd.md](./prd.md)**. **Ports, backends, and internals** are in **[ARCHITECTURE.md](./ARCHITECTURE.md)**.

---

## In plain English (for everyone)

**What problem does this solve?**  
Companies are shipping chatbots and “AI agents” that can call tools, read documents, and talk to users. That’s powerful—and easy to get wrong. ASCP is software that sits **beside or in front of** those systems to help you **control what’s allowed**, **see what happened**, and **test whether your app holds up** when someone tries to trick it or leak data.

**Think of it like:**

| Idea | Plain meaning |
|------|----------------|
| **Rules for your AI** | Only certain **models** you’ve approved. Only certain **tools** (e.g. “search OK,” “delete database not OK”). You write the rules; ASCP checks them. |
| **A gate for chat traffic** | Your app can send chat requests **through ASCP** instead of straight to the AI vendor. If the request breaks the rules, it’s **blocked**; if not, it goes through—like a **bouncer** with a list. |
| **A flight recorder** | Important decisions (allowed, blocked, who asked what at a high level) can be **logged** and **exported** so security or compliance can review later—not “spying,” but **evidence** you chose to keep. |
| **Fire drills** | ASCP can run a **battery of tricky prompts** against a **staging copy** of your app (with your permission) and give you a **score**: did it refuse jailbreaks? Did it leak fake “secrets” in the test? Useful before every release. |
| **“Did bad docs poison the answer?”** | A **simple lab** lets you load example documents (including a **planted bad one**) and ask: if someone searches like a user, does the **bad stuff** float to the top? It’s a **teaching aid**, not a full search engine—real RAG setups are more complex. |
| **Fingerprints of dependencies** | You can **upload lockfiles or bill-of-materials files** so you have a **record of what was submitted** (hashes, copies). It’s a **starting point** for “what did we ship?” conversations—not a full supply-chain product by itself. |

**Who is it for?**  
Engineers who want **guardrails** without building everything from scratch; security or compliance folks who want **logs and repeatable checks**; leaders who want **confidence** that AI features aren’t a black box.

**What it is *not*.**  
It’s not a replacement for your **lawyer**, your **cloud security team**, or **human review** of model outputs. It doesn’t “make AI safe” by itself—it **helps you enforce the rules you choose** and **prove you tested what you said you would**.

### How it interacts when it’s running (important context)

People often ask: *Does ASCP watch all our network traffic? Do users send documents to it?* **Short answers: no, and only if you wire that in.**

| Question | Plain answer |
|----------|----------------|
| **Does it monitor traffic passively?** | **No.** ASCP is not a tap on your firewall or a tool that silently reads everything on your network. If your app never talks to ASCP, ASCP sees **nothing**. |
| **So how does chat get checked?** | **You choose to send chat through it.** Your backend (or client config) points at ASCP’s **gateway URL** instead of going straight to OpenAI (or another provider). ASCP applies your rules, then forwards allowed requests. **No redirect = no gateway involvement.** |
| **Who sends what where?** | **Your servers** call ASCP for policy + proxy. **End-users** usually still talk to *your* app; your app is what calls the model—via ASCP if you set it up that way. |
| **What about the “red team” / assurance stuff?** | You give ASCP a **staging URL** (a copy of your app you control). ASCP’s service **calls that URL** with test prompts—like a **robot tester** knocking on your door. It’s **outbound from ASCP to you**, not eavesdropping on real customers. |
| **Do users upload documents to ASCP?** | **Not by default.** The **RAG lab** is where **you** (or a script) **upload example chunks** via the API to experiment with “what if a bad snippet were in the index?” Real user documents don’t flow into ASCP unless **you** build a pipeline that sends them—which this repo doesn’t do for you. |
| **Supply chain / lockfiles?** | **You upload** those files (or your CI does) on purpose—again, **explicit API upload**, not automatic scraping of your laptop or GitHub. |

**One-line summary:** ASCP is **opt-in plumbing** and **opt-in APIs**. You **turn the hoses** toward it for chat; you **push** test corpora and lockfiles when you want; you **point** assurance at a server **you** own. It does **not** sit in the background monitoring all traffic or all user documents unless **you** integrate it that way.

---

## What you get today

| Area | What it does |
|------|----------------|
| **Trust registry** | Per-tenant allowlist of **model IDs**. Unregistered models can be blocked. |
| **Policy documents (v1)** | JSON/YAML rules for **tools**: allowlist / denylist, block vs warn on violations. See [examples/policy.example.yaml](./examples/policy.example.yaml). |
| **Evaluation** | Chain: trust registry → document policy. Used by the API **evaluate** endpoint and the **gateway**. |
| **Operator HTTP API** | Policies, models, **evaluate**, **assurance runs**, **OpenAI-compatible gateway proxy**. |
| **Gateway** | `POST .../gateway/v1/chat/completions` — policy check, then **sync** or **`stream: true`** (SSE) forward to **`ASCP_UPSTREAM_*`**. |
| **Assurance runs** | **`builtin-v0`**; stub or live **`target_url`**. **Scoring:** pass rate, jailbreak/refusal + leak heuristics; **`min_pass_rate`** in run metadata (default 0.7). **`?fail_ci=true`** on execute → **422** if below threshold. **`replay_from_run_id`** copies target settings into a new run. |
| **Docker** | **`docker compose up --build`** (SQLite volume). Profile **`postgres`**: Postgres + API on port **8001** (`pip install ".[postgres]"` in image for PG URL). |
| **Postgres** | Set **`ASCP_DATABASE_URL=postgresql://...`** and **`pip install ".[postgres]"`** — same API, metadata in Postgres, artifacts still on disk. |
| **Tenant API keys** | **`POST /v1/admin/tenants/{id}/api-keys`** (needs **`ASCP_API_KEY`**) returns a one-time **`ascp_ten_...`** token. Use **Bearer** or **`X-ASCP-Tenant-Token`**; path tenant must match key’s tenant. |
| **Supply chain (stub)** | Upload lockfile: **`POST .../supply-chain/lockfile?filename=...`** (raw body) → SHA-256 + artifact. **`POST .../supply-chain/cyclonedx`** stores CycloneDX JSON blob. |
| **RAG lab (stub)** | **`PUT .../rag/corpora/{corpus_id}`** with **`chunks: [{chunk_id, text, is_poison}]`**. **`POST .../rag/corpora/{id}/evaluate`** keyword overlap “retrieval” + **`poison_in_top_k`**. |
| **Observability** | **`GET .../audit/export.jsonl`** (tenant-filtered NDJSON). Optional **`ASCP_AUDIT_WEBHOOK_URL`** POST on each audit append. See **[docs/OBSERVABILITY.md](./docs/OBSERVABILITY.md)**. |
| **Web dashboard** | **`GET /dashboard`** — tenant list and per-tenant overview (models, default policy, assurance runs, lockfiles, recent audit). When **`ASCP_API_KEY`** is set, use **HTTP Basic** (any username, password = API key). Skips JSON API auth middleware so the browser can prompt once. |
| **Demo tenants** | **`PYTHONPATH=src python scripts/seed_demo_tenants.py`** — seeds **`demo-fragile`** (super weak), **`demo-mixed`** (partial), **`demo-golden`** (strong) for the same DB as the API. |

**Roadmap:** S3 artifacts, full SBOM diffing, richer RAG/vector eval, richer dashboard, OTLP native export.

### Developer journey (PR CI)

End-to-end: **upload lockfiles** to ASCP + **assurance run** against staging; merge fails if score is below **`min_pass_rate`** (`execute?fail_ci=true`).

- **Guide:** **[docs/DEVELOPER_JOURNEY.md](./docs/DEVELOPER_JOURNEY.md)**
- **Copy-paste:** **[examples/developer-journey/github-actions-pr.yml](./examples/developer-journey/github-actions-pr.yml)** → your app repo’s `.github/workflows/`
- **Script (stdlib):** `python3 examples/developer-journey/ascp_pr_checks.py`

---

## Requirements

- **Python 3.11+**

---

## Install

**Library only** (policy types, engines, SQLite backend, YAML policies, assurance runner—usable from your own code):

```bash
pip install -e .          # from repo root, after clone
# or eventually: pip install ascp
```

**Operator API + gateway** (FastAPI + Uvicorn):

```bash
pip install -e ".[api]"
# Postgres metadata: pip install -e ".[api,postgres]"
# dev/tests: pip install -e ".[dev]"
```

---

## Run the API server

```bash
export ASCP_DATABASE_URL="sqlite:///./ascp.db"
export ASCP_ARTIFACT_ROOT="./ascp_artifacts"
# Gateway: forward allowed traffic to OpenAI-compatible API
export ASCP_UPSTREAM_BASE_URL="https://api.openai.com/v1"
export ASCP_UPSTREAM_API_KEY="sk-..."   # upstream provider key (keep secret)

# Optional: lock down the operator API (health check stays open)
# export ASCP_API_KEY="your-operator-secret"

ascp-serve
# Listens on 0.0.0.0:8000 by default
```

**Docker**

```bash
docker compose up --build
# Data under volume ./ascp-data (mapped in compose). Postgres profile: docker compose --profile postgres up --build
```

Configuration uses **`ASCP_*`** environment variables (and optional `.env`). See **`ascp.config.Settings`** for the full list (timeouts, assurance target auth, log level, etc.).

---

## Using it (quick flows)

Replace `TENANT`, `HOST` (e.g. `http://127.0.0.1:8000`), and add headers if **`ASCP_API_KEY`** is set:

`Authorization: Bearer <key>` or `X-ASCP-API-Key: <key>`.

### 1. Register a model and install a policy

```bash
# Policy document (tools: allowlist example)
curl -X PUT "$HOST/v1/tenants/$TENANT/policies/default/versions/v1" \
  -H "Content-Type: application/json" \
  -d '{"schema_version":"1","tools":{"mode":"allowlist","allowed":["search","read_file"],"deny":["execute_shell"],"on_violation":"block"}}'

curl -X POST "$HOST/v1/tenants/$TENANT/models" \
  -H "Content-Type: application/json" \
  -d '{"model_id":"gpt-4o"}'
```

### 2. Evaluate a decision (no LLM call)

```bash
curl -X POST "$HOST/v1/tenants/$TENANT/evaluate" \
  -H "Content-Type: application/json" \
  -d '{"policy_id":"default","policy_version":"v1","model_id":"gpt-4o","tools_invoked":["search"],"audit":true}'
```

### 3. Chat via the gateway (policy → upstream)

Point your app at ASCP instead of the provider directly:

`POST $HOST/v1/tenants/$TENANT/gateway/v1/chat/completions?policy_id=default&policy_version=v1`

Same JSON body as OpenAI **chat completions** (must include **`model`**). Blocked requests return **403** with violation details.

### 4. Assurance run (stub vs live)

```bash
# List suites
curl "$HOST/v1/assurance/suites"

# Stub run (no HTTP to a target)
curl -X POST "$HOST/v1/tenants/$TENANT/assurance-runs" \
  -H "Content-Type: application/json" \
  -d '{"suite":"builtin-v0"}'
# → run_id; then:
curl -X POST "$HOST/v1/tenants/$TENANT/assurance-runs/<run_id>/execute"

# Live run: POST each scenario to your staging chat URL
curl -X POST "$HOST/v1/tenants/$TENANT/assurance-runs" \
  -H "Content-Type: application/json" \
  -d '{"suite":"builtin-v0","metadata":{"target_url":"https://your-staging.example/v1/chat/completions","target_model":"gpt-4o-mini"}}'
# Optional: ASCP_ASSURANCE_TARGET_AUTHORIZATION on server for Bearer to staging
curl -X POST "$HOST/v1/tenants/$TENANT/assurance-runs/<run_id>/execute"
```

Reports land under artifact keys like **`assurance/<run_id>/report.json`** (on disk under **`ASCP_ARTIFACT_ROOT`**).

---

## Python library (skipping HTTP)

```python
from ascp import SqliteFsBackend, PolicyRef, PolicyEvaluationContext
from ascp.policy import ChainedPolicyEngine, TrustRegistryPolicyEngine, DocumentPolicyEngine

backend = SqliteFsBackend("sqlite:///./ascp.db", artifact_root="./ascp_artifacts")
backend.register_model("my-tenant", "gpt-4o")
backend.put_policy_document(
    PolicyRef(tenant_id="my-tenant", policy_id="default", version="v1"),
    {"schema_version": "1", "tools": {"mode": "open"}},
)
chain = ChainedPolicyEngine(
    TrustRegistryPolicyEngine(backend),
    DocumentPolicyEngine(backend, policy_ref=PolicyRef(tenant_id="my-tenant", policy_id="default", version="v1")),
)
decision = chain.evaluate(
    PolicyEvaluationContext(tenant_id="my-tenant", model_id="gpt-4o", extra={"tools_invoked": ["search"]})
)
print(decision.outcome, decision.violations)
```

---

## Tests

```bash
pip install -e ".[dev]"
PYTHONPATH=src python -m pytest tests/ -q
```

---

## Admin & tenant tokens

With **`ASCP_API_KEY`** set, use it as **Bearer** for all routes, **or** create per-tenant keys:

```bash
curl -X POST "$HOST/v1/admin/tenants/$TENANT/api-keys" \
  -H "Authorization: Bearer $ASCP_API_KEY" -H "Content-Type: application/json" \
  -d '{"name":"ci"}'
# Save the returned "token"; then:
curl "$HOST/v1/tenants/$TENANT/models" -H "Authorization: Bearer ascp_ten_...."
```

## Roadmap (abbrev.)

- S3/GCS artifacts; vector RAG eval; OTLP; Helm; responsible-use docs for offensive scenarios. See **[prd.md](./prd.md)**.

---

## License

MIT (see [pyproject.toml](./pyproject.toml)).
