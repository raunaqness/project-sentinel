"""Rebuilds transaction state, runs reconciliation and records the outcome.

Callers own the DB transaction boundary. Everything here — state upsert, findings,
audit rows — commits or rolls back together.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.db.models import Event, ReconciliationResult, Transaction
from sentinel.domain.transaction_state import TxnState, compute_state, overall_state
from sentinel.reconciliation.engine import context_at, evaluate
from sentinel.services import audit, investigations

OPEN, RESOLVED = "OPEN", "RESOLVED"


@dataclass(frozen=True)
class ReconcileOutcome:
    state: TxnState
    opened: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    investigations_opened: list[str] = field(default_factory=list)


async def reconcile(
    session: AsyncSession,
    tenant_id: str,
    transaction_id: str,
    *,
    actor: str,
    now: datetime | None = None,
) -> ReconcileOutcome:
    """Recompute facts from all events, run every rule, and persist state + findings."""
    now = now or datetime.now(UTC)

    # Serialize work on one transaction (consumer vs scheduler) for this DB transaction.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"{tenant_id}:{transaction_id}"},
    )

    events = (
        await session.scalars(
            select(Event).where(
                Event.tenant_id == tenant_id, Event.transaction_id == transaction_id
            )
        )
    ).all()
    facts = compute_state(list(events))
    findings = {f.anomaly_type: f for f in evaluate(facts, context_at(now))}
    state = overall_state(facts, has_open_findings=bool(findings))

    columns = asdict(facts) | {"state": state}
    await session.execute(
        insert(Transaction)
        .values(tenant_id=tenant_id, transaction_id=transaction_id, **columns)
        .on_conflict_do_update(
            index_elements=[Transaction.tenant_id, Transaction.transaction_id],
            set_=columns | {"updated_at": func.now()},
        )
    )

    existing = {
        row.anomaly_type: row
        for row in await session.scalars(
            select(ReconciliationResult).where(
                ReconciliationResult.tenant_id == tenant_id,
                ReconciliationResult.transaction_id == transaction_id,
            )
        )
    }
    outcome = ReconcileOutcome(state=state)

    opened_rows: list[ReconciliationResult] = []
    for anomaly_type, finding in findings.items():
        row = existing.get(anomaly_type)
        if row is None:
            row = ReconciliationResult(
                tenant_id=tenant_id,
                transaction_id=transaction_id,
                anomaly_type=anomaly_type,
                first_detected_at=now,
            )
            session.add(row)
        if row.status != OPEN:
            outcome.opened.append(anomaly_type)
            opened_rows.append(row)
            row.resolved_at = None
        row.status = OPEN
        row.severity = finding.severity
        row.details = finding.details
        row.last_evaluated_at = now

    for anomaly_type, row in existing.items():
        if anomaly_type not in findings and row.status == OPEN:
            row.status, row.resolved_at, row.last_evaluated_at = RESOLVED, now, now
            outcome.resolved.append(anomaly_type)

    for anomaly_type in outcome.opened:
        finding = findings[anomaly_type]
        audit.record(
            session,
            tenant_id=tenant_id,
            actor=actor,
            action="DISCREPANCY_DETECTED",
            entity_type="transaction",
            entity_id=transaction_id,
            details={"anomaly_type": anomaly_type, "severity": finding.severity, **finding.details},
        )
    for anomaly_type in outcome.resolved:
        audit.record(
            session,
            tenant_id=tenant_id,
            actor=actor,
            action="DISCREPANCY_RESOLVED",
            entity_type="transaction",
            entity_id=transaction_id,
            details={"anomaly_type": anomaly_type},
        )
        await investigations.auto_resolve(
            session, tenant_id, transaction_id, anomaly_type, actor=actor, now=now
        )

    await session.flush()  # assigns ids to newly opened findings
    amount = facts.payment_amount or facts.ledger_amount or facts.settlement_amount
    for row in opened_rows:
        investigation_id = await investigations.open_for_finding(session, row, amount, actor=actor)
        if investigation_id is not None:
            outcome.investigations_opened.append(str(investigation_id))
    return outcome


async def get_transaction(
    session: AsyncSession, tenant_id: str, transaction_id: str
) -> Transaction | None:
    return await session.get(Transaction, (tenant_id, transaction_id))


async def list_findings(
    session: AsyncSession,
    tenant_id: str,
    *,
    transaction_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> Sequence[ReconciliationResult]:
    stmt = select(ReconciliationResult).where(ReconciliationResult.tenant_id == tenant_id)
    if transaction_id is not None:
        stmt = stmt.where(ReconciliationResult.transaction_id == transaction_id)
    if status is not None:
        stmt = stmt.where(ReconciliationResult.status == status)
    stmt = stmt.order_by(ReconciliationResult.last_evaluated_at.desc()).limit(limit)
    return (await session.scalars(stmt)).all()
