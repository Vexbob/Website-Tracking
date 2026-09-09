"""Musik-Router — das Hoerregister aus dem Spotify-Datenexport.

Endpoints:
  POST   /api/music/import          — CSV hochladen (``dry_run=1`` = nur Vorschau)
  GET    /api/music/imports         — Protokoll der Uploads
  DELETE /api/music/imports/{id}    — Protokolleintrag loeschen (Daten bleiben)
  GET    /api/music/summary         — Kennzahlen und abgedeckter Zeitraum
  GET    /api/music/series          — Verlauf, zeitlich zusammengefasst
  GET    /api/music/top             — Rangliste (Interpret / Titel / Album / Art)
  GET    /api/music/entries         — das Register selbst, gefiltert und sortiert
  GET    /api/music/facets          — womit sich filtern laesst
  DELETE /api/music/entries         — Register leeren

Alle Listen-Endpoints teilen sich denselben Filtersatz (``_filters``). Ein
Filter, den nur die Haelfte der Ansichten kennt, waere im Gebrauch eine Falle:
man stellt ihn ein, wechselt den Reiter und sieht andere Zahlen.

Hinweis: bewusst OHNE ``from __future__ import annotations`` — FastAPI 0.109
kann ``UploadFile = File(...)`` sonst nicht aufloesen (siehe health_router.py).
"""
import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File

from auth import get_current_user
from database import get_db
from deps import logger, limiter, LIMIT_WRITE_RARE, LIMIT_WRITE_STANDARD
from helpers import ser
from services import music_ingest as ingest

router = APIRouter(tags=["music"])

# Eine hochgeladene CSV ist Text und wird komplett im Speicher zerlegt. Zehn
# Jahre woechentlich nach Titel sind etwa 3 MB -- 25 MB sind also reichlich
# Luft und trotzdem eine Grenze.
MAX_IMPORT_BYTES = 25 * 1024 * 1024

# ---------------------------------------------------------------------------
# Zeitliche Zusammenfassung
# ---------------------------------------------------------------------------
# Gespeichert ist, was die CSV geliefert hat (Woche, Monat, Jahr — je Block
# verschieden). Angezeigt wird, was zur Laenge des Zeitraums passt. Zusammen-
# gefasst wird dabei immer nur NACH OBEN: aus Wochen werden Monate, aus
# Monaten Jahre. Der umgekehrte Weg waere geraten.
#
# Gebucket wird ueber ``period_start``. Eine Kalenderwoche, die ueber einen
# Monatswechsel laeuft, zaehlt damit ganz in den Monat, in dem sie beginnt --
# die einzige Zuordnung, die ohne die Rohdaten ueberhaupt moeglich ist.

GRAIN_BUCKET = {
    "tag":   "to_char(period_start, 'YYYY-MM-DD')",
    "woche": "to_char(period_start, 'IYYY-\"KW\"IW')",
    "monat": "to_char(period_start, 'YYYY-MM')",
    "jahr":  "to_char(period_start, 'YYYY')",
}
GRAIN_KEYS = list(GRAIN_BUCKET)
GRAIN_LABEL = {"tag": "täglich", "woche": "wöchentlich",
               "monat": "monatlich", "jahr": "jährlich"}

# Ab welcher Laenge welche Stufe. Die Schwellen sind so gesetzt, dass ein
# Diagramm nie mehr als rund 120 Saeulen bekommt — darueber ist es eine
# Textur, keine Information mehr.
AUTO_STEPS = [(92, "tag"), (800, "woche"), (2200, "monat")]


def resolve_grain(grain: Optional[str], span_days: Optional[int]) -> str:
    """``auto`` in eine echte Stufe uebersetzen. Ohne bekannten Zeitraum
    (offener Anfang) ist das Jahr die einzige Stufe, die bei zehn Jahren
    Historie noch lesbar bleibt."""
    if grain in GRAIN_BUCKET:
        return grain
    if not span_days or span_days <= 0:
        return "jahr"
    for limit, step in AUTO_STEPS:
        if span_days <= limit:
            return step
    return "jahr"


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

def _parse_date(v: Optional[str], name: str) -> Optional[date]:
    if not v:
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise HTTPException(400, f"{name} muss im Format YYYY-MM-DD sein")


