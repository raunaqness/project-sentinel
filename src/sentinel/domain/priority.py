"""Investigation priority: deterministic scoring from anomaly, severity and amount."""

from decimal import Decimal
from enum import StrEnum


class Priority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


CRITICAL_AMOUNT = Decimal("100000")
HIGH_AMOUNT = Decimal("10000")
CRITICAL_ANOMALIES = frozenset({"DUPLICATE_CAPTURE"})  # customer charged twice


def score(anomaly_type: str, severity: str, amount: Decimal | None) -> Priority:
    amount = amount or Decimal(0)
    if anomaly_type in CRITICAL_ANOMALIES or amount >= CRITICAL_AMOUNT:
        return Priority.CRITICAL
    if severity in ("HIGH", "CRITICAL") or amount >= HIGH_AMOUNT:
        return Priority.HIGH
    if severity == "MEDIUM":
        return Priority.MEDIUM
    return Priority.LOW
