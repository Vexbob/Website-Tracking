"""Geteilte Utilities & Konstanten für alle Router.

Bewusst schlank gehalten: nur was von >=2 Modulen gebraucht wird.
Alles was nur ein Router braucht, bleibt in dessen Datei.
"""
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address


logger = logging.getLogger("vexbob")

# Ein einziger Limiter für die gesamte App (in main.py an app.state gebunden).
limiter = Limiter(key_func=get_remote_address)

# Rate-Limit-Konstanten (Slowapi-Syntax)
LIMIT_LOGIN = "5/minute"
LIMIT_WRITE_FREQUENT = "60/minute"
LIMIT_WRITE_STANDARD = "30/minute"
LIMIT_WRITE_RARE = "10/minute"

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
    """Serialisiert eine asyncpg-Row zu dict mit ISO-Dates & Float-Decimals."""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = float(v)
    return d


def _parse_iso_date(s: Optional[str]):
    """Parst YYYY-MM-DD in datetime.date. Wirft HTTP 400 bei Fehler."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        raise HTTPException(400, "Datum muss ISO-Format YYYY-MM-DD sein")
