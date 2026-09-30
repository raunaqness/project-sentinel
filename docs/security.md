# Security

Covers tenant isolation, RBAC, audit, secrets and prompt injection (spec §13, §18).

## Authentication

- Every endpoint except `/health` and `/metrics` requires an `X-API-Key` header.
- Keys are random: `secrets.token_urlsafe(24)` behind a readable prefix. Only their
  **SHA-256 hash** is stored (`users.api_key_hash`), so a database leak doesn't reveal
  usable keys.
- `make seed` issues one key per role per tenant and prints them once, into
  `.api-keys.json` (gitignored). Re-running it rotates every key.
- A user can be disabled (`users.disabled`); a disabled user's key is rejected
  immediately.

*Production note:* API keys stand in for the brief's "authentication". Behind a real
identity provider the same `Principal` (user, tenant, role) would come from a verified
JWT or mTLS identity; nothing downstream would change.

## Authorization (RBAC, enforced server-side)

| Role | read | review (approve / reject / retry) | audit | ingest (`POST /events`) |
|---|---|---|---|---|
| `VIEWER` | ✔ | | | |
| `INVESTIGATOR` | ✔ | ✔ | | |
| `ADMIN` | ✔ | ✔ | ✔ (and dead letters) | ✔ |
| `SERVICE` (a source system) | | | | ✔ |

Each route declares its permission as a FastAPI dependency (`Reader`, `Reviewer`,
`Auditor`, `Ingestor` in [`api/auth.py`](../src/sentinel/api/auth.py)). A role without
it gets **403**. Source systems get `SERVICE` keys that can submit events but read
nothing.

## Tenant isolation

- **The tenant comes from the API key, never from the request.** There is no tenant
  parameter a client could change.
- Every tenant-owned table has `tenant_id`, and every query filters on the caller's
  tenant.
- Another tenant's resource returns **404, not 403**, so its existence isn't revealed.
- `POST /events` rejects an event whose `tenant_id` differs from the key's tenant
  (**403**).
- **Retrieval** requires a tenant: `search()` raises without one. Every query is
  restricted to that tenant's private documents plus global ones, for both the vector and
  the full-text ranking, including the degraded text-only mode.
- **Worker processing is tenant-scoped too.** An investigation's data collection and
  retrieval use its own `tenant_id`, so a report can only cite that tenant's events and
  documents. The citation `enum` sent to the model contains nothing else.
- **Kafka messages are keyed `tenant_id:transaction_id`.**

Proof:
- `tests/integration/test_rbac.py`: cross-tenant 404s and empty lists on every resource,
  the role matrix, missing and invalid keys.
- `test_ingestion.py`: a spoofed tenant on ingest gets 403.
- `test_retrieval.py`: a tenant never sees another's private documents.
- Walkthrough `t`.

## Audit trail

`audit_logs` is append-only from the application's point of view (no update or delete
path). It records the actor (`user:<name>`, `worker:<id>`, `system:event-consumer`,
`system:scheduler`), action, entity and details for:

- `EVENT_RECEIVED`
- `DISCREPANCY_DETECTED` / `DISCREPANCY_RESOLVED`
- `INVESTIGATION_CREATED`, `WORKFLOW_STARTED` / `WORKFLOW_RESUMED`,
  `INVESTIGATION_COMPLETED`, `INVESTIGATION_FAILED`, `INVESTIGATION_AUTO_RESOLVED`
- `INVESTIGATION_APPROVED` / `INVESTIGATION_REJECTED` (with the reviewer and comment),
  `INVESTIGATION_RETRIED`

Each row is written **in the same DB transaction** as the change it describes, so the
trail can't miss a committed change or record one that rolled back. It is read per
tenant via `GET /audit-logs` (ADMIN).

## Secrets

- `OPENROUTER_API_KEY` and `POSTGRES_PASSWORD` come from the environment:
  - `.env` (gitignored) under compose;
  - a Kubernetes `Secret` in [`deploy/k8s/secret.yaml`](../deploy/k8s/secret.yaml),
    which holds **placeholders only**.
- Settings hold the OpenRouter key as a Pydantic `SecretStr`, so it doesn't appear in
  reprs or logs.
- Containers run as a non-root user (UID 10001) without privilege escalation.
- The API binds to `127.0.0.1` in compose. Public exposure is meant to go through a
  reverse proxy or tunnel that terminates TLS.

## Prompt injection (§18)

The knowledge base is treated as **untrusted input**. Defence in depth, from the
outside in:

1. **Screening.** Retrieved chunks are screened for injection patterns: instruction
   overrides, role changes, cross-tenant exfiltration, "always mark as reconciled".
   Matching chunks are **quarantined**: recorded in the checkpoint, never sent to the
   model, never citable. See [`ai/injection.py`](../src/sentinel/ai/injection.py).
2. **Prompt framing.** The prompt labels evidence (finding, transaction, events) as
   authoritative. It labels documents as "untrusted, for context only", to be used for
   explanations and never as instructions.
3. **Constrained output.** A strict JSON schema: the classification comes from a fixed
   list, and fact sources are an enum of the ids actually supplied. The model can't cite
   or invent anything else.
4. **Grounding.** A claim whose numbers don't appear in its cited source is demoted to
   an "Unverified" hypothesis, and confidence is capped by the share of supported facts.
5. **No authority.** The model has no tools, no database access and no write path.
   Transaction state and findings come only from deterministic rules. Every report
   requires a human decision (`requires_human_review` is forced true).

Even a fully compromised model can only produce a wrong *suggestion* that a human still
has to approve. `test_obedient_model_cannot_override_financial_truth` proves this: a mock
that obeys the injection returns "NO_DISCREPANCY, confidence 1.0", and the transaction
stays `DISCREPANCY` while the investigation still awaits review.

Proof:
- `test_hardening.py::test_adversarial_documents_are_quarantined`
- `test_injection.py`
- eval scenarios S20 and S21 ([eval-report.md](eval-report.md))
- walkthrough `pi`

**Limit:** pattern screening is a heuristic and can be evaded by paraphrase. That is why
layers 2–5 exist and why none of them depend on layer 1. A production system would add a
classifier-based screen and review of knowledge-base changes before ingest.
