from decimal import Decimal

import pytest

from sentinel.domain.priority import Priority, score


@pytest.mark.parametrize(
    ("anomaly", "severity", "amount", "expected"),
    [
        ("DUPLICATE_CAPTURE", "HIGH", Decimal("10"), Priority.CRITICAL),
        ("SETTLEMENT_MISMATCH", "MEDIUM", Decimal("100000"), Priority.CRITICAL),
        ("MISSING_LEDGER", "HIGH", Decimal("50"), Priority.HIGH),
        ("SETTLEMENT_MISMATCH", "MEDIUM", Decimal("10000"), Priority.HIGH),
        ("SETTLEMENT_MISMATCH", "MEDIUM", Decimal("9999.99"), Priority.MEDIUM),
        ("SOMETHING_MINOR", "LOW", Decimal("5"), Priority.LOW),
        ("SOMETHING_MINOR", "LOW", None, Priority.LOW),
    ],
)
def test_score(anomaly: str, severity: str, amount: Decimal | None, expected: Priority) -> None:
    assert score(anomaly, severity, amount) is expected
