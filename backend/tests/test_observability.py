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


# ------------------------------------ Serverfehler bleibt lesbar (v2.11.0)
# Starlettes ServerErrorMiddleware liegt ausserhalb der CORS-Middleware. Eine
# 500er-Antwort ohne Access-Control-Allow-Origin verwirft der Browser, bevor
# das Skript sie sieht: ``fetch`` wirft, und api.js meldet "Netzwerkfehler".
# Server abgestuerzt und Server nicht erreichbar sahen damit gleich aus.
import main                                                    # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402


@main.app.get("/api/_testfehler")
async def _kaputt():
    raise RuntimeError("absichtlich")


def _client():
    # ``raise_server_exceptions=False``: sonst reicht der Testclient den
    # Fehler durch, statt die Antwort zu liefern, um die es hier geht.
    return TestClient(main.app, raise_server_exceptions=False)


def test_serverfehler_traegt_die_cors_koepfe():
    herkunft = main.CORS_ORIGINS[0]
    res = _client().get("/api/_testfehler", headers={"Origin": herkunft})
    assert res.status_code == 500
    assert res.headers.get("access-control-allow-origin") == herkunft
    # Die Kennung steht in der Antwort UND im Kopf -- sonst muesste man im
    # Log nach einem Zeitstempel suchen.
    assert res.headers.get("x-request-id")
    assert res.headers["x-request-id"] in res.json()["detail"]


def test_serverfehler_verraet_nicht_was_kaputt_ist():
    """Ein Stacktrace im Browser ist fuer niemanden gedacht."""
    res = _client().get("/api/_testfehler",
                        headers={"Origin": main.CORS_ORIGINS[0]})
    assert "absichtlich" not in res.text
    assert "RuntimeError" not in res.text


def test_fremde_herkunft_bekommt_keinen_freibrief():
    res = _client().get("/api/_testfehler",
                        headers={"Origin": "https://boese.example"})
    assert res.status_code == 500
    assert "access-control-allow-origin" not in res.headers
