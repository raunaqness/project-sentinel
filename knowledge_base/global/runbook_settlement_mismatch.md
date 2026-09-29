---
doc_key: runbook-settlement-mismatch
title: Runbook — Settlement amount mismatch
tenant_id: null
document_type: runbook
gateway: null
effective_date: 2026-01-01
---
# When this applies

The bank settlement amount differs from the amount captured by the payment gateway for the same transaction. The ledger may agree with either side.

# Investigation steps

1. Confirm the captured amount from the gateway capture event and the settled amount from the bank settlement event.
2. Compute the difference. Check the merchant's fee agreement: some gateways deduct the merchant discount rate (MDR) at source, so a settlement lower than the capture can be expected.
3. Only treat the difference as a fee if the merchant agreement states the rate and the deduction method. Never assume a fee rate that is not documented.
4. If the difference does not match a documented fee, raise a settlement query with the acquiring bank with the transaction id and both amounts.

# Do not

Do not post a correcting ledger entry until the cause is confirmed. A fee explanation remains a hypothesis until matched against the agreement.
