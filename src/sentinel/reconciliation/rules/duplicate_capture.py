from sentinel.domain.transaction_state import TransactionState
from sentinel.reconciliation.base import Finding, Rule, RuleContext, Severity, register


@register
class DuplicateCapture(Rule):
    """More than one distinct capture event for the same transaction."""

    anomaly_type = "DUPLICATE_CAPTURE"
    severity = Severity.HIGH

    def evaluate(self, txn: TransactionState, ctx: RuleContext) -> Finding | None:
        if txn.capture_count <= 1:
            return None
        return self.finding(capture_count=txn.capture_count)
