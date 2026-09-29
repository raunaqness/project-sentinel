#!/usr/bin/env bash
# Manual walkthrough of the running stack: sends real events through the API and
# checks what the system did. Safe to re-run: every run uses fresh transaction ids.
#
#   scripts/walkthrough.sh            # run every scenario
#   scripts/walkthrough.sh b c        # run selected scenarios
#
# Scenarios:
#   a    healthy transaction                 -> MATCHED, no investigation
#   b    spec example: out of order + dup    -> DISCREPANCY, investigation with report
#   c    missing ledger, then it arrives     -> opened by scheduler, then auto-resolved
#   d1   crash after LLM response (§9)       -> worker killed, resumes, 2 LLM requests
#   d2   FAIL_AFTER_STEP env var (§21)       -> worker killed, resumes, 1 LLM request
#   look audit trail, JSON logs and DB rows for the transactions of this run
#
# Needs: curl, jq, docker compose. Scenarios c and d1 need docker-compose.dev.yml in
# COMPOSE_FILE (2s grace period, 5s lease, per-event fault injection).
set -euo pipefail
cd "$(dirname "$0")/.."

port=$(grep -E '^SENTINEL_API_PORT=' .env 2>/dev/null | cut -d= -f2 | cut -d' ' -f1 || true)
API=${SENTINEL_API_URL:-http://localhost:${port:-8000}}
TENANT=merchant_123
RUN=$(date +%H%M%S)
FAILED=0

# --- helpers ---------------------------------------------------------------
ev() {  # ev <txn> <event_id> <source> <type> <amount> [metadata-json]
  local meta='{}'; [ -n "${6:-}" ] && meta=$6
  curl -s -o /dev/null -w "  POST /events $2 -> %{http_code}\n" -X POST "$API/events" \
    -H 'content-type: application/json' -d "{
    \"event_id\": \"$2\", \"tenant_id\": \"$TENANT\", \"transaction_id\": \"$1\",
    \"source\": \"$3\", \"type\": \"$4\", \"amount\": $5, \"currency\": \"INR\",
    \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\", \"metadata\": $meta }"
}
txn()  { curl -s "$API/transactions/$1?tenant_id=$TENANT"; }
invs() { curl -s "$API/investigations?tenant_id=$TENANT&transaction_id=$1"; }

expect() {  # expect <description> <actual> <expected>
  if [ "$2" = "$3" ]; then echo "  ✔ $1: $2"
  else echo "  ✘ $1: got '$2', expected '$3'"; FAILED=1; fi
}

wait_for() {  # wait_for <seconds> <command...>: retry until the command's output is non-empty
  local deadline=$((SECONDS + $1)); shift
  until [ -n "$("$@" 2>/dev/null)" ]; do
    [ $SECONDS -ge $deadline ] && return 0
    sleep 1
  done
}

header() { echo; echo "=== $1"; }

# --- scenarios -------------------------------------------------------------
scenario_a() {
  header "A: healthy transaction"
  local t=txn_A_$RUN
  ev "$t" "evt_A_p_$RUN" PAYMENT_GATEWAY PAYMENT_CAPTURED 10000
  ev "$t" "evt_A_l_$RUN" LEDGER LEDGER_POSTED 10000
  ev "$t" "evt_A_s_$RUN" BANK_SETTLEMENT SETTLEMENT_RECEIVED 10000
  wait_for 10 sh -c "curl -s '$API/transactions/$t?tenant_id=$TENANT' | jq -e 'select(.event_count==3)'"
  expect "state" "$(txn "$t" | jq -r .state)" MATCHED
  expect "findings" "$(txn "$t" | jq -c .findings)" "[]"
  expect "investigations" "$(invs "$t" | jq length)" 0
}

scenario_b() {
  header "B: spec example — settlement, ledger, payment, payment (duplicate)"
  local t=txn_B_$RUN
  ev "$t" "evt_B_s_$RUN" BANK_SETTLEMENT SETTLEMENT_RECEIVED 9950
  ev "$t" "evt_B_l_$RUN" LEDGER LEDGER_POSTED 10000
  ev "$t" "evt_B_p_$RUN" PAYMENT_GATEWAY PAYMENT_CAPTURED 10000
  ev "$t" "evt_B_p_$RUN" PAYMENT_GATEWAY PAYMENT_CAPTURED 10000
  wait_for 20 sh -c "curl -s '$API/investigations?tenant_id=$TENANT&transaction_id=$t' | jq -e '.[] | select(.status==\"AWAITING_REVIEW\")'"
  txn "$t" | jq '{state, payment_amount, ledger_amount, settlement_amount, capture_count,
                  findings: [.findings[] | {anomaly_type, status, details}]}'
  expect "state" "$(txn "$t" | jq -r .state)" DISCREPANCY
  expect "capture_count (duplicate ignored)" "$(txn "$t" | jq -r .capture_count)" 1
  expect "finding" "$(txn "$t" | jq -r '.findings[0].anomaly_type')" SETTLEMENT_MISMATCH
  local id; id=$(invs "$t" | jq -r '.[0].id')
  expect "investigations" "$(invs "$t" | jq length)" 1
  expect "investigation status" "$(invs "$t" | jq -r '.[0].status')" AWAITING_REVIEW
  expect "priority" "$(invs "$t" | jq -r '.[0].priority')" HIGH
  curl -s "$API/investigations/$id?tenant_id=$TENANT" | jq '{steps: [.steps[].step], report}'
  expect "steps completed" "$(curl -s "$API/investigations/$id?tenant_id=$TENANT" | jq '.steps | length')" 7
}

