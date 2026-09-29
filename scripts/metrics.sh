#!/usr/bin/env bash
# Show the Sentinel metrics (spec §19) from every service: the API's GET /metrics and
# each worker's internal :9100/metrics (read from inside its container; not published).
#   scripts/metrics.sh            # business metrics only
#   scripts/metrics.sh --all      # everything, incl. process/python metrics
#   scripts/metrics.sh --raw      # everything, unfiltered (incl. # HELP / # TYPE lines)
set -euo pipefail
cd "$(dirname "$0")/.."
port=$(grep -E '^SENTINEL_API_PORT=' .env 2>/dev/null | cut -d= -f2 | cut -d' ' -f1 || true)
filter='^(events_|reconciliation_|investigation|llm_|queue_depth)'
comments='^# '
[ "${1:-}" = "--all" ] && filter='.'
[ "${1:-}" = "--raw" ] && filter='.' && comments='^$'  # keep comment lines

echo "== api"
curl -s "http://localhost:${port:-8000}/metrics" | grep -E "$filter" | grep -Ev "$comments" || true
for service in event-consumer scheduler investigation-worker; do
  echo "== $service"
  docker compose exec -T "$service" python -c \
    "import urllib.request; print(urllib.request.urlopen('http://localhost:9100/metrics').read().decode())" \
    | grep -E "$filter" | grep -Ev "$comments" || true
done
