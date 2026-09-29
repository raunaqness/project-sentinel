"""Evidence grounding: a fact survives only if its cited source supports it.

Deterministic post-processing of the model's report. Facts that cite an unknown
source, or contain a number that does not appear in the cited source (or in the
authoritative finding/transaction data), are moved to hypotheses and flagged, so
unsupported statements are never presented as facts (spec §11.1).
"""

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from sentinel.ai.schemas import Fact, InvestigationReport

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[Decimal]:
    found = set()
    for raw in _NUMBER.findall(text):
        try:
            found.add(Decimal(raw.replace(",", "")).normalize())
        except InvalidOperation:
            continue
    return found


def ground(
    report: InvestigationReport,
    events: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    authoritative: dict[str, Any],
) -> tuple[InvestigationReport, dict[str, Any]]:
    sources: dict[str, str] = {e["event_id"]: json.dumps(e, default=str) for e in events}
    sources |= {c["chunk_id"]: str(c["content"]) for c in chunks}
    always_known = _numbers(json.dumps(authoritative, default=str))

    kept: list[Fact] = []
    demoted: list[dict[str, str]] = []
    for fact in report.facts:
        if fact.source not in sources:
            demoted.append({"claim": fact.claim, "source": fact.source, "reason": "unknown source"})
            continue
        unsupported = _numbers(fact.claim) - _numbers(sources[fact.source]) - always_known
        if unsupported:
            demoted.append(
                {
                    "claim": fact.claim,
                    "source": fact.source,
                    "reason": f"numbers not in source: {sorted(str(n) for n in unsupported)}",
                }
            )
            continue
        kept.append(fact)

    grounded = report.model_copy(
        update={
            "facts": kept,
            "hypotheses": report.hypotheses + [f"Unverified: {d['claim']}" for d in demoted],
            "requires_human_review": True,  # the model cannot opt out of human review
        }
    )
    stats = {
        "facts_total": len(report.facts),
        "facts_supported": len(kept),
        "unsupported_claims": demoted,
    }
    return grounded, stats
