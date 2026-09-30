"""Shared fixtures for integration tests: API clients authenticated per tenant and role.

Keys come from `.api-keys.json`, written by `make seed`.
"""

import json
import os
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

API_URL = os.environ.get("SENTINEL_API_URL", "http://localhost:8000")
KEYS_FILE = Path(
    os.environ.get("SENTINEL_API_KEYS_FILE", Path(__file__).parents[2] / ".api-keys.json")
)


@pytest.fixture(scope="session")
def api_keys() -> dict[str, dict[str, str]]:
    if not KEYS_FILE.exists():
        pytest.fail(f"{KEYS_FILE} not found — run `make seed` first")
    keys: dict[str, dict[str, str]] = json.loads(KEYS_FILE.read_text())
    return keys


@pytest.fixture
def client_for(api_keys: dict[str, dict[str, str]]) -> Callable[[str, str], httpx.Client]:
    def make(tenant: str = "merchant_123", role: str = "ADMIN") -> httpx.Client:
        return httpx.Client(
            base_url=API_URL, timeout=10, headers={"X-API-Key": api_keys[tenant][role]}
        )

    return make


@pytest.fixture
def client(client_for: Callable[[str, str], httpx.Client]) -> httpx.Client:
    """merchant_123 ADMIN: may ingest events and read everything of its own tenant."""
    return client_for("merchant_123", "ADMIN")
