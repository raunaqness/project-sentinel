"""Deterministic screening of retrieved text for prompt-injection attempts (spec §18).

First line of defence: chunks that look like instructions to the model are quarantined
and never reach it. The prompt's untrusted-data framing, citation constraints, grounding
and the model's lack of any write access are the layers behind this one.
"""

import re

_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in {
        "override_instructions": (
            r"\b(ignore|disregard|forget)\b.{0,40}\b(instructions|rules|prompt)"
        ),
        "role_change": r"\byou are now\b|\bact as\b|\bmaintenance mode\b|\bsystem prompt\b",
        "cross_tenant_exfiltration": (
            r"\b(every|all)\b.{0,20}\b(merchant|tenant|transaction)s?\b.{0,40}"
            r"\b(return|reveal|list|include|show)"
            r"|\b(return|reveal|list|show)\b.{0,30}\b(every|all)\b"
            r".{0,20}\b(merchant|tenant|transaction)s?"
        ),
        "truth_override": r"\b(always|automatically)\b.{0,30}\b(mark|report|treat)\b.{0,40}"
        r"\b(reconciled|resolved|matched)\b|\bignore\b.{0,30}\b(transaction records|amounts)\b",
    }.items()
}


def injection_signals(text: str) -> list[str]:
    """Names of the injection patterns found in `text` (empty if it looks benign)."""
    return [name for name, pattern in _PATTERNS.items() if pattern.search(text)]
