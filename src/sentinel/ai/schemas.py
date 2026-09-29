"""Contract between the workflow and any investigator (mock or LLM-backed)."""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class InvestigationInput(BaseModel):
    tenant_id: str
    transaction_id: str
    anomaly_type: str
    finding: dict[str, Any]  # deterministic rule output (amounts, differences)
    transaction: dict[str, Any]  # materialized state
    events: list[dict[str, Any]]  # raw events; `event_id` is the citation key
    knowledge: list[dict[str, Any]] = Field(default_factory=list)  # retrieved chunks


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1)
    source: str = Field(min_length=1)  # an event_id or knowledge chunk id


class InvestigationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1)
    facts: list[Fact]
    hypotheses: list[str]
    recommended_action: str = Field(min_length=1)
    requires_human_review: bool = True


class AnalysisResult(BaseModel):
    report: InvestigationReport
    meta: dict[str, Any] = Field(default_factory=dict)  # model, tokens, latency, repairs


class ReportFormatError(ValueError):
    """The model's reply was empty, not JSON, or did not match the report schema."""


def parse_report(text: str | None) -> InvestigationReport:
    if not text or not text.strip():
        raise ReportFormatError("empty response")
    cleaned = text.strip()
    if cleaned.startswith("```"):  # tolerate a fenced JSON block
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        return InvestigationReport.model_validate(json.loads(cleaned))
    except json.JSONDecodeError as error:
        raise ReportFormatError(f"invalid JSON: {error}") from error
    except ValidationError as error:
        raise ReportFormatError(f"schema mismatch: {error.errors(include_url=False)}") from error


# Strict JSON schema for OpenAI-style structured outputs (all fields required,
# no additional properties).
REPORT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "classification",
        "confidence",
        "summary",
        "facts",
        "hypotheses",
        "recommended_action",
        "requires_human_review",
    ],
    "properties": {
        "classification": {"type": "string"},
        "confidence": {"type": "number"},
        "summary": {"type": "string"},
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim", "source"],
                "properties": {"claim": {"type": "string"}, "source": {"type": "string"}},
            },
        },
        "hypotheses": {"type": "array", "items": {"type": "string"}},
        "recommended_action": {"type": "string"},
        "requires_human_review": {"type": "boolean"},
    },
}
