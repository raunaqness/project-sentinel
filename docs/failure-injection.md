# Failure Injection

Every way to deliberately break Sentinel and watch it recover (spec §21). Each switch
has an automated test and a walkthrough scenario that exercises it on the compose stack.

Per-event switches (event `metadata`) only work when the service runs with
`SENTINEL_ALLOW_FAULT_INJECTION=true`, which `docker-compose.dev.yml` sets for the event
consumer and investigation worker. They are ignored everywhere else.

## Workflow crashes (§9)

| Switch | Effect | Proof |
|---|---|---|
| `FAIL_AFTER_STEP=<STEP>` on the worker | Hard-kills the worker (`os._exit`) right after that step's checkpoint commits, on each investigation's **first** attempt, so a restarted worker recovers even with the variable still set | `scripts/walkthrough.sh d2` |
| `FAIL_AFTER_STEP=LLM_RESPONSE` | Kills the worker after the LLM answered but **before** the answer is committed (the spec's mandatory scenario) | `test_workflow.py::test_crash_after_llm_response_before_checkpoint`, walkthrough `d1` |
| event `metadata.fail_after_step` | Same, for one investigation only | `test_workflow.py` |
| `docker compose stop investigation-worker` | SIGTERM: the step in flight finishes and is checkpointed, the lease is released | walkthrough `s` (`metadata.mock_llm_delay_seconds` slows the mock so the stop lands mid-analysis) |
| `docker compose kill investigation-worker` | SIGKILL: the lease expires and another worker resumes from the last checkpoint | [`failure-model.md`](failure-model.md) |

Valid steps: `STARTED`, `TRANSACTION_DATA_COLLECTED`, `RELATED_EVENTS_COLLECTED`,
`KNOWLEDGE_RETRIEVED`, `AI_ANALYSIS_COMPLETED`, `RESULT_VERIFIED`, `COMPLETED`, plus
`LLM_RESPONSE`.

## Event delivery (§4.1, §15)

| Switch | Effect | Proof |
|---|---|---|
| event `metadata.fail_after_commit: true` | Kills the event consumer after the DB transaction commits and **before** the Kafka offset commit; the redelivered event is absorbed by the unique key | `test_hardening.py::test_commit_then_crash_before_ack_is_absorbed`, walkthrough `q` |
| A malformed message produced straight to Kafka (`rpk topic produce sentinel.events`) | Dead-lettered with the validation error, never dropped | `test_hardening.py::test_malformed_message_is_dead_lettered`, walkthrough `m` |

## LLM provider failures (§17)

| Switch | Effect | Proof |
|---|---|---|
| `SENTINEL_LLM_FAULT=<mode>` | Every LLM call fails in that mode, so investigations exhaust their attempts and are dead-lettered | `test_fault_simulator.py` |
| event `metadata.llm_fault: <mode>`, `llm_fault_calls: n` | The first *n* LLM calls of that investigation fail (counted across human retries) | `test_hardening.py`, walkthrough `f` |

Modes: `timeout`, `http_429`, `http_500`, `malformed`, `empty`, `slow` (8 s delay).
These model what the workflow sees after the SDK's own HTTP retries are exhausted; the
SDK-level retries are tested separately against simulated HTTP replies
(`test_openrouter_investigator.py`).

## Dependencies

| Action | Expected behaviour |
|---|---|
| `docker compose stop redis` | Workers switch to a per-process LLM rate limit (`limiter: local-fallback` on the analysis checkpoint) and keep completing investigations |
| `docker compose stop postgres` | See [`failure-model.md`](failure-model.md) |
| `docker compose stop redpanda` | `POST /events` returns 503 within `SENTINEL_KAFKA_SEND_TIMEOUT_SECONDS` (5 s) and recovers as soon as the broker is back; nothing is acknowledged with 202 unless the broker has it |

## Prompt injection (§18)

| Switch | Effect | Proof |
|---|---|---|
| event `metadata.retrieval_extra_query: <text>` | Steers retrieval toward the adversarial documents so their quarantine can be observed | `test_hardening.py::test_adversarial_documents_are_quarantined`, walkthrough `pi` |
| event `metadata.mock_obey_injection: true` | The mock investigator behaves like a compromised model that obeyed an injection | `test_hardening.py::test_obedient_model_cannot_override_financial_truth` |
