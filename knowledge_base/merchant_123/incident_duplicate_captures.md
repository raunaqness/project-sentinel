---
doc_key: merchant-123-incident-duplicate-captures
title: Merchant 123 incident — Duplicate captures from checkout retries
tenant_id: merchant_123
document_type: incident_report
gateway: GATEWAY_ALPHA
effective_date: 2026-05-02
---
# Summary

In May 2026 Merchant 123's checkout retried capture requests without an idempotency key after client timeouts, producing duplicate captures for 41 orders. All duplicates were refunded. The checkout now sends idempotency keys.
