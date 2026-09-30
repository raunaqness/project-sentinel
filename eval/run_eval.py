"""AI evaluation (spec §25): run every scenario in eval/scenarios.json end to end through
the running stack and score the investigations it produces.

    uv run python eval/run_eval.py            # needs `make up` and `make seed`

Each scenario's events are sent through `POST /events` under a fresh transaction id, so
runs never interfere. The runner waits for the investigations to finish, then reads the
workflow checkpoints from PostgreSQL and reports:

- detection: expected anomalies that opened an investigation; false positives
- classification accuracy: the model's classification is one of the acceptable ones
- citation correctness: facts citing a source the model was actually given
- unsupported claim rate: facts the grounding check demoted (bad source or numbers)
- retrieval recall: expected documents among the retrieved chunks
- quarantine: adversarial documents caught and never shown to the model
- latency (workflow and LLM call) and cost (tokens x price)

Results: eval/results/<run>.json and eval/results/<run>.md
"""

import argparse
import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from sentinel.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"AWAITING_REVIEW", "FAILED", "APPROVED", "REJECTED", "AUTO_RESOLVED"}
# openai/gpt-4o-mini list price, USD per million tokens
PRICE_IN, PRICE_OUT = 0.15, 0.60


def api_url() -> str:
    for line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
        if line.startswith("SENTINEL_API_PORT="):
            return f"http://localhost:{line.split('=', 1)[1].split()[0]}"
    return "http://localhost:8000"


def build_events(scenario: dict[str, Any], run: str) -> list[dict[str, Any]]:
    if "timestamp" in scenario:
        base = datetime.fromisoformat(scenario["timestamp"])
    else:
        base = datetime.now(UTC) - timedelta(days=scenario.get("days_ago", 0), seconds=30)
    txn = f"ev{run}_{scenario['id']}"
    events = []
    for n, (source, type_, amount) in enumerate(scenario["events"]):
        events.append(
            {
                "event_id": f"{txn}_{n}",
                "tenant_id": scenario["tenant"],
                "transaction_id": txn,
                "source": source,
                "type": type_,
                "amount": amount,
                "currency": None if amount is None else "INR",
                "timestamp": (base + timedelta(seconds=n)).isoformat(),
                "metadata": dict(scenario.get("metadata", {})) if n == 0 else {},
            }
        )
    return events


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


async def wait_for_investigations(
    engine: AsyncEngine, run: str, expected: int, min_wait: float, limit_s: float
) -> list[Row[Any]]:
    started = time.monotonic()
    while True:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "select id, transaction_id, anomaly_type, status, created_at"
                        " from investigations where transaction_id like :p"
                    ),
                    {"p": f"ev{run}_%"},
                )
            ).all()
        elapsed = time.monotonic() - started
        done = [r for r in rows if r.status in TERMINAL]
        print(f"  {elapsed:5.0f}s  investigations {len(rows)}/{expected}, finished {len(done)}")
        if elapsed >= min_wait and len(rows) >= expected and len(done) == len(rows):
            return list(rows)
        if elapsed > limit_s:
            print("  timeout: scoring what finished")
            return list(rows)
        await asyncio.sleep(3)


async def load_steps(engine: AsyncEngine, investigation_id: Any) -> dict[str, Any]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "select step, output, completed_at from investigation_steps"
                    " where investigation_id = :id"
                ),
                {"id": investigation_id},
            )
        ).all()
    return {r.step: {"output": r.output, "completed_at": r.completed_at} for r in rows}


