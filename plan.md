# Project Sentinel — Build Plan

Production-grade AI transaction investigation platform (M37 Labs take-home).
This file is the working plan. Each phase ends with passing tests, updated docs,
and the matching sections of [ASSIGNMENT_ANSWERS.md](ASSIGNMENT_ANSWERS.md) filled in.

## Working Agreement

- No file is created or changed without explicit approval.
- Every approved change is committed and pushed immediately, so no work is lost.
- A phase is "done" only when its exit criteria pass and its answers are written.
- Answers in `ASSIGNMENT_ANSWERS.md` describe what is built, never what is planned.
- From Phase 1 on, every completed phase leaves `docker compose up` running the full
  system built so far, verifiable on the VPS.
- Build one feature at a time, in the order of the assignment brief. Get each feature
  working end to end with sensible defaults first; concurrency and failure hardening
  come in Phase 9.
- Zero-cost safeguards go in from day one: `tenant_id` on every table, durable unique
  keys, exact decimal amounts, broker offsets committed after the DB commit.
- Keep it lean: no layer or file without a present use.

## Tech Stack

| Concern | Choice | Rationale |
|---|---|---|
| Language / API | Python 3.12, FastAPI | Pydantic-native, free OpenAPI/Swagger UI |
| Message broker | Redpanda (Kafka API) | Preferred by spec; single binary; partitioned ordering |
| Database | PostgreSQL 16 + pgvector | One source of truth for state and vectors; tenant filtering in SQL |
| Idempotency | `UNIQUE (tenant_id, event_id)` in Postgres | Durable; committed atomically with the state update |
| Investigation uniqueness | Partial unique index on active investigations | Race safety enforced by the database, not app locks |
| Workflow | DB-backed state machine, leases + heartbeats, `FOR UPDATE SKIP LOCKED` | Explicit, demonstrable crash recovery |
| Cache / rate limiting | Redis | Token bucket for LLM throughput; never used for correctness |
| LLM | OpenRouter via OpenAI SDK (`base_url` override) | Provider-agnostic; model is config |
| Embeddings | OpenRouter embeddings API (model TBC in Phase 6) | Behind `Embedder` interface; `FakeEmbedder` for tests |
| Tooling | uv, ruff, mypy, pytest, Alembic | Integration tests run against the compose stack |
| Delivery | Docker Compose, Kubernetes (kustomize), GitHub Actions | |

## Deployment Target (VPS)

The system is deployed with Docker Compose on a shared VPS after each phase.

- **Host:** x86_64, 4 vCPU, 8 GB RAM — already ~5 GB used and swapping, so
  Sentinel must stay within a hard memory budget.
- **Ingress:** existing Cloudflare setup routes a subdomain to the API; only the
  API is ever reachable from outside. Postgres, Redis and Redpanda are never
  published (Docker bypasses `ufw`).
- **LLM:** the deployed system uses OpenRouter; the mock is for tests/CI only.
- **Load testing** runs off the VPS (laptop or CI), never on the shared host.

| Service | Memory limit | Tuning |
|---|---|---|
| Redpanda | 1 GB | `--smp 1 --memory 768M --overprovisioned` |
| PostgreSQL + pgvector | 384 MB | `shared_buffers=128MB`, `max_connections=50` |
| Redis | 64 MB | `maxmemory 48mb` |
| API | 256 MB | 1 uvicorn worker |
| Event consumer | 256 MB | |
| Investigation worker | 256 MB | |
| Scheduler | 128 MB | Added in Phase 3 |
| **Total ceiling** | **~2.3 GB** | Typical idle ~1.5 GB |

## Phases

### Phase 0 — Foundations ✅
Spec: §22.1, §23 (partial), §27 (skeletons)

