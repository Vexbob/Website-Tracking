"""Musik-Ingest: aus der Spotify-Export-CSV wird das Hoerregister.

Die Datei kommt aus dem Programm "Spotify-Export" und ist BEREITS
zusammengefasst. Ihr Aufbau:

    Block                                        Periode    Interpret  Titel  Wiedergaben
    Anfang bis heute · woechentlich · nach Titel  2026-KW01  Marsimoto  ...    5

Drei Dinge macht dieser Ingest daraus:

1. **Spalten erkennen.** Welche Spalten die Datei hat, entscheidet der Nutzer
   beim Export -- "Minuten", "Album" oder "Art" koennen da sein oder fehlen.
   Erkannt wird am Kopf, nicht an der Position.
2. **Perioden aufloesen.** ``2026-KW01`` ist als Zeichenkette nicht
   vergleichbar. Jede Zeile bekommt deshalb Anfang und Ende ihrer Periode als
   Datum; alles Zeitliche rechnet danach.
3. **Bloecke ersetzen ihren Zeitraum.** Ein Block deckt einen Zeitraum
   vollstaendig ab. Beim Import verschwindet alles, was sich mit diesem
   Zeitraum ueberschneidet, und die Zeilen des Blocks treten an seine Stelle.
   Nur so ist derselbe Upload zweimal hintereinander folgenlos, und nur so
   koennen sich Wochen- und Monatszeilen desselben Zeitraums nicht gegenseitig
   doppelt zaehlen.

Zeilen OHNE Periode werden nicht uebernommen. Ein Block "ohne Zeitraster" ist
eine Gesamtsumme, kein Register-Eintrag -- er liesse sich weder einordnen noch
je wieder gezielt ersetzen. Der Import sagt, wie viele Zeilen das betraf.
"""
from __future__ import annotations

import calendar
import csv
import io
import json
import re
from datetime import date, datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Spaltenkoepfe
# ---------------------------------------------------------------------------
# Erkannt wird ueber eine normalisierte Fassung des Kopfes: klein, ohne
# Leerzeichen und Sonderzeichen, Umlaute aufgeloest. Damit passen "Anteil %",
# "anteil_prozent" und "Anteil%" auf denselben Schluessel, und ein spaeter
# umbenannter Kopf im Export-Programm bricht nicht sofort den Import.

_UML = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                      "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").strip().lower().translate(_UML))


# Kopf -> Feld. Mehrere Koepfe duerfen auf dasselbe Feld zeigen.
HEADER_ALIASES = {
    # Kopfspalten der Zusammenfassung
    "block":              "block",
    "raster":             "raster",
    "periode":            "period",
    # Gruppierungsfelder
    "interpret":          "artist",
    "kuenstler":          "artist",
    "artist":             "artist",
    "titel":              "title",
    "track":              "title",
    "album":              "album",
    "art":                "kind",
    # Kennzahlen
    "wiedergaben":        "plays",
    "minuten":            "minutes",
    "stunden":            "hours",
    "millisekunden":      "ms",
    "msplayed":           "ms",
    "uebersprungen":      "skipped",
    "verschiedenetitel":  "distinct_titles",
    "erstewiedergabe":    "first_play",
    "letztewiedergabe":   "last_play",
    # Rohansicht (eine Zeile = eine Wiedergabe). Wird beim Import verdichtet.
    "zeitpunkt":          "ts",
    "datum":              "day",
    "monat":              "month",
    "kalenderwoche":      "week",
    "woche":              "week",
    "jahr":               "year",
}

GRAIN_ORDER = ["tag", "woche", "monat", "jahr"]
GRAIN_LABEL = {"tag": "täglich", "woche": "wöchentlich",
               "monat": "monatlich", "jahr": "jährlich"}


class MusicImportError(Exception):
    """Die Datei ist als Ganzes unbrauchbar -- kein Kopf, keine erkannten
    Spalten. Einzelne unbrauchbare Zeilen sind kein Fehler, sie werden
    gezaehlt und uebersprungen."""


# ---------------------------------------------------------------------------
# Datei lesen
# ---------------------------------------------------------------------------

def decode(raw: bytes) -> str:
    """UTF-8 mit oder ohne BOM, sonst Windows-1252. Excel schreibt beim
    Zwischenspeichern gern das eine, das Export-Programm das andere."""
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def sniff_delimiter(text: str) -> str:
    """Semikolon ist die Vorgabe des Export-Programms, Tab entsteht beim Weg
    ueber die Zwischenablage, Komma bei englischen Einstellungen. Entschieden
    wird an der Kopfzeile: dort steht kein Trennzeichen im Inhalt."""
    head = text.split("\n", 1)[0]
    counts = {d: head.count(d) for d in (";", "\t", ",")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] > 0 else ";"


