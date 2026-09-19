"""Export-Router — kombinierter Gesamt-Export aller Module.

Kein Prefix: absolute Pfade ``/api/export/...``.

v1.28.0: Response wird transparent mit gzip komprimiert, wenn der Client
``Accept-Encoding: gzip`` sendet. Bei einem typischen 1-Jahres-Export
sinkt die Uebertragungsgroesse dadurch um ~85 % (Textdaten mit vielen
wiederkehrenden Werten komprimieren extrem gut).

v1.37.1: Optionale Query-Parameter
    * ``from`` / ``to`` (ISO-Datum, YYYY-MM-DD) - filtert alle
      zeitreihen-basierten Sektionen.
    * ``aggregate`` - fasst grosse Zeitraeume zu Perioden zusammen.

v1.60.0: Der Export ist zusammenstellbar.
    * ``sections`` - kommagetrennte Sektions-Schluessel. Ohne Angabe ist
      alles dabei; unbekannte Schluessel werden verworfen, eine leere
      Auswahl faellt auf "alles" zurueck (eine leere Datei hilft niemandem).
    * ``GET /api/export/sections`` liefert die Sektions- und Gruppenliste,
      damit die Oberflaeche sie nicht ein zweites Mal fuehrt.
    * ``GET /api/export/preview`` liefert dieselbe Zusammenstellung als
      Kennzahlen samt der ersten Zeilen der echten Datei.

v1.67.0: Der Export ist dynamisch statt fest verdrahtet.
    * Die Aggregation je Modul heisst ``agg_<gruppe>`` und wird aus der
      Anfrage GELESEN statt einzeln deklariert. Ein neues Modul braucht
      damit keine neue Zeile in diesem Router mehr -- vorher standen
      ``agg_sparziel``, ``agg_ausgaben`` und ``agg_health`` je dreimal hier.
    * Die Stufen kommen aus ``EXPORT_AGGREGATES``: none, auto, day, week,
      month, year. ``auto`` waehlt nach Laenge des Zeitraums.
    * ``cols_<sektion>`` waehlt die Spalten einer Sektion (Kommaliste ihrer
      Ueberschriften). Welche es gibt, sagt die Vorschau je Sektion mit --
      sie haengen von der Aggregation ab und lassen sich deshalb nicht
      statisch auflisten.

v1.68.0: ``GET /api/export/fit?max_bytes=...`` stellt die Aggregation selbst
    so ein, dass die Datei eine Hoechstgroesse nicht ueberschreitet. Gedreht
    wird nur an der Zeit; Sektionen und Spalten bleiben unangetastet.

v2.8.0: ``compact_before=YYYY-MM-DD`` verdichtet alles VOR diesem Tag
    monatsweise, waehrend ab diesem Tag die gewaehlte Stufe gilt. Fehlt der
    Parameter, gilt die Voreinstellung des Nutzers (``ui_export``) -- sie ist
    der Grund, warum es sie gibt: eine Regel, die man einmal setzt, darf man
    nicht bei jedem Aufruf wiederholen muessen. ``compact_before=`` (leer)
    schaltet sie fuer diesen einen Aufruf ab.
"""
import gzip
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from database import get_db
from auth import get_current_user
from services.full_export import (
    AGG_KEYS,
    EXPORT_AGGREGATES,
    EXPORT_GROUPS,
    EXPORT_SECTIONS,
    build_export_preview,
    build_full_export_csv,
    clean_aggregate_map,
    fit_export_to_size,
)

router = APIRouter(tags=["export"])

GROUP_KEYS = [g["key"] for g in EXPORT_GROUPS]
SECTION_KEYS = [s["key"] for s in EXPORT_SECTIONS]

# Grenzen fuer die Hoechstgroesse. Unter 50 kB traegt schon der erklaerende
# Vorspann die Datei, darueber waere jede Antwort "passt nicht" und damit
# nutzlos; 2 GB ist die Grenze, ab der die Zahl offensichtlich ein Vertipper
# ist.
MIN_FIT_BYTES = 50 * 1024
MAX_FIT_BYTES = 2 * 1024 * 1024 * 1024


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


