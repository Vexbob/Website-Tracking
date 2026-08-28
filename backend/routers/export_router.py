"""Export-Router — kombinierter Gesamt-Export (Sparziel + Ausgaben + Gesundheit).

Kein Prefix: absoluter Pfad ``/api/export/all``.

v1.28.0: Response wird transparent mit gzip komprimiert, wenn der Client
``Accept-Encoding: gzip`` sendet. Bei einem typischen 1-Jahres-Export
sinkt die Uebertragungsgroesse dadurch um ~85 % (Textdaten mit vielen
wiederkehrenden Werten komprimieren extrem gut).
"""
import gzip

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from database import get_db
from auth import get_current_user
from services.full_export import build_full_export_csv

router = APIRouter(tags=["export"])


@router.get("/api/export/all")
async def export_all(request: Request, db=Depends(get_db), user=Depends(get_current_user)):
    """Eine einzige CSV mit Sparziel-, Ausgaben- und Gesundheitsdaten,
    inkl. erklaerender Kommentarzeilen vor jeder Sektion (siehe
    services/full_export.py)."""
    csv = await build_full_export_csv(db, user)
    # UTF-8 mit BOM, damit Excel Umlaute (ä/ö/ü/ß) korrekt darstellt
    body = ("\ufeff" + csv).encode("utf-8")

    headers = {
        "Content-Disposition": 'attachment; filename="vexbob-gesamt-export.csv"',
        "Cache-Control": "no-store",
    }
    # Optionale gzip-Kompression - massive Ersparnis bei grossen Exports
    accept_enc = request.headers.get("accept-encoding", "").lower()
    if "gzip" in accept_enc:
        body = gzip.compress(body, compresslevel=6)
        headers["Content-Encoding"] = "gzip"
        headers["Vary"] = "Accept-Encoding"

    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )

