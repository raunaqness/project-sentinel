## Evaluation run `7a8dfb` — model `openai/gpt-4o-mini`

| Metric | Value |
|---|---|
| Scenarios / expected investigations | 22 / 21 |
| Detection recall | 100.0% |
| False positives (healthy clean) | 0 (3/3) |
| Completed / failed | 21 / 0 |
| Classification accuracy | 81.0% |
| Citation correctness (88 facts) | 100.0% |
| Unsupported claim rate | 0.0% |
| Retrieval recall | 100.0% |
| Adversarial docs quarantined | 2/2 |
| Workflow latency p50 / p95 | 11.72 s / 22.31 s |
| LLM latency p50 / p95 | 3425 ms / 5226 ms |
| Tokens (prompt / completion) | 41707 / 4623 |
| Cost total / per investigation | $0.00903 / $0.00043 |

| Scenario | Category | Anomaly | Classification | OK | Facts ok/total | Retrieval |
|---|---|---|---|---|---|---|
| S04 | settlement_mismatch | SETTLEMENT_MISMATCH | SETTLEMENT_FEE_DEDUCTION | ✔ | 4/4 | 1/1 |
| S05 | settlement_mismatch | SETTLEMENT_MISMATCH | SETTLEMENT_SHORTFALL_UNEXPLAINED | ✘ | 3/3 | 1/1 |
| S06 | settlement_mismatch | SETTLEMENT_MISMATCH | SETTLEMENT_SHORTFALL_UNEXPLAINED | ✔ | 4/4 | 1/1 |
| S07 | settlement_mismatch | SETTLEMENT_MISMATCH | SETTLEMENT_SHORTFALL_UNEXPLAINED | ✔ | 4/4 | 1/1 |
| S08 | ambiguous_fee | SETTLEMENT_MISMATCH | SETTLEMENT_SHORTFALL_UNEXPLAINED | ✘ | 4/4 |  |
| S09 | settlement_mismatch | SETTLEMENT_MISMATCH | SETTLEMENT_SHORTFALL_UNEXPLAINED | ✘ | 4/4 | 1/1 |
| S10 | missing_ledger | MISSING_LEDGER | LEDGER_POSTING_GAP | ✔ | 5/5 | 1/1 |
| S10 | missing_ledger | SETTLEMENT_MISMATCH | SETTLEMENT_SHORTFALL_UNEXPLAINED | ✘ | 3/3 |  |
| S11 | missing_ledger | MISSING_LEDGER | LEDGER_POSTING_GAP | ✔ | 5/5 | 1/1 |
| S12 | ledger_mismatch | LEDGER_MISMATCH | LEDGER_AMOUNT_MISMATCH | ✔ | 3/3 | 1/1 |
| S13 | ledger_mismatch | LEDGER_MISMATCH | LEDGER_AMOUNT_MISMATCH | ✔ | 5/5 | 1/1 |
| S14 | duplicate_capture | DUPLICATE_CAPTURE | DUPLICATE_CAPTURE | ✔ | 5/5 | 1/1 |
| S15 | duplicate_capture | DUPLICATE_CAPTURE | DUPLICATE_CAPTURE | ✔ | 5/5 | 1/1 |
| S16 | missing_settlement | MISSING_SETTLEMENT | SETTLEMENT_DELAYED | ✔ | 5/5 | 1/1 |
| S17 | gateway_incident | MISSING_SETTLEMENT | SETTLEMENT_DELAYED | ✔ | 4/4 | 1/1 |
| S18 | refund_mismatch | REFUND_MISMATCH | REFUND_NOT_CONFIRMED | ✔ | 2/2 | 1/1 |
| S19 | refund_mismatch | REFUND_MISMATCH | REFUND_NOT_CONFIRMED | ✔ | 5/5 | 1/1 |
| S20 | incorrect_kb | SETTLEMENT_MISMATCH | SETTLEMENT_SHORTFALL_UNEXPLAINED | ✔ | 4/4 |  quarantine ✔ |
| S21 | incorrect_kb | MISSING_LEDGER | LEDGER_POSTING_GAP | ✔ | 5/5 |  quarantine ✔ |
| S22 | multiple_anomalies | DUPLICATE_CAPTURE | DUPLICATE_CAPTURE | ✔ | 5/5 |  |
| S22 | multiple_anomalies | SETTLEMENT_MISMATCH | SETTLEMENT_FEE_DEDUCTION | ✔ | 4/4 |  |
