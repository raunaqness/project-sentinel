# Project Sentinel

**AI-assisted transaction investigation platform** — M37 Labs take-home assignment.

Sentinel ingests transaction events from independent financial systems (payment
gateway, internal ledger, bank settlement, refund service, merchant platform),
reconstructs each transaction's state, detects discrepancies with deterministic
reconciliation rules, and opens an AI-assisted investigation that produces an
evidence-backed report for human approval.

It is built to stay correct under duplicate delivery, out-of-order events,
concurrent workers, worker crashes, dependency outages and malicious knowledge-base
content.

> **Reviewers:** every question asked in the assignment brief is answered directly
> in **[ASSIGNMENT_ANSWERS.md](ASSIGNMENT_ANSWERS.md)**, with links to the code,
> tests and docs that back each answer.

## Status

Under active development. Progress is tracked phase by phase in [plan.md](plan.md).

| Phase | Feature | Status |
|---|---|---|
| 0 | Foundations | Done |
| 1 | Event ingestion (§4) | Done |
| 2 | Idempotency & transaction state (§5) | Done |
| 3 | Reconciliation engine (§6) | Done |
| 4 | Investigation creation (§7) | Done |
| 5 | Investigation workflow & crash recovery (§8–9) | Done |
| 6 | Knowledge base & retrieval (§10) | Done |
| 7 | AI investigator (§11) | Done (real-model check pending) |
| 8 | Review APIs, multi-tenancy, RBAC & audit (§12–13) | Next |
| 9 | Hardening (§14–18) | Not started |
| 10 | Observability, load & failure injection (§19–21) | Not started |
| 11 | Kubernetes & CI (§22–23) | Not started |
| 12 | Tests, evaluation, docs & demo (§24–32) | Not started |

## How It Works

```
POST /events → Redpanda → Event consumer
                            │  dedupe + update state (one DB transaction)
                            ▼
                     Reconciliation rules ──(discrepancy)──▶ Investigation (one active per tenant+txn+anomaly)
                                                                  │
                                                                  ▼
                                   Investigation worker: collect data → retrieve knowledge
                                   → LLM analysis → grounding check → report
                                                                  │
                                                                  ▼
                                                   Human approves / rejects
```

## Tech Stack

Python 3.12 · FastAPI · PostgreSQL 16 + pgvector · Redpanda (Kafka API) · Redis ·
OpenRouter (LLM + embeddings) · Docker Compose · Kubernetes · GitHub Actions

Rationale for each choice: [docs/decisions.md](docs/decisions.md).

## Quickstart

```bash
cp .env.example .env     # set POSTGRES_PASSWORD (letters/digits) in both places it appears
make up                  # build, migrate, start everything; waits until healthy
curl -s localhost:8000/health
scripts/walkthrough.sh   # send real events through the stack and check the outcomes
```

- **Port clashes:** change `SENTINEL_API_PORT` / `POSTGRES_PORT` in `.env`.
- **On a shared VPS:** use
  `COMPOSE_FILE=docker-compose.yml:docker-compose.vps.yml:docker-compose.dev.yml` for
  memory limits plus fast demo timings.
- Swagger UI: `http://localhost:8000/docs`.

`scripts/walkthrough.sh` runs these scenarios (all by default, or pick some,
e.g. `scripts/walkthrough.sh b d1`), printing ✔/✘ for each expectation:

| Scenario | What it shows |
|---|---|
| `a` | Healthy transaction → `MATCHED`, no investigation |
| `b` | Spec example (settlement, ledger, payment, duplicate payment) → `DISCREPANCY`, one investigation with a report |
| `c` | Missing ledger opened by the scheduler, then resolved when the ledger arrives |
| `d1` | Worker hard-killed after the LLM answered, before commit (§9) → resumes, finishes once |
| `d2` | `FAIL_AFTER_STEP=RESULT_VERIFIED` on the worker (§21) → resumes, reuses the LLM result |
| `k` | Knowledge base: tenant-isolated search, and an investigation citing retrieved guidance |
| `ai` | Investigation report after evidence grounding, with the model call's tokens and latency |
| `s` | SIGTERM while the analysis runs: step finishes, lease released, restart resumes (mock investigator) |
| `look` | Audit trail, cross-service JSON logs and DB rows for the run |

## Running Tests

*Pending (Phase 0).*

## Configuration

*Pending (Phase 0).* All settings come from environment variables; see `.env.example`.

## Documentation

| Document | Contents |
|---|---|
| [ASSIGNMENT_ANSWERS.md](ASSIGNMENT_ANSWERS.md) | Direct answers to every question in the brief |
| [plan.md](plan.md) | Phased build plan and project structure |
| [docs/architecture.md](docs/architecture.md) | Components, data flow, consistency model |
| [docs/failure-model.md](docs/failure-model.md) | Behaviour under each dependency failure |
| [docs/security.md](docs/security.md) | Tenant isolation, RBAC, audit, prompt injection |
| [docs/decisions.md](docs/decisions.md) | Architecture decision records |
| [docs/load-test-report.md](docs/load-test-report.md) | Load test results |
| [docs/eval-report.md](docs/eval-report.md) | AI evaluation results |

## Project Structure

See [plan.md → Project Structure](plan.md#project-structure).