class _Filters:
    """Sammelt WHERE-Teile und Parameter. Als Objekt statt als Tupel-Rueckgabe,
    weil jeder Endpoint danach noch eigene Bedingungen anhaengt und die
    Nummerierung der Positional-Parameter sonst von Hand mitgezaehlt werden
    muesste — genau dort entstehen die Fehler, die niemand sieht."""

    def __init__(self, user_id: int):
        self.parts = ["user_id = $1"]
        self.params = [user_id]

    def add(self, sql_template: str, value):
        self.params.append(value)
        self.parts.append(sql_template.format(n=len(self.params)))

    @property
    def where(self) -> str:
        return " AND ".join(self.parts)

    def next_index(self) -> int:
        return len(self.params) + 1


def _filters(user_id: int, date_from, date_to, q, artist, kind, grain,
             group_by, min_plays) -> _Filters:
    f = _Filters(user_id)
    # Ein Zeitraum trifft jede Periode, die ihn beruehrt. Wer "2024" filtert,
    # will die Jahreszeile 2024 sehen, auch wenn sie am 01.01. beginnt.
    if date_from:
        f.add("period_end >= ${n}", date_from)
    if date_to:
        f.add("period_start <= ${n}", date_to)
    if q:
        f.params.append(f"%{q}%")
        n = len(f.params)
        f.parts.append(f"(artist ILIKE ${n} OR title ILIKE ${n} OR album ILIKE ${n})")
    if artist:
        f.add("artist = ${n}", artist)
    if kind:
        f.add("kind = ${n}", kind)
    if grain in GRAIN_BUCKET:
        f.add("grain = ${n}", grain)
    if group_by:
        f.add("group_by = ${n}", group_by)
    if min_plays and int(min_plays) > 1:
        f.add("plays >= ${n}", int(min_plays))
    return f


def _common(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    q: Optional[str] = Query(None, description="Suche in Interpret, Titel, Album"),
    artist: Optional[str] = None,
    kind: Optional[str] = Query(None, description="Musik | Podcast | Hörbuch"),
    grain: Optional[str] = Query(None, description="Nur Zeilen dieser Auflösung"),
    group_by: Optional[str] = Query(None, description="titel | interpret | album | art"),
    min_plays: Optional[int] = None,
):
    """Der gemeinsame Filtersatz aller Listen-Endpoints."""
    d_from = _parse_date(date_from, "from")
    d_to = _parse_date(date_to, "to")
    if d_from and d_to and d_from > d_to:
        raise HTTPException(400, "'from' liegt nach 'to'")
    return {"date_from": d_from, "date_to": d_to, "q": (q or "").strip() or None,
            "artist": (artist or "").strip() or None,
            "kind": (kind or "").strip() or None, "grain": grain,
            "group_by": (group_by or "").strip() or None, "min_plays": min_plays}


