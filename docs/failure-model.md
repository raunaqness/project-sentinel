# Failure Model

How Sentinel behaves when each part fails (spec §26). For every failure:
- what the caller or operator sees;
- what is retried, and by whom;
- where state is persisted;
- why correctness holds.

## The invariants

1. **PostgreSQL is the only system of record.** Kafka carries events *to* PostgreSQL.
   Redis only holds a rate-limit counter. The LLM only proposes a report.
2. **Every state change is one PostgreSQL transaction.** It holds the event insert,
   state rebuild, findings, investigations and audit row, or a checkpoint plus its lease
   check. It either commits whole or not at all.
3. **Every write is idempotent or conditional.**
   - `UNIQUE (tenant_id, event_id)` for events.
   - One active investigation per (tenant, transaction, anomaly), via a partial unique
     index.
   - `UNIQUE (investigation_id, step)` for checkpoints.
   - Lease-checked and status-checked `UPDATE`s for workers and reviewers.
4. **Acknowledge only after persisting.**
   - `POST /events` answers 202 only once the broker has the event (`acks=all`).
   - The consumer commits a Kafka offset only after the DB transaction commits.

Together these make **at-least-once delivery produce exactly-once effects**. Retrying is
always safe, so every component can simply crash and restart.

## Worker crash

| | |
|---|---|
| **Investigation worker, hard crash** (SIGKILL, OOM, node loss) | The heartbeat stops. After `SENTINEL_LEASE_SECONDS` (60 s; 5 s in the dev overlay) any worker's claim query picks the investigation up again, and it **resumes after the last committed checkpoint**. |
| **Investigation worker, SIGTERM** (deploy, scale-in) | The step in flight finishes and is checkpointed, and the lease is released for immediate pickup. The pod has a 60 s termination grace period. |
| **Event consumer crash** | Uncommitted offsets are redelivered to the restarted consumer (or another group member). Events whose DB transaction had committed are absorbed by the unique key. |
| **Scheduler crash** | Nothing to recover: it is stateless and the next sweep re-derives everything. |
| **Persisted** | Checkpoints in `investigation_steps`; lease, attempt count and errors on `investigations`. |
| **Why correct** | A worker that lost its lease cannot write: every checkpoint is a conditional `UPDATE … WHERE lease_owner = me`. A completed analysis is never re-run, so a resumed workflow **reuses** the stored LLM answer instead of calling (and paying for) the model again. |
| **Proof** | `tests/integration/test_workflow.py` (crash after every step, including after the LLM answered but before its checkpoint); walkthrough `d1`, `d2`, `s`, `q` |

## PostgreSQL unavailable

| | |
|---|---|
| **API** | Every authenticated request looks up its API key in PostgreSQL, so requests get **503 `database unavailable`** with `Retry-After: 5`. `/health` stays up, since it is a liveness probe and the process is healthy. |
| **Event consumer** | The DB transaction fails and the process exits **without committing the offset**. Docker (`restart: unless-stopped`) or Kubernetes restarts it with backoff. Once PostgreSQL is back, the uncommitted events are redelivered and stored. |
| **Investigation worker** | The claim or checkpoint query fails and the process exits and is restarted. Leases held at that moment expire and are reclaimed, as after a crash. |
| **Scheduler** | The sweep fails, is logged, and runs again next interval. |
| **Persisted** | Events accepted before the outage wait in Kafka, and nothing is acknowledged that isn't stored somewhere durable. |
| **Why correct** | No component keeps state outside PostgreSQL, so a restart loses nothing. Invariants 3 and 4 make the replays harmless. |
| **Verified** | On the compose stack: a request during the outage got 503 in 8 ms. An event produced to Kafka during the outage was **persisted 2 s after PostgreSQL returned**. The walkthrough and integration suite passed afterwards. |

## Broker (Redpanda / Kafka) unavailable

| | |
|---|---|
| **API** | `POST /events` waits at most `SENTINEL_KAFKA_SEND_TIMEOUT_SECONDS` (5 s) for the broker and returns **503**, so the source system retries. Read endpoints and reviews are unaffected. |
| **Consumer** | Idles and reconnects. Offsets are stored in the broker, so it resumes where it stopped. |
| **Workers, scheduler** | Unaffected: they work from PostgreSQL. |
| **Why correct** | 202 means the broker has the event. A 503 may still be delivered from the producer's buffer later; the caller's retry of it is then a duplicate absorbed by the unique key. |
| **Verified** | `docker compose stop redpanda`: 503 after 5 s, 202 again as soon as it is back ([failure-injection.md](failure-injection.md)). |

