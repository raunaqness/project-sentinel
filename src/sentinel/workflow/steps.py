"""The work done at each workflow step. Each returns a JSON-serialisable checkpoint."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.ai.grounding import ground
from sentinel.ai.investigator import Investigator
from sentinel.ai.schemas import InvestigationInput, InvestigationReport
from sentinel.db.models import Event, ReconciliationResult, Transaction
from sentinel.retrieval.embeddings import Embedder
from sentinel.retrieval.search import search
from sentinel.workflow.states import Step


@dataclass
class StepContext:
    investigation_id: str
    tenant_id: str
    transaction_id: str
    anomaly_type: str
    reconciliation_result_id: int
    outputs: dict[str, dict[str, Any]]  # checkpoints of completed steps
    session: AsyncSession
    investigator: Investigator
    embedder: Embedder
    top_k: int
    before_llm_call: Callable[[], Awaitable[None]]


# Retrieval queries phrased in the vocabulary of runbooks and agreements, per anomaly.
_ANOMALY_QUERIES = {
    "SETTLEMENT_MISMATCH": "settlement amount lower than captured amount fee merchant discount "
    "rate agreement deducted at settlement",
    "MISSING_LEDGER": "payment captured ledger entry missing posting job failed",
    "LEDGER_MISMATCH": "ledger amount differs from captured amount adjustment entry",
    "DUPLICATE_CAPTURE": "duplicate capture charged twice retry idempotency key refund",
    "MISSING_SETTLEMENT": "settlement not received settlement file delay T+1 acquirer",
    "REFUND_MISMATCH": "internal refund gateway refund not confirmed",
}


def _json(value: object) -> Any:
    return None if value is None else str(value)


async def started(ctx: StepContext) -> dict[str, Any]:
    return {}


async def collect_transaction(ctx: StepContext) -> dict[str, Any]:
    txn = await ctx.session.get(Transaction, (ctx.tenant_id, ctx.transaction_id))
    finding = await ctx.session.get(ReconciliationResult, ctx.reconciliation_result_id)
    if txn is None or finding is None:
        raise LookupError("transaction or finding disappeared")
    columns = [c.key for c in Transaction.__table__.columns if c.key != "tenant_id"]
    return {
        "transaction": {c: _json(getattr(txn, c)) for c in columns},
        "finding": {"anomaly_type": finding.anomaly_type, **finding.details},
    }


async def collect_events(ctx: StepContext) -> dict[str, Any]:
    rows = await ctx.session.scalars(
        select(Event)
        .where(Event.tenant_id == ctx.tenant_id, Event.transaction_id == ctx.transaction_id)
        .order_by(Event.event_timestamp, Event.id)
    )
    return {
        "events": [
            {
                "event_id": e.event_id,
                "source": e.source,
                "type": e.type,
                "amount": _json(e.amount),
                "currency": e.currency,
                "event_timestamp": e.event_timestamp.isoformat(),
                "metadata": e.metadata_,
            }
            for e in rows
        ]
    }


async def retrieve_knowledge(ctx: StepContext) -> dict[str, Any]:
    """Tenant-scoped hybrid search for guidance relevant to this anomaly."""
    events = ctx.outputs[Step.RELATED_EVENTS_COLLECTED]["events"]
    gateway = next((e["metadata"]["gateway"] for e in events if "gateway" in e["metadata"]), None)
    query = _ANOMALY_QUERIES.get(ctx.anomaly_type, ctx.anomaly_type.replace("_", " ").lower())
    chunks = await search(
        ctx.session,
        ctx.embedder,
        tenant_id=ctx.tenant_id,
        query=query,
        k=ctx.top_k,
        gateway=gateway,
    )
    return {"query": query, "gateway": gateway, "chunks": [c.as_dict() for c in chunks]}


async def analyze(ctx: StepContext) -> dict[str, Any]:
    data = InvestigationInput(
        tenant_id=ctx.tenant_id,
        transaction_id=ctx.transaction_id,
        anomaly_type=ctx.anomaly_type,
        finding=ctx.outputs[Step.TRANSACTION_DATA_COLLECTED]["finding"],
        transaction=ctx.outputs[Step.TRANSACTION_DATA_COLLECTED]["transaction"],
        events=ctx.outputs[Step.RELATED_EVENTS_COLLECTED]["events"],
        knowledge=ctx.outputs[Step.KNOWLEDGE_RETRIEVED]["chunks"],
    )
    await ctx.before_llm_call()
    result = await ctx.investigator.analyze(data)
    return {"report": result.report.model_dump(mode="json"), "llm": result.meta}


async def verify(ctx: StepContext) -> dict[str, Any]:
    """Keep only facts that their cited evidence supports; demote the rest to hypotheses."""
    collected = ctx.outputs[Step.TRANSACTION_DATA_COLLECTED]
    report, stats = ground(
        InvestigationReport.model_validate(ctx.outputs[Step.AI_ANALYSIS_COMPLETED]["report"]),
        events=ctx.outputs[Step.RELATED_EVENTS_COLLECTED]["events"],
        chunks=ctx.outputs[Step.KNOWLEDGE_RETRIEVED]["chunks"],
        authoritative={"finding": collected["finding"], "transaction": collected["transaction"]},
    )
    return {"report": report.model_dump(mode="json"), "verification": stats}


async def complete(ctx: StepContext) -> dict[str, Any]:
    return {}  # the engine stores the report in the same DB transaction as this checkpoint


STEP_FUNCTIONS: dict[Step, Callable[[StepContext], Awaitable[dict[str, Any]]]] = {
    Step.STARTED: started,
    Step.TRANSACTION_DATA_COLLECTED: collect_transaction,
    Step.RELATED_EVENTS_COLLECTED: collect_events,
    Step.KNOWLEDGE_RETRIEVED: retrieve_knowledge,
    Step.AI_ANALYSIS_COMPLETED: analyze,
    Step.RESULT_VERIFIED: verify,
    Step.COMPLETED: complete,
}