- [x] `README.md` skeleton linking `plan.md` and `ASSIGNMENT_ANSWERS.md`
- [x] `ASSIGNMENT_ANSWERS.md` skeleton — all questions listed, marked *pending*
- [x] `docs/decisions.md` with initial stack decisions
- [x] `pyproject.toml`, `uv.lock`, ruff/mypy/pytest configuration
- [x] `src/sentinel/` package skeleton, `config.py`
- [x] `.gitignore`
- [x] `docker-compose.yml` (secure base, no published ports), `docker-compose.dev.yml`,
      `docker-compose.vps.yml`
- [x] `.env.example`, `.dockerignore`, `Makefile`
- [x] Minimal CI: lint + unit tests (frozen until Phase 11)

### Phase 1 — Event Ingestion (§4) ✅

- [x] Event schema: enums for source/type, Pydantic `EventIn` validation
- [x] Migration `0001`: `tenants` (seeded: merchant_123, merchant_456), `events`
      with `UNIQUE (tenant_id, event_id)` and index on `(tenant_id, transaction_id)`
- [x] `POST /events` → 422 on malformed, else produce to `sentinel.events`
      (key = `tenant_id:transaction_id`) → 202
- [x] Event consumer: insert with `ON CONFLICT DO NOTHING`, commit offset after DB commit
- [x] `GET /events?tenant_id=&transaction_id=`, `GET /health`
- [x] Dockerfile; compose services `migrate`, `api`, `event-consumer`

**Done when:** `docker compose up` → POST an event → GET shows it; posting it twice
still shows one row. Unit test for validation, one integration test against compose.

### Phase 2 — Idempotency & Transaction State (§5) ✅

- [x] `transactions` table (materialized state per tenant + transaction)
- [x] Order-independent state reducer (`domain/transaction_state.py`)
- [x] Event insert + state update in one DB transaction; duplicates skip the update
- [x] `GET /transactions/{id}`

**Done when:** out-of-order and duplicate events produce the correct final state.

### Phase 3 — Reconciliation Engine (§6) ✅

- [x] Rule interface + decorator registry; rule modules auto-discovered
- [x] Rules: missing ledger, ledger mismatch, settlement mismatch, duplicate capture,
      missing settlement (configurable threshold), refund mismatch
- [x] `reconciliation_results` (one row per transaction + anomaly, OPEN/RESOLVED);
      overall state is DISCREPANCY iff a finding is open
- [x] Grace periods measured from arrival time (no false alarms on late delivery);
      missing-settlement deadline measured from capture time
- [x] Scheduler worker re-reconciles unfinished transactions for time-based rules
- [x] `audit_logs` (append-only, same DB transaction as the change): EVENT_RECEIVED,
      DISCREPANCY_DETECTED, DISCREPANCY_RESOLVED
- [x] JSON logs on stdout with service, worker_id, request_id, tenant/transaction/event ids
- [x] `GET /reconciliation-results`, `GET /audit-logs`, findings on `GET /transactions/{id}`

**Done when:** each rule has a unit test; mismatched transactions show results via API.

### Phase 4 — Investigation Creation (§7) ✅

- [x] `investigations` table with partial unique index on
      (tenant, transaction, anomaly type) WHERE `closed_at IS NULL`
- [x] Created with the finding, in the same DB transaction (`INSERT … ON CONFLICT DO NOTHING`)
- [x] Auto-resolved (`AUTO_RESOLVED`) when the finding resolves before work starts
- [x] Priority scoring (LOW → CRITICAL) from anomaly, severity and amount
- [x] Audit: INVESTIGATION_CREATED, INVESTIGATION_AUTO_RESOLVED
- [x] `GET /investigations`, `GET /investigations/{id}` (tenant-scoped)

**Done when:** a mismatch opens exactly one investigation, visible via API.

### Phase 5 — Investigation Workflow & Crash Recovery (§8, §9)

- [ ] `investigation_steps` table; state machine STARTED → … → COMPLETED
- [ ] Investigation worker: claims jobs, checkpoints after each step
- [ ] Mock investigator behind the `Investigator` interface
- [ ] Lease expiry + reclaim so a killed worker's job resumes
- [ ] `FAIL_AFTER_STEP` failure injection; SIGTERM handling

