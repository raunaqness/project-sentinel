---
doc_key: runbook-missing-ledger
title: Runbook — Payment captured but ledger entry missing
tenant_id: null
document_type: runbook
gateway: null
effective_date: 2026-01-01
---
# When this applies

The gateway reports a successful capture but no internal ledger posting exists after the grace period.

# Investigation steps

1. Check the ledger posting job logs for the transaction id. Posting jobs retry for up to 30 minutes.
2. Check whether the ledger service was degraded at the capture time (see incident reports).
3. If the posting job failed permanently, re-run the posting for the transaction id. Do not post manually unless the job cannot be re-run.
4. Confirm the posted amount equals the captured amount after re-posting.