def read_table(raw: bytes) -> tuple[list[str], list[dict]]:
    """Kopfzeile und Zeilen als Feld-Woerterbuecher. Leere Zeilen und die
    Kommentarzeilen eines Vexbob-Exports (``# ...``) fliegen raus."""
    text = decode(raw)
    delim = sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header: list[str] = []
    rows: list[dict] = []
    fields: list[str] = []
    for parts in reader:
        if not parts or all(not p.strip() for p in parts):
            continue
        if parts[0].lstrip().startswith("#"):
            continue
        if not header:
            header = [p.strip() for p in parts]
            fields = [HEADER_ALIASES.get(_norm_header(h), "") for h in header]
            if not any(fields):
                raise MusicImportError(
                    "In der Kopfzeile steht keine bekannte Spalte. Erwartet "
                    "wird eine CSV aus dem Spotify-Export mit mindestens "
                    "„Periode“ und „Titel“ oder „Interpret“.")
            continue
        row = {}
        for i, value in enumerate(parts):
            key = fields[i] if i < len(fields) else ""
            if key and key not in row:
                row[key] = value.strip()
        rows.append(row)
    if not header:
        raise MusicImportError("Die Datei enthält keine Kopfzeile.")
    return header, rows


# ---------------------------------------------------------------------------
# Werte
# ---------------------------------------------------------------------------

def _num(v) -> Optional[float]:
    """Deutsche und englische Schreibweise. Das Export-Programm schreibt
    Komma-Dezimal ohne Tausenderpunkte; robust gegen beides zu sein kostet
    nichts und rettet die von Hand nachbearbeitete Datei."""
    s = str(v or "").strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        # Das zuletzt stehende Zeichen ist das Dezimaltrennzeichen.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") == 1:
        left, right = s.split(".")
        # "1.234" ist ein Tausenderpunkt, "3.5" eine Dezimalzahl.
        if len(right) == 3 and 1 <= len(left.lstrip("-")) <= 3:
            s = left + right
    try:
        return float(s)
    except ValueError:
        return None


def _int(v) -> Optional[int]:
    f = _num(v)
    return None if f is None else int(round(f))


def _ts(v) -> Optional[datetime]:
    """"2016-02-21 11:38:29" aus der Spalte "Erste/Letzte Wiedergabe"."""
    s = str(v or "").strip().replace(" ", "T")
    if len(s) < 10:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


_WEEK_RE = re.compile(r"^(\d{4})-(?:KW|W)(\d{1,2})$", re.IGNORECASE)


def parse_period(value: str) -> Optional[tuple[str, str, date, date]]:
    """``(grain, key, start, end)`` oder ``None``, wenn die Zeichenkette keine
    Periode ist. Der Schluessel wird dabei vereinheitlicht (``2026-KW01``,
    nicht ``2026-KW1``), damit derselbe Zeitraum nicht unter zwei Namen im
    Register landet."""
    s = str(value or "").strip()
    if not s:
        return None

    m = _WEEK_RE.match(s)
    if m:
        year, week = int(m.group(1)), int(m.group(2))
        try:
            start = date.fromisocalendar(year, week, 1)
        except ValueError:
            return None            # KW 53 gibt es nicht in jedem Jahr
        end = date.fromordinal(start.toordinal() + 6)
        return "woche", f"{year:04d}-KW{week:02d}", start, end

    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            d = date.fromisoformat(s)
        except ValueError:
            return None
        return "tag", s, d, d

    if re.match(r"^\d{4}-\d{2}$", s):
        year, month = int(s[:4]), int(s[5:7])
        if not 1 <= month <= 12:
            return None
        last = calendar.monthrange(year, month)[1]
        return "monat", s, date(year, month, 1), date(year, month, last)

    if re.match(r"^\d{4}$", s):
        year = int(s)
        if not 1900 <= year <= 2999:
            return None
        return "jahr", s, date(year, 1, 1), date(year, 12, 31)

    return None


_BLOCK_RANGE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|Anfang)\s+bis\s+(\d{4}-\d{2}-\d{2}|heute)",
    re.IGNORECASE)