**Done when:** killing the worker after the LLM step and restarting it completes
the investigation with no duplicate.

### Phase 6 — Knowledge Base & Retrieval (§10)

- [ ] 15+ markdown documents with front-matter metadata, incl. adversarial ones
- [ ] `documents` / `document_chunks` with pgvector; chunking + OpenRouter embeddings
- [ ] Hybrid search (vector + full-text) with mandatory tenant filter

**Done when:** retrieval returns relevant chunks and never another tenant's.

### Phase 7 — AI Investigator (§11)

- [ ] OpenRouter client + `OpenRouterInvestigator`
- [ ] Structured report schema (facts / hypotheses / recommendation) + safe parsing
- [ ] Grounding check: every fact cites a real event or chunk

**Done when:** a real mismatch produces a validated, evidence-backed report.

### Phase 8 — Review APIs, Multi-Tenancy, RBAC & Audit (§12, §13)

- [ ] API-key auth → user, tenant, role (VIEWER / INVESTIGATOR / ADMIN)
- [ ] `GET /investigations`, `GET /investigations/{id}`, approve, reject, retry
- [ ] Tenant scoping on every endpoint; extend `audit_logs` to user actions

**Done when:** tenant A cannot see tenant B's data; roles are enforced server-side.

### Phase 9 — Hardening (§14–§18)

- [ ] Concurrency: two workers creating the same investigation → one active
- [ ] Delivery semantics: commit-then-crash-before-ack documented and tested
- [ ] Backpressure: priority claiming, Redis token bucket for LLM rate, retry policy
- [ ] LLM fault simulator (timeout, 429, 500, malformed, empty, slow), bounded
      backoff, dead-letter records + inspection endpoint
- [ ] Prompt-injection defences verified against adversarial documents
- [ ] Malformed events dead-lettered instead of dropped

### Phase 10 — Observability, Load & Failure Injection (§19–§21)

- [ ] `/metrics` with all required metrics (JSON logs already in place since Phase 3)
- [ ] Load generator (100k+ events), run off the VPS; `docs/load-test-report.md`

### Phase 11 — Kubernetes & CI (§22–§23)

- [ ] Dockerfile hardening (multi-stage, non-root)
- [ ] Kubernetes manifests: probes, requests/limits, config/secrets
- [ ] CI: lint → unit → integration → container build
- [ ] `docs/deployment-vps.md` + README "Deploy to a VPS" section

### Phase 12 — Tests, Evaluation, Docs & Demo (§24–§32)

- [ ] All 7 mandatory tests present and passing
- [ ] 20+ eval scenarios + `docs/eval-report.md`
- [ ] `scripts/demo.sh` and `scripts/crash_demo.sh`
- [ ] `docs/architecture.md`, `docs/failure-model.md`, `docs/security.md`
- [ ] Implemented / simplified / omitted section; 1B events/day section

## Answers Map

| Q | Spec § | Topic | Phase |
|---|---|---|---|
| 1 | §5 | Durable idempotency & eventual consistency | 2 |
| 2 | §4.1 | Duplicate / delayed / out-of-order / malformed / redelivery / crash | 1–2, 9 |
| 3 | §6 | Rule engine extensibility | 3 |
| 4 | §7 | One active investigation under concurrency | 4, 9 |
| 5 | §8, §9 | Workflow state machine & crash recovery | 5 |
| 6 | §10 | Tenant isolation in retrieval | 6 |
| 7 | §11.1, §11.2 | Fact vs hypothesis; deterministic vs AI | 7 |
| 8 | §11.3 | Invalid / malformed model output | 7 |
| 9 | §13 | RBAC & audit enforcement | 8 |
| 10 | §14 | Indexes, constraints, transaction boundaries | 1–5 |
| 11 | §15 | Commit-then-crash-before-ack; where "exactly once" holds | 9 |
| 12 | §16 | Backpressure, priority, rate limiting, retries | 9 |
| 13 | §17 | LLM failure handling & dead-lettering | 9 |
| 14 | §18 | Prompt injection & source of truth | 9 |
| 15 | §20 | Load test results & first bottleneck | 10 |
| 16 | §22.3 | SIGTERM mid-investigation | 5 |
| 17 | §25 | AI evaluation results | 12 |
| 18 | §27 | Component rationale; strong vs eventual consistency | 12 |
| 19 | §28 | Failure model per dependency | 12 |
| 20 | §31 | Implemented / simplified / omitted / productionization | 12 |
| 21 | §32 | 1B events/day: first five changes | 12 |