def score(
    scenarios: list[dict[str, Any]], run: str, rows: list[Any], steps: dict[Any, dict[str, Any]]
) -> dict[str, Any]:
    by_key = {(r.transaction_id.removeprefix(f"ev{run}_"), r.anomaly_type): r for r in rows}
    cases: list[dict[str, Any]] = []
    false_positives = [
        {"scenario": sid, "anomaly": anomaly}
        for sid, anomaly in by_key
        if anomaly not in next(s for s in scenarios if s["id"] == sid)["expect"]["anomalies"]
    ]
    for scenario in scenarios:
        expect = scenario["expect"]
        for anomaly, acceptable in expect["anomalies"].items():
            case: dict[str, Any] = {
                "scenario": scenario["id"],
                "category": scenario["category"],
                "anomaly": anomaly,
                "acceptable": acceptable,
                "detected": False,
            }
            cases.append(case)
            row = by_key.get((scenario["id"], anomaly))
            if row is None:
                continue
            case |= {"detected": True, "status": row.status}
            s = steps[row.id]
            if "AI_ANALYSIS_COMPLETED" not in s:
                continue
            report = s["AI_ANALYSIS_COMPLETED"]["output"]["report"]
            llm = s["AI_ANALYSIS_COMPLETED"]["output"].get("llm", {})
            knowledge = s.get("KNOWLEDGE_RETRIEVED", {}).get("output", {})
            retrieved = {c["doc_key"] for c in knowledge.get("chunks", [])}
            quarantined = {q["doc_key"] for q in knowledge.get("quarantined", [])}
            case |= {
                "classification": report["classification"],
                "classification_correct": report["classification"] in acceptable,
                "model_confidence": report["confidence"],
                "model": llm.get("model"),
                "llm_latency_ms": llm.get("latency_ms"),
                "prompt_tokens": llm.get("prompt_tokens", 0),
                "completion_tokens": llm.get("completion_tokens", 0),
                "retrieved_docs": sorted(retrieved),
                "quarantined_docs": sorted(quarantined),
            }
            if "RESULT_VERIFIED" in s:
                verification = s["RESULT_VERIFIED"]["output"]["verification"]
                unsupported = verification["unsupported_claims"]
                case |= {
                    "facts_total": verification["facts_total"],
                    "facts_supported": verification["facts_supported"],
                    "facts_bad_source": sum(u["reason"] == "unknown source" for u in unsupported),
                    "unsupported_claims": unsupported,
                    "grounded_confidence": s["RESULT_VERIFIED"]["output"]["report"]["confidence"],
                }
            if "COMPLETED" in s:
                case["workflow_seconds"] = round(
                    (s["COMPLETED"]["completed_at"] - row.created_at).total_seconds(), 2
                )
            if expect.get("quarantined_docs"):
                want = set(expect["quarantined_docs"])
                case["quarantine_ok"] = want <= quarantined and not (want & retrieved)

    # Retrieval is scored per scenario: the expected documents must appear among the chunks
    # retrieved by any of the scenario's investigations.
    for scenario in scenarios:
        relevant_docs = scenario["expect"].get("relevant_docs")
        own = [c for c in cases if c["scenario"] == scenario["id"] and "retrieved_docs" in c]
        if relevant_docs and own:
            union = set().union(*(c["retrieved_docs"] for c in own))
            own[0]["relevant_docs"] = relevant_docs
            own[0]["retrieval_hits"] = len(set(relevant_docs) & union)

    analysed = [c for c in cases if "classification" in c]
    verified = [c for c in cases if "facts_total" in c]
    facts = sum(c["facts_total"] for c in verified)
    relevant = [c for c in cases if "relevant_docs" in c and "retrieved_docs" in c]
    prompt_tokens = sum(c.get("prompt_tokens", 0) for c in cases)
    completion_tokens = sum(c.get("completion_tokens", 0) for c in cases)
    workflow = [c["workflow_seconds"] for c in cases if "workflow_seconds" in c]
    llm_ms = [c["llm_latency_ms"] for c in cases if c.get("llm_latency_ms") is not None]
    cost = (prompt_tokens * PRICE_IN + completion_tokens * PRICE_OUT) / 1_000_000
    healthy = [s for s in scenarios if not s["expect"]["anomalies"]]
    summary = {
        "model": next((c["model"] for c in analysed if c.get("model")), None),
        "scenarios": len(scenarios),
        "expected_investigations": len(cases),
        "detection_recall": ratio(sum(c["detected"] for c in cases), len(cases)),
        "false_positives": len(false_positives),
        "healthy_scenarios_clean": sum(
            not any(sid == s["id"] for sid, _ in by_key) for s in healthy
        ),
        "healthy_scenarios": len(healthy),
        "completed": sum(c.get("status") == "AWAITING_REVIEW" for c in cases),
        "failed": sum(c.get("status") == "FAILED" for c in cases),
        "classification_accuracy": ratio(
            sum(c["classification_correct"] for c in analysed), len(analysed)
        ),
        "facts_total": facts,
        "citation_correctness": ratio(facts - sum(c["facts_bad_source"] for c in verified), facts),
        "unsupported_claim_rate": ratio(
            sum(c["facts_total"] - c["facts_supported"] for c in verified), facts
        ),
        "retrieval_recall": ratio(
            sum(c["retrieval_hits"] for c in relevant),
            sum(len(c["relevant_docs"]) for c in relevant),
        ),
        "quarantine_ok": f"{sum(bool(c.get('quarantine_ok')) for c in cases)}/"
        f"{sum('quarantine_ok' in c for c in cases)}",
        "workflow_latency_s": {"p50": pct(workflow, 0.5), "p95": pct(workflow, 0.95)},
        "llm_latency_ms": {"p50": pct(llm_ms, 0.5), "p95": pct(llm_ms, 0.95)},
        "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
        "cost_usd": round(cost, 5),
        "cost_per_investigation_usd": round(cost / len(analysed), 6) if analysed else None,
    }
    return {"summary": summary, "cases": cases, "false_positives": false_positives}


