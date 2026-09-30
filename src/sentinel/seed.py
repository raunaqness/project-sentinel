"""Creates one API-key user per role for every tenant and prints their keys as JSON.

Every run issues fresh keys (old keys stop working); only SHA-256 hashes are stored.

    python -m sentinel.seed > .api-keys.json      # via `make seed`
"""

import asyncio
import json
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from sentinel.api.auth import Role, hash_key
from sentinel.db.models import Tenant, User
from sentinel.db.session import get_engine, get_sessionmaker


async def seed() -> dict[str, dict[str, str]]:
    keys: dict[str, dict[str, str]] = {}
    async with get_sessionmaker()() as session, session.begin():
        tenants = (await session.scalars(select(Tenant.id).order_by(Tenant.id))).all()
        for tenant_id in tenants:
            for role in Role:
                key = f"sk_{tenant_id}_{role.lower()}_{secrets.token_urlsafe(24)}"
                await session.execute(
                    insert(User)
                    .values(
                        tenant_id=tenant_id,
                        name=f"{tenant_id}-{role.lower()}",
                        role=role,
                        api_key_hash=hash_key(key),
                    )
                    .on_conflict_do_update(
                        index_elements=[User.name], set_={"api_key_hash": hash_key(key)}
                    )
                )
                keys.setdefault(tenant_id, {})[role] = key
    await get_engine().dispose()
    return keys


def main() -> None:
    keys = asyncio.run(seed())
    json.dump(keys, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
