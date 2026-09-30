"""Simulated LLM provider failures (spec §17), injected just before the model call.

Modes: timeout, http_429, http_500, malformed, empty, slow. Enabled globally with
SENTINEL_LLM_FAULT=<mode>, or per investigation (dev/test only) with event metadata
{"llm_fault": "<mode>", "llm_fault_calls": n}: the first n LLM calls fail.

These model what the workflow sees *after* the SDK's own retries are exhausted, so the
workflow-level handling (bounded attempts, backoff, dead-lettering) can be exercised
without a real provider.
"""

import asyncio

import httpx2
from openai import APITimeoutError, InternalServerError, RateLimitError

from sentinel.ai.schemas import ReportFormatError

MODES = frozenset({"timeout", "http_429", "http_500", "malformed", "empty", "slow"})
SLOW_SECONDS = 8.0

_REQUEST = httpx2.Request("POST", "https://llm.simulated/v1/chat/completions")


async def apply(mode: str) -> None:
    """Raise the simulated failure for `mode` (or, for `slow`, just delay the call)."""
    if mode == "timeout":
        raise APITimeoutError(request=_REQUEST)
    if mode == "http_429":
        response = httpx2.Response(429, request=_REQUEST)
        raise RateLimitError("simulated rate limit", response=response, body=None)
    if mode == "http_500":
        response = httpx2.Response(500, request=_REQUEST)
        raise InternalServerError("simulated server error", response=response, body=None)
    if mode == "malformed":
        raise ReportFormatError("invalid JSON: simulated malformed response")
    if mode == "empty":
        raise ReportFormatError("empty response (simulated)")
    if mode == "slow":
        await asyncio.sleep(SLOW_SECONDS)
        return
    raise ValueError(f"unknown LLM fault mode {mode!r}; expected one of {sorted(MODES)}")