def _agg_map(request: Request) -> dict:
    """``agg_<gruppe>=<stufe>`` aus der Anfrage. Unbekannte Gruppen und
    unbekannte Stufen werden still verworfen -- der Rest erbt in
    ``clean_aggregate_map`` den Gesamtwert aus ``aggregate``."""
    out = {}
    for key, value in request.query_params.items():
        if not key.startswith("agg_"):
            continue
        group = key[4:]
        if group in GROUP_KEYS and value in AGG_KEYS:
            out[group] = value
    return out


def _column_map(request: Request) -> dict:
    """``cols_<sektion>=Spalte,Spalte`` aus der Anfrage."""
    out = {}
    for key, value in request.query_params.items():
        if not key.startswith("cols_"):
            continue
        section = key[5:]
        if section not in SECTION_KEYS:
            continue
        names = [p.strip() for p in value.split(",") if p.strip()]
        if names:
            out[section] = names
    return out


def _validated_range(date_from: str | None, date_to: str | None):
    d_from = _parse_date(date_from, "from")
    d_to = _parse_date(date_to, "to")
    if d_from and d_to and d_from > d_to:
        raise HTTPException(400, "'from' liegt nach 'to'")
    return d_from, d_to


async def _export_prefs(db, user) -> dict:
    """Die gespeicherte Voreinstellung. Fehlt oder taugt sie nicht, ist sie
    leer -- eine kaputte Einstellung darf keinen Export verhindern."""
    row = await db.fetchrow(
        "SELECT value FROM user_prefs WHERE user_id=$1 AND key='ui_export'",
        user["id"])
    if not row:
        return {}
    try:
        wert = json.loads(row["value"])
        return wert if isinstance(wert, dict) else {}
    except (ValueError, TypeError):
        return {}


async def _compact_before(request: Request, db, user) -> date | None:
    """Ab wann die gewaehlte Stufe gilt. Die Anfrage schlaegt die
    Voreinstellung -- auch mit einem leeren Wert, der sie ausdruecklich
    abschaltet."""
    if "compact_before" in request.query_params:
        return _parse_date(request.query_params["compact_before"], "compact_before")
    gespeichert = (await _export_prefs(db, user)).get("compact_before")
    return _parse_date(gespeichert, "compact_before") if gespeichert else None


async def _agg_map_mit_vorgabe(request: Request, db, user) -> dict:
    """``agg_<gruppe>`` aus der Anfrage, sonst die Voreinstellung. Eine
    Gruppe, die in der Anfrage steht, bleibt wie sie dort steht."""
    aus_anfrage = _agg_map(request)
    vorgabe = (await _export_prefs(db, user)).get("aggregate") or {}
    out = {g: s for g, s in vorgabe.items()
           if g in GROUP_KEYS and s in AGG_KEYS}
    out.update(aus_anfrage)
    return out


def _validated_aggregate(value: str) -> str:
    if value not in AGG_KEYS:
        raise HTTPException(400, "Unbekannte Aggregation: " + str(value))
    return value


@router.get("/api/export/sections")
async def export_sections(user=Depends(get_current_user)):
    """Was sich exportieren laesst und wie es sich zusammenfassen laesst. Die
    Oberflaeche baut ihre Auswahl daraus, damit eine neue Sektion oder eine
    neue Aggregationsstufe nur an einer Stelle eingetragen werden muss."""
    return {"sections": EXPORT_SECTIONS, "groups": EXPORT_GROUPS,
            "aggregates": EXPORT_AGGREGATES}


