"""Runs every registered rule against a transaction's facts."""

import importlib
import pkgutil
from datetime import datetime, timedelta

from sentinel.config import get_settings
from sentinel.domain.transaction_state import TransactionState
from sentinel.reconciliation import rules
from sentinel.reconciliation.base import RULES, Finding, RuleContext

for _module in pkgutil.iter_modules(rules.__path__):
    importlib.import_module(f"{rules.__name__}.{_module.name}")


def context_at(now: datetime) -> RuleContext:
    settings = get_settings()
    return RuleContext(
        now=now,
        grace=timedelta(seconds=settings.reconciliation_grace_seconds),
        missing_settlement_after=timedelta(seconds=settings.missing_settlement_seconds),
    )


def evaluate(txn: TransactionState, ctx: RuleContext) -> list[Finding]:
    return [finding for rule in RULES if (finding := rule.evaluate(txn, ctx)) is not None]
