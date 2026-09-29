"""API metrics endpoint (spec §19). Worker metrics are covered by `scripts/walkthrough.sh obs`."""

import httpx
import pytest

pytestmark = pytest.mark.integration


def test_api_exposes_prometheus_metrics_and_counts_events(client: httpx.Client) -> None:
    def received() -> float:
        body = httpx.get(str(client.base_url.join("/metrics"))).text  # public, like /health
        (line,) = [ln for ln in body.splitlines() if ln.startswith("events_received_total ")]
        return float(line.split()[1])

    before = received()
    bad = client.post("/events", json={"event_id": "x"})  # malformed -> 422
    assert bad.status_code == 422
    body = httpx.get(str(client.base_url.join("/metrics"))).text
    assert 'events_failed_total{reason="http_422"}' in body
    assert received() == before  # rejected events are not counted as received
