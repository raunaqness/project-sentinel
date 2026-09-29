"""FastAPI application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sentinel import __version__
from sentinel.api.routes import events
from sentinel.db.session import get_engine
from sentinel.messaging.kafka import make_producer
from sentinel.observability.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
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


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
