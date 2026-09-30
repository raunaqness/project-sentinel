# Project Sentinel

**AI-assisted transaction investigation platform** — M37 Labs take-home assignment.

Sentinel ingests transaction events from independent financial systems: payment
gateway, internal ledger, bank settlement and refund service. It then:
- reconstructs each transaction's state;
- detects discrepancies with deterministic reconciliation rules;
- opens an AI-assisted investigation that retrieves tenant-scoped guidance, asks an LLM
  for a structured, evidence-cited report, verifies every cited fact, and waits for a
  human to approve or reject it.

It stays correct under duplicate, delayed and out-of-order delivery, concurrent workers,
worker crashes, dependency outages and malicious knowledge-base content. Each of those
has a test.

> **Reviewers:** every question in the brief is answered directly in
> **[ASSIGNMENT_ANSWERS.md](ASSIGNMENT_ANSWERS.md)**, with links to the code, tests and
> docs behind each answer. To see it run: [Quickstart](#quickstart), then
> [`make demo`](#demo-30).

## Deliverables (§29)

| Deliverable | Where |
|---|---|
| Source code | [`src/sentinel`](src/sentinel) — API, workers, workflow, retrieval, AI, rules |
| Docker setup | [`Dockerfile`](Dockerfile), [`docker-compose.yml`](docker-compose.yml) plus dev and VPS overlays |
| Kubernetes manifests | [`deploy/k8s`](deploy/k8s) (kustomize; validated with kubeconform in CI) |
| Automated tests | [`tests/unit`](tests/unit) (95), [`tests/integration`](tests/integration) (38, against the full stack) |
| CI | [`.github/workflows/ci.yml`](.github/workflows/ci.yml): lint, types, unit, integration + walkthrough, image build |
| AI evaluation dataset and results | [`eval/scenarios.json`](eval/scenarios.json) (22 scenarios), [`eval/run_eval.py`](eval/run_eval.py), [docs/eval-report.md](docs/eval-report.md) |
| Load generator and load-test summary | [`scripts/load_generator.py`](scripts/load_generator.py), [docs/load-test-report.md](docs/load-test-report.md) |
| Architecture and failure-model docs | [architecture](docs/architecture.md), [failure model](docs/failure-model.md), [security](docs/security.md), [decisions](docs/decisions.md), [failure injection](docs/failure-injection.md) |
| README with setup and demo | this file |

## Verification

Before submission, everything was re-run on a VPS with `make verify`. The script runs
the unit and integration tests, the full walkthrough, the §30 demo and the AI evaluation
against the live stack. It then writes
**[docs/verification.md](docs/verification.md)** from the actual output: environment,
commit, per-check results, the evaluation table and raw logs.

**Submission run:** 2026-09-30, commit `337c09c`, on a 4 vCPU / 8 GB VPS. The demo and
evaluation used `openai/gpt-4o-mini` via OpenRouter, with OpenRouter embeddings.

- **Tests: all pass.** 95 unit tests, plus 38 integration tests against the full stack.
- **End to end: all pass.** 71/71 walkthrough checks, and 5/5 checks in the §30 demo on
  the real model, including a worker SIGKILLed mid-analysis resuming from its last
  checkpoint.
- **AI evaluation (real model):**
  - 100% detection, 0 false positives, 2/2 adversarial documents quarantined.
  - **81% classification accuracy** (17/21). All 88 cited facts are valid and supported
    by evidence.
  - LLM latency p50 3.4 s; about $0.0004 per investigation.
  - Every miss errs toward escalation, never toward clearing a real discrepancy.
    See [eval-report](docs/eval-report.md#results-openaigpt-4o-mini-via-openrouter).

## How It Works

```
POST /events ──▶ Redpanda (Kafka) ──▶ Event consumer ── one DB transaction: dedupe, state,
 (auth, 202 only                        rules, findings, investigation, audit ──▶ PostgreSQL
  once the broker has it)                                                          │
                       Scheduler ── re-checks time-based rules (missing ledger/settlement)
                                                                                   │
 Investigation workers ◀── claim by priority (SKIP LOCKED, lease) ─────────────────┘
   STARTED → collect transaction → collect events → retrieve knowledge (pgvector + full-text,
   tenant-scoped, injection-screened) → LLM analysis (rate-limited via Redis, strict JSON)
   → evidence grounding → COMPLETED ── checkpoint after every step
                                                                                   │
 Human reviewer ── approve / reject / retry (RBAC, audited) ◀──────────────────────┘
```

Details and a component diagram: [docs/architecture.md](docs/architecture.md).

**Stack:** Python 3.12 · FastAPI · PostgreSQL 16 + pgvector · Redpanda (Kafka API) ·
Redis · OpenRouter (`openai/gpt-4o-mini`, `text-embedding-3-small`) · Docker Compose ·
Kubernetes · GitHub Actions. The rationale for each choice is in
[docs/decisions.md](docs/decisions.md).

## Quickstart

Requires Docker with Compose v2, `jq` and `curl`. The test and eval runners also need
[uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env     # set POSTGRES_PASSWORD (letters/digits) in both places it appears
make up                  # build, migrate, index the knowledge base, start everything; waits until healthy
make seed                # issue API keys (one per role per tenant) into .api-keys.json
curl -s localhost:8000/health
make demo                # the §30 demo flow, narrated
```

- **Port clashes:** change `SENTINEL_API_PORT` or `POSTGRES_PORT` in `.env`, and keep
  the port in `SENTINEL_DATABASE_URL` in step with `POSTGRES_PORT`.
- **Default setup:** the stack runs the **mock investigator** and offline embeddings.
  It needs no API key, and every test and demo passes with it. To use the real model,
  see [Real model](#real-model).
- **Shared VPS:** `COMPOSE_FILE=docker-compose.yml:docker-compose.vps.yml:docker-compose.dev.yml`
  adds memory limits on top of the fast demo timings.
- **API docs:** Swagger UI at `http://localhost:8000/docs`. Use **Authorize** with a key
  from `.api-keys.json`. Every endpoint except `/health` and `/metrics` needs an
  `X-API-Key` header, and the tenant always comes from the key.

## Demo (§30)

`make demo` runs the brief's demo flow against the live stack and narrates each step.

**Part 1**
1. Create a transaction: payment 10,000, ledger 10,000, settlement 9,950.
2. The rules detect the settlement mismatch.
3. An investigation is created.
4. Knowledge is retrieved: the checkpoint shows the tenant's fee agreement and the
   global runbooks.
5. The AI report is generated.
6. The evidence is shown: each fact with its cited event or chunk, and the grounding
   stats.
7. An INVESTIGATOR approves it.

**Part 2**
1. A second investigation starts, and its analysis is slowed to 8 s.
2. The worker is **killed with SIGKILL** mid-analysis.
3. It restarts, the lease expires, and the workflow **resumes from its last checkpoint**.
   The audit trail shows `WORKFLOW_STARTED` → `WORKFLOW_RESUMED` →
   `INVESTIGATION_COMPLETED`.

For more, `scripts/walkthrough.sh` checks every behaviour with ✔/✘. Run all scenarios
(the default) or pick some, e.g. `scripts/walkthrough.sh b d1`:

| Scenario | What it shows |
|---|---|
| `a` | Healthy transaction → `MATCHED`, no investigation |
| `b` | Spec example (settlement, ledger, payment, duplicate payment) → `DISCREPANCY`, one investigation with a report |
| `c` | Missing ledger opened by the scheduler, then resolved when the ledger arrives |
| `d1` | Worker hard-killed after the LLM answered, before commit (§9) → resumes, finishes once |
| `d2` | `FAIL_AFTER_STEP=RESULT_VERIFIED` on the worker (§21) → resumes, reuses the LLM result |
| `k` | Knowledge base: tenant-isolated search, and an investigation citing retrieved guidance |
| `ai` | Investigation report after evidence grounding, with the model call's tokens and latency |
| `s` | SIGTERM while the analysis runs: step finishes, lease released, restart resumes |
| `r` | Human review: approve (reviewer recorded), conflicting decision → 409, retry re-runs the workflow |
| `t` | Tenant isolation and RBAC: another tenant gets 404, roles enforced server-side |
| `q` | Consumer killed after the DB commit, before acknowledging Kafka (§15): redelivery absorbed |
| `m` | Malformed message written straight to Kafka → dead-lettered, inspectable |
| `f` | LLM failures (§17): 429s retried with backoff; 500s exhaust attempts → `FAILED` + dead letter → human retry |
| `pi` | Prompt injection (§18): adversarial documents quarantined; state and human review intact |
| `obs` | All 11 required Prometheus metrics exposed; one `request_id` traced from the API into the consumer |
| `look` | Audit trail, cross-service JSON logs and DB rows for the run |
| `demo` | The §30 flow above (not part of the default run) |

`make metrics` prints the business metrics from the API and every worker.

## Running Tests

```bash
make install            # uv sync
make check              # ruff lint + format check, strict mypy, unit tests (no Docker needed)
make up && make seed    # the integration tests run against the real stack
make test-integration   # 38 tests: API → Kafka → consumer → PostgreSQL → workers
scripts/walkthrough.sh  # end-to-end scenarios (CI runs this too)
make verify             # all of the above plus demo and eval → docs/verification.md
make eval               # AI evaluation: 22 scenarios through the stack → eval/results/
uv run python scripts/load_generator.py --events 100000   # load test → loadtest-output/
```

No test calls a paid model. On every push, CI
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs lint, type checks, unit
tests and Kubernetes manifest validation. It then starts the full stack and runs the
integration tests and the walkthrough, and builds the container image.

**The mandatory tests (§24):**

| Scenario | Test |
|---|---|
| Same event sent 10 times → one result | `tests/integration/test_ingestion.py::test_same_event_sent_ten_times_is_stored_once` |
| Settlement, ledger, then payment → correct state | `tests/integration/test_transaction_state.py::test_out_of_order_with_duplicate_reaches_correct_state` |
| Two workers create the same investigation → one active | `tests/integration/test_hardening.py::test_concurrent_creators_yield_exactly_one_active_investigation` |
| Worker killed mid-investigation → safe resume | `tests/integration/test_workflow.py::test_crash_after_llm_response_before_checkpoint`, `::test_crash_after_verification_reuses_llm_result` |
| Tenant A accesses tenant B → denied | `tests/integration/test_rbac.py::test_tenant_a_cannot_access_tenant_b_resources` |
| Malformed LLM output → safe, no corruption | `tests/integration/test_hardening.py::test_malformed_llm_output_leaves_no_trace_and_is_retried`, `tests/unit/test_openrouter_investigator.py` |
| Malicious document → ignored | `tests/integration/test_hardening.py::test_adversarial_documents_are_quarantined`, `::test_obedient_model_cannot_override_financial_truth` |

## Real Model

Set these in `.env`, then run `make up`:

```bash
OPENROUTER_API_KEY=...                # never commit it; .env is gitignored
SENTINEL_INVESTIGATOR=openrouter      # the LLM investigator (default: mock)
SENTINEL_EMBEDDER=openrouter          # real embeddings (default: fake; changing it re-indexes the KB)
```

`make demo` and `make eval` then use `openai/gpt-4o-mini` via OpenRouter. An eval run
makes 21 model calls, costing about one cent (measured: $0.009).

## Configuration

All settings are environment variables, read by
[`config.py`](src/sentinel/config.py) and documented in
[`.env.example`](.env.example). The main ones:

| Variable | Default | Purpose |
|---|---|---|
| `COMPOSE_FILE` | `docker-compose.yml:docker-compose.dev.yml` | Compose file set; the dev overlay publishes ports and uses 2 s grace periods and a 5 s lease |
| `SENTINEL_INVESTIGATOR` | `mock` | `mock` or `openrouter` |
| `SENTINEL_EMBEDDER` | `fake` | `fake` (offline, deterministic) or `openrouter` |
| `SENTINEL_LLM_MODEL` | `openai/gpt-4o-mini` | Any OpenRouter model with structured outputs |
| `SENTINEL_RECONCILIATION_GRACE_SECONDS` | `300` | How long to wait for other sources before flagging a missing record |
| `SENTINEL_MISSING_SETTLEMENT_SECONDS` | `86400` | Settlement deadline after capture |
| `SENTINEL_SCHEDULER_INTERVAL_SECONDS` | `30` | How often time-based rules are re-checked |
| `SENTINEL_LEASE_SECONDS` | `60` | How soon a crashed worker's investigation is reclaimed |
| `SENTINEL_MAX_ATTEMPTS` / `SENTINEL_RETRY_BACKOFF_SECONDS` | `3` / `5` | Retry policy before `FAILED` + dead letter |
| `SENTINEL_WORKER_CONCURRENCY` | `4` | Investigations in parallel per worker process |
| `SENTINEL_LLM_RATE_PER_SECOND` | `20` | LLM calls per second across **all** workers (Redis token bucket) |
| `SENTINEL_KAFKA_SEND_TIMEOUT_SECONDS` | `5` | `POST /events` returns 503 if the broker hasn't acknowledged by then |
| `SENTINEL_LLM_FAULT`, `FAIL_AFTER_STEP` | empty | Failure injection ([docs/failure-injection.md](docs/failure-injection.md)) |

## Deployment

- **Docker Compose:** `make up` locally. On a VPS, add `docker-compose.vps.yml` for
  memory limits. The API binds to `127.0.0.1`, so put a TLS-terminating proxy or tunnel
  in front of it.
- **Kubernetes:** `kubectl apply -k deploy/k8s`.
  - It deploys the namespace, config, a placeholder secret, Redis, Redpanda, the
    migration and knowledge-base jobs, and the API and worker deployments.
  - All workloads have probes, resource limits, non-root security contexts and
    Prometheus annotations.
  - PostgreSQL is external: set its URL and the OpenRouter key in
    [`secret.yaml`](deploy/k8s/secret.yaml).
  - Build and push the image (`docker build -t <registry>/sentinel .`), then point
    `images:` in [`kustomization.yaml`](deploy/k8s/kustomization.yaml) at it.

## Documentation

| Document | Contents |
|---|---|
| [ASSIGNMENT_ANSWERS.md](ASSIGNMENT_ANSWERS.md) | Direct answers to all 21 questions in the brief |
| [docs/architecture.md](docs/architecture.md) | Components, event path, workflow, AI analysis, data model |
| [docs/failure-model.md](docs/failure-model.md) | Behaviour when each dependency fails, and why correctness holds |
| [docs/security.md](docs/security.md) | Authentication, RBAC, tenant isolation, audit, prompt injection |
| [docs/decisions.md](docs/decisions.md) | Architecture decision records |
| [docs/failure-injection.md](docs/failure-injection.md) | Every fault switch and how to trigger it |
| [docs/load-test-report.md](docs/load-test-report.md) | 100k-event load test and the bottlenecks found |
| [docs/eval-report.md](docs/eval-report.md) | AI evaluation method and results |
| [plan.md](plan.md) | How the build was phased |

## Project Structure

```
src/sentinel/
  api/             FastAPI app, auth (API keys, RBAC), routes
  domain/          event schema, transaction state reducer, priority
  reconciliation/  rule engine and one file per rule
  services/        ingestion, reconciliation, investigations, review, audit, dead letters
  workers/         event consumer, scheduler, investigation worker
  workflow/        step state machine, checkpoints, leases, failure injection
  retrieval/       chunking, embeddings, knowledge-base indexer, hybrid search
  ai/              prompts, schemas, mock + OpenRouter investigators, grounding,
                   injection screening, rate limiter, LLM fault simulator
  observability/   JSON logging with context, Prometheus metrics
  db/              SQLAlchemy models, Alembic migrations
knowledge_base/    runbooks, policies, fee agreements (global and per tenant), adversarial docs
eval/              evaluation scenarios, runner, results
scripts/           walkthrough/demo, load generator, metrics
deploy/k8s/        Kubernetes manifests
tests/             unit and integration tests
```
