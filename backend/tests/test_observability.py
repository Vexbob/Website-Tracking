"""Tests fuer Observability-Helper (v1.34.0):
- RequestIdFilter setzt request_id-Attribut auf jedem Log-Record
- ContextVar isoliert korrekt zwischen "Requests"
"""
import logging
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from deps import RequestIdFilter, request_id_ctx  # noqa: E402


def _make_record(msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )


def test_filter_default_is_dash():
    # Ausserhalb eines Requests: Default-Wert
    f = RequestIdFilter()
    rec = _make_record()
    f.filter(rec)
    assert rec.request_id == "-"


def test_filter_uses_contextvar():
    f = RequestIdFilter()
    tok = request_id_ctx.set("abc123")
    try:
        rec = _make_record()
        f.filter(rec)
        assert rec.request_id == "abc123"
    finally:
        request_id_ctx.reset(tok)


def test_filter_isolates_between_resets():
    f = RequestIdFilter()
    tok1 = request_id_ctx.set("req-1")
    rec1 = _make_record()
    f.filter(rec1)
    request_id_ctx.reset(tok1)

    tok2 = request_id_ctx.set("req-2")
    rec2 = _make_record()
    f.filter(rec2)
    request_id_ctx.reset(tok2)

    assert rec1.request_id == "req-1"
    assert rec2.request_id == "req-2"


def test_ser_consolidated_iso_and_decimal():
    """v1.34.0: helpers.ser() ersetzt drei Duplikate. Wir pruefen beide Modi."""
    from datetime import datetime, timezone
    from decimal import Decimal
    from helpers import ser

    row = {
        "id": 1,
        "created_at": datetime(2025, 1, 2, 3, 4, tzinfo=timezone.utc),
        "amount": Decimal("12.34"),
        "name": "Bob",
    }
    d1 = ser(row)  # Default: Decimals bleiben Decimals
    assert d1["created_at"].startswith("2025-01-02T03:04:00")
    assert isinstance(d1["amount"], Decimal)

    d2 = ser(row, decimals_as_float=True)
    assert isinstance(d2["amount"], float)
    assert abs(d2["amount"] - 12.34) < 1e-9
