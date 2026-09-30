---
doc_key: runbook-duplicate-capture
title: Runbook — Duplicate capture
tenant_id: null
document_type: runbook
gateway: null
effective_date: 2026-01-01
---
# When this applies

More than one distinct capture exists for the same logical transaction, meaning the customer may have been charged twice.

# Investigation steps

1. Compare the capture events: identical amounts within seconds usually indicate a client or gateway retry without an idempotency key.
2. Confirm with the gateway dashboard that both captures settled.
3. Refund the duplicate capture to the customer. Treat this as high priority: customer funds are affected.
4. Record the root cause (merchant retry, gateway retry) so the integration can be fixed.
