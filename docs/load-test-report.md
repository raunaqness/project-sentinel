# Load Test Report

Load generator: [`scripts/load_generator.py`](../scripts/load_generator.py) (spec §20).
Raw results with per-second samples are written to `loadtest-output/<run>.json`.

## Baseline run (`96f178`)

**Environment:** the full docker-compose stack on one cloud sandbox VM (4 vCPU, 16 GB RAM),
no memory limits, dev timings (2 s grace period, 2 s scheduler interval), mock LLM
investigator (no provider latency or cost), 1 API process, 1 event consumer, 1 scheduler,
1 investigation worker (4 concurrent investigations), topic `sentinel.events` with a
single partition. Not run on the shared VPS (see [plan](../plan.md#deployment-target-vps)).

**Workload:** 100,002 sends = 95,235 unique events across two tenants —
70% healthy transactions, 12% settlement mismatch, 6% missing ledger, 5% missing
settlement, 4% duplicate capture, 3% unconfirmed refund; 10% of transactions out of order,
5% of events re-sent as duplicates, 3% of transactions with their last event delayed to
the end of the run. 200 concurrent senders.

| Metric | Result |
|---|---|
| Accepted by the API | **71.7 events/s** (99,408 × 202 in 1386.0 s) |
| API latency p50 / p95 / p99 | **1.77 s / 6.90 s / 7.82 s** |
| Error rate | **0.59%** — 594 client-side failures (no HTTP response), 0 HTTP errors |
| Persisted (consumer throughput) | ~68.3 events/s over the sending window |
| End-to-end latency (sent → persisted) p50 / p95 / p99 | 2.7 s / 7.53 s / 8.72 s |
| Peak event backlog (accepted, not yet persisted) | 5,483 |
| Peak investigations queued or running | 26 |
| Investigations created | 10,695 (9,680 awaiting review, 1,015 auto-resolved) |

**Correctness under load:** every event the API acknowledged with 202 was persisted
exactly once (no dead letters, no consumer errors). The 539
unique events missing from the database are exactly the sends that never received a 202:
the client knows they were not accepted and would retry (at-least-once at the edge).

### First bottleneck: the API ingest path

The API process saturated first (~80% of a core, p50 latency 1.8 s under 200 concurrent
senders, and ~0.6% of client connections failing). Each `POST /events` does a
synchronous API-key lookup in PostgreSQL and then waits for the broker's acknowledgement
(`acks=all`), in a single uvicorn process. The pipeline behind it kept up: end-to-end
latency stayed under 9 s at p99 and the backlog never exceeded 5,483 events.

### Second: the scheduler's full rescans

The scheduler re-reconciled every `PENDING`/`DISCREPANCY` transaction each interval (500 per
sweep). With thousands of such transactions it ran at ~70% CPU and competed with the
consumer for PostgreSQL, even though almost none of them could change without a new event.

### Not exercised by this run

LLM backpressure (§16): investigations arrived at ~8/s against the 20/s token bucket, and
the mock investigator is instant, so the rate limit never engaged. The LLM path is
bounded by design — pending investigations wait in PostgreSQL, claimed by priority, at
most `SENTINEL_LLM_RATE_PER_SECOND` calls per second across all workers.
