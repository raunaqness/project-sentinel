import asyncio

import pytest
from openai import APITimeoutError, InternalServerError, RateLimitError

from sentinel.ai import fault_simulator
from sentinel.ai.schemas import ReportFormatError


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("timeout", APITimeoutError),
        ("http_429", RateLimitError),
        ("http_500", InternalServerError),
        ("malformed", ReportFormatError),
        ("empty", ReportFormatError),
    ],
)
def test_failure_modes_raise_what_the_workflow_would_see(mode: str, error: type) -> None:
    with pytest.raises(error):
        asyncio.run(fault_simulator.apply(mode))


def test_slow_mode_delays_but_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fault_simulator, "SLOW_SECONDS", 0.01)
    asyncio.run(fault_simulator.apply("slow"))


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError, match="unknown"):
        asyncio.run(fault_simulator.apply("gremlins"))
