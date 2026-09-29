from sentinel.domain.transaction_state import TransactionState
from sentinel.reconciliation.base import Finding, Rule, RuleContext, Severity, register


@register
class RefundMismatch(Rule):
    """Internal refund exists but the gateway has not refunded the same amount."""

    anomaly_type = "REFUND_MISMATCH"
    severity = Severity.HIGH

    def evaluate(self, txn: TransactionState, ctx: RuleContext) -> Finding | None:
        internal = txn.internal_refund_amount
        if internal is None or internal == txn.gateway_refund_amount:
            return None
        if ctx.now - txn.last_received_at < ctx.grace:
            return None
        return self.finding(
            internal_refund_amount=str(internal),
            gateway_refund_amount=str(txn.gateway_refund_amount),
        )
