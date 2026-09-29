# Project Sentinel — Build Plan

Production-grade AI transaction investigation platform (M37 Labs take-home).
This file is the working plan. Each phase ends with passing tests, updated docs,
and the matching sections of [ASSIGNMENT_ANSWERS.md](ASSIGNMENT_ANSWERS.md) filled in.

## Working Agreement

- No file is created or changed without explicit approval.
- Every approved change is committed and pushed immediately, so no work is lost.
- A phase is "done" only when its exit criteria pass and its answers are written.
- Answers in `ASSIGNMENT_ANSWERS.md` describe what is built, never what is planned.

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
| Embeddings | OpenRouter embeddings API (model TBC in Phase 4) | Behind `Embedder` interface; `FakeEmbedder` for tests |
| Tooling | uv, ruff, mypy, pytest, testcontainers, Alembic | |
| Delivery | Docker Compose, Kubernetes (kustomize), GitHub Actions | |

## Phases

### Phase 0 — Foundations
Spec: §22.1, §23 (partial), §27 (skeletons)

- [x] `README.md` skeleton linking `plan.md` and `ASSIGNMENT_ANSWERS.md`
- [x] `ASSIGNMENT_ANSWERS.md` skeleton — all questions listed, marked *pending*
- [x] `docs/decisions.md` with initial stack decisions
- [ ] `pyproject.toml`, `uv.lock`, ruff/mypy/pytest configuration
- [ ] `src/sentinel/` package skeleton, `config.py`
- [ ] `docker-compose.yml`: postgres (pgvector), redpanda, redis
- [ ] `.env.example`, `.gitignore`, `.dockerignore`, `Makefile`
- [ ] Minimal CI: lint + unit tests

**Exit:** `docker compose up` brings infrastructure up healthy; CI green.

### Phase 1 — Ingestion, Idempotency & Transaction State
Spec: §4, §5, §14, §15

- [ ] Schema + migrations: tenants, users, events, transactions (tenant-scoped)
- [ ] Event schemas with validation; malformed events rejected/quarantined
- [ ] `POST /events` → Redpanda (partition key = tenant + transaction)
- [ ] Event consumer: dedupe insert + state rebuild in one DB transaction; offset committed after DB commit
- [ ] Order-independent state reducer (`domain/transaction_state.py`)
- [ ] `GET /transactions/{id}`

**Tests:** duplicate event ×10 → one logical result; settlement → ledger → payment → correct state; malformed event handling.
**Answers:** Q1, Q2, Q10 (partial), Q11.

### Phase 2 — Reconciliation & Investigation Creation
Spec: §6, §7, §16 (priority)

- [ ] Rule interface + self-registering registry
- [ ] Rules: missing ledger, settlement mismatch, duplicate capture, missing settlement (configurable threshold), refund mismatch
- [ ] `reconciliation_results` table
- [ ] Investigations table with partial unique index on (tenant, transaction, anomaly type) WHERE active
- [ ] Race-safe creation (`INSERT … ON CONFLICT DO NOTHING`)
- [ ] Priority scoring (LOW → CRITICAL)
- [ ] `audit_logs` table + audit service

**Tests:** each rule in isolation; two concurrent creators → exactly one active investigation.
**Answers:** Q3, Q4.

### Phase 3 — Workflow Engine & Crash Recovery
Spec: §8, §9, §21, §22.3, §26

- [ ] `investigation_steps` table; state machine with allowed transitions
- [ ] Worker claims jobs with `SKIP LOCKED`, lease + heartbeat
- [ ] Checkpoint after every step; LLM response persisted before report commit
- [ ] Scheduler reclaims expired leases
- [ ] `FAIL_AFTER_STEP` failure injection
- [ ] SIGTERM: stop claiming, finish or release current step
- [ ] `Investigator` interface + `MockInvestigator`

**Tests:** kill worker after LLM response, before report commit → recovers, no duplicates, no hang.
**Answers:** Q5, Q16.

### Phase 4 — Knowledge Base, Retrieval & AI Investigator
Spec: §10, §11, §18

- [ ] 15+ KB documents with front-matter metadata (tenant_id, document_type, gateway, effective_date)
- [ ] Adversarial documents (instruction override, source-of-truth override)
- [ ] Chunking, embeddings, `documents` / `document_chunks` tables with pgvector
- [ ] Hybrid retrieval (vector + full-text) with mandatory tenant filter; reranking (bonus)
- [ ] OpenRouter LLM client + `OpenRouterInvestigator`
- [ ] Structured output schema (facts / hypotheses / recommendation), safe parsing
- [ ] Grounding verifier: every fact cites a real event/chunk; amounts cross-checked against DB

**Tests:** cross-tenant retrieval denied; malformed LLM output handled without state corruption; prompt injection ignored.
**Answers:** Q6, Q7, Q8, Q14.

### Phase 5 — Human Review, RBAC & Security
Spec: §12, §13

- [ ] Auth (API keys/JWT → user, tenant, role)
- [ ] Server-side RBAC: VIEWER, INVESTIGATOR, ADMIN
- [ ] `GET /investigations`, `GET /investigations/{id}`, approve, reject, retry
- [ ] Full audit coverage (actor, tenant, entity, action, timestamp)
- [ ] `docs/security.md`

**Tests:** tenant A → tenant B resources denied; role permission matrix.
**Answers:** Q9.

### Phase 6 — Resilience Under Load & Observability
Spec: §16, §17, §19, §20

- [ ] LLM fault simulator: timeout, 429, 500, malformed JSON, empty, slow
- [ ] Bounded retries with exponential backoff + jitter
- [ ] Dead-letter records + inspection endpoint
- [ ] Priority-aware job claiming; Redis token bucket for LLM rate
- [ ] Backpressure strategy (queue growth, consumer concurrency, throttling)
- [ ] `/metrics` with all required metrics; structured JSON logs with correlation IDs
- [ ] Load generator (100k+ events) + `docs/load-test-report.md`

**Tests:** repeated LLM failures → DLQ, inspectable, retryable.
**Answers:** Q12, Q13, Q15.

### Phase 7 — Deployment & CI
Spec: §22, §23

- [ ] Production Dockerfile (multi-stage, non-root)
- [ ] Full compose: api, event-consumer, investigation-worker, scheduler + infra
- [ ] Kubernetes manifests: probes, requests/limits, config/secrets
- [ ] CI: lint → unit → integration → container build

**Exit:** `docker compose up` runs the whole system; CI green end to end.

### Phase 8 — Evaluation, Demo & Final Documentation
Spec: §25, §27, §28, §30, §31, §32

- [ ] 20+ eval scenarios; runner reporting accuracy, citation correctness, unsupported-claim rate (+ latency/cost)
- [ ] `docs/eval-report.md`
- [ ] `scripts/demo.sh` (happy path) and `scripts/crash_demo.sh` (kill + recover)
- [ ] Final `docs/architecture.md`, `docs/failure-model.md`
- [ ] Implemented / simplified / omitted / productionization section
- [ ] 1B events/day scaling section

**Answers:** Q17–Q21.

## Answers Map

| Q | Spec § | Topic | Phase |
|---|---|---|---|
| 1 | §5 | Durable idempotency & eventual consistency | 1 |
| 2 | §4.1 | Duplicate / delayed / out-of-order / malformed / redelivery / crash | 1 |
| 3 | §6 | Rule engine extensibility | 2 |
| 4 | §7 | One active investigation under concurrency | 2 |
| 5 | §8, §9 | Workflow state machine & crash recovery | 3 |
| 6 | §10 | Tenant isolation in retrieval | 4 |
| 7 | §11.1, §11.2 | Fact vs hypothesis; deterministic vs AI | 4 |
| 8 | §11.3 | Invalid / malformed model output | 4 |
| 9 | §13 | RBAC & audit enforcement | 5 |
| 10 | §14 | Indexes, constraints, transaction boundaries | 1–2 |
| 11 | §15 | Commit-then-crash-before-ack; where "exactly once" holds | 1 |
| 12 | §16 | Backpressure, priority, rate limiting, retries | 6 |
| 13 | §17 | LLM failure handling & dead-lettering | 6 |
| 14 | §18 | Prompt injection & source of truth | 4 |
| 15 | §20 | Load test results & first bottleneck | 6 |
| 16 | §22.3 | SIGTERM mid-investigation | 3 |
| 17 | §25 | AI evaluation results | 8 |
| 18 | §27 | Component rationale; strong vs eventual consistency | 8 |
| 19 | §28 | Failure model per dependency | 8 |
| 20 | §31 | Implemented / simplified / omitted / productionization | 8 |
| 21 | §32 | 1B events/day: first five changes | 8 |

## Project Structure

```
project-sentinel/
├── README.md                     # Overview, quickstart, demo steps, links to plan and answers
├── plan.md                       # Phased build plan with a checklist per phase
├── ASSIGNMENT_ANSWERS.md         # Answers to every question in the assignment PDF
├── pyproject.toml                # Dependencies + ruff/mypy/pytest config (uv)
├── uv.lock
├── alembic.ini
├── Makefile                      # make up / test / lint / demo / load-test / eval
├── Dockerfile                    # One image; API or worker chosen by command
├── docker-compose.yml            # api, workers, postgres(pgvector), redpanda, redis
├── .env.example                  # OPENROUTER_API_KEY, model names, FAIL_AFTER_STEP, ...
├── .gitignore
├── .dockerignore
│
├── .github/workflows/
│   └── ci.yml                    # lint → unit → integration → docker build
│
├── docs/
│   ├── architecture.md
│   ├── failure-model.md
│   ├── security.md
│   ├── decisions.md              # Why each technology was chosen (ADR style)
│   ├── load-test-report.md
│   └── eval-report.md
│
├── src/sentinel/                 # ← all application code
│   ├── __init__.py
│   ├── config.py                 # Typed settings loaded from env
│   │
│   ├── api/                      # HTTP layer: validation, auth, calls services
│   │   ├── main.py               # FastAPI app factory, startup/shutdown
│   │   ├── deps.py               # DB session, current user, tenant context
│   │   ├── middleware.py         # request_id, structured request logging
│   │   └── routes/
│   │       ├── events.py         # POST /events
│   │       ├── transactions.py   # GET /transactions/{id}
│   │       ├── investigations.py # list/get/approve/reject/retry
│   │       ├── dead_letters.py   # inspect dead-lettered jobs
│   │       ├── health.py         # liveness / readiness
│   │       └── metrics.py        # GET /metrics
│   │
│   ├── auth/
│   │   ├── tokens.py             # API key / JWT → user, tenant, role
│   │   └── rbac.py               # VIEWER / INVESTIGATOR / ADMIN permission checks
│   │
│   ├── domain/                   # Pure logic, no I/O (easy to unit test)
│   │   ├── enums.py              # sources, event types, statuses, severity, priority
│   │   ├── events.py             # Pydantic event schemas + validation
│   │   ├── transaction_state.py  # Rebuilds state from events; arrival order doesn't matter
│   │   └── priority.py           # Scores LOW..CRITICAL (amount, anomaly, age, tenant policy)
│   │
│   ├── reconciliation/
│   │   ├── base.py               # Rule interface + RuleResult
│   │   ├── registry.py           # Rules register themselves (no if/elif chain)
│   │   ├── engine.py             # Runs all rules against a transaction state
│   │   └── rules/
│   │       ├── missing_ledger.py
│   │       ├── settlement_mismatch.py
│   │       ├── duplicate_capture.py
│   │       ├── missing_settlement.py
│   │       └── refund_mismatch.py
│   │
│   ├── services/                 # Use cases; each owns its DB transaction boundary
│   │   ├── ingestion.py          # store event + update state in one DB transaction
│   │   ├── reconciliation.py     # run rules, store results
│   │   ├── investigations.py     # create investigation (race-safe), retry
│   │   ├── review.py             # approve / reject
│   │   └── audit.py              # write audit log entries
│   │
│   ├── db/
│   │   ├── session.py            # async engine + session factory
│   │   ├── models.py             # tables, indexes, unique + partial constraints
│   │   ├── repositories/         # every query takes tenant_id
│   │   │   ├── events.py
│   │   │   ├── transactions.py
│   │   │   ├── investigations.py
│   │   │   ├── documents.py
│   │   │   └── audit_logs.py
│   │   └── migrations/
│   │       ├── env.py
│   │       └── versions/
│   │
│   ├── messaging/
│   │   ├── topics.py             # topic names, partition key = tenant+transaction
│   │   ├── producer.py
│   │   └── consumer.py           # at-least-once, commits offset only after the DB commit
│   │
│   ├── workers/                  # Entry points for long-running processes
│   │   ├── event_consumer.py     # broker → ingestion → reconciliation → investigation
│   │   ├── investigation_worker.py # claims jobs (SKIP LOCKED), lease + heartbeat
│   │   ├── scheduler.py          # expired leases, missing-settlement timer, retry backoff
│   │   └── shutdown.py           # SIGTERM: stop claiming, finish/release current step
│   │
│   ├── workflow/
│   │   ├── states.py             # STARTED → … → COMPLETED + allowed transitions
│   │   ├── engine.py             # runs steps, saves a checkpoint after each step
│   │   ├── steps.py              # collect data, collect events, retrieve, analyze, verify
│   │   ├── failure_injection.py  # FAIL_AFTER_STEP=LLM_RESPONSE / RETRIEVAL / ...
│   │   └── dead_letter.py        # retry limit reached → DLQ record (inspectable)
│   │
│   ├── retrieval/
│   │   ├── loader.py             # reads KB markdown + front-matter metadata
│   │   ├── chunking.py
│   │   ├── embeddings.py         # Embedder interface: OpenRouterEmbedder, FakeEmbedder
│   │   ├── indexer.py            # chunks → embeddings → document_chunks
│   │   ├── search.py             # hybrid pgvector + full-text, tenant filter always applied
│   │   └── rerank.py             # bonus
│   │
│   ├── ai/
│   │   ├── investigator.py       # Investigator interface
│   │   ├── openrouter_investigator.py
│   │   ├── mock_investigator.py  # deterministic, used by tests + eval baseline
│   │   ├── llm_client.py         # OpenAI SDK + OpenRouter base_url, timeouts, backoff
│   │   ├── fault_simulator.py    # simulates 429 / 500 / timeout / bad JSON / empty / slow
│   │   ├── prompts.py            # system prompt; retrieved text wrapped as untrusted data
│   │   ├── schemas.py            # InvestigationReport (facts / hypotheses / action)
│   │   ├── parsing.py            # safe parse + validate, never partial writes
│   │   └── grounding.py          # every fact must cite a real event/chunk; amounts checked against DB
│   │
│   ├── ratelimit/
│   │   └── token_bucket.py       # Redis-based LLM throttle (20/s) with priority handling
│   │
│   └── observability/
│       ├── logging.py            # JSON logs with request/tenant/txn/event/investigation/worker ids
│       └── metrics.py            # all Prometheus counters/histograms from §19
│
├── knowledge_base/               # Data, not code: markdown + YAML front-matter
│   ├── global/                   # runbooks, policies, settlement rules, refund procedures
│   ├── merchant_123/             # tenant-private docs + incident reports
│   ├── merchant_456/
│   └── adversarial/              # "ignore all instructions…", "always mark reconciled…"
│
├── eval/
│   ├── scenarios/                # 20+ JSON scenarios (events + expected classification)
│   ├── run_eval.py
│   ├── metrics.py                # accuracy, citation correctness, unsupported-claim rate
│   └── results/
│
├── scripts/                      # Thin CLIs that call into src/sentinel
│   ├── seed.py                   # tenants, users, API keys
│   ├── ingest_kb.py
│   ├── load_generator.py         # 100k+ events: healthy, mismatches, duplicates, out-of-order
│   ├── demo.sh                   # happy path end-to-end
│   └── crash_demo.sh             # kill worker mid-investigation, restart, show recovery
│
├── deploy/k8s/
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secret.example.yaml
│   ├── api.yaml                  # Deployment + Service, probes, requests/limits
│   ├── event-consumer.yaml
│   ├── investigation-worker.yaml
│   ├── scheduler.yaml
│   ├── redis.yaml
│   └── redpanda.yaml             # Postgres assumed external (per spec)
│
└── tests/
    ├── conftest.py               # testcontainers: postgres + redpanda + redis
    ├── fixtures/
    ├── unit/
    │   ├── test_transaction_state.py
    │   ├── test_rules.py
    │   ├── test_priority.py
    │   ├── test_parsing.py
    │   ├── test_grounding.py
    │   └── test_chunking.py
    └── integration/              # the 7 mandatory tests + extras
        ├── test_duplicate_event.py
        ├── test_out_of_order.py
        ├── test_concurrency.py
        ├── test_worker_crash.py
        ├── test_tenant_isolation.py
        ├── test_malformed_llm_output.py
        ├── test_prompt_injection.py
        ├── test_llm_failures_dlq.py
        └── test_rbac.py
```
