"""Claims investigations and runs their workflow, several at a time per process.

SIGTERM: stop claiming, finish the step in flight, commit its checkpoint, then release
the lease so another worker resumes immediately. SIGKILL/crash: the lease simply
expires and the investigation is reclaimed and resumed from its last checkpoint.
"""

import asyncio
import contextlib
import logging

from sentinel.ai.investigator import Investigator, MockInvestigator
from sentinel.ai.openrouter_investigator import OpenRouterInvestigator
from sentinel.ai.ratelimit import LLMRateLimiter
from sentinel.config import get_settings
from sentinel.db.session import get_engine
from sentinel.observability import metrics
from sentinel.observability.logging import configure_logging, log_context
from sentinel.retrieval.embeddings import Embedder, get_embedder
from sentinel.workers.base import stop_on_signals, worker_id
from sentinel.workflow import engine

log = logging.getLogger("sentinel.investigation_worker")


def make_investigator() -> Investigator:
    if get_settings().investigator == "openrouter":
        return OpenRouterInvestigator.from_settings()
    return MockInvestigator()


async def _slot(
    me: str,
    investigator: Investigator,
    embedder: Embedder,
    limiter: LLMRateLimiter,
    stop: asyncio.Event,
) -> None:
    """One claim loop. A process runs `worker_concurrency` of these concurrently."""
    poll = get_settings().worker_poll_seconds
    while not stop.is_set():
        claim = await engine.claim_next(me)
        if claim is None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=poll)
            continue
        await engine.run(claim, me, investigator, embedder, limiter, stop)


async def _sample_queue_depth(stop: asyncio.Event) -> None:
    """Investigations waiting or running, for the queue_depth gauge."""
    while not stop.is_set():
        with contextlib.suppress(Exception):
            metrics.QUEUE_DEPTH.labels(queue="investigations").set(await engine.pending_count())
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=5)


async def run() -> None:
    stop = stop_on_signals()
    me = worker_id()
    settings = get_settings()
    investigator = make_investigator()
    embedder = get_embedder()
    limiter = LLMRateLimiter.from_settings()
    metrics.LLM_REQUESTS.labels(model=settings.llm_model_label)  # expose as 0 from the start
    log.info(
        "started",
        extra={
            "investigator": type(investigator).__name__,
            "concurrency": settings.worker_concurrency,
            "llm_rate_per_second": settings.llm_rate_per_second,
        },
    )
    try:
        await asyncio.gather(
            _sample_queue_depth(stop),
            *(
                _slot(me, investigator, embedder, limiter, stop)
                for _ in range(settings.worker_concurrency)
            ),
        )
    finally:
        await get_engine().dispose()
        log.info("stopped")


def main() -> None:
    configure_logging("investigation-worker")
    metrics.serve_worker_metrics()
    with log_context(worker_id=worker_id()):
        asyncio.run(run())


if __name__ == "__main__":
    main()
