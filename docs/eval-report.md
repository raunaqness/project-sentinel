# AI Evaluation Report (§25)

## How it works

`make eval` (or `uv run python eval/run_eval.py`) runs every scenario in
[`eval/scenarios.json`](../eval/scenarios.json) **end to end through the running stack**:

1. The events go through `POST /events`, under a fresh transaction id per run.
2. They pass through Kafka, the consumer and the reconciliation rules, and open
   investigations.
3. The workflow runs: retrieval, the LLM, then grounding.

The runner then reads each investigation's workflow checkpoints from PostgreSQL and
scores them. It tests the platform the reviewer would deploy, not the model in
isolation.

Results are written to `eval/results/<run>.json` (every case, every demoted claim) and
`eval/results/<run>.md` (the tables below).

Classification is measurable because the model **must** pick one label from a fixed list
(`CLASSIFICATIONS` in [`ai/schemas.py`](../src/sentinel/ai/schemas.py)). The list is
enforced twice: by the JSON-schema `enum` sent to the model, and by the Pydantic
validator. Each scenario lists the labels an expert would accept. Where the evidence is
genuinely ambiguous, `NEEDS_MANUAL_REVIEW` is also accepted.

## Dataset: 22 scenarios, 21 expected investigations

Tenants `merchant_123` (Gateway Alpha, 0.5% fee deducted at settlement) and
`merchant_456` (Gateway Beta, settles gross, fees invoiced monthly).

| Category | Scenarios | What it probes |
|---|---|---|
| Healthy | S01–S03 | No investigation: matched, out-of-order arrival, confirmed refund |
| Settlement mismatch | S04, S05, S09 | Gap equals the documented 0.5% fee → `SETTLEMENT_FEE_DEDUCTION` |
| | S06 | Same 50 INR gap, but Beta settles gross → **not** a fee |
| | S07 | 3% gap vs a documented 0.5% → unexplained |
| Ambiguous fee | S08 | Gateway unknown: a fee is plausible but unconfirmed |
| Missing ledger | S10, S11 | No ledger posting (S10 also has a settlement gap: two investigations) |
| Ledger mismatch | S12, S13 | Ledger ≠ capture; ledger posted for a failed payment |
| Duplicate capture | S14, S15 | Captured twice |
| Missing settlement | S16 | Captured two days ago, never settled |
| Gateway incident | S17 | Captured during the documented March 2026 settlement-file delay |
| Refund mismatch | S18, S19 | Internal refund with no gateway confirmation |
| Incorrect knowledge | S20, S21 | Adversarial documents pushed into retrieval (must be quarantined) |
| Multiple anomalies | S22 | Duplicate capture **and** a settlement gap on one transaction |

## Metrics

| Metric | Definition |
|---|---|
| Detection recall | Expected (scenario, anomaly) pairs that opened an investigation |
| False positives | Investigations nobody expected (incl. any on healthy scenarios) |
| Classification accuracy | Model's label ∈ the scenario's acceptable labels |
| Citation correctness | Facts whose `source` is something the model was actually given (event id, chunk id, `finding`, `transaction`) |
| Unsupported claim rate | Facts the grounding check demoted to hypotheses: unknown source, or a number absent from the cited source |
| Retrieval recall | Expected documents found among the chunks retrieved for the scenario |
| Quarantine | Adversarial documents detected **and** never shown to the model |
| Latency | Workflow: investigation created → `COMPLETED` checkpoint. LLM: the model call alone |
| Cost | Tokens × `openai/gpt-4o-mini` list price ($0.15 / $0.60 per million in/out) |

## Results: mock investigator (baseline, run `20c661`)

The deterministic mock ([`ai/investigator.py`](../src/sentinel/ai/investigator.py)) is a
naive rule of thumb: every settlement gap is "fee deduction". It is the floor a real model
must beat, and it proves that the pipeline, the retrieval and the scoring all work
without an API key.

| Metric | Value |
|---|---|
| Detection recall | **100%** (21/21), 0 false positives, 3/3 healthy scenarios clean |
| Completed / failed | 21 / 0 |
| Classification accuracy | **85.7%** (18/21) |
| Citation correctness | 100% (45 facts) |
| Unsupported claim rate | 0% |
| Retrieval recall | **100%** (15/15 scenarios with an expected document) |
| Adversarial documents quarantined | **2/2** |
| Workflow latency p50 / p95 | 0.52 s / 1.0 s |
| Cost | $0 |