scenario_c() {
  header "C: missing ledger — detected by the scheduler, resolved when the ledger arrives"
  local t=txn_C_$RUN
  ev "$t" "evt_C_p_$RUN" PAYMENT_GATEWAY PAYMENT_CAPTURED 10000
  ev "$t" "evt_C_s_$RUN" BANK_SETTLEMENT SETTLEMENT_RECEIVED 10000
  sleep 1
  expect "state right after arrival" "$(txn "$t" | jq -r .state)" PENDING
  wait_for 20 sh -c "curl -s '$API/transactions/$t?tenant_id=$TENANT' | jq -e 'select(.state==\"DISCREPANCY\")'"
  expect "state after grace period" "$(txn "$t" | jq -r .state)" DISCREPANCY
  expect "finding" "$(txn "$t" | jq -r '.findings[0] | "\(.anomaly_type) \(.status)"')" "MISSING_LEDGER OPEN"
  ev "$t" "evt_C_l_$RUN" LEDGER LEDGER_POSTED 10000
  wait_for 10 sh -c "curl -s '$API/transactions/$t?tenant_id=$TENANT' | jq -e 'select(.state==\"MATCHED\")'"
  expect "state after ledger" "$(txn "$t" | jq -r .state)" MATCHED
  expect "finding" "$(txn "$t" | jq -r '.findings[0] | "\(.anomaly_type) \(.status)"')" "MISSING_LEDGER RESOLVED"
  wait_for 10 sh -c "curl -s '$API/investigations?tenant_id=$TENANT&transaction_id=$t' | jq -e '.[] | select(.status==\"AUTO_RESOLVED\")'"
  expect "investigation" "$(invs "$t" | jq -r '.[0].status')" AUTO_RESOLVED
}

crash_case() {  # crash_case <label> <txn> <metadata-json>
  local t=$2
  local before; before=$(docker inspect -f '{{.RestartCount}}' sentinel-investigation-worker-1)
  ev "$t" "evt_${1}_p_$RUN" PAYMENT_GATEWAY PAYMENT_CAPTURED 10000 "$3"
  ev "$t" "evt_${1}_l_$RUN" LEDGER LEDGER_POSTED 10000
  ev "$t" "evt_${1}_s_$RUN" BANK_SETTLEMENT SETTLEMENT_RECEIVED 9950
  wait_for 45 sh -c "curl -s '$API/investigations?tenant_id=$TENANT&transaction_id=$t' | jq -e '.[] | select(.status==\"AWAITING_REVIEW\")'"
  invs "$t" | jq -c '.[] | {status, attempts, llm_requests}'
  expect "worker restarted" "$(( $(docker inspect -f '{{.RestartCount}}' sentinel-investigation-worker-1) > before ))" 1
  expect "investigation status" "$(invs "$t" | jq -r '.[0].status')" AWAITING_REVIEW
  expect "attempts" "$(invs "$t" | jq -r '.[0].attempts')" 2
  echo "  worker log for $t:"
  docker compose logs --no-log-prefix investigation-worker \
    | jq -Rc --arg t "$t" 'fromjson? | select(.transaction_id==$t) | {ts, msg, attempt, fail_after_step, remaining}' \
    | sed 's/^/    /'
}

scenario_d1() {
  header "D1: crash after the LLM answered, before the result was committed (spec §9)"
  local t=txn_D1_$RUN
  crash_case D1 "$t" '{"fail_after_step": "LLM_RESPONSE"}'
  expect "llm_requests (uncommitted answer redone)" "$(invs "$t" | jq -r '.[0].llm_requests')" 2
}

scenario_d2() {
  header "D2: FAIL_AFTER_STEP=RESULT_VERIFIED on the worker (spec §21)"
  local t=txn_D2_$RUN
  FAIL_AFTER_STEP=RESULT_VERIFIED docker compose up -d --wait investigation-worker >/dev/null 2>&1
  crash_case D2 "$t" '{}'
  expect "llm_requests (checkpointed answer reused)" "$(invs "$t" | jq -r '.[0].llm_requests')" 1
  docker compose up -d --wait investigation-worker >/dev/null 2>&1  # fault injection off again
  echo "  worker recreated without FAIL_AFTER_STEP"
}

scenario_look() {
  header "Look inside: this run's transactions"
  docker compose exec -T postgres psql -U "${POSTGRES_USER:-sentinel}" -d "${POSTGRES_DB:-sentinel}" -c \
    "select t.transaction_id, t.state, i.anomaly_type, i.status, i.attempts, i.llm_requests
       from transactions t left join investigations i using (tenant_id, transaction_id)
      where t.transaction_id like '%_$RUN' order by 1"
  local b=txn_B_$RUN
  if [ "$(invs "$b" | jq length)" -gt 0 ]; then
    echo "Audit trail for the investigation of $b:"
    curl -s "$API/audit-logs?tenant_id=$TENANT&entity_id=$(invs "$b" | jq -r '.[0].id')" \
      | jq -r '.[] | [.created_at, .actor, .action] | @tsv' | sed 's/^/  /'
  fi
  echo "JSON logs across services for $b:"
  docker compose logs --no-log-prefix api event-consumer scheduler investigation-worker \
    | jq -Rc --arg t "$b" 'fromjson? | select(.transaction_id==$t) | {ts, service, msg, state}' \
    | sort | sed 's/^/  /'
}

# --- main ------------------------------------------------------------------
curl -sf "$API/health" >/dev/null || { echo "API not reachable at $API — is the stack up (make up)?"; exit 1; }
echo "API: $API   run id: $RUN"

scenarios=("$@"); [ ${#scenarios[@]} -eq 0 ] && scenarios=(a b c d1 d2 look)
for s in "${scenarios[@]}"; do "scenario_$s"; done

echo
if [ $FAILED -eq 0 ]; then echo "All checks passed."; else echo "Some checks failed (see ✘ above)."; exit 1; fi
