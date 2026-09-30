#!/usr/bin/env bash
# Re-runs every check against the running stack and writes docs/verification.md from the
# actual results (nothing in the report is hand-written).
#
#   make up && make seed
#   make verify
#
# Phase 1 — mock investigator (exactly what CI runs): unit tests, integration tests, the
#           full walkthrough. These tests assert deterministic mock behaviour.
# Phase 2 — the investigator configured in .env (e.g. the real model): the §30 demo and
#           the AI evaluation.
#
# Unit/integration tests and the eval run on the host and need uv; without it those
# steps are reported as SKIPPED, never as passed.
set -uo pipefail
cd "$(dirname "$0")/.."

OUT=docs/verification.md
LOGS=$(mktemp -d)
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//; s/^"//; s/"$//'; }

port=$(env_value SENTINEL_API_PORT)
export SENTINEL_API_URL=${SENTINEL_API_URL:-http://localhost:${port:-8000}}
INVESTIGATOR=$(env_value SENTINEL_INVESTIGATOR); INVESTIGATOR=${INVESTIGATOR:-mock}
MODEL=$(env_value SENTINEL_LLM_MODEL); MODEL=${MODEL:-openai/gpt-4o-mini}
EMBEDDER=$(env_value SENTINEL_EMBEDDER); EMBEDDER=${EMBEDDER:-fake}
[ "$INVESTIGATOR" = openrouter ] && MODEL_LABEL="$MODEL (OpenRouter)" || MODEL_LABEL="mock"

# --- preflight -------------------------------------------------------------------------
for tool in docker curl jq git; do
  command -v "$tool" >/dev/null || { echo "missing required tool: $tool"; exit 1; }
done
[ -f .api-keys.json ] || { echo "No .api-keys.json — run: make seed"; exit 1; }
curl -sf "$SENTINEL_API_URL/health" >/dev/null \
  || { echo "API not reachable at $SENTINEL_API_URL — run: make up && make seed"; exit 1; }
HAVE_UV=0; command -v uv >/dev/null && HAVE_UV=1
if [ $HAVE_UV = 1 ]; then
  db_port=$(env_value SENTINEL_DATABASE_URL | sed -E 's#.*@[^:/]+:([0-9]+)/.*#\1#')
  pg_port=$(env_value POSTGRES_PORT); pg_port=${pg_port:-5432}
  if [ "$db_port" != "$pg_port" ]; then
    echo "SENTINEL_DATABASE_URL uses port $db_port but POSTGRES_PORT is $pg_port;"
    echo "the host-side tests and eval connect with SENTINEL_DATABASE_URL — make them match."
    exit 1
  fi
fi

echo "Verifying commit $(git rev-parse --short HEAD) against $SENTINEL_API_URL"
echo "Phase 1: mock investigator | Phase 2: $MODEL_LABEL"

# --- runner ----------------------------------------------------------------------------
declare -a ROWS
FAILED=0
STEP=0
run_step() {  # run_step <name> <investigator label> <summary-fn> <command...>
  local name=$1 label=$2 summarize=$3; shift 3
  STEP=$((STEP + 1))
  local log; log="$LOGS/$(printf %02d $STEP)_${name// /_}.log"
  local started=$SECONDS status
  echo; echo "=== $name"
  "$@" >"$log" 2>&1; status=$?
  local took=$((SECONDS - started)) summary; summary=$($summarize "$log")
  if [ $status -eq 0 ]; then
    ROWS+=("| $name | $label | ✔ $summary | ${took}s |")
    echo "✔ $summary (${took}s)"
  else
    ROWS+=("| $name | $label | ✘ FAILED — $summary | ${took}s |")
    echo "✘ FAILED — $summary (${took}s); last lines:"; tail -15 "$log"
    FAILED=1
  fi
}
skip_step() {  # skip_step <name> <reason>
  ROWS+=("| $1 | — | SKIPPED — $2 | — |"); echo; echo "=== $1"; echo "SKIPPED — $2"
}
pytest_summary() { grep -E '[0-9]+ (passed|failed)' "$1" | tail -1 | sed -E 's/ in [0-9.]+s.*//; s/, [0-9]+ deselected//; s/=//g; s/^ +| +$//g'; }
check_summary() {
  local ok bad; ok=$(grep -cE '^ *✔ ' "$1"); bad=$(grep -cE '^ *✘ ' "$1")
  echo "$ok checks passed, $bad failed"
}
eval_summary() {
  local md; md=$(grep -oE 'eval/results/[0-9a-f]+\.md' "$1" | tail -1)
  [ -n "$md" ] && grep -E '^\| (Classification accuracy|Citation correctness)' "$md" \
    | sed -E 's/^\| //; s/ \|$//; s/ \| /: /' | paste -sd ';' - | sed 's/;/; /' || echo "no results"
}
switch_investigator() {  # restart the worker with the given investigator; wait until healthy
  SENTINEL_INVESTIGATOR=$1 docker compose up -d --wait investigation-worker >/dev/null 2>&1
}
started_at=$(date -u '+%Y-%m-%d %H:%M UTC')

# --- phase 1: mock, as in CI -----------------------------------------------------------
switch_investigator mock
if [ $HAVE_UV = 1 ]; then
  run_step "Unit tests" "—" pytest_summary uv run pytest -q -m "not integration"
  run_step "Integration tests" "mock" pytest_summary uv run pytest -q -m integration
else
  skip_step "Unit tests" "uv not installed"
  skip_step "Integration tests" "uv not installed"
fi
run_step "Walkthrough (all scenarios)" "mock" check_summary scripts/walkthrough.sh

# --- phase 2: the configured investigator ----------------------------------------------
switch_investigator "$INVESTIGATOR"
run_step "§30 demo" "$MODEL_LABEL" check_summary scripts/walkthrough.sh demo
if [ $HAVE_UV = 1 ]; then
  run_step "AI evaluation (22 scenarios)" "$MODEL_LABEL" eval_summary uv run python eval/run_eval.py
else
  skip_step "AI evaluation (22 scenarios)" "uv not installed"
fi

# --- report ----------------------------------------------------------------------------
redact() { sed -E 's/sk_[A-Za-z0-9_-]+/sk_***/g; s/sk-or-[A-Za-z0-9_-]+/sk-or-***/g'; }
eval_md=$(grep -ohE 'eval/results/[0-9a-f]+\.md' "$LOGS"/*AI_evaluation*.log 2>/dev/null | tail -1)
dirty=""; [ -n "$(git status --porcelain --untracked-files=no)" ] && dirty=" (with uncommitted changes)"
mem_gb=$(awk '/MemTotal/ {printf "%.0f", $2/1048576}' /proc/meminfo 2>/dev/null || echo "?")
{
  echo "# Verification Report"
  echo
  echo "Generated by \`make verify\` ([\`scripts/verify.sh\`](../scripts/verify.sh)) from the"
  echo "actual output of the run below; nothing in it is written by hand."
  echo
  echo "| | |"
  echo "|---|---|"
  echo "| Run | $started_at |"
  echo "| Commit | \`$(git rev-parse --short HEAD)\`$dirty |"
  echo "| Host | $(nproc) vCPU, ${mem_gb} GB RAM, $(uname -sm) |"
  echo "| Compose files | \`$(env_value COMPOSE_FILE)\` |"
  echo "| Investigator (demo, eval) | $MODEL_LABEL |"
  echo "| Embeddings | $EMBEDDER |"
  echo
  echo "## Results"
  echo
  echo "| Check | Investigator | Result | Time |"
  echo "|---|---|---|---|"
  printf '%s\n' "${ROWS[@]}"
  echo
  if [ $FAILED -eq 0 ]; then echo "**Overall: every check that ran passed.**"
  else echo "**Overall: some checks FAILED — see below.**"; fi
  if [ -n "$eval_md" ] && [ -f "$eval_md" ]; then
    echo
    echo "## AI Evaluation"
    echo
    sed -E 's/^## /### /' "$eval_md"
    echo
    echo "Full per-case results: [\`${eval_md%.md}.json\`](../${eval_md%.md}.json)"
  fi
  echo
  echo "## Output (last lines of each step)"
  for log in "$LOGS"/*.log; do
    echo
    echo "<details><summary>$(basename "$log" .log | cut -c4- | tr '_' ' ')</summary>"
    echo
    echo '```'
    tail -40 "$log" | redact
    echo '```'
    echo "</details>"
  done
} >"$OUT"
rm -rf "$LOGS"

echo
echo "================================================================"
printf '%s\n' "${ROWS[@]}"
echo "Report written to $OUT"
[ $FAILED -eq 0 ] && echo "All checks that ran passed." || { echo "Some checks FAILED."; exit 1; }
