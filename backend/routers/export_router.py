"""Export-Router — kombinierter Gesamt-Export (Sparziel + Ausgaben + Gesundheit).

Kein Prefix: absoluter Pfad ``/api/export/all``.

v1.28.0: Response wird transparent mit gzip komprimiert, wenn der Client
``Accept-Encoding: gzip`` sendet. Bei einem typischen 1-Jahres-Export
sinkt die Uebertragungsgroesse dadurch um ~85 % (Textdaten mit vielen
wiederkehrenden Werten komprimieren extrem gut).

v1.37.1: Optionale Query-Parameter
    * ``date_from`` / ``date_to`` (ISO-Datum, YYYY-MM-DD) - filtert alle
      zeitreihen-basierten Sektionen (Ausgaben, Sparziel-Protokoll,
      Health-Vitalwerte, Blutdruck, Blutzucker, Schlaf, Workouts).
      Metadaten-Sektionen (Sparziel-Definitionen, Achievements, ...)
      bleiben unveraendert, sonst wird der Kontext der aggregierten
      Zahlen unverstaendlich.
    * ``aggregate`` = ``none`` | ``week`` | ``month`` - fasst grosse
      Zeitraeume zu Perioden zusammen. Ausgaben werden dann als
      Wochen-/Monats-Zusammenfassung (Anzahl Bons + Summe) statt als
      Einzel-Bons ausgegeben, Vitalwerte als Perioden-Durchschnitte.
"""
import gzip
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from database import get_db
from auth import get_current_user
from services.full_export import build_full_export_csv

router = APIRouter(tags=["export"])


def _parse_date(v: str | None, name: str) -> date | None:
    if v is None or v == "":
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise HTTPException(400, f"{name} muss im Format YYYY-MM-DD sein")


@router.get("/api/export/all")
async def export_all(
    request: Request,
    date_from: str | None = Query(None, alias="from", description="ISO-Datum YYYY-MM-DD"),
    date_to: str | None = Query(None, alias="to", description="ISO-Datum YYYY-MM-DD"),
    aggregate: str = Query("none", pattern="^(none|week|month)$"),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Eine einzige CSV mit Sparziel-, Ausgaben- und Gesundheitsdaten,
    inkl. erklaerender Kommentarzeilen vor jeder Sektion. Optional per
    Zeitraum gefiltert und/oder wochen-/monatsweise aggregiert."""
    d_from = _parse_date(date_from, "from")
    d_to = _parse_date(date_to, "to")
    if d_from and d_to and d_from > d_to:
        raise HTTPException(400, "'from' liegt nach 'to'")

    csv = await build_full_export_csv(
        db, user, date_from=d_from, date_to=d_to, aggregate=aggregate)
    # UTF-8 mit BOM, damit Excel Umlaute (ä/ö/ü/ß) korrekt darstellt
    body = ("\ufeff" + csv).encode("utf-8")

    # Dateiname mit Optionen anreichern, damit mehrere Exports im Downloads-
    # Ordner nicht kollidieren.
    parts = ["vexbob-gesamt-export"]
    if d_from or d_to:
        parts.append(f"{(d_from.isoformat() if d_from else 'start')}_bis_{(d_to.isoformat() if d_to else 'ende')}")
    if aggregate != "none":
        parts.append(aggregate)
    filename = "-".join(parts) + ".csv"

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
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

