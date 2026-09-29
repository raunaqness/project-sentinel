# Architecture Decision Records

Each record captures one significant decision: the context, what we chose,
what we rejected, and the consequences we accept.

| ADR | Decision | Status |
|---|---|---|
| [001](#adr-001) | Python 3.12 + FastAPI | Accepted |
| [002](#adr-002) | Redpanda (Kafka API) as the event broker | Accepted |
| [003](#adr-003) | PostgreSQL as the single source of truth, pgvector for retrieval | Accepted |
| [004](#adr-004) | Idempotency enforced by a database unique constraint | Accepted |
| [005](#adr-005) | Partial unique index for "one active investigation" | Accepted |
| [006](#adr-006) | Database-backed workflow state machine | Accepted |
| [007](#adr-007) | Redis only for non-correctness concerns | Accepted |
| [008](#adr-008) | OpenRouter via the OpenAI SDK, behind swappable interfaces | Accepted |
| [009](#adr-009) | Deterministic reconciliation; AI only interprets | Accepted |
| [010](#adr-010) | `src/` layout with uv, ruff, mypy, pytest | Accepted |
| [011](#adr-011) | Audit trail in Postgres; JSON logs on stdout | Accepted |

---

<a id="adr-001"></a>
## ADR-001 — Python 3.12 + FastAPI

**Context:** The spec leans on Pydantic for validation and accepts Swagger as the UI.
The AI/RAG ecosystem is strongest in Python.

**Decision:** Python 3.12, FastAPI, async SQLAlchemy.

**Alternatives:** Go (faster, weaker AI tooling); Django (heavier, sync-first).

**Consequences:** Swagger UI for free; one language across API, workers and eval.
Throughput per process is lower than Go, which we offset by scaling workers horizontally.

---

<a id="adr-002"></a>
## ADR-002 — Redpanda (Kafka API) as the event broker

**Context:** The spec prefers Kafka/Redpanda and requires at-least-once delivery,
ordering tolerance and replay.

**Decision:** Redpanda, with partition key `tenant_id:transaction_id` so events
for one transaction go to one partition and are processed by one consumer at a time.

**Alternatives:** Kafka (heavier to run locally, needs extra components); RabbitMQ (no replay,
no partitioned ordering); Redis Streams (durability depends on Redis persistence).

**Consequences:** Per-transaction ordering within a partition greatly reduces
contention on transaction rows. We still do not rely on arrival order for correctness
(see ADR-004, ADR-009).

---

<a id="adr-003"></a>
## ADR-003 — PostgreSQL as the single source of truth, pgvector for retrieval

**Context:** We need transactional guarantees for events, state and investigations,
plus vector search with strict tenant filtering.

**Decision:** PostgreSQL 16 holds all authoritative state. Embeddings live in the same
database via pgvector.

**Alternatives:** A dedicated vector DB (Qdrant, Weaviate) — one more system
to operate, and tenant filtering would have to be kept in sync across two stores.

**Consequences:** Tenant isolation for retrieval is a SQL `WHERE` clause in the same
query as the similarity search. One fewer failure mode. At very large scale vectors
may move out (see Q21).

---

<a id="adr-004"></a>
## ADR-004 — Idempotency enforced by a database unique constraint

**Context:** Spec §5: the same event sent 20 times must produce one logical update,
with durable guarantees — not only an ephemeral Redis key.

**Decision:** `UNIQUE (tenant_id, event_id)` on `events`. The event insert and the
transaction-state update happen in the same database transaction; a conflicting
insert means "already applied" and the state update is skipped.

**Alternatives:** Redis `SETNX` (lost on eviction/restart; not atomic with the DB write).

**Consequences:** Idempotency survives restarts and redelivery. It costs one
unique-index lookup per event.

---

<a id="adr-005"></a>
## ADR-005 — Partial unique index for "one active investigation"

**Context:** Spec §7: concurrent workers may detect the same anomaly; only one
active investigation may exist per tenant + transaction + anomaly type.

**Decision:** A partial unique index on `(tenant_id, transaction_id, anomaly_type)`
`WHERE status` is one of the active statuses, and creation with `INSERT … ON CONFLICT DO NOTHING`.

**Alternatives:** Application locks or Redis locks (can be lost, need expiry tuning);
`SELECT` then `INSERT` (race window between the two).

**Consequences:** The database decides the race; the loser gets a no-op. Once an
investigation is closed, a new one for the same anomaly can be opened.

---

<a id="adr-006"></a>
## ADR-006 — Database-backed workflow state machine

**Context:** Spec §8–9: persist workflow progress; recover from a crash after the
LLM response but before the report commits. "The framework matters less than the
recovery semantics."

**Decision:** Own state machine persisted in `investigations` / `investigation_steps`.
Workers claim jobs with `FOR UPDATE SKIP LOCKED`, hold a lease renewed by heartbeat,
and checkpoint after every step. Expired leases are reclaimed by the scheduler.

**Alternatives:** Temporal (strong, but heavy to run and learn within the time
budget); Celery (no step checkpoints; acknowledgement semantics are easy to get
wrong); LangGraph persistence (couples the workflow to the AI library).

**Consequences:** Recovery behaviour is explicit, testable and easy to demonstrate.
We own lease/retry logic ourselves.

---

<a id="adr-007"></a>
## ADR-007 — Redis only for non-correctness concerns

**Context:** The spec lists Redis as a dependency and asks how the system behaves
when Redis is down.

**Decision:** Redis is used for the LLM rate-limit token bucket and caching only.
No correctness guarantee depends on it.

**Consequences:** If Redis is unavailable, investigations slow down by falling back
to a conservative in-process rate limit, but no data is lost or corrupted.

---

<a id="adr-008"></a>
## ADR-008 — OpenRouter via the OpenAI SDK, behind swappable interfaces

**Context:** Spec §26: tests must not require a paid model; real and mock
investigators must be swappable.

**Decision:** The OpenAI Python SDK with `base_url` pointed at OpenRouter for both
chat and embeddings. All model access sits behind `Investigator` and `Embedder`
interfaces, with `MockInvestigator` and `FakeEmbedder` for tests and CI.

**Consequences:** The model is a config value. Embedding dimension fixes the pgvector
column size, so the embedding model is chosen before the Phase 4 migration.

---

<a id="adr-009"></a>
## ADR-009 — Deterministic reconciliation; AI only interprets

**Context:** Spec §11.2 and §18: arithmetic, state and reconciliation must be
deterministic; the database must stay authoritative against malicious documents.

**Decision:** Transaction state and rule results are computed in pure Python from
database records. The LLM receives them as read-only input and can only produce a
report; it cannot change state, rule outcomes or investigation status. Every fact
in a report must cite a real event or document chunk, and amounts are re-checked
against the database.

**Consequences:** A prompt-injected or hallucinating model can at worst produce a
report that fails verification — it cannot change financial truth.

---

<a id="adr-010"></a>
## ADR-010 — `src/` layout with uv, ruff, mypy, pytest

**Context:** Needs reproducible installs, fast CI and tests that run against the
installed package.

**Decision:** `src/sentinel/` package; uv for dependency management and lockfile;
ruff for lint and format; mypy for type checks; pytest, with integration tests
run against the same docker compose stack that is deployed.

**Consequences:** Import mistakes surface in tests rather than in deployment; one
lockfile shared by CI and Docker. No testcontainers: one fewer dependency, and tests
exercise the real deployment configuration.

---

<a id="adr-011"></a>
## ADR-011 — Audit trail in Postgres; JSON logs on stdout

**Context:** We need a durable, queryable history of what the system did (§13 audit)
and operational logs that can be correlated across services (§19), on a VPS with
little spare memory.

**Decision:** Two separate records.
- **`audit_logs` table:** append-only business actions (actor, tenant, action,
  entity, details, timestamp), written in the *same DB transaction* as the change
  they describe, so the audit can never disagree with the data.
- **JSON logs on stdout:** one object per line with `service`, `worker_id`,
  `request_id`, `tenant_id`, `transaction_id`, `event_id` from a context variable.

**Alternatives:** A log aggregation stack (Loki/Grafana, ELK) — 300 MB+ on a
memory-constrained host; audit via log files — not transactional, not tenant-scoped.

**Consequences:** `docker compose logs | jq` traces a transaction across services
today; any aggregator can ingest the same JSON later without code changes.

