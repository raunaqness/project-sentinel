"""Claims investigations and drives them through the workflow with checkpoints.

Recovery model:
- A claim sets a lease (owner + expiry). Heartbeats extend it while work runs.
- Every step's output is committed as a checkpoint, together with a lease check.
  If the lease was lost (another worker took over, or the investigation was closed),
  this worker stops without writing anything.
- A crashed worker simply stops heartbeating; once the lease expires the claim query
  picks the investigation up again and it resumes from the last checkpoint.
"""

import asyncio
import contextlib
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.ai import fault_simulator
from sentinel.ai.investigator import Investigator
from sentinel.ai.ratelimit import LLMRateLimiter
from sentinel.config import get_settings
from sentinel.db.models import Event, Investigation, InvestigationStep
from sentinel.db.session import get_sessionmaker
from sentinel.observability.logging import log_context
from sentinel.retrieval.embeddings import Embedder
from sentinel.services import audit, dead_letters
from sentinel.workflow.failure_injection import LLM_RESPONSE, VALID_POINTS, crash_if
from sentinel.workflow.states import Status, Step, remaining
from sentinel.workflow.steps import STEP_FUNCTIONS, StepContext

log = logging.getLogger("sentinel.workflow")

_PRIORITY_RANK = case(
    {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}, value=Investigation.priority, else_=4
)


@dataclass(frozen=True)
class Claim:
    id: uuid.UUID
    tenant_id: str
    transaction_id: str
    anomaly_type: str
    reconciliation_result_id: int
    attempt: int
    llm_requests: int


class LeaseLostError(Exception):
    pass


