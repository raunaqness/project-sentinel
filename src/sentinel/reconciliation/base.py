"""Rule contract and registry.

Adding a check = adding one module under `rules/` with a `@register`-ed Rule
subclass. Modules in that package are imported automatically by the engine.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, ClassVar

from sentinel.domain.transaction_state import TransactionState


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class RuleContext:
    now: datetime
    # Tolerance for normal asynchronous arrival, measured from when Sentinel *received*
    # the triggering event, so late-delivered events don't raise false alarms.
    grace: timedelta
    # Business deadline, measured from the capture's event time.
    missing_settlement_after: timedelta


@dataclass(frozen=True)
class Finding:
    anomaly_type: str
    severity: Severity
    details: dict[str, Any] = field(default_factory=dict)


class Rule(ABC):
    anomaly_type: ClassVar[str]
    severity: ClassVar[Severity]

    @abstractmethod
    def evaluate(self, txn: TransactionState, ctx: RuleContext) -> Finding | None:
        """Return a Finding if the rule fires, else None. Must be pure and deterministic."""

    def finding(self, **details: Any) -> Finding:
        return Finding(self.anomaly_type, self.severity, details)


RULES: list[Rule] = []


def register[R: type[Rule]](cls: R) -> R:
    RULES.append(cls())
    return cls
