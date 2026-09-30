---
doc_key: gateway-alpha-guide
title: Gateway Alpha integration guide
tenant_id: null
document_type: gateway_guide
gateway: GATEWAY_ALPHA
effective_date: 2026-01-01
---
# Settlement

Gateway Alpha settles net of fees: the merchant discount rate agreed with each merchant is deducted before payout, so the settled amount is lower than the captured amount by the fee.

# Retries

Gateway Alpha retries a capture automatically when the acquirer times out. Merchants must send an idempotency key; without it, a retry can create a second capture.
