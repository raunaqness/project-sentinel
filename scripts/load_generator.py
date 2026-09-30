"""Load generator (spec §20): drives the running stack with realistic event traffic and
reports throughput, latency, backlog/queue depth, error rate and drain times.

    uv run python scripts/load_generator.py --events 100000 --concurrency 200

Workload per transaction (both tenants): 70% healthy, 12% settlement mismatch, 6% missing
ledger, 5% missing settlement (captured two days ago), 4% duplicate capture, 3% refund
without gateway confirmation. On top: 10% of transactions arrive out of order, 5% of
events are re-sent as duplicates, and 3% of transactions hold their last event back
until the end of the run (delayed delivery).

Measurements come from the client (API latency, errors) and from PostgreSQL (events
persisted, end-to-end latency from send to persistence, investigations pending).
Needs `make up` and `make seed`. Results: loadtest-output/<run>.json
"""

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from sentinel.config import get_settings

ROOT = Path(__file__).resolve().parents[1]


def api_url() -> str:
    for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
        if line.startswith("SENTINEL_API_PORT="):
            return f"http://localhost:{line.split('=', 1)[1].split()[0]}"
    return "http://localhost:8000"


def build_workload(
    n_events: int, run: str, rng: random.Random
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (main stream, delayed tail) of event payloads."""
    main: list[dict[str, Any]] = []
    delayed: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    tenants = ["merchant_123", "merchant_456"]
    i = 0
    while len(main) + len(delayed) < n_events:
        i += 1
        tenant = tenants[i % 2]
        txn = f"lt{run}_t{i}"
        amount = rng.choice([500, 1200, 2500, 10000, 25000, 150000])
        kind = rng.choices(
            [
                "healthy",
                "settlement_mismatch",
                "missing_ledger",
                "missing_settlement",
                "duplicate_capture",
                "refund_mismatch",
            ],
            weights=[70, 12, 6, 5, 4, 3],
        )[0]
        ts = now - timedelta(days=2) if kind == "missing_settlement" else now
        events = [("PAYMENT_GATEWAY", "PAYMENT_CAPTURED", amount)]
        if kind != "missing_ledger":
            events.append(("LEDGER", "LEDGER_POSTED", amount))
        if kind not in ("missing_settlement",):
            settled = amount - rng.choice([1, 50, 120]) if kind == "settlement_mismatch" else amount
            events.append(("BANK_SETTLEMENT", "SETTLEMENT_RECEIVED", settled))
        if kind == "duplicate_capture":
            events.append(("PAYMENT_GATEWAY", "PAYMENT_CAPTURED", amount))
        if kind == "refund_mismatch":
            events.append(("REFUND_SERVICE", "REFUND_ISSUED", amount // 10))
        payloads = [
            {
                "event_id": f"lt{run}_e{i}_{n}",
                "tenant_id": tenant,
                "transaction_id": txn,
                "source": source,
                "type": type_,
                "amount": amt,
                "currency": "INR",
                "timestamp": ts.isoformat(),
                "metadata": {"load_test": run},
            }
            for n, (source, type_, amt) in enumerate(events)
        ]
        if rng.random() < 0.10:
            rng.shuffle(payloads)  # out of order
        if rng.random() < 0.03 and len(payloads) > 1:
            delayed.append(payloads.pop())  # held back until the end
        main.extend(payloads)
        main.extend(p for p in payloads if rng.random() < 0.05)  # duplicate deliveries
    return main, delayed


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=int, default=100_000)
    parser.add_argument("--concurrency", type=int, default=200)
    parser.add_argument("--drain-timeout", type=float, default=1800)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    run = uuid.uuid4().hex[:6]
    rng = random.Random(args.seed)  # noqa: S311 - reproducible workload, not security
    keys = json.loads((ROOT / ".api-keys.json").read_text())
    main_stream, delayed = build_workload(args.events, run, rng)
    stream = main_stream + delayed
    unique_ids = {e["event_id"] for e in stream}
    print(
        f"run {run}: {len(stream)} sends ({len(unique_ids)} unique events), "
        f"{len(delayed)} delayed, concurrency {args.concurrency}"
    )

    engine = create_async_engine(str(get_settings().database_url))
    samples: list[dict[str, Any]] = []
    latencies: list[float] = []
    statuses: dict[int, int] = {}
    sent = 0
    t0 = time.monotonic()

    async def sample() -> dict[str, Any]:
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "select (select count(*) from events where event_id like :p),"
                        " (select count(*) from investigations"
                        "  where status in ('OPEN','IN_PROGRESS')),"
                        " (select count(*) from investigations where transaction_id like :t)"
                    ),
                    {"p": f"lt{run}_%", "t": f"lt{run}_%"},
                )
            ).one()
        return {
            "t": round(time.monotonic() - t0, 1),
            "sent": sent,
            "persisted": row[0],
            "event_backlog": sent - row[0],
            "investigations_pending": row[1],
            "investigations_created": row[2],
        }

    stop_sampling = asyncio.Event()

    async def sampler() -> None:
        while not stop_sampling.is_set():
            samples.append(await sample())
            await asyncio.sleep(1)

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    for payload in stream:
        queue.put_nowait(payload)

    async def sender(client: httpx.AsyncClient) -> None:
        nonlocal sent
        while not queue.empty():
            payload = queue.get_nowait()
            payload["metadata"]["sent_at"] = datetime.now(UTC).isoformat()
            started = time.perf_counter()
            try:
                response = await client.post(
                    "/events",
                    json=payload,
                    headers={"X-API-Key": keys[payload["tenant_id"]]["SERVICE"]},
                )
                code = response.status_code
            except httpx.HTTPError:
                code = 0
            latencies.append(time.perf_counter() - started)
            statuses[code] = statuses.get(code, 0) + 1
            sent += 1

    sampling = asyncio.create_task(sampler())
    limits = httpx.Limits(
        max_connections=args.concurrency, max_keepalive_connections=args.concurrency
    )
    async with httpx.AsyncClient(base_url=api_url(), timeout=30, limits=limits) as client:
        await asyncio.gather(*(sender(client) for _ in range(args.concurrency)))
    send_seconds = time.monotonic() - t0
    print(f"sent in {send_seconds:.1f}s; waiting for the pipeline to drain...")

    deadline = time.monotonic() + args.drain_timeout
    events_drained_at = investigations_drained_at = None
    while time.monotonic() < deadline:
        latest = samples[-1] if samples else await sample()
        if events_drained_at is None and latest["persisted"] >= len(unique_ids):
            events_drained_at = latest["t"]
        if (
            events_drained_at is not None
            and latest["investigations_pending"] == 0
            and latest["t"] > events_drained_at + 5
        ):
            investigations_drained_at = latest["t"]
            break
        await asyncio.sleep(1)
    stop_sampling.set()
    await sampling

    async with engine.connect() as conn:
        e2e = [
            float(r[0])
            for r in (
                await conn.execute(
                    text(
                        "select extract(epoch from"
                        " received_at - (metadata->>'sent_at')::timestamptz)"
                        " from events where event_id like :p"
                    ),
                    {"p": f"lt{run}_%"},
                )
            ).all()
        ]
        inv = (
            await conn.execute(
                text(
                    "select status, count(*) from investigations"
                    " where transaction_id like :t group by 1"
                ),
                {"t": f"lt{run}_%"},
            )
        ).all()
    await engine.dispose()

    errors = sum(n for code, n in statuses.items() if code != 202)
    result = {
        "run": run,
        "config": vars(args),
        "sends": len(stream),
        "unique_events": len(unique_ids),
        "send_seconds": round(send_seconds, 1),
        "accepted_per_second": round(statuses.get(202, 0) / send_seconds, 1),
        "api_latency_ms": {
            q: round(pct(latencies, v) * 1000, 1)
            for q, v in (("p50", 0.5), ("p95", 0.95), ("p99", 0.99))
        },
        "error_rate": round(errors / max(1, len(stream)), 5),
        "status_counts": {str(k): v for k, v in sorted(statuses.items())},
        "events_drained_at_s": events_drained_at,
        "persisted_per_second": round(len(unique_ids) / events_drained_at, 1)
        if events_drained_at
        else None,
        "end_to_end_latency_s": {
            q: round(pct(e2e, v), 2) for q, v in (("p50", 0.5), ("p95", 0.95), ("p99", 0.99))
        },
        "peak_event_backlog": max((s["event_backlog"] for s in samples), default=0),
        "peak_investigations_pending": max(
            (s["investigations_pending"] for s in samples), default=0
        ),
        "investigations": {status: n for status, n in inv},
        "investigations_drained_at_s": investigations_drained_at,
        "samples": samples,
    }
    out = ROOT / "loadtest-output" / f"{run}.json"
    out.write_text(json.dumps(result, indent=2, default=str))
    summary = {k: v for k, v in result.items() if k != "samples"}
    print(json.dumps(summary, indent=2, default=str))
    print(f"full results (incl. per-second samples): {out}")
    if latencies:
        print(f"mean API latency {statistics.mean(latencies) * 1000:.1f} ms")


if __name__ == "__main__":
    asyncio.run(main())