## Project Structure

Files are created only when the phase that needs them starts.

```
project-sentinel/
├── README.md
├── plan.md
├── ASSIGNMENT_ANSWERS.md
├── pyproject.toml / uv.lock
├── alembic.ini
├── Makefile
├── Dockerfile                    # One image; API or worker chosen by command
├── docker-compose.yml            # secure base (no published ports)
├── docker-compose.dev.yml        # local dev: publishes ports on 127.0.0.1
├── docker-compose.vps.yml        # VPS: memory limits
├── .env.example
├── .github/workflows/ci.yml
│
├── docs/
│   ├── decisions.md              # ADRs
│   ├── architecture.md
│   ├── failure-model.md
│   ├── security.md
│   ├── deployment-vps.md
│   ├── load-test-report.md
│   └── eval-report.md
│
├── src/sentinel/
│   ├── config.py                 # Typed settings from env
│   ├── api/
│   │   ├── main.py               # FastAPI app
│   │   ├── auth.py               # API keys → user/tenant/role; RBAC checks
│   │   └── routes/               # events, transactions, investigations, dead_letters, health, metrics
│   ├── domain/                   # Pure logic, no I/O
│   │   ├── events.py             # enums + Pydantic event schema
│   │   ├── transaction_state.py  # order-independent reducer
│   │   └── priority.py
│   ├── reconciliation/
│   │   ├── base.py / registry.py / engine.py
│   │   └── rules/                # one file per rule
│   ├── services/                 # Use cases; own their SQL and DB transaction boundary
│   │   ├── ingestion.py
│   │   ├── reconciliation.py
│   │   ├── investigations.py
│   │   ├── review.py
│   │   └── audit.py
│   ├── db/
│   │   ├── session.py
│   │   ├── models.py
│   │   └── migrations/
│   ├── messaging/
│   │   └── kafka.py              # producer + consumer helpers, topic names
│   ├── workers/
│   │   ├── base.py               # run loop + SIGTERM handling
│   │   ├── event_consumer.py
│   │   ├── investigation_worker.py
│   │   └── scheduler.py          # lease reclaim, missing-settlement timer
│   ├── workflow/
│   │   ├── states.py / engine.py / steps.py
│   │   ├── failure_injection.py  # FAIL_AFTER_STEP
│   │   └── dead_letter.py
│   ├── retrieval/
│   │   ├── chunking.py
│   │   ├── embeddings.py         # Embedder interface: OpenRouter + fake
│   │   ├── indexer.py            # load KB → chunk → embed → store
│   │   └── search.py             # hybrid search, tenant filter always applied
│   ├── ai/
│   │   ├── investigator.py       # interface + mock
│   │   ├── openrouter_investigator.py
│   │   ├── llm_client.py
│   │   ├── fault_simulator.py
│   │   ├── prompts.py
│   │   ├── schemas.py            # report model + safe parsing
│   │   ├── grounding.py
│   │   └── ratelimit.py          # Redis token bucket
│   └── observability/
│       ├── logging.py
│       └── metrics.py
│
├── knowledge_base/               # markdown + front-matter (global/, merchant_*/, adversarial/)
├── eval/                         # scenarios/, run_eval.py, results/
├── scripts/                      # seed, load_generator, demo, crash_demo
├── deploy/k8s/                   # kustomize manifests
└── tests/
    ├── unit/
    └── integration/              # run against the compose stack
```