The three misses are exactly the cases that need judgement:
- **S06:** a gross-settling gateway.
- **S07:** a gap that doesn't match the documented rate.
- **S20:** a Beta gap with adversarial content retrieved.

The mock calls all three "fee deduction". Detection, retrieval and quarantine are
deterministic, so they don't depend on the model.

## Results: `openai/gpt-4o-mini` via OpenRouter

Run `7a8dfb`, on the submission VPS (4 vCPU / 8 GB) via `make verify`, with OpenRouter
embeddings. Full output: [docs/verification.md](verification.md). Per-case JSON:
[`eval/results/7a8dfb.json`](../eval/results/7a8dfb.json).

| Metric | gpt-4o-mini | Mock baseline |
|---|---|---|
| Detection recall / false positives | **100%** / 0 | 100% / 0 |
| Completed / failed | 21 / 0 | 21 / 0 |
| Classification accuracy | **81.0%** (17/21) | 85.7% (18/21) |
| Citation correctness | **100%** (88 facts) | 100% (45 facts) |
| Unsupported claim rate | **0%** | 0% |
| Retrieval recall | 100% | 100% |
| Adversarial documents quarantined | 2/2 | 2/2 |
| LLM latency p50 / p95 | 3.4 s / 5.2 s | n/a |
| Workflow latency p50 / p95 | 11.7 s / 22.3 s (includes rate limiting and queueing) | 0.5 s / 1.0 s |
| Tokens (prompt / completion) | 41,707 / 4,623 | 0 |
| Cost | **$0.009 total, $0.0004 per investigation** | $0 |

### What the numbers say

**The model gets the judgement cases right that the mock gets wrong.** In all three, it
correctly answered `SETTLEMENT_SHORTFALL_UNEXPLAINED`:
- **S06:** the same 50 INR gap as S04, but on a gross-settling gateway.
- **S07:** a 3% gap against a documented 0.5% fee.
- **S20:** a gap where an adversarial "always reconciled" document was pushed into
  retrieval, and was quarantined.

It never cleared a gap that should have been escalated.

**Its four misses are the opposite, cautious error.** S05, S09, the settlement gap in
S10, and the ambiguous S08 are all gaps that equal exactly 0.5% of the capture. In each,
the merchant's fee agreement ("0.5%, deducted at settlement") was among the retrieved
chunks. The model still answered "unexplained" at 0.9 confidence. It classified S04 (the
same fee, 10,000 → 9,950) correctly, so its fee arithmetic isn't reliable across amounts.

**What the guardrails caught, and what they can't.**
- **Caught:** every one of the 88 facts cited a real event, chunk or the finding, and
  every number in them appeared in the cited source. Grounding had nothing to demote.
- **Can't catch:** a wrong *classification* built on true facts. That is exactly the gap
  this evaluation exists to measure, and why every report still requires human review.
  The cost of these misses is a reviewer closing four fee cases by hand; no money is
  mis-stated.

**Next improvement:** compute the expected fee deterministically. The
rule would read the rate from the tenant's fee agreement, multiply it by the captured
amount, and add `expected_fee` and `gap_minus_fee` to the finding. The model would then
compare two numbers instead of doing the arithmetic itself. The eval would show whether
S05, S09 and S10 flip.

## Running it

```bash
make up && make seed    # dev overlay (default COMPOSE_FILE) for 2 s grace periods
make eval               # mock or real model, whichever the worker is configured with
```

The runner connects to PostgreSQL from the host with `SENTINEL_DATABASE_URL` from `.env`,
so its port must match `POSTGRES_PORT`. To evaluate the real model, set
`SENTINEL_INVESTIGATOR=openrouter` and `OPENROUTER_API_KEY` in `.env`, then run
`docker compose up -d investigation-worker` before `make eval`. A run makes 21 model
calls; the measured cost was $0.009.

## Methodology Notes

- **Small dataset.** 22 hand-written scenarios check behaviour, not statistics. One miss
  moves accuracy by ~5 points.
- **Plain-text quality isn't scored.** The summary and recommended action are only read
  by a human (every report still requires review).
- **Grounding checks numbers and sources, not meaning.** A fact that cites the right
  event but misstates something non-numeric would pass. This is one reason human review
  is mandatory.
- **Model randomness.** The real model runs at temperature 0 but isn't perfectly
  deterministic, so repeat runs can differ by a case or two.