def parse_block_range(label: str) -> tuple[Optional[date], Optional[date]]:
    """Der Zeitraum, den ein Block laut seiner Beschriftung abdeckt.

    Das Export-Programm schreibt ihn hinein (``2016-01-01 bis 2019-12-31``);
    offene Enden heissen dort "Anfang" bzw. "heute" und kommen hier als
    ``None`` zurueck. Er ist wichtiger als der Zeitraum der tatsaechlich
    vorhandenen Zeilen: ein Block ueber 2016-2019, in dem 2016 kein einziger
    Titel steht, soll 2016 trotzdem leerraeumen -- dort gab es nichts.
    """
    m = _BLOCK_RANGE_RE.search(label or "")
    if not m:
        return None, None
    a, b = m.group(1), m.group(2)
    try:
        start = None if a.lower() == "anfang" else date.fromisoformat(a)
        end = None if b.lower() == "heute" else date.fromisoformat(b)
    except ValueError:
        return None, None
    return start, end


# ---------------------------------------------------------------------------
# Zeilen deuten
# ---------------------------------------------------------------------------

def _group_of(row: dict) -> str:
    """Wonach diese Zeile gruppiert ist -- abgelesen an dem, was belegt ist.
    Die Reihenfolge geht vom Feinen zum Groben: eine Zeile mit Titel ist eine
    Titelzeile, auch wenn sie zusaetzlich das Album nennt."""
    if row.get("title"):
        return "titel"
    if row.get("album"):
        return "album"
    if row.get("artist"):
        return "interpret"
    if row.get("kind"):
        return "art"
    return "gesamt"


def _ms_of(row: dict) -> Optional[int]:
    """Hoerdauer in Millisekunden -- je nachdem, welche Dauerspalte der Export
    enthaelt. Fehlt jede, bleibt sie leer: eine aus Wiedergaben geschaetzte
    Dauer waere eine Erfindung."""
    ms = _int(row.get("ms"))
    if ms is not None:
        return ms
    minutes = _num(row.get("minutes"))
    if minutes is None:
        hours = _num(row.get("hours"))
        minutes = hours * 60 if hours is not None else None
    return int(round(minutes * 60000)) if minutes is not None else None


def _entry_from_row(row: dict) -> Optional[dict]:
    """Eine Registerzeile aus einer CSV-Zeile. ``None``, wenn sie keine
    Periode hat oder nichts benennt."""
    period = parse_period(row.get("period", ""))
    if period is None:
        return None
    grain, key, start, end = period

    group_by = _group_of(row)
    if group_by == "gesamt":
        return None            # nichts zu benennen, nichts nachzuschlagen

    plays = _int(row.get("plays"))
    return {
        "block": (row.get("block") or "").strip(),
        "grain": grain,
        "period_key": key,
        "period_start": start,
        "period_end": end,
        "group_by": group_by,
        "kind": (row.get("kind") or "").strip(),
        "artist": (row.get("artist") or "").strip(),
        "title": (row.get("title") or "").strip(),
        "album": (row.get("album") or "").strip(),
        "plays": plays if plays is not None else 0,
        "ms_played": _ms_of(row),
        "skipped": _int(row.get("skipped")),
        "distinct_titles": _int(row.get("distinct_titles")),
        "first_play": _ts(row.get("first_play")),
        "last_play": _ts(row.get("last_play")),
    }


def _raw_row_period(row: dict) -> Optional[tuple[str, str, date, date]]:
    """Die Rohansicht (eine Zeile = eine Wiedergabe) hat keine Spalte
    "Periode", aber je nach Auswahl Datum, Monat, Kalenderwoche oder Jahr.
    Genommen wird die feinste vorhandene."""
    ts = row.get("ts") or ""
    if len(ts) >= 10:
        got = parse_period(ts[:10])
        if got:
            return got
    for field in ("day", "week", "month", "year"):
        got = parse_period(row.get(field, ""))
        if got:
            return got
    return None


def _condense_raw(rows: list[dict]) -> list[dict]:
    """Rohzeilen zu Registerzeilen verdichten: je Periode und Gruppe eine.

    Die Rohansicht ist nicht der vorgesehene Weg -- das Export-Programm kann
    zusammenfassen und tut es besser. Sie trotzdem anzunehmen kostet wenig und
    verhindert die Sackgasse "falsche Einstellung gewaehlt, Datei unbrauchbar".
    """
    buckets: dict[tuple, dict] = {}
    for row in rows:
        period = _raw_row_period(row)
        if period is None:
            continue
        grain, key, start, end = period
        group_by = _group_of(row)
        if group_by == "gesamt":
            continue
        ident = (grain, key, group_by, row.get("kind", ""), row.get("artist", ""),
                 row.get("title", ""), row.get("album", ""))
        entry = buckets.get(ident)
        if entry is None:
            entry = buckets[ident] = {
                "block": (row.get("block") or "").strip(),
                "grain": grain, "period_key": key,
                "period_start": start, "period_end": end,
                "group_by": group_by,
                "kind": (row.get("kind") or "").strip(),
                "artist": (row.get("artist") or "").strip(),
                "title": (row.get("title") or "").strip(),
                "album": (row.get("album") or "").strip(),
                "plays": 0, "ms_played": 0, "skipped": None,
                "distinct_titles": None, "first_play": None, "last_play": None,
            }
        entry["plays"] += 1
        entry["ms_played"] = (entry["ms_played"] or 0) + (_ms_of(row) or 0)
        stamp = _ts(row.get("ts"))
        if stamp:
            if entry["first_play"] is None or stamp < entry["first_play"]:
                entry["first_play"] = stamp
            if entry["last_play"] is None or stamp > entry["last_play"]:
                entry["last_play"] = stamp
    return list(buckets.values())


