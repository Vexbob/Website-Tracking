"""Geteilte Utilities & Konstanten für alle Router.

Bewusst schlank gehalten: nur was von >=2 Modulen gebraucht wird.
Alles was nur ein Router braucht, bleibt in dessen Datei.
"""
import logging
from contextvars import ContextVar
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address


# ---------------------------------------------------------------------------
# Structured Logging (v1.34.0)
# ---------------------------------------------------------------------------
# ContextVar wird per Middleware pro Request gesetzt und automatisch an jedes
# Log-Record angehaengt. Anderer Code muss NICHTS aendern -- ``logger.info(...)``
# bekommt die request_id via LogFilter mitgeliefert. Praktisch, um in einem
# Multi-User-Setup auf Railway einzelne fehlgeschlagene Requests von der ersten
# bis zur letzten Log-Zeile durchzugreppen.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """Fuegt jedem LogRecord ein Attribut ``request_id`` hinzu. Ohne diesen
    Filter wuerde ``%(request_id)s`` im Log-Format zu KeyError fuehren, sobald
    ein Log ausserhalb eines Requests emittiert wird (z.B. beim Startup)."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        record.request_id = request_id_ctx.get()
        return True


logger = logging.getLogger("vexbob")

def besucher_adresse(request) -> str:
    """Wer eine Anfrage schickt -- der Schluessel fuer die Rate-Limits.

    Bis v2.39.0 stand hier ``get_remote_address``: die Adresse der
    Verbindung. Auf Railway ist das der vorgeschaltete Proxy, nicht der
    Besucher -- uvicorn traut ``X-Forwarded-For`` nur von 127.0.0.1. Damit
    teilten sich ALLE dieselben fuenf Login-Versuche je Minute, und wer
    fuenfmal falsch tippte, sperrte auch den Besitzer aus.

    Genommen wird der LETZTE Eintrag von ``X-Forwarded-For``: den haengt der
    Proxy selbst an. Die Eintraege davor kommen vom Besucher und lassen sich
    beliebig faelschen -- wer den ersten naehme, koennte mit jeder Anfrage
    eine neue Adresse behaupten und die Sperre umgehen. Ohne den Kopf (lokal,
    Tests) gilt wie bisher die Adresse der Verbindung."""
    weiter = request.headers.get("x-forwarded-for", "")
    letzte = weiter.split(",")[-1].strip() if weiter else ""
    return letzte or get_remote_address(request)


# Ein einziger Limiter für die gesamte App (in main.py an app.state gebunden).
limiter = Limiter(key_func=besucher_adresse)

# Rate-Limit-Konstanten (Slowapi-Syntax)
LIMIT_LOGIN = "5/minute"
LIMIT_WRITE_FREQUENT = "60/minute"
LIMIT_WRITE_STANDARD = "30/minute"
LIMIT_WRITE_RARE = "10/minute"
# Health-Sync (Auto Health Export synct typischerweise mehrmals taeglich
# automatisiert, aber grosszuegig genug fuer manuelle Re-Syncs/Backfills).
LIMIT_HEALTH_IMPORT = "20/hour"

# Upload-Grenze für Belegbilder
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def _num(v):
    """asyncpg NUMERIC/Decimal -> float, sonst durchreichen."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _ser_exp(row) -> dict:
    """Serialisiert eine asyncpg-Row zu dict mit ISO-Dates & Float-Decimals.

    v1.34.0: Ist nur noch ein duenner Wrapper um ``helpers.ser`` mit
    ``decimals_as_float=True``. Damit bleiben alte Router-Imports
    (``from deps import _ser_exp``) kompatibel, ohne Logik-Duplikat.
    """
    from helpers import ser
    return ser(row, decimals_as_float=True)


def _parse_iso_date(s: Optional[str]):
    """Parst YYYY-MM-DD in datetime.date. Wirft HTTP 400 bei Fehler."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        raise HTTPException(400, "Datum muss ISO-Format YYYY-MM-DD sein")
