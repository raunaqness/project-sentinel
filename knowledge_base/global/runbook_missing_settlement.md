---
doc_key: runbook-missing-settlement
title: Runbook — Settlement not received
tenant_id: null
document_type: runbook
gateway: null
effective_date: 2026-01-01
---
# When this applies

A payment was captured but no bank settlement arrived within the expected settlement window.

# Investigation steps

1. Check the settlement rules for the gateway: most settle T+1 business days; weekends and bank holidays extend the window.
2. Check the latest settlement file from the acquiring bank for the transaction id.
3. Check incident reports for known settlement file delays.
4. If the transaction is absent from settlement files beyond T+3, raise a missing-settlement claim with the acquirer.
