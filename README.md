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
| 4 | Investigation creation (§7) | Next |
| 5 | Investigation workflow & crash recovery (§8–9) | Not started |
| 6 | Knowledge base & retrieval (§10) | Not started |
| 7 | AI investigator (§11) | Not started |
| 8 | Review APIs, multi-tenancy, RBAC & audit (§12–13) | Not started |
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

*Pending (Phase 0 / Phase 7).*

## Demo

*Pending (Phase 8).* Happy path (events → mismatch → investigation → AI report →
approve/reject) and crash-recovery demo (kill worker mid-investigation → restart
→ recovery).

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
