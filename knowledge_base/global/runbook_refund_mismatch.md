---
doc_key: runbook-refund-mismatch
title: Runbook — Internal refund without gateway refund
tenant_id: null
document_type: runbook
gateway: null
effective_date: 2026-01-01
---
# When this applies

The internal refund service recorded a refund, but the gateway has not confirmed a refund for the same amount.

# Investigation steps

1. Check whether the refund request was submitted to the gateway and what the gateway responded.
2. If the gateway rejected the refund (for example, insufficient merchant balance), inform the merchant and retry after the balance is restored.
3. Never issue a second refund before confirming the first one did not go through: this risks a double refund.
