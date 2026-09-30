from sentinel.domain.transaction_state import TransactionState
from sentinel.reconciliation.base import Finding, Rule, RuleContext, Severity, register


@register
class SettlementMismatch(Rule):
    """Captured amount and bank settlement amount differ."""

    anomaly_type = "SETTLEMENT_MISMATCH"
    severity = Severity.MEDIUM

    def evaluate(self, txn: TransactionState, ctx: RuleContext) -> Finding | None:
        if txn.payment_amount is None or txn.settlement_amount is None:
            return None
        if txn.payment_amount == txn.settlement_amount:
            return None
        return self.finding(
            payment_amount=str(txn.payment_amount),
            settlement_amount=str(txn.settlement_amount),
            difference=str(txn.payment_amount - txn.settlement_amount),
        )