def _looks_aggregated(rows: list[dict]) -> bool:
    """Eine zusammengefasste Datei hat eine Spalte "Wiedergaben"; in der
    Rohansicht ist jede Zeile eine einzelne Wiedergabe."""
    return any("plays" in r for r in rows[:50])


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def build_plan(raw: bytes, filename: str = "") -> dict:
    """Was diese Datei bedeutet -- ohne Datenbank, damit Vorschau und Import
    garantiert dasselbe verstehen.

    Rueckgabe: ``entries`` (fertige Registerzeilen), ``blocks`` (je Block
    Beschriftung, Raster, Zeitraum, Zeilen) und die Zaehler fuers Protokoll.
    """
    _header, rows = read_table(raw)
    if not rows:
        raise MusicImportError("Die Datei enthält keine Datenzeilen.")

    aggregated = _looks_aggregated(rows)
    if aggregated:
        entries = [e for e in (_entry_from_row(r) for r in rows) if e is not None]
        skipped = len(rows) - len(entries)
    else:
        entries = _condense_raw(rows)
        skipped = 0

    if not entries:
        raise MusicImportError(
            "Keine einzige Zeile hat eine Periode. Der Block wurde vermutlich "
            "„ohne Zeitraster“ exportiert — mit täglich, wöchentlich, "
            "monatlich oder jährlich lässt er sich einordnen.")

    # Bloecke: die Datei kann mehrere enthalten (2016-2019 monatlich, ab 2020
    # woechentlich). Jeder ersetzt seinen eigenen Zeitraum.
    blocks: dict[str, dict] = {}
    for entry in entries:
        label = entry["block"]
        block = blocks.get(label)
        if block is None:
            declared_from, declared_to = parse_block_range(label)
            block = blocks[label] = {
                "label": label or "(ohne Bezeichnung)",
                "grains": set(),
                "rows": 0,
                "plays": 0,
                "data_from": entry["period_start"],
                "data_to": entry["period_end"],
                "declared_from": declared_from,
                "declared_to": declared_to,
            }
        block["grains"].add(entry["grain"])
        block["rows"] += 1
        block["plays"] += entry["plays"] or 0
        block["data_from"] = min(block["data_from"], entry["period_start"])
        block["data_to"] = max(block["data_to"], entry["period_end"])

    ordered = []
    for block in blocks.values():
        # Der zu ersetzende Zeitraum: die Ansage des Blocks, mindestens aber
        # das, was tatsaechlich drinsteht. Ein offenes Ende ("bis heute")
        # reicht genau bis zur letzten vorhandenen Periode -- weiter zu
        # loeschen hiesse, spaetere Zeilen eines anderen Blocks zu treffen.
        start = min(block["declared_from"] or block["data_from"], block["data_from"])
        end = max(block["declared_to"] or block["data_to"], block["data_to"])
        ordered.append({
            "label": block["label"],
            "grains": sorted(block["grains"], key=GRAIN_ORDER.index),
            "rows": block["rows"],
            "plays": block["plays"],
            "replace_from": start,
            "replace_to": end,
        })
    ordered.sort(key=lambda b: b["replace_from"])

    return {
        "filename": filename,
        "size_bytes": len(raw),
        "aggregated": aggregated,
        "rows_read": len(rows),
        "rows_written": len(entries),
        "rows_skipped": skipped,
        "entries": entries,
        "blocks": ordered,
    }


def plan_summary(plan: dict) -> dict:
    """Der Plan ohne die Zeilen selbst -- das, was ueber die Leitung geht."""
    return {
        "filename": plan["filename"],
        "size_bytes": plan["size_bytes"],
        "aggregated": plan["aggregated"],
        "rows_read": plan["rows_read"],
        "rows_written": plan["rows_written"],
        "rows_skipped": plan["rows_skipped"],
        "blocks": [
            {**b,
             "replace_from": b["replace_from"].isoformat(),
             "replace_to": b["replace_to"].isoformat()}
            for b in plan["blocks"]
        ],
    }


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------

