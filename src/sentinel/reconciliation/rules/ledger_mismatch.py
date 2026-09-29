from sentinel.domain.transaction_state import TransactionState
from sentinel.reconciliation.base import Finding, Rule, RuleContext, Severity, register


@register
class LedgerMismatch(Rule):
    """Ledger posted an amount that differs from the capture, or posted for a failed payment."""

    anomaly_type = "LEDGER_MISMATCH"
    severity = Severity.HIGH

    def evaluate(self, txn: TransactionState, ctx: RuleContext) -> Finding | None:
        if txn.ledger_amount is None:
            return None
        if txn.payment_status == "FAILED":
            return self.finding(reason="ledger posted for failed payment")
        if txn.payment_amount is None or txn.payment_amount == txn.ledger_amount:
            return None
        return self.finding(
            payment_amount=str(txn.payment_amount),
            ledger_amount=str(txn.ledger_amount),
            difference=str(txn.payment_amount - txn.ledger_amount),
        )
