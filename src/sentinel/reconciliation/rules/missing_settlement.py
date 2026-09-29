from sentinel.domain.transaction_state import TransactionState
from sentinel.reconciliation.base import Finding, Rule, RuleContext, Severity, register


@register
class MissingSettlement(Rule):
    """Payment succeeded but no settlement arrived within the configured threshold."""

    anomaly_type = "MISSING_SETTLEMENT"
    severity = Severity.MEDIUM

    def evaluate(self, txn: TransactionState, ctx: RuleContext) -> Finding | None:
        if txn.payment_status != "SUCCESS" or txn.settlement_status is not None:
            return None
        captured_at = txn.payment_captured_at
        if captured_at is None or ctx.now - captured_at < ctx.missing_settlement_after:
            return None
        return self.finding(
            captured_at=captured_at.isoformat(),
            threshold_seconds=int(ctx.missing_settlement_after.total_seconds()),
        )
