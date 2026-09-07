"""Export-Router — kombinierter Gesamt-Export (Sparziel + Ausgaben + Gesundheit).

Kein Prefix: absolute Pfade ``/api/export/...``.

v1.28.0: Response wird transparent mit gzip komprimiert, wenn der Client
``Accept-Encoding: gzip`` sendet. Bei einem typischen 1-Jahres-Export
sinkt die Uebertragungsgroesse dadurch um ~85 % (Textdaten mit vielen
wiederkehrenden Werten komprimieren extrem gut).

v1.37.1: Optionale Query-Parameter
    * ``from`` / ``to`` (ISO-Datum, YYYY-MM-DD) - filtert alle
      zeitreihen-basierten Sektionen (Ausgaben, Sparziel-Protokoll,
      Health-Vitalwerte, Blutdruck, Blutzucker, Schlaf, Workouts).
      Metadaten-Sektionen (Sparziel-Definitionen, Achievements, ...)
      bleiben unveraendert, sonst wird der Kontext der aggregierten
      Zahlen unverstaendlich.
    * ``aggregate`` = ``none`` | ``week`` | ``month`` - fasst grosse
      Zeitraeume zu Perioden zusammen.

v1.60.0: Der Export ist zusammenstellbar.
    * ``sections`` - kommagetrennte Sektions-Schluessel. Ohne Angabe ist
      alles dabei; unbekannte Schluessel werden verworfen, eine leere
      Auswahl faellt auf "alles" zurueck (eine leere Datei hilft niemandem).
    * ``agg_sparziel`` / ``agg_ausgaben`` / ``agg_health`` - Aggregation je
      Modul. Was fehlt, erbt ``aggregate``; damit bleiben alte Aufrufe
      (nur ``aggregate``) unveraendert gueltig.
    * ``GET /api/export/sections`` liefert die Sektions- und Gruppenliste,
      damit die Oberflaeche sie nicht ein zweites Mal fuehrt.
    * ``GET /api/export/preview`` liefert dieselbe Zusammenstellung als
      Kennzahlen samt der ersten Zeilen der echten Datei.
"""
import gzip
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from database import get_db
from auth import get_current_user
from services.full_export import (
    EXPORT_GROUPS,
    EXPORT_SECTIONS,
    build_export_preview,
    build_full_export_csv,
    clean_aggregate_map,
)

router = APIRouter(tags=["export"])

AGG_PATTERN = "^(none|week|month)$"


def _parse_date(v: str | None, name: str) -> date | None:
    if v is None or v == "":
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise HTTPException(400, f"{name} muss im Format YYYY-MM-DD sein")


def _parse_sections(raw: str | None) -> list[str] | None:
    """``sections`` kommt als Kommaliste. ``None`` heisst "nicht angegeben"
    und damit alles -- eine leere Zeichenkette ebenfalls, denn ein Export
    ohne Sektionen ist eine leere Datei."""
    if not raw:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]


def _agg_map(sparziel, ausgaben, health) -> dict:
    """Nur die tatsaechlich uebergebenen Module. Der Rest erbt in
    ``clean_aggregate_map`` den Gesamtwert."""
    given = {"sparziel": sparziel, "ausgaben": ausgaben, "health": health}
    return {k: v for k, v in given.items() if v}


def _validated_range(date_from: str | None, date_to: str | None):
    d_from = _parse_date(date_from, "from")
    d_to = _parse_date(date_to, "to")
    if d_from and d_to and d_from > d_to:
        raise HTTPException(400, "'from' liegt nach 'to'")
    return d_from, d_to


@router.get("/api/export/sections")
async def export_sections(user=Depends(get_current_user)):
    """Was sich exportieren laesst. Die Oberflaeche baut ihre Auswahl daraus,
    damit eine neue Sektion nur an einer Stelle eingetragen werden muss."""
    return {"sections": EXPORT_SECTIONS, "groups": EXPORT_GROUPS}


@router.get("/api/export/preview")
async def export_preview(
    date_from: str | None = Query(None, alias="from", description="ISO-Datum YYYY-MM-DD"),
    date_to: str | None = Query(None, alias="to", description="ISO-Datum YYYY-MM-DD"),
    aggregate: str = Query("none", pattern=AGG_PATTERN),
    sections: str | None = Query(None, description="Kommaliste von Sektions-Schluesseln"),
    agg_sparziel: str | None = Query(None, pattern=AGG_PATTERN),
    agg_ausgaben: str | None = Query(None, pattern=AGG_PATTERN),
    agg_health: str | None = Query(None, pattern=AGG_PATTERN),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Zeilen und Groesse je Sektion plus die ersten Zeilen der Datei."""
    d_from, d_to = _validated_range(date_from, date_to)
    return await build_export_preview(
        db, user, date_from=d_from, date_to=d_to, aggregate=aggregate,
        sections=_parse_sections(sections),
        aggregate_map=_agg_map(agg_sparziel, agg_ausgaben, agg_health))


@router.get("/api/export/all")
async def export_all(
    request: Request,
    date_from: str | None = Query(None, alias="from", description="ISO-Datum YYYY-MM-DD"),
    date_to: str | None = Query(None, alias="to", description="ISO-Datum YYYY-MM-DD"),
    aggregate: str = Query("none", pattern=AGG_PATTERN),
    sections: str | None = Query(None, description="Kommaliste von Sektions-Schluesseln"),
    agg_sparziel: str | None = Query(None, pattern=AGG_PATTERN),
    agg_ausgaben: str | None = Query(None, pattern=AGG_PATTERN),
    agg_health: str | None = Query(None, pattern=AGG_PATTERN),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Eine CSV mit den gewaehlten Sektionen, inkl. erklaerender
    Kommentarzeilen vor jeder Sektion. Optional per Zeitraum gefiltert und
    je Modul wochen-/monatsweise zusammengefasst."""
    d_from, d_to = _validated_range(date_from, date_to)
    picked = _parse_sections(sections)
    agg_map = _agg_map(agg_sparziel, agg_ausgaben, agg_health)

    csv = await build_full_export_csv(
        db, user, date_from=d_from, date_to=d_to, aggregate=aggregate,
        sections=picked, aggregate_map=agg_map)
    # UTF-8 mit BOM, damit Excel Umlaute (ä/ö/ü/ß) korrekt darstellt
    body = ("\ufeff" + csv).encode("utf-8")

    # Dateiname mit Optionen anreichern, damit mehrere Exports im Downloads-
    # Ordner nicht kollidieren.
    parts = ["vexbob-gesamt-export"]
    if d_from or d_to:
        parts.append(f"{(d_from.isoformat() if d_from else 'start')}_bis_{(d_to.isoformat() if d_to else 'ende')}")
    # Der Dateiname nennt die Aggregation nur, wenn sie ueberall dieselbe ist;
    # sonst waere "…-month" eine Behauptung ueber Sektionen, die einzeln
    # exportiert wurden.
    used_aggs = set(clean_aggregate_map(agg_map, aggregate).values())
    if len(used_aggs) == 1 and used_aggs != {"none"}:
        parts.append(used_aggs.pop())
    elif len(used_aggs) > 1:
        parts.append("gemischt")
    if picked:
        parts.append("auswahl")
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