## Redis unavailable

| | |
|---|---|
| **Behaviour** | The LLM rate limiter switches to a **per-process token bucket** at `SENTINEL_LLM_FALLBACK_FRACTION` (25%) of the global rate, and the checkpoint records `limiter: local-fallback`. Investigations keep completing. It switches back automatically. |
| **Why correct** | Redis holds no business state; the worst case is a less precise global rate. The fallback fraction keeps N workers from multiplying the provider rate while degraded. |
| **Proof** | `tests/unit/test_ratelimit.py`; `docker compose stop redis` ([failure-injection.md](failure-injection.md)) |

## LLM provider unavailable or misbehaving

| | |
|---|---|
| **Retries, layer 1** | The OpenAI SDK retries 429, 5xx and timeouts `SENTINEL_LLM_MAX_RETRIES` (2) times with exponential backoff, within a `SENTINEL_LLM_TIMEOUT_SECONDS` (60 s) timeout. |
| **Retries, layer 2** | If the call still fails, the investigation is requeued with exponential backoff and jitter (`next_attempt_at`: 5 s, 10 s, … capped at 300 s). Other investigations keep flowing. |
| **Malformed output** | The model gets one repair round with the validation error. After that, the step fails and retries as above. |
| **Exhausted** | After `SENTINEL_MAX_ATTEMPTS` (3) the investigation is **`FAILED`**, a dead letter is recorded (`GET /dead-letters`), and `investigations_failed_total` increments. A human can `POST /investigations/{id}/retry` once the provider recovers. |
| **Persisted** | Every attempt's error in `investigations.errors`; all checkpoints before the analysis are kept, so a retry starts at the LLM step. |
| **Why correct** | The LLM never changes financial state. At worst an investigation waits longer or needs a human retry; findings and transaction state are unaffected. |
| **Proof** | Fault modes `timeout`, `http_429`, `http_500`, `malformed`, `empty`, `slow` ([failure-injection.md](failure-injection.md)); walkthrough `f` |

## Vector search (embeddings) unavailable

| | |
|---|---|
| **Behaviour** | If the query can't be embedded (embedding provider down), retrieval **degrades to full-text ranking only** instead of failing. The step's checkpoint records `mode: "text-only"`, and the investigation proceeds with keyword-ranked guidance. `GET /knowledge/search` degrades the same way. |
| **pgvector itself** | It lives inside PostgreSQL, so "vector search down" without "PostgreSQL down" means the embedding call. If PostgreSQL is down, see above. |
| **Knowledge ingest** | `kb-ingest` fails and exits non-zero. It is idempotent (documents are re-embedded only when their content hash changes), so it is simply re-run. |
| **Why correct** | Retrieval only adds context. Tenant scoping is applied to the full-text query exactly as to the vector query. |
| **Proof** | `tests/integration/test_retrieval.py::test_embedding_outage_degrades_to_full_text_search` |

## Poison and malformed messages

| | |
|---|---|
| **Behaviour** | A message that fails validation or violates a DB constraint is written to `dead_letters` with the error, and its offset is committed, so it never blocks the partition. |
| **Compression** | The consumer ships with snappy, lz4 and zstd codecs, so a producer's choice of compression can't wedge it. (Found while testing this document: a snappy-compressed message crash-looped the consumer until the codecs were added.) |
| **Limit** | A batch the Kafka client itself cannot decode (corrupt on disk) would still stop the consumer; it would need an operator to skip the offset. |
| **Proof** | `test_hardening.py::test_malformed_message_is_dead_lettered`; walkthrough `m` |

## Concurrency hazards

| Hazard | Protection |
|---|---|
| Duplicate event delivered twice at once | `UNIQUE (tenant_id, event_id)`; the loser's insert is a no-op |
| Consumer and scheduler reconciling the same transaction | `pg_advisory_xact_lock` per (tenant, transaction) |
| Two creators opening the same investigation | Partial unique index plus `ON CONFLICT DO NOTHING` |
| Two workers claiming the same job | `FOR UPDATE SKIP LOCKED`, plus a lease-checked checkpoint |
| Two reviewers deciding at once | Conditional `UPDATE`: one wins, the other gets **409** |

Proof: `test_hardening.py::test_concurrent_creators_yield_exactly_one_active_investigation`,
`test_rbac.py::test_concurrent_reviews_only_one_wins`. Concurrent claims have no dedicated
test, but every integration and eval run executes several claim loops in parallel (4 per
worker) against the same queue; the crash-recovery tests assert a single completion per
investigation.
