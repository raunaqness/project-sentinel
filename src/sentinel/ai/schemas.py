"""Contract between the workflow and any investigator (mock or LLM-backed)."""

from typing import Any

from pydantic import BaseModel, Field


class InvestigationInput(BaseModel):
    tenant_id: str
    transaction_id: str
    anomaly_type: str
    finding: dict[str, Any]  # deterministic rule output (amounts, differences)
    transaction: dict[str, Any]  # materialized state
    events: list[dict[str, Any]]  # raw events; `event_id` is the citation key
    knowledge: list[dict[str, Any]] = Field(default_factory=list)  # retrieved chunks


class Fact(BaseModel):
    claim: str = Field(min_length=1)
    source: str = Field(min_length=1)  # an event_id or knowledge chunk id


class InvestigationReport(BaseModel):
    classification: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1)
    facts: list[Fact]
    hypotheses: list[str]
    recommended_action: str = Field(min_length=1)
    requires_human_review: bool = True
