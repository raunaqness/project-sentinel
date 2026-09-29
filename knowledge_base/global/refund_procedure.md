---
doc_key: refund-procedure
title: Refund procedure
tenant_id: null
document_type: refund_procedure
gateway: null
effective_date: 2026-01-01
---
# Procedure

Refunds are initiated by the internal refund service, which submits them to the gateway that captured the payment. The gateway confirms the refund asynchronously, usually within minutes.

A refund is complete only when the gateway confirmation has been received and matches the refunded amount. Partial refunds are allowed up to the captured amount.
