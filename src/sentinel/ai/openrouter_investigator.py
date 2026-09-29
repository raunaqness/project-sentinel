"""LLM-backed investigator using OpenRouter's OpenAI-compatible API."""

import logging
import time
from typing import Any, cast

import httpx2
from openai import AsyncOpenAI

from sentinel.ai.prompts import build_messages
from sentinel.ai.schemas import (
    REPORT_JSON_SCHEMA,
    AnalysisResult,
    InvestigationInput,
    ReportFormatError,
    parse_report,
)
from sentinel.config import get_settings

log = logging.getLogger("sentinel.ai")

REPAIR_ATTEMPTS = 1  # one chance to fix a malformed reply, then the step fails and retries

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "investigation_report", "strict": True, "schema": REPORT_JSON_SCHEMA},
}


class OpenRouterInvestigator:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float,
        max_retries: int,
        http_client: httpx2.AsyncClient | None = None,  # injected by tests
    ) -> None:
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            http_client=http_client,
        )

    @classmethod
    def from_settings(cls) -> "OpenRouterInvestigator":
        settings = get_settings()
        if settings.openrouter_api_key is None:
            raise RuntimeError("SENTINEL_INVESTIGATOR=openrouter requires OPENROUTER_API_KEY")
        return cls(
            settings.openrouter_api_key.get_secret_value(),
            settings.openrouter_base_url,
            settings.llm_model,
            settings.llm_timeout_seconds,
            settings.llm_max_retries,
        )

    async def analyze(self, data: InvestigationInput) -> AnalysisResult:
        messages: list[dict[str, Any]] = list(build_messages(data))
        usage = {"prompt_tokens": 0, "completion_tokens": 0}
        started = time.monotonic()
        for attempt in range(REPAIR_ATTEMPTS + 1):
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=cast(Any, messages),
                temperature=0,
                response_format=cast(Any, _RESPONSE_FORMAT),
            )
            if response.usage is not None:
                usage["prompt_tokens"] += response.usage.prompt_tokens
                usage["completion_tokens"] += response.usage.completion_tokens
            text = response.choices[0].message.content if response.choices else None
            try:
                report = parse_report(text)
            except ReportFormatError as error:
                log.warning("malformed LLM reply", extra={"attempt": attempt, "error": str(error)})
                if attempt == REPAIR_ATTEMPTS:
                    raise
                messages += [
                    {"role": "assistant", "content": text or ""},
                    {
                        "role": "user",
                        "content": f"Your reply was invalid ({error}). Reply again with only "
                        "the JSON object matching the schema.",
                    },
                ]
                continue
            return AnalysisResult(
                report=report,
                meta={
                    "model": self._model,
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "repairs": attempt,
                    **usage,
                },
            )
        raise AssertionError("unreachable")
