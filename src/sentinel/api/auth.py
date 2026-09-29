"""API-key authentication and role-based authorization, enforced server-side.

Every protected route declares the permission it needs. The caller's tenant comes
from their API key — never from the request — so a client cannot ask for another
tenant's data.
"""

import hashlib
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select

from sentinel.api.deps import SessionDep
from sentinel.db.models import User


class Role(StrEnum):
    VIEWER = "VIEWER"
    INVESTIGATOR = "INVESTIGATOR"
    ADMIN = "ADMIN"
    SERVICE = "SERVICE"  # machine identity of a source system: may only submit events


class Permission(StrEnum):
    READ = "read"  # transactions, events, findings, investigations, knowledge
    REVIEW = "review"  # approve / reject / retry investigations
    AUDIT = "audit"  # audit trail
    INGEST = "ingest"  # POST /events


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset({Permission.READ}),
    Role.INVESTIGATOR: frozenset({Permission.READ, Permission.REVIEW}),
    Role.ADMIN: frozenset(Permission),
    Role.SERVICE: frozenset({Permission.INGEST}),
}


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    name: str
    tenant_id: str
    role: Role

    @property
    def actor(self) -> str:
        return f"user:{self.name}"


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)


async def authenticate(
    session: SessionDep, api_key: Annotated[str | None, Security(_api_key)]
) -> Principal:
    if not api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing X-API-Key header")
    user = await session.scalar(
        select(User).where(User.api_key_hash == hash_key(api_key), User.disabled.is_(False))
    )
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")
    return Principal(user.id, user.name, user.tenant_id, Role(user.role))


def requires(permission: Permission) -> object:
    async def check(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
        if permission not in ROLE_PERMISSIONS[principal.role]:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"role {principal.role} lacks '{permission}' permission"
            )
        return principal

    return Depends(check)


Reader = Annotated[Principal, requires(Permission.READ)]
Reviewer = Annotated[Principal, requires(Permission.REVIEW)]
Auditor = Annotated[Principal, requires(Permission.AUDIT)]
Ingestor = Annotated[Principal, requires(Permission.INGEST)]
