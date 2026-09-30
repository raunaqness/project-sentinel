from sentinel.domain.transaction_state import TransactionState
from sentinel.reconciliation.base import Finding, Rule, RuleContext, Severity, register


@register
class MissingLedger(Rule):
    """Payment succeeded but no ledger entry exists after the grace period."""

    anomaly_type = "MISSING_LEDGER"
    severity = Severity.HIGH

    def evaluate(self, txn: TransactionState, ctx: RuleContext) -> Finding | None:
        if txn.payment_status != "SUCCESS" or txn.ledger_status is not None:
            return None
        received_at = txn.payment_received_at
        if received_at is None or ctx.now - received_at < ctx.grace:
            return None
        return self.finding(
            payment_amount=str(txn.payment_amount), payment_received_at=received_at.isoformat()
        )
