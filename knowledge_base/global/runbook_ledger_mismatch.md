---
doc_key: runbook-ledger-mismatch
title: Runbook — Ledger amount differs from capture
tenant_id: null
document_type: runbook
gateway: null
effective_date: 2026-01-01
---
# When this applies

The ledger posted an amount different from the captured amount, or posted an entry for a payment that failed.

# Investigation steps

1. Compare the ledger entry with the capture event. Partial captures and currency conversion are common causes.
2. For a failed payment with a ledger entry, reverse the ledger entry: no money was collected.
3. Corrections are made through adjustment entries, never by editing the original posting.
