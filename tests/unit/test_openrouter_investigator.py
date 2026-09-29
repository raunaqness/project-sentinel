"""OpenRouterInvestigator against simulated HTTP replies (no network, no key)."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from openai import APIStatusError

from sentinel.ai.openrouter_investigator import OpenRouterInvestigator
from sentinel.ai.schemas import InvestigationInput, ReportFormatError

VALID = {
    "classification": "SETTLEMENT_FEE_MISMATCH",
    "confidence": 0.8,
    "summary": "Settlement is INR 50 lower than the capture.",
    "facts": [{"claim": "Settlement amount is INR 9950", "source": "evt_s"}],
    "hypotheses": ["A settlement fee may explain the difference."],
    "recommended_action": "Verify the merchant's MDR.",
    "requires_human_review": True,
}

DATA = InvestigationInput(
    tenant_id="merchant_123",
    transaction_id="txn_1",
    anomaly_type="SETTLEMENT_MISMATCH",
    finding={"difference": "50.00"},
    transaction={},
    events=[{"event_id": "evt_s", "type": "SETTLEMENT_RECEIVED", "amount": "9950.00"}],
)


def completion(content: str | None) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "openai/gpt-4o-mini",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        },
    )


def investigator(
    replies: list[httpx2.Response], seen: list[dict[str, Any]]
) -> OpenRouterInvestigator:
    queue = list(replies)

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return queue.pop(0)

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return OpenRouterInvestigator(
        "key",
        "https://openrouter.test/api/v1",
        "openai/gpt-4o-mini",
        timeout=5,
        max_retries=2,
        http_client=client,
    )


def run(replies: list[httpx2.Response]) -> tuple[Any, list[dict[str, Any]]]:
    seen: list[dict[str, Any]] = []
    return asyncio.run(investigator(replies, seen).analyze(DATA)), seen


def test_valid_reply_parsed_with_usage() -> None:
    result, seen = run([completion(json.dumps(VALID))])
    assert result.report.classification == "SETTLEMENT_FEE_MISMATCH"
    assert result.meta["prompt_tokens"] == 100 and result.meta["repairs"] == 0
    request = seen[0]
    assert request["model"] == "openai/gpt-4o-mini"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["temperature"] == 0


@pytest.mark.parametrize(
    "bad",
    [
        "not json at all",
        "",
        json.dumps({k: v for k, v in VALID.items() if k != "summary"}),  # missing field
        json.dumps(VALID | {"confidence": 7}),  # out of range
        json.dumps(VALID | {"sql": "DROP TABLE"}),  # unexpected field
    ],
)
def test_malformed_reply_is_repaired_once(bad: str) -> None:
    result, seen = run([completion(bad), completion(json.dumps(VALID))])
    assert result.meta["repairs"] == 1
    assert "invalid" in seen[1]["messages"][-1]["content"]


def test_malformed_twice_raises() -> None:
    with pytest.raises(ReportFormatError):
        run([completion("nope"), completion("still nope")])


def test_null_content_is_handled() -> None:
    with pytest.raises(ReportFormatError):
        run([completion(None), completion(None)])


def test_rate_limit_retried_then_succeeds() -> None:
    throttled = httpx2.Response(429, headers={"retry-after-ms": "10"}, json={"error": "rate"})
    result, seen = run([throttled, completion(json.dumps(VALID))])
    assert len(seen) == 2 and result.report.confidence == 0.8


def test_server_errors_exhaust_bounded_retries() -> None:
    error: Callable[[], httpx2.Response] = lambda: httpx2.Response(  # noqa: E731
        500, headers={"retry-after-ms": "10"}, json={"error": "boom"}
    )
    with pytest.raises(APIStatusError):
        run([error(), error(), error()])  # 1 call + 2 retries, then give up