def markdown(run: str, result: dict[str, Any]) -> str:
    s = result["summary"]
    lines = [
        f"## Evaluation run `{run}` — model `{s['model']}`",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Scenarios / expected investigations | {s['scenarios']} / "
        f"{s['expected_investigations']} |",
        f"| Detection recall | {fmt(s['detection_recall'])} |",
        f"| False positives (healthy clean) | {s['false_positives']} "
        f"({s['healthy_scenarios_clean']}/{s['healthy_scenarios']}) |",
        f"| Completed / failed | {s['completed']} / {s['failed']} |",
        f"| Classification accuracy | {fmt(s['classification_accuracy'])} |",
        f"| Citation correctness ({s['facts_total']} facts) | {fmt(s['citation_correctness'])} |",
        f"| Unsupported claim rate | {fmt(s['unsupported_claim_rate'])} |",
        f"| Retrieval recall | {fmt(s['retrieval_recall'])} |",
        f"| Adversarial docs quarantined | {s['quarantine_ok']} |",
        f"| Workflow latency p50 / p95 | {s['workflow_latency_s']['p50']} s / "
        f"{s['workflow_latency_s']['p95']} s |",
        f"| LLM latency p50 / p95 | {s['llm_latency_ms']['p50'] or 'n/a'} ms / "
        f"{s['llm_latency_ms']['p95'] or 'n/a'} ms |",
        f"| Tokens (prompt / completion) | {s['tokens']['prompt']} / {s['tokens']['completion']} |",
        f"| Cost total / per investigation | ${s['cost_usd']} / "
        f"${s['cost_per_investigation_usd']} |",
        "",
        "| Scenario | Category | Anomaly | Classification | OK | Facts ok/total | Retrieval |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in result["cases"]:
        retrieval = (
            f"{c['retrieval_hits']}/{len(c['relevant_docs'])}" if "retrieval_hits" in c else ""
        )
        if "quarantine_ok" in c:
            retrieval += " quarantine " + ("✔" if c["quarantine_ok"] else "✘")
        lines.append(
            f"| {c['scenario']} | {c['category']} | {c['anomaly']} "
            f"| {c.get('classification', 'not detected' if not c['detected'] else '—')} "
            f"| {'✔' if c.get('classification_correct') else '✘'} "
            f"| {c.get('facts_supported', '')}/{c.get('facts_total', '')} | {retrieval} |"
        )
    if result["false_positives"]:
        lines += ["", f"False positives: {result['false_positives']}"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", default=str(ROOT / "eval" / "scenarios.json"))
    parser.add_argument("--only", nargs="*", help="scenario ids to run, e.g. S04 S08")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument(
        "--min-wait", type=float, default=15, help="let grace periods and the scheduler fire"
    )
    args = parser.parse_args()

    scenarios = json.loads(Path(args.scenarios).read_text())
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in args.only]
    keys = json.loads((ROOT / ".api-keys.json").read_text())
    run = uuid.uuid4().hex[:6]
    result = asyncio.run(evaluate(scenarios, keys, run, args.min_wait, args.timeout))
    out = ROOT / "eval" / "results"
    out.mkdir(exist_ok=True)
    (out / f"{run}.json").write_text(json.dumps(result, indent=2, default=str))
    report = markdown(run, result)
    (out / f"{run}.md").write_text(report)
    print()
    print(report)
    print(f"results: eval/results/{run}.json, eval/results/{run}.md")


async def evaluate(
    scenarios: list[dict[str, Any]],
    keys: dict[str, dict[str, str]],
    run: str,
    min_wait: float,
    limit_s: float,
) -> dict[str, Any]:
    expected = sum(len(s["expect"]["anomalies"]) for s in scenarios)
    print(f"eval run {run}: {len(scenarios)} scenarios, {expected} expected investigations")

    async with httpx.AsyncClient(base_url=api_url(), timeout=30) as client:
        for scenario in scenarios:
            for event in build_events(scenario, run):
                response = await client.post(
                    "/events",
                    json=event,
                    headers={"X-API-Key": keys[event["tenant_id"]]["SERVICE"]},
                )
                if response.status_code != 202:
                    raise SystemExit(f"{event['event_id']}: {response.status_code} {response.text}")

    engine = create_async_engine(str(get_settings().database_url))
    rows = await wait_for_investigations(engine, run, expected, min_wait, limit_s)
    steps = {row.id: await load_steps(engine, row.id) for row in rows}
    await engine.dispose()
    return score(scenarios, run, rows, steps)


if __name__ == "__main__":
    main()
