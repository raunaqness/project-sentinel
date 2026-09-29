"""FastAPI application."""

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from sentinel import __version__
from sentinel.api.routes import (
    audit,
    dead_letters,
    events,
    investigations,
    knowledge,
    transactions,
)
from sentinel.db.session import get_engine
from sentinel.messaging.kafka import make_producer
from sentinel.observability.logging import configure_logging, log_context

log = logging.getLogger("sentinel.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("api")
    producer = make_producer()
    await producer.start()
    app.state.producer = producer
    try:
        yield
    finally:
        await producer.stop()
        await get_engine().dispose()


app = FastAPI(title="Project Sentinel", version=__version__, lifespan=lifespan)
app.include_router(events.router)
app.include_router(transactions.router)
app.include_router(investigations.router)
app.include_router(knowledge.router)
app.include_router(audit.router)
app.include_router(dead_letters.router)


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Tag every log line of a request with a request_id, and log one access line."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    start = time.perf_counter()
    with log_context(request_id=request_id):
        response = await call_next(request)
        if request.url.path != "/health":
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
    response.headers["x-request-id"] = request_id
    return response


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
