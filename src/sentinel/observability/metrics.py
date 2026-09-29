"""Prometheus metrics (spec §19). Every service exposes its own GET /metrics: the API on
its HTTP port, the workers on an internal port (9100). Prometheus scrapes each instance.

Business counters are incremented only after the DB transaction that performed the
work has committed, so rolled-back work is never counted.
"""

from prometheus_client import Counter, Gauge, Histogram, disable_created_metrics, start_http_server

disable_created_metrics()  # type: ignore[no-untyped-call]  # drop the *_created timestamp series; they add noise, not signal

WORKER_METRICS_PORT = 9100

EVENTS_RECEIVED = Counter("events_received_total", "Events accepted by the API (202)")
EVENTS_PROCESSED = Counter(
    "events_processed_total",
    "Events handled by the consumer",
    ["outcome"],  # stored|duplicate
)
EVENTS_FAILED = Counter(
    "events_failed_total", "Events rejected by the API or dead-lettered by the consumer", ["reason"]
)
RECONCILIATION_FAILURES = Counter(
    "reconciliation_failures_total", "Reconciliation findings opened", ["anomaly_type"]
)
INVESTIGATIONS_CREATED = Counter(
    "investigations_created_total", "Investigations opened", ["priority"]
)
INVESTIGATIONS_COMPLETED = Counter(
    "investigations_completed_total", "Investigations that produced a verified report"
)
INVESTIGATIONS_FAILED = Counter(
    "investigations_failed_total", "Investigations whose attempts were exhausted"
)
INVESTIGATION_LATENCY = Histogram(
    "investigation_latency_seconds",
    "From investigation created to report ready for review",
    buckets=(1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1800, 3600),
)
LLM_REQUESTS = Counter("llm_requests_total", "LLM calls attempted", ["model"])
LLM_FAILURES = Counter("llm_failures_total", "LLM calls that failed", ["error"])
QUEUE_DEPTH = Gauge(
    "queue_depth",
    "Work waiting to be processed",
    ["queue"],  # events (Kafka lag) | investigations
)


def serve_worker_metrics() -> None:
    """Expose this worker process's metrics on the internal port (not published)."""
    start_http_server(WORKER_METRICS_PORT)
