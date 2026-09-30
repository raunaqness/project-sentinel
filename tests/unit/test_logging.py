import json
import logging

from sentinel.observability.logging import JsonFormatter, log_context


def render(record: logging.LogRecord) -> dict[str, object]:
    return json.loads(JsonFormatter("test").format(record))  # type: ignore[no-any-return]


def make_record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("sentinel.test", logging.INFO, __file__, 1, msg, None, None)
    record.__dict__.update(extra)
    return record


def test_context_and_extra_fields_are_included() -> None:
    with log_context(tenant_id="merchant_123", transaction_id="txn_1"):
        line = render(make_record("event stored", state="MATCHED"))
    assert line["msg"] == "event stored"
    assert line["service"] == "test"
    assert line["tenant_id"] == "merchant_123"
    assert line["transaction_id"] == "txn_1"
    assert line["state"] == "MATCHED"


def test_context_is_scoped() -> None:
    with log_context(tenant_id="merchant_123"):
        pass
    assert "tenant_id" not in render(make_record("outside"))