# Ein Block ersetzt seinen Zeitraum: getroffen wird jede Zeile, die sich mit
# ihm ueberschneidet -- auch eine Jahreszeile, die nur zur Haelfte hineinragt.
# Sie stehen zu lassen hiesse, denselben Zeitraum zweimal zu zaehlen; das
# waere der stillere und schlimmere Fehler.
_OVERLAP = "user_id=$1 AND period_start <= $3 AND period_end >= $2"


async def count_replaced(db, user_id: int, blocks: list[dict]) -> int:
    """Wie viele vorhandene Zeilen dieser Import ersetzen wuerde. Fuer die
    Vorschau -- geloescht wird hier nichts."""
    total = 0
    for block in blocks:
        row = await db.fetchrow(
            f"SELECT COUNT(*) AS n FROM music_entries WHERE {_OVERLAP}",
            user_id, block["replace_from"], block["replace_to"])
        total += int(row["n"] or 0)
    return total


async def preview(db, user_id: int, raw: bytes, filename: str = "") -> dict:
    """Was der Import taete. Baut denselben Plan wie ``apply`` -- eine zweite
    Rechnung waere irgendwann eine andere."""
    plan = build_plan(raw, filename)
    summary = plan_summary(plan)
    summary["rows_replaced"] = await count_replaced(db, user_id, plan["blocks"])
    known = await db.fetchrow(
        "SELECT COUNT(*) AS n, MIN(period_start) AS von, MAX(period_end) AS bis "
        "  FROM music_entries WHERE user_id=$1", user_id)
    summary["existing_rows"] = int(known["n"] or 0)
    summary["existing_from"] = known["von"].isoformat() if known["von"] else None
    summary["existing_to"] = known["bis"].isoformat() if known["bis"] else None
    return summary


async def apply(db, user_id: int, raw: bytes, filename: str = "") -> dict:
    """Import ausfuehren: Zeitraeume der Bloecke leerraeumen, Zeilen schreiben,
    Protokolleintrag anlegen. Alles in einer Transaktion -- ein zur Haelfte
    ersetzter Zeitraum waere schlimmer als ein fehlgeschlagener Import."""
    plan = build_plan(raw, filename)
    entries = plan["entries"]

    async with db.transaction():
        replaced = 0
        for block in plan["blocks"]:
            result = await db.execute(
                f"DELETE FROM music_entries WHERE {_OVERLAP}",
                user_id, block["replace_from"], block["replace_to"])
            # asyncpg liefert "DELETE <n>".
            try:
                replaced += int(str(result).rsplit(" ", 1)[-1])
            except ValueError:
                pass

        log = await db.fetchrow(
            "INSERT INTO music_imports "
            "  (user_id, filename, size_bytes, rows_read, rows_written,"
            "   rows_skipped, rows_replaced, blocks) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id, uploaded_at",
            user_id, filename or None, plan["size_bytes"], plan["rows_read"],
            len(entries), plan["rows_skipped"], replaced,
            json.dumps(plan_summary(plan)["blocks"], ensure_ascii=False))
        import_id = log["id"]

        if entries:
            await db.executemany(
                "INSERT INTO music_entries "
                "  (user_id, import_id, block, grain, period_key, period_start,"
                "   period_end, group_by, kind, artist, title, album, plays,"
                "   ms_played, skipped, distinct_titles, first_play, last_play) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18) "
                # Zwei identische Zeilen im selben Block sind ein Fehler der
                # Quelle, kein Grund zum Abbruch: die zweite gewinnt.
                "ON CONFLICT (user_id, entry_hash) DO UPDATE SET "
                "  plays=EXCLUDED.plays, ms_played=EXCLUDED.ms_played, "
                "  skipped=EXCLUDED.skipped, distinct_titles=EXCLUDED.distinct_titles, "
                "  first_play=EXCLUDED.first_play, last_play=EXCLUDED.last_play, "
                "  import_id=EXCLUDED.import_id, block=EXCLUDED.block",
                [(user_id, import_id, e["block"], e["grain"], e["period_key"],
                  e["period_start"], e["period_end"], e["group_by"], e["kind"],
                  e["artist"], e["title"], e["album"], e["plays"], e["ms_played"],
                  e["skipped"], e["distinct_titles"], e["first_play"], e["last_play"])
                 for e in entries])

    out = plan_summary(plan)
    out["rows_replaced"] = replaced
    out["import_id"] = import_id
    out["uploaded_at"] = log["uploaded_at"].isoformat() if log["uploaded_at"] else None
    return out
