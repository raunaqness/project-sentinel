"""Claims investigations and runs their workflow, one at a time per process.

SIGTERM: stop claiming, finish the step in flight, commit its checkpoint, then release
the lease so another worker resumes immediately. SIGKILL/crash: the lease simply
expires and the investigation is reclaimed and resumed from its last checkpoint.
"""

import asyncio
import contextlib
import logging

from sentinel.ai.investigator import MockInvestigator
from sentinel.config import get_settings
from sentinel.db.session import get_engine
from sentinel.observability.logging import configure_logging, log_context
from sentinel.retrieval.embeddings import get_embedder
from sentinel.workers.base import stop_on_signals, worker_id
from sentinel.workflow import engine

log = logging.getLogger("sentinel.investigation_worker")


async def run() -> None:
    stop = stop_on_signals()
    me = worker_id()
    investigator = MockInvestigator()  # OpenRouter-backed investigator arrives in Phase 7
    embedder = get_embedder()
    poll = get_settings().worker_poll_seconds
    log.info("started")
    try:
        while not stop.is_set():
            claim = await engine.claim_next(me)
            if claim is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=poll)
                continue
            await engine.run(claim, me, investigator, embedder, stop)
    finally:
        await get_engine().dispose()
        log.info("stopped")


def main() -> None:
    configure_logging("investigation-worker")
    with log_context(worker_id=worker_id()):
        asyncio.run(run())


if __name__ == "__main__":
    main()