async def _span_days(db, user_id: int, f: dict) -> Optional[int]:
    """Wie lang der gefilterte Zeitraum wirklich ist — fuer ``grain=auto``.
    Steht kein Von/Bis fest, entscheidet die Spanne der vorhandenen Daten;
    sonst waere "Gesamt" bei drei Wochen Historie eine Jahresansicht."""
    if f["date_from"] and f["date_to"]:
        return (f["date_to"] - f["date_from"]).days + 1
    row = await db.fetchrow(
        "SELECT MIN(period_start) AS von, MAX(period_end) AS bis "
        "  FROM music_entries WHERE user_id=$1", user_id)
    if not row or not row["von"]:
        return None
    start = f["date_from"] or row["von"]
    end = f["date_to"] or row["bis"]
    return (end - start).days + 1


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@router.post("/api/music/import")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def import_music_csv(request: Request,
                           file: UploadFile = File(...),
                           dry_run: bool = Query(False, description="Nur zeigen, was passieren würde"),
                           db=Depends(get_db),
                           user=Depends(get_current_user)):
    """CSV aus dem Spotify-Export übernehmen.

    Mit ``dry_run=1`` wird nichts geschrieben — die Antwort sagt, welche
    Blöcke erkannt wurden, welchen Zeitraum jeder ersetzen würde und wie viele
    vorhandene Zeilen das trifft. Der Dialog zeigt das, bevor er fragt: ein
    Import, der einen Zeitraum leerräumt, darf keine Überraschung sein.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Die Datei ist leer.")
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(413, "Die Datei ist größer als 25 MB.")

    name = (file.filename or "").rsplit("/", 1)[-1][:200]
    try:
        if dry_run:
            return await ingest.preview(db, user["id"], raw, name)
        result = await ingest.apply(db, user["id"], raw, name)
    except ingest.MusicImportError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("music import failed")
        raise HTTPException(500, f"Import fehlgeschlagen: {e}")

    logger.info("music import user=%s rows=%s replaced=%s",
                user["id"], result["rows_written"], result["rows_replaced"])
    return result


@router.get("/api/music/imports")
async def list_imports(limit: Optional[int] = 50, db=Depends(get_db),
                       user=Depends(get_current_user)):
    """Was wann hochgeladen wurde, mit den Blöcken der jeweiligen Datei."""
    lim = max(1, min(int(limit or 50), 200))
    rows = await db.fetch(
        "SELECT i.*, (SELECT COUNT(*) FROM music_entries e WHERE e.import_id = i.id) AS rows_alive "
        "  FROM music_imports i WHERE i.user_id=$1 "
        " ORDER BY i.uploaded_at DESC, i.id DESC LIMIT $2",
        user["id"], lim)
    out = []
    for r in rows:
        d = ser(r)
        if isinstance(d.get("blocks"), str):
            try:
                d["blocks"] = json.loads(d["blocks"])
            except ValueError:
                d["blocks"] = []
        out.append(d)
    return out


@router.delete("/api/music/imports/{iid}")
@limiter.limit(LIMIT_WRITE_RARE)
async def delete_import(request: Request, iid: int, db=Depends(get_db),
                        user=Depends(get_current_user)):
    """Streicht einen Protokolleintrag. Die importierten Zeilen bleiben —
    sie sind inzwischen Teil des Registers, und ein Zeitraum, den dieser
    Upload ersetzt hat, käme durch ein Zurücknehmen auch nicht wieder."""
    row = await db.fetchrow(
        "DELETE FROM music_imports WHERE id=$1 AND user_id=$2 RETURNING id",
        iid, user["id"])
    if not row:
        raise HTTPException(404, "Eintrag nicht gefunden")
    return {"deleted": iid}


@router.delete("/api/music/entries")
@limiter.limit(LIMIT_WRITE_RARE)
async def clear_entries(request: Request, db=Depends(get_db),
                        user=Depends(get_current_user)):
    """Leert das Register vollständig. Das Protokoll bleibt stehen, damit
    nachvollziehbar ist, was es einmal gab."""
    result = await db.execute("DELETE FROM music_entries WHERE user_id=$1", user["id"])
    try:
        removed = int(str(result).rsplit(" ", 1)[-1])
    except ValueError:
        removed = 0
    return {"deleted": removed}


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------

@router.get("/api/music/summary")
async def summary(f: dict = Depends(_common), db=Depends(get_db),
                  user=Depends(get_current_user)):
    """Die Kopfzahlen: Wiedergaben, verschiedene Titel und Interpreten,
    Hörzeit (falls die CSV sie enthielt) und der abgedeckte Zeitraum."""
    flt = _filters(user["id"], **f)
    row = await db.fetchrow(
        "SELECT COALESCE(SUM(plays),0) AS plays, COUNT(*) AS rows, "
        "       SUM(ms_played) AS ms, "
        "       COUNT(DISTINCT NULLIF(title,'')) AS titles, "
        "       COUNT(DISTINCT NULLIF(artist,'')) AS artists, "
        "       MIN(period_start) AS von, MAX(period_end) AS bis "
        f"  FROM music_entries WHERE {flt.where}", *flt.params)
    grains = await db.fetch(
        f"SELECT grain, COUNT(*) AS rows, MIN(period_start) AS von, MAX(period_end) AS bis "
        f"  FROM music_entries WHERE {flt.where} GROUP BY grain", *flt.params)
    # Je Art dieselben Kennzahlen. Musik und Podcast sind nicht dasselbe: bei
    # Podcasts steht im Feld "Interpret" die Show und in "Titel" die Episode,
    # eine gemeinsame Zahl "610 Titel" vermischt also zwei Dinge.
    kinds = await db.fetch(
        f"SELECT kind, COALESCE(SUM(plays),0) AS plays, SUM(ms_played) AS ms, "
        f"       COUNT(DISTINCT NULLIF(title,'')) AS titles, "
        f"       COUNT(DISTINCT NULLIF(artist,'')) AS artists, COUNT(*) AS rows "
        f"  FROM music_entries WHERE {flt.where} AND kind <> '' "
        f" GROUP BY kind ORDER BY plays DESC", *flt.params)
    return {
        "by_kind": [{"kind": k["kind"], "plays": int(k["plays"] or 0),
                     "ms_played": int(k["ms"]) if k["ms"] is not None else None,
                     "titles": int(k["titles"] or 0), "artists": int(k["artists"] or 0),
                     "rows": int(k["rows"] or 0)} for k in kinds],
        "plays": int(row["plays"] or 0),
        "rows": int(row["rows"] or 0),
        "ms_played": int(row["ms"]) if row["ms"] is not None else None,
        "titles": int(row["titles"] or 0),
        "artists": int(row["artists"] or 0),
        "from": row["von"].isoformat() if row["von"] else None,
        "to": row["bis"].isoformat() if row["bis"] else None,
        # Welche Auflösungen im Register liegen — die Oberfläche sagt damit,
        # warum ein alter Zeitraum gröber aussieht als ein neuer.
        "grains": [{"grain": g["grain"], "rows": int(g["rows"]),
                    "from": g["von"].isoformat() if g["von"] else None,
                    "to": g["bis"].isoformat() if g["bis"] else None}
                   for g in sorted(grains, key=lambda g: GRAIN_KEYS.index(g["grain"])
                                   if g["grain"] in GRAIN_KEYS else 99)],
    }


@router.get("/api/music/series")
async def series(step: str = Query("auto", description="auto | tag | woche | monat | jahr"),
                 split: Optional[str] = Query(None, description="kind = zusätzlich je Art aufgeschlüsselt"),
                 f: dict = Depends(_common), db=Depends(get_db),
                 user=Depends(get_current_user)):
    """Der Verlauf, auf die gewünschte Stufe zusammengefasst.

    ``coarser`` zählt die Zeilen, die gröber gespeichert sind als die
    gewünschte Stufe (eine Jahreszeile in einer Monatsansicht). Sie landen im
    Bucket ihres ersten Tages — die Oberfläche sagt das dazu, statt eine
    Genauigkeit vorzutäuschen, die die Daten nicht haben.
    """
    flt = _filters(user["id"], **f)
    target = resolve_grain(step, await _span_days(db, user["id"], f))
    bucket = GRAIN_BUCKET[target]
    # Groeber gespeichert als die Zielstufe: alles, was in GRAIN_KEYS hinter
    # ihr steht. Der Cast ist noetig, weil die Liste bei "jahr" leer ist und
    # asyncpg den Typ dann nicht erraten kann.
    coarser = GRAIN_KEYS[GRAIN_KEYS.index(target) + 1:]
    n_coarser = flt.next_index()

    rows = await db.fetch(
        f"SELECT {bucket} AS period, MIN(period_start) AS start, "
        f"       SUM(plays) AS plays, SUM(ms_played) AS ms, "
        f"       COUNT(DISTINCT NULLIF(title,'')) AS titles, "
        f"       COUNT(DISTINCT NULLIF(artist,'')) AS artists, "
        f"       SUM(CASE WHEN grain = ANY(${n_coarser}::text[]) THEN 1 ELSE 0 END) AS coarse "
        f"  FROM music_entries WHERE {flt.where} "
        f" GROUP BY 1 ORDER BY 2",
        *flt.params, coarser)
    points = [{"period": r["period"], "start": r["start"].isoformat(),
               "plays": int(r["plays"] or 0),
               "ms_played": int(r["ms"]) if r["ms"] is not None else None,
               "titles": int(r["titles"] or 0),
               "artists": int(r["artists"] or 0),
               "coarser": int(r["coarse"] or 0)} for r in rows]
    out = {
        "grain": target,
        "grain_label": GRAIN_LABEL[target],
        "auto": step not in GRAIN_BUCKET,
        "points": points,
    }

    if split == "kind":
        # Je Art eine Reihe, ausgerichtet an denselben Perioden wie ``points``.
        # Ausgerichtet statt als eigene Punktliste, damit die Oberflaeche die
        # Balken ohne zweites Zusammenfuehren stapeln kann -- und damit eine
        # Art, die in einer Periode nicht vorkommt, dort eine 0 hat und nicht
        # die Achse verschiebt.
        per = await db.fetch(
            f"SELECT {bucket} AS period, kind, SUM(plays) AS plays, SUM(ms_played) AS ms "
            f"  FROM music_entries WHERE {flt.where} "
            f" GROUP BY 1, 2", *flt.params)
        index = {p["period"]: i for i, p in enumerate(points)}
        buckets: dict[str, list] = {}
        for r in per:
            # Ohne Spalte "Art" in der CSV steht hier ein leerer Wert. Er
            # bekommt einen Namen, statt als namenlose Reihe zu erscheinen.
            key = (r["kind"] or "").strip() or "Ohne Angabe"
            i = index.get(r["period"])
            if i is None:
                continue
            values = buckets.setdefault(key, [0] * len(points))
            values[i] += int(r["plays"] or 0)
        out["split"] = "kind"
        out["series"] = [
            {"kind": k, "plays": sum(v), "values": v}
            for k, v in sorted(buckets.items(), key=lambda kv: -sum(kv[1]))
        ]
    return out


TOP_FIELDS = {"interpret": "artist", "titel": "title", "album": "album", "art": "kind"}


# Wonach eine Rangliste sortiert. Musik und Podcast fragen verschiedene
# Dinge: bei Musik zaehlt, wie OFT man etwas gehoert hat, bei einem Podcast
# WIE VIELE Folgen -- eine Episode hoert man einmal, "Top-Episode nach
# Wiedergaben" waere dort eine Liste von Einsen.
TOP_METRICS = {
    "plays": "SUM(plays) DESC NULLS LAST",
    "titles": "COUNT(DISTINCT NULLIF(title,'')) DESC",
    "last": "MAX(period_start) DESC",
}


@router.get("/api/music/top")
async def top(by: str = Query("interpret", description="interpret | titel | album | art"),
              metric: str = Query("plays", description="plays | titles | last"),
              limit: int = 20,
              f: dict = Depends(_common), db=Depends(get_db),
              user=Depends(get_current_user)):
    """Rangliste. Bei ``titel`` steht der Interpret mit im Schlüssel — zwei
    verschiedene Lieder dürfen denselben Namen tragen.

    ``metric`` entscheidet die Sortierung, nicht den Inhalt: jede Zeile bringt
    Wiedergaben, verschiedene Titel und den letzten Zeitpunkt ohnehin mit,
    damit die Oberfläche beschriften kann, ohne ein zweites Mal zu fragen.
    """
    if by not in TOP_FIELDS:
        raise HTTPException(400, "Unbekannte Rangliste")
    if metric not in TOP_METRICS:
        raise HTTPException(400, "Unbekannte Sortierung")
    field = TOP_FIELDS[by]
    lim = max(1, min(int(limit or 20), 200))
    flt = _filters(user["id"], **f)
    group_cols = "artist, title" if by == "titel" else field
    rows = await db.fetch(
        f"SELECT {group_cols}, SUM(plays) AS plays, SUM(ms_played) AS ms, "
        f"       COUNT(DISTINCT NULLIF(title,'')) AS titles, "
        f"       MIN(period_start) AS von, MAX(period_end) AS bis "
        f"  FROM music_entries WHERE {flt.where} AND {field} <> '' "
        f" GROUP BY {group_cols} ORDER BY {TOP_METRICS[metric]} LIMIT ${flt.next_index()}",
        *flt.params, lim)
    out = []
    for r in rows:
        item = {"plays": int(r["plays"] or 0),
                "titles": int(r["titles"] or 0),
                "ms_played": int(r["ms"]) if r["ms"] is not None else None,
                "from": r["von"].isoformat() if r["von"] else None,
                "to": r["bis"].isoformat() if r["bis"] else None}
        item["label"] = r["title"] if by == "titel" else r[field]
        item["sub"] = r["artist"] if by == "titel" else None
        out.append(item)
    return {"by": by, "metric": metric, "items": out}


SORT_COLUMNS = {
    "period": "period_start",
    "artist": "artist",
    "title": "title",
    "album": "album",
    "plays": "plays",
    "ms": "ms_played",
}


@router.get("/api/music/entries")
async def entries(sort: str = "period", direction: str = "desc",
                  limit: int = 100, offset: int = 0,
                  f: dict = Depends(_common), db=Depends(get_db),
                  user=Depends(get_current_user)):
    """Das Register selbst — gefiltert, sortiert, seitenweise."""
    col = SORT_COLUMNS.get(sort, "period_start")
    order = "ASC" if str(direction).lower() == "asc" else "DESC"
    lim = max(1, min(int(limit or 100), 500))
    off = max(0, int(offset or 0))
    flt = _filters(user["id"], **f)

    total = await db.fetchrow(
        f"SELECT COUNT(*) AS n, COALESCE(SUM(plays),0) AS plays "
        f"  FROM music_entries WHERE {flt.where}", *flt.params)
    rows = await db.fetch(
        f"SELECT id, block, grain, period_key, period_start, period_end, group_by, "
        f"       kind, artist, title, album, plays, ms_played, skipped, "
        f"       distinct_titles, first_play, last_play "
        f"  FROM music_entries WHERE {flt.where} "
        # Zweitschluessel ist immer die Wiedergabezahl: bei gleichem Datum
        # steht sonst eine zufaellige Zeile oben und die Liste "springt"
        # zwischen zwei Aufrufen.
        f" ORDER BY {col} {order} NULLS LAST, plays DESC, id "
        f" LIMIT ${flt.next_index()} OFFSET ${flt.next_index() + 1}",
        *flt.params, lim, off)
    return {
        "total": int(total["n"] or 0),
        "plays": int(total["plays"] or 0),
        "limit": lim, "offset": off,
        "items": [ser(r) for r in rows],
    }


@router.get("/api/music/facets")
async def facets(db=Depends(get_db), user=Depends(get_current_user)):
    """Womit sich filtern lässt — Arten, Auflösungen, Gruppierungen und der
    abgedeckte Zeitraum. Die Oberfläche baut ihre Filter daraus, statt eine
    zweite Liste derselben Werte zu führen."""
    uid = user["id"]
    kinds = await db.fetch(
        "SELECT kind, COUNT(*) AS rows, SUM(plays) AS plays FROM music_entries "
        " WHERE user_id=$1 AND kind <> '' GROUP BY kind ORDER BY plays DESC", uid)
    grains = await db.fetch(
        "SELECT grain, COUNT(*) AS rows FROM music_entries WHERE user_id=$1 "
        " GROUP BY grain", uid)
    groups = await db.fetch(
        "SELECT group_by, COUNT(*) AS rows FROM music_entries WHERE user_id=$1 "
        " GROUP BY group_by ORDER BY rows DESC", uid)
    span = await db.fetchrow(
        "SELECT MIN(period_start) AS von, MAX(period_end) AS bis, COUNT(*) AS rows "
        "  FROM music_entries WHERE user_id=$1", uid)
    return {
        "kinds": [{"key": k["kind"], "rows": int(k["rows"]), "plays": int(k["plays"] or 0)}
                  for k in kinds],
        "grains": [{"key": g["grain"], "label": GRAIN_LABEL.get(g["grain"], g["grain"]),
                    "rows": int(g["rows"])}
                   for g in sorted(grains, key=lambda g: GRAIN_KEYS.index(g["grain"])
                                   if g["grain"] in GRAIN_KEYS else 99)],
        "groups": [{"key": g["group_by"], "rows": int(g["rows"])} for g in groups],
        "rows": int(span["rows"] or 0),
        "from": span["von"].isoformat() if span["von"] else None,
        "to": span["bis"].isoformat() if span["bis"] else None,
    }