@router.get("/api/export/preview")
async def export_preview(
    request: Request,
    date_from: str | None = Query(None, alias="from", description="ISO-Datum YYYY-MM-DD"),
    date_to: str | None = Query(None, alias="to", description="ISO-Datum YYYY-MM-DD"),
    aggregate: str = Query("none"),
    sections: str | None = Query(None, description="Kommaliste von Sektions-Schluesseln"),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Zeilen, Groesse und verfuegbare Spalten je Sektion plus die ersten
    Zeilen der Datei."""
    d_from, d_to = _validated_range(date_from, date_to)
    return await build_export_preview(
        db, user, date_from=d_from, date_to=d_to,
        aggregate=_validated_aggregate(aggregate),
        sections=_parse_sections(sections),
        aggregate_map=await _agg_map_mit_vorgabe(request, db, user),
        column_map=_column_map(request),
        compact_before=await _compact_before(request, db, user))


@router.get("/api/export/fit")
async def export_fit(
    request: Request,
    max_bytes: int = Query(..., gt=0, description="Hoechstgroesse der Datei in Byte"),
    date_from: str | None = Query(None, alias="from", description="ISO-Datum YYYY-MM-DD"),
    date_to: str | None = Query(None, alias="to", description="ISO-Datum YYYY-MM-DD"),
    aggregate: str = Query("none"),
    sections: str | None = Query(None, description="Kommaliste von Sektions-Schluesseln"),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Stellt die Aggregation so ein, dass die Datei unter ``max_bytes`` bleibt.

    Gedreht wird nur an der Zeit -- Sektionen und Spalten bleiben, wie sie
    gewaehlt sind. Passt es auch jahresweise nicht, sagt die Antwort das
    (``fits: false``) samt der groessten Sektion, statt heimlich zu kuerzen.

    Die Antwort enthaelt die fertige Vorschau der gefundenen Einstellung, damit
    die Oberflaeche sie ohne zweiten Aufruf anzeigen kann.
    """
    if max_bytes < MIN_FIT_BYTES:
        raise HTTPException(400, f"Die Hoechstgroesse muss mindestens {MIN_FIT_BYTES} Byte sein")
    if max_bytes > MAX_FIT_BYTES:
        raise HTTPException(400, "Die Hoechstgroesse ist unrealistisch gross")
    d_from, d_to = _validated_range(date_from, date_to)
    return await fit_export_to_size(
        db, user, max_bytes, date_from=d_from, date_to=d_to,
        sections=_parse_sections(sections),
        aggregate_map=await _agg_map_mit_vorgabe(request, db, user),
        column_map=_column_map(request),
        compact_before=await _compact_before(request, db, user))


@router.get("/api/export/all")
async def export_all(
    request: Request,
    date_from: str | None = Query(None, alias="from", description="ISO-Datum YYYY-MM-DD"),
    date_to: str | None = Query(None, alias="to", description="ISO-Datum YYYY-MM-DD"),
    aggregate: str = Query("none"),
    sections: str | None = Query(None, description="Kommaliste von Sektions-Schluesseln"),
    db=Depends(get_db),
    user=Depends(get_current_user),
):
    """Eine CSV mit den gewaehlten Sektionen, inkl. erklaerender
    Kommentarzeilen vor jeder Sektion. Optional per Zeitraum gefiltert, je
    Modul zusammengefasst und je Sektion auf bestimmte Spalten beschraenkt."""
    d_from, d_to = _validated_range(date_from, date_to)
    picked = _parse_sections(sections)
    agg = _validated_aggregate(aggregate)
    agg_map = await _agg_map_mit_vorgabe(request, db, user)
    col_map = _column_map(request)
    grenze = await _compact_before(request, db, user)

    csv = await build_full_export_csv(
        db, user, date_from=d_from, date_to=d_to, aggregate=agg,
        sections=picked, aggregate_map=agg_map, column_map=col_map,
        compact_before=grenze)
    # UTF-8 mit BOM, damit Excel Umlaute (ä/ö/ü/ß) korrekt darstellt
    body = ("﻿" + csv).encode("utf-8")

    # Dateiname mit Optionen anreichern, damit mehrere Exports im Downloads-
    # Ordner nicht kollidieren.
    parts = ["vexbob-gesamt-export"]
    if d_from or d_to:
        parts.append(f"{(d_from.isoformat() if d_from else 'start')}_bis_{(d_to.isoformat() if d_to else 'ende')}")
    # Der Dateiname nennt die Aggregation nur, wenn sie ueberall dieselbe ist;
    # sonst waere "…-month" eine Behauptung ueber Sektionen, die einzeln
    # exportiert wurden.
    used_aggs = set(clean_aggregate_map(agg_map, agg, d_from, d_to).values())
    if len(used_aggs) == 1 and used_aggs != {"none"}:
        parts.append(used_aggs.pop())
    elif len(used_aggs) > 1:
        parts.append("gemischt")
    if picked:
        parts.append("auswahl")
    if col_map:
        parts.append("spalten")
    if grenze:
        parts.append("verdichtet-ab-" + grenze.isoformat())
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
