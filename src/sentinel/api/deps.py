"""FastAPI dependencies shared by routes."""

from collections.abc import AsyncIterator
from typing import Annotated

from aiokafka import AIOKafkaProducer
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.db.session import get_sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


def get_producer(request: Request) -> AIOKafkaProducer:
    producer: AIOKafkaProducer = request.app.state.producer
    return producer


SessionDep = Annotated[AsyncSession, Depends(get_session)]
ProducerDep = Annotated[AIOKafkaProducer, Depends(get_producer)]