async def claim_next(worker_id: str) -> Claim | None:
    """Claim the most urgent investigation that is queued or whose lease expired."""
    settings = get_settings()
    now = datetime.now(UTC)
    async with get_sessionmaker()() as session, session.begin():
        inv = await session.scalar(
            select(Investigation)
            .where(
                or_(
                    # queued, and any retry backoff has elapsed
                    (Investigation.status == Status.OPEN)
                    & or_(
                        Investigation.next_attempt_at.is_(None),
                        Investigation.next_attempt_at <= now,
                    ),
                    # claimed by a worker that stopped heartbeating (crashed)
                    (Investigation.status == Status.IN_PROGRESS)
                    & (Investigation.lease_expires_at < now),
                )
            )
            .order_by(_PRIORITY_RANK, Investigation.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if inv is None:
            return None
        resumed_from = inv.current_step
        inv.status = Status.IN_PROGRESS
        inv.lease_owner = worker_id
        inv.lease_expires_at = now + timedelta(seconds=settings.lease_seconds)
        inv.attempts += 1
        inv.updated_at = now
        audit.record(
            session,
            tenant_id=inv.tenant_id,
            actor=f"worker:{worker_id}",
            action="WORKFLOW_RESUMED" if resumed_from else "WORKFLOW_STARTED",
            entity_type="investigation",
            entity_id=str(inv.id),
            details={"attempt": inv.attempts, "resumed_after_step": resumed_from},
        )
        return Claim(
            inv.id,
            inv.tenant_id,
            inv.transaction_id,
            inv.anomaly_type,
            inv.reconciliation_result_id,
            inv.attempts,
            inv.llm_requests,
        )


async def _fault_for(session: AsyncSession, claim: Claim) -> str | None:
    """The injected fault for this run, if any (first attempt only)."""
    settings = get_settings()
    if claim.attempt != 1:
        return None
    fault = settings.fail_after_step
    if not fault and settings.allow_fault_injection:
        fault = await session.scalar(
            select(Event.metadata_["fail_after_step"].astext).where(
                Event.tenant_id == claim.tenant_id,
                Event.transaction_id == claim.transaction_id,
                Event.metadata_.has_key("fail_after_step"),
            )
        )
    if fault and fault not in VALID_POINTS:
        log.warning("ignoring unknown FAIL_AFTER_STEP", extra={"fail_after_step": fault})
        return None
    return fault or None


async def _llm_fault_for(session: AsyncSession, claim: Claim) -> tuple[str | None, int]:
    """Simulated LLM failure mode and how many calls it affects (spec §17)."""
    settings = get_settings()
    if settings.llm_fault:
        return settings.llm_fault, 10**9  # global: every call fails
    if not settings.allow_fault_injection:
        return None, 0
    row = await session.execute(
        select(
            Event.metadata_["llm_fault"].astext, Event.metadata_["llm_fault_calls"].astext
        ).where(
            Event.tenant_id == claim.tenant_id,
            Event.transaction_id == claim.transaction_id,
            Event.metadata_.has_key("llm_fault"),
        )
    )
    first = row.first()
    if first is None:
        return None, 0
    return first[0], int(first[1] or 1)


def _still_ours(claim: Claim, worker_id: str) -> Any:
    return (
        (Investigation.id == claim.id)
        & (Investigation.lease_owner == worker_id)
        & (Investigation.status == Status.IN_PROGRESS)
    )


async def _heartbeat(claim: Claim, worker_id: str) -> None:
    lease = get_settings().lease_seconds
    while True:
        await asyncio.sleep(lease / 3)
        async with get_sessionmaker()() as session, session.begin():
            await session.execute(
                update(Investigation)
                .where(_still_ours(claim, worker_id))
                .values(lease_expires_at=func.now() + timedelta(seconds=lease))
            )


async def _checkpoint(
    claim: Claim, worker_id: str, step: Step, output: dict[str, Any], report: Any = None
) -> None:
    """Commit a step's output atomically with a lease check (and, at the end, the report)."""
    lease = get_settings().lease_seconds
    values: dict[str, Any] = {
        "current_step": step,
        "lease_expires_at": func.now() + timedelta(seconds=lease),
        "updated_at": func.now(),
    }
    if step is Step.COMPLETED:
        values |= {
            "status": Status.AWAITING_REVIEW,
            "report": report,
            "lease_owner": None,
            "lease_expires_at": None,
            "last_error": None,
        }
    async with get_sessionmaker()() as session, session.begin():
        owned = await session.scalar(
            update(Investigation)
            .where(_still_ours(claim, worker_id))
            .values(**values)
            .returning(Investigation.id)
        )
        if owned is None:
            raise LeaseLostError(str(claim.id))
        await session.execute(
            insert(InvestigationStep)
            .values(investigation_id=claim.id, step=step, attempt=claim.attempt, output=output)
            .on_conflict_do_nothing(constraint="uq_steps_investigation_step")
        )
        if step is Step.COMPLETED:
            audit.record(
                session,
                tenant_id=claim.tenant_id,
                actor=f"worker:{worker_id}",
                action="INVESTIGATION_COMPLETED",
                entity_type="investigation",
                entity_id=str(claim.id),
                details={"attempt": claim.attempt, "classification": report["classification"]},
            )


def _backoff_seconds(attempt: int) -> float:
    settings = get_settings()
    delay = settings.retry_backoff_seconds * float(2 ** (attempt - 1))
    return min(settings.retry_backoff_max_seconds, delay) * random.uniform(0.8, 1.2)  # noqa: S311


async def _record_failure(claim: Claim, worker_id: str, error: Exception) -> None:
    """Requeue with exponential backoff, or — attempts exhausted — fail and dead-letter."""
    exhausted = claim.attempt >= get_settings().max_attempts
    message = f"{type(error).__name__}: {error}"
    now = datetime.now(UTC)
    entry = {"attempt": claim.attempt, "error": message, "at": now.isoformat()}
    retry_at = None if exhausted else now + timedelta(seconds=_backoff_seconds(claim.attempt))
    async with get_sessionmaker()() as session, session.begin():
        errors = await session.scalar(
            update(Investigation)
            .where(_still_ours(claim, worker_id))
            .values(
                status=Status.FAILED if exhausted else Status.OPEN,
                lease_owner=None,
                lease_expires_at=None,
                next_attempt_at=retry_at,
                last_error=message,
                errors=Investigation.errors.op("||")(literal([entry], type_=JSONB)),  # append
                updated_at=func.now(),
            )
            .returning(Investigation.errors)
        )
        if errors is None:  # lease lost meanwhile; the new owner handles it
            return
        if not exhausted:
            log.warning(
                "attempt failed; retrying with backoff",
                extra={"attempt": claim.attempt, "retry_at": retry_at, "error": message},
            )
            return
        audit.record(
            session,
            tenant_id=claim.tenant_id,
            actor=f"worker:{worker_id}",
            action="INVESTIGATION_FAILED",
            entity_type="investigation",
            entity_id=str(claim.id),
            details={"attempts": claim.attempt, "error": message},
        )
        dead_letters.record(
            session,
            kind=dead_letters.INVESTIGATION,
            tenant_id=claim.tenant_id,
            reference=str(claim.id),
            error=message,
            payload={
                "transaction_id": claim.transaction_id,
                "anomaly_type": claim.anomaly_type,
                "attempts": claim.attempt,
                "errors": errors,
            },
        )
        log.error("attempts exhausted; dead-lettered", extra={"attempts": claim.attempt})


async def release(claim: Claim, worker_id: str) -> None:
    """Graceful shutdown: make the job immediately reclaimable by another worker."""
    async with get_sessionmaker()() as session, session.begin():
        await session.execute(
            update(Investigation)
            .where(_still_ours(claim, worker_id))
            .values(lease_owner=None, lease_expires_at=func.now())
        )


async def run(
    claim: Claim,
    worker_id: str,
    investigator: Investigator,
    embedder: Embedder,
    limiter: LLMRateLimiter,
    stop: asyncio.Event,
) -> None:
    with log_context(
        investigation_id=str(claim.id),
        tenant_id=claim.tenant_id,
        transaction_id=claim.transaction_id,
    ):
        heartbeat = asyncio.create_task(_heartbeat(claim, worker_id))
        try:
            await _run_steps(claim, worker_id, investigator, embedder, limiter, stop)
        except LeaseLostError:
            log.info("lease lost; another worker or a close took over")
        except Exception as error:
            log.exception("workflow step failed", extra={"attempt": claim.attempt})
            await _record_failure(claim, worker_id, error)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat


async def _run_steps(
    claim: Claim,
    worker_id: str,
    investigator: Investigator,
    embedder: Embedder,
    limiter: LLMRateLimiter,
    stop: asyncio.Event,
) -> None:
    async with get_sessionmaker()() as session:
        rows = await session.scalars(
            select(InvestigationStep).where(InvestigationStep.investigation_id == claim.id)
        )
        outputs: dict[str, dict[str, Any]] = {r.step: r.output for r in rows}
        fault = await _fault_for(session, claim)
        llm_fault, llm_fault_calls = await _llm_fault_for(session, claim)
    todo = remaining(set(outputs))
    log.info("workflow running", extra={"attempt": claim.attempt, "remaining": todo[:1]})

    async def before_llm_call() -> dict[str, Any]:
        """Wait for rate-limit budget, count the request, then apply any simulated fault."""
        limits = await limiter.acquire()
        async with get_sessionmaker()() as s, s.begin():
            calls = await s.scalar(
                update(Investigation)
                .where(Investigation.id == claim.id)
                .values(llm_requests=Investigation.llm_requests + 1)
                .returning(Investigation.llm_requests)
            )
        if llm_fault and (calls or 0) <= llm_fault_calls:
            log.warning("simulated LLM failure", extra={"llm_fault": llm_fault, "call": calls})
            await fault_simulator.apply(llm_fault)
        return limits

    for step in todo:
        if stop.is_set():
            await release(claim, worker_id)
            log.info("released on shutdown", extra={"next_step": step})
            return
        async with get_sessionmaker()() as session:
            ctx = StepContext(
                investigation_id=str(claim.id),
                tenant_id=claim.tenant_id,
                transaction_id=claim.transaction_id,
                anomaly_type=claim.anomaly_type,
                reconciliation_result_id=claim.reconciliation_result_id,
                outputs=outputs,
                session=session,
                investigator=investigator,
                embedder=embedder,
                top_k=get_settings().retrieval_top_k,
                before_llm_call=before_llm_call,
            )
            output = await STEP_FUNCTIONS[step](ctx)
        if step is Step.AI_ANALYSIS_COMPLETED:
            crash_if(LLM_RESPONSE, fault)  # LLM answered, checkpoint not yet committed
        report = None
        if step is Step.COMPLETED:  # the verified (grounded) report, with its verification
            verified = outputs[Step.RESULT_VERIFIED]
            report = verified["report"] | {"verification": verified["verification"]}
        await _checkpoint(claim, worker_id, step, output, report)
        outputs[step] = output
        crash_if(step, fault)
    log.info("workflow completed", extra={"attempt": claim.attempt})
