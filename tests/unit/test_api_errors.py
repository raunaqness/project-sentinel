import json
import socket

import pytest
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.requests import Request

from sentinel.api.main import app, database_unavailable


def test_database_errors_are_routed_to_the_503_handler() -> None:
    for error_type in (OSError, OperationalError, InterfaceError):
        assert app.exception_handlers[error_type] is database_unavailable


@pytest.mark.parametrize(
    "error",
    [
        socket.gaierror(-2, "Name or service not known"),  # DB host gone (container stopped)
        ConnectionRefusedError(111, "Connection refused"),
        OperationalError("SELECT 1", {}, Exception("server closed the connection")),
    ],
)
async def test_database_outage_is_a_retryable_503(error: Exception) -> None:
    response = await database_unavailable(Request({"type": "http", "headers": []}), error)
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert json.loads(bytes(response.body)) == {"detail": "database unavailable"}
