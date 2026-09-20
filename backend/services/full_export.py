"""Gesamt-Export: Sparziel + Ausgaben + Gesundheit in einer einzigen CSV.

v1.28.0 - kompaktes Format (~40 % kleiner als v1.27):
  * Timestamps: Mikrosekunden entfernt, ``+00:00`` -> ``Z``
    (globaler Hinweis im Header: alle Zeiten UTC).
  * Vitalwerte werden im Wide-Format ausgegeben (eine Zeile pro Tag,
    Metriken als Spalten) statt Long-Format mit vielen leeren Feldern.
  * Ausgaben sind in zwei Sektionen aufgeteilt: "Bons" (ein Eintrag pro
    Beleg) und "Bon-Positionen" (mit ``expense_id`` als Fremdschluessel).
    Damit werden Bon-Kopfdaten nicht mehr pro Position wiederholt.
  * Trailing ``.00`` bei ganzzahligen Werten wird entfernt.
  * Konstante Metadaten-Spalten (z. B. ``source`` bei Vitalwerten) werden
    in Kommentarzeilen ausgelagert statt in jeder Zeile wiederholt.
  * Der dedizierte Health-Export (``build_health_export_csv``) nutzt
    exakt dieselben Sektions-Helfer, damit beide konsistent bleiben.

v1.60.0 - der Export ist zusammenstellbar:
  * ``EXPORT_SECTIONS`` ist die eine Liste, aus der Auswahl, Vorschau und
    Oberflaeche leben. ``sections`` waehlt daraus aus; ohne Angabe ist alles
    dabei.
  * Die Aggregation ist je Modul waehlbar (``aggregate_map``) statt einmal
    fuer die ganze Datei -- Ausgaben monatsweise, Gesundheit einzeln.
  * ``build_export_preview`` liefert dieselbe Zusammenstellung als
    Kennzahlen (Sektionen, Zeilen, Groesse) samt der ersten Zeilen. Es baut
    den Export dafuer wirklich: eine Schaetzung waere schneller und falsch.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from services import food_mahlzeit as mahlzeiten
from helpers import (
    _export_csv_field as _f,
    _export_amt as _amt,  # noqa: F401  (kompatibel gehalten fuer moegliche Reimporte)
    _build_export_metadata,
    _sparziel_protocol_lines,
)


# ---------- v1.37.1 Zeitraum- + Aggregations-Helfer ----------
#
# v1.67.0: Die Stufen stehen in EINER Liste. Vorher kannte der Export nur
# Woche und Monat, und die Oberflaeche fuehrte dieselben drei Eintraege ein
# zweites Mal -- eine neue Stufe war damit zwei Aenderungen an zwei Orten.
# ``/api/export/sections`` liefert diese Liste jetzt mit.

EXPORT_AGGREGATES: list[dict] = [
    {"key": "none", "label": "Einzeln",
     "hint": "Jeder Eintrag steht einzeln in der Datei."},
    {"key": "auto", "label": "Automatisch",
     "hint": "Die Stufe richtet sich nach der Laenge des Zeitraums."},
    {"key": "day", "label": "Pro Tag",
     "hint": "Je Tag eine Summenzeile."},
    {"key": "week", "label": "Pro Woche",
     "hint": "Je Woche eine Summenzeile; Einkaeufe bleiben einzeln, aber ohne Positionen."},
    {"key": "month", "label": "Pro Monat",
     "hint": "Je Monat eine Summenzeile."},
    {"key": "year", "label": "Pro Jahr",
     "hint": "Je Jahr eine Zeile. Fuer zehn Jahre Historie die einzige lesbare Form."},
]
AGG_KEYS = [a["key"] for a in EXPORT_AGGREGATES]
# Die Stufen, die wirklich zusammenfassen -- ``none`` und ``auto`` sind keine.
AGG_LEVELS = ["day", "week", "month", "year"]

# Ab welcher Laenge welche Stufe, wenn "Automatisch" gewaehlt ist. Die
# Schwellen sind so gesetzt, dass eine Sektion selten mehr als rund
# 120 Perioden bekommt.
_AUTO_STEPS = [(92, "day"), (800, "week"), (2200, "month")]


def resolve_auto(date_from: Optional[date], date_to: Optional[date]) -> str:
    """Welche Stufe ``auto`` bedeutet. Ohne begrenzten Zeitraum ist es das
    Jahr: "Gesamt" reicht bei diesem Nutzer ueber zehn Jahre zurueck, und
    monatsweise waeren das 120 Zeilen je Sektion nur fuer den Kontext."""
    if not date_from or not date_to:
        return "year"
    span = (date_to - date_from).days + 1
    for limit, step in _AUTO_STEPS:
        if span <= limit:
            return step
    return "year"


def _agg_on(mode: str) -> bool:
    """Fasst diese Einstellung ueberhaupt zusammen?"""
    return mode in AGG_LEVELS


def _period_key(d: date, mode: str) -> str:
    """Liefert einen Sortier- und Anzeige-freundlichen Perioden-Key.

    ``day``   -> ``YYYY-MM-DD``
    ``week``  -> ISO-Woche ``YYYY-Www`` (z. B. ``2024-W03``)
    ``month`` -> ``YYYY-MM``
    ``year``  -> ``YYYY``
    """
    if mode == "day":
        return d.isoformat()
    if mode == "week":
        iso = d.isocalendar()
        return f"{iso[0]:04d}-W{iso[1]:02d}"
    if mode == "year":
        return f"{d.year:04d}"
    return f"{d.year:04d}-{d.month:02d}"


_PERIOD_WORDS = {
    "day":   ("Tag",    "Tages",   "tageweise"),
    "week":  ("Woche",  "Wochen",  "wochenweise"),
    "month": ("Monat",  "Monats",  "monatsweise"),
    "year":  ("Jahr",   "Jahres",  "jahresweise"),
}


def _period_label(mode: str) -> str:
    """Singular-Label fuer eine Periode (``Woche`` / ``Monat``)."""
    return _PERIOD_WORDS.get(mode, ("Periode",))[0]


def _period_prefix(mode: str) -> str:
    """Wortstamm fuer Substantiv-Zusammensetzungen wie ``Wochen-Zusammenfassung``
    oder ``Monats-Zusammenfassung``. Vermeidet den frueheren Bug ``Woches-...``.
    """
    return _PERIOD_WORDS.get(mode, (None, "Perioden"))[1]


def _period_adverb(mode: str) -> str:
    """Adverb fuer Beschreibungen wie ``wochenweise aggregiert``."""
    return _PERIOD_WORDS.get(mode, (None, None, "periodenweise"))[2]


def _date_from_iso_prefix(s: str) -> Optional[date]:
    """Extrahiert das Datum aus dem Anfang eines ISO-Timestamps
    (``YYYY-MM-DD...``). Wird zum Nachfiltern von String-basierten
    Protokoll-Zeilen genutzt."""
    if not s or len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _in_range(d: Optional[date], d_from: Optional[date], d_to: Optional[date]) -> bool:
    if d is None:
        return False
    if d_from and d < d_from:
        return False
    if d_to and d > d_to:
        return False
    return True


# ---------- Kompakt-Helfer ----------

# Muster fuer UTC-Timestamps im ISO-Format:
#   YYYY-MM-DDTHH:MM:SS(.ffffff)?+00:00  ->  YYYY-MM-DDTHH:MM:SSZ
_TS_UTC_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?\+00:00"
)


def _compact_timestamps(csv_text: str) -> str:
    """Entfernt Mikrosekunden und ersetzt ``+00:00`` durch ``Z`` in allen
    ISO-UTC-Timestamps. Wirkt global auf die fertige CSV, damit alle
    Sektionen einheitlich kompakt sind - unabhaengig davon, welcher
    Helfer die jeweiligen Zeilen gebaut hat."""
    return _TS_UTC_RE.sub(r"\1Z", csv_text)


def _num(v) -> str:
    """Health-Zahlenformat: Punkt-Dezimal, aber ohne unnoetiges ``.00``
    bei ganzzahligen Werten (spart bei Vitalwerten wie ``steps`` oder
    ``resting_hr`` pro Zeile 3 Zeichen).

    ``None`` bleibt LEER und wird nicht zu 0: in der Ernaehrung heisst eine
    fehlende Angabe "wir wissen es nicht", und eine 0 waere eine Behauptung
    ueber einen Naehrwert, den niemand kennt."""
    if v is None:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    if f == int(f):
        return str(int(f))
    return f"{f:.2f}"


def _euro_de(v) -> str:
    """Euro-Betraege -- seit v2.10.0 mit PUNKT, wie jede andere Zahl der Datei.

    Der Name bleibt, damit die zehn Aufrufstellen nicht anfassen muss, wer
    das hier liest; die Bedeutung ist eine andere. Bis v2.9.0 schrieb diese
    Funktion Komma und ``_num`` Punkt -- in DERSELBEN Datei, getrennt durch
    Semikolon. Damit war die Haelfte der Zahlen fuer jedes Programm, das die
    Datei liest, keine Zahl, sondern Text. Der Kopf nannte das eine
    "Konvention"; es war ein Fehler mit Erklaerung davor.

    Punkt und nicht Komma, weil diese Datei ausgewertet wird und nicht in ein
    deutsches Tabellenblatt getippt: Punkt ist das, womit jede Auswertung
    rechnet, und es kann nie mit dem Feldtrenner verwechselt werden.
    """
    if v is None:
        return ""
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return ""



# ---------- Sektionen (v1.60.0) ----------
# Die eine Liste, aus der Auswahl, Vorschau und Frontend leben. Wer eine
# Sektion hinzufuegt, traegt sie hier ein und baut sie in ``_build_sections``
# -- die Oberflaeche zieht ueber /api/export/sections automatisch nach.
#
# ``group`` bestimmt, welche Aggregations-Einstellung greift; ``aggregatable``
# sagt, ob die Sektion ueberhaupt zusammenfassbar ist. Metadaten (Ziele,
# Achievements, Zusammenfassung) sind es nicht: sie sind Stammdaten, keine
# Zeitreihe, und werden deshalb auch vom Zeitraum-Filter nicht angefasst.
#
# ``bulk`` (v2.10.0) heisst: Rohdaten, die eine Auswertung nicht braucht --
# Zugfolgen als PGN und die beiden Upload-Protokolle. Sie sind Herkunfts-
# und Wiederherstellungsmaterial; in einer Datei, die jemand liest, machen
# sie nur die Zeilen lang. Der Knopf "Zum Auswerten" laesst sie deshalb weg,
# und weil das Kennzeichen HIER steht, muss die Oberflaeche keine zweite
# Liste davon fuehren.

EXPORT_SECTIONS: list[dict] = [
    {"key": "sparziel_meta", "group": "sparziel", "aggregatable": False, "dated": False,
     "label": "Ziele, Achievements, Wochenziele, Trophaeen"},
    {"key": "sparziel_log", "group": "sparziel", "aggregatable": True, "dated": True,
     "label": "Protokoll (Check-ins, Meilensteine, Auszahlungen)"},
    {"key": "ausgaben", "group": "ausgaben", "aggregatable": True, "dated": True,
     "label": "Bons und ihre Positionen"},
    {"key": "expense_imports", "group": "ausgaben", "aggregatable": False, "dated": False,
     "bulk": True,
     "label": "Protokoll der Kontoauszug-Uploads"},
    {"key": "health_summary", "group": "health", "aggregatable": False, "dated": False,
     "label": "Zusammenfassung"},
    {"key": "health_vitals", "group": "health", "aggregatable": True, "dated": True,
     "label": "Vitalwerte (ein Tag je Zeile)"},
    {"key": "health_bp", "group": "health", "aggregatable": True, "dated": True,
     "label": "Blutdruck"},
    {"key": "health_glucose", "group": "health", "aggregatable": True, "dated": True,
     "label": "Blutzucker"},
    {"key": "health_sleep", "group": "health", "aggregatable": True, "dated": True,
     "label": "Schlaf inkl. Phasen"},
    {"key": "health_workouts", "group": "health", "aggregatable": True, "dated": True,
     "label": "Workouts inkl. Zusatzmetriken"},
    {"key": "music_register", "group": "musik", "aggregatable": True, "dated": True,
     "label": "Hörregister (Periode, Interpret, Titel, Wiedergaben)"},
    {"key": "music_imports", "group": "musik", "aggregatable": False, "dated": False,
     "bulk": True,
     "label": "Protokoll der CSV-Uploads"},
    # Zwei Module, zwei Genauigkeiten -- deshalb zwei Protokolle. Sie in eine
    # Sektion zu werfen hiesse, "Pizza, uebermaessig" und "180 g Brot" in
    # dieselbe Spalte zu schreiben.
    {"key": "diary_log", "group": "ernaehrung", "aggregatable": True, "dated": True,
     "label": "Essenstagebuch (Tag, Mahlzeit, Was, Stufe)"},
    {"key": "track_log", "group": "ernaehrung", "aggregatable": True, "dated": True,
     "label": "Naehrwerte-Eintraege (Menge, kcal, Makros)"},
    {"key": "food_stock", "group": "ernaehrung", "aggregatable": False, "dated": False,
     "label": "Eigener Bestand samt eigenen Groessen"},
    {"key": "food_dishes", "group": "ernaehrung", "aggregatable": False, "dated": False,
     "label": "Eigene Gerichte (eine Zeile je Zutat)"},
    # Schach (v2.1.0). Die Zugfolge steht bewusst in einer EIGENEN Sektion:
    # ein PGN ist ein mehrzeiliges Dokument, das hier zu einer sehr langen
    # Zelle wird. In der Partienliste haette es jede Tabellenkalkulation
    # unlesbar gemacht -- getrennt nimmt es mit, wer es braucht.
    {"key": "chess_games", "group": "schach", "aggregatable": True, "dated": True,
     "label": "Partien (Ergebnis, Gegner, Wertung, Eroeffnung)"},
    {"key": "chess_pgn", "group": "schach", "aggregatable": False, "dated": True,
     "bulk": True,
     "label": "Zugfolgen als PGN (eine Zeile je Partie)"},
    {"key": "chess_ratings", "group": "schach", "aggregatable": False, "dated": True,
     "label": "Wertungsverlauf (ein Tag je Disziplin)"},
    {"key": "notes", "group": "notizen", "aggregatable": False, "dated": False,
     "label": "Notizen samt Text, Farbe und Schlagworten"},
]

EXPORT_GROUPS: list[dict] = [
    {"key": "sparziel", "label": "Sparziel"},
    {"key": "ausgaben", "label": "Ausgaben"},
    {"key": "health", "label": "Gesundheit"},
    {"key": "musik", "label": "Musik"},
    {"key": "ernaehrung", "label": "Ernährung"},
    {"key": "schach", "label": "Schach"},
    {"key": "notizen", "label": "Notizen"},
]

ALL_SECTION_KEYS = [s["key"] for s in EXPORT_SECTIONS]

# Was in eine Datei gehoert, die ausgewertet werden soll: alles ausser den
# Rohdaten. Steht hier und nicht im Frontend -- sonst waere eine neue
# Sektion zwei Aenderungen an zwei Orten.
AUSWERTBARE_SECTION_KEYS = [s["key"] for s in EXPORT_SECTIONS if not s.get("bulk")]

# Wie eine Buchung entstanden ist. Steht als Klartext in der Datei -- ein
# Schluessel wie 'import' waere in fuenf Jahren eine Ratearbeit.
HERKUNFT = {
    "receipt": "Bon gescannt",
    "manual": "von Hand erfasst",
    "import": "CSV-Import (Kontoauszug)",
}


def clean_sections(raw) -> list[str]:
    """Bekannte Schluessel in der Reihenfolge der Registry. Leer heisst alle --
    ein Export ohne Sektionen waere eine leere Datei, und die will niemand."""
    if not raw:
        return list(ALL_SECTION_KEYS)
    wanted = {str(x).strip() for x in raw if str(x).strip()}
    picked = [k for k in ALL_SECTION_KEYS if k in wanted]
    return picked or list(ALL_SECTION_KEYS)


def clean_aggregate_map(raw, fallback: str = "none",
                        date_from: Optional[date] = None,
                        date_to: Optional[date] = None) -> dict:
    """Aggregation je Modul. Was fehlt oder unbekannt ist, bekommt den
    Gesamtwert -- so bleibt der alte Aufruf mit nur ``aggregate`` gueltig.

    ``auto`` wird hier schon in eine echte Stufe uebersetzt: ab hier
    rechnet niemand mehr mit einer Einstellung, die keine Periode benennt,
    und der Datei-Vorspann kann die tatsaechlich benutzte Stufe nennen.
    """
    fallback = fallback if fallback in AGG_KEYS else "none"
    out = {g["key"]: fallback for g in EXPORT_GROUPS}
    for key, value in (raw or {}).items():
        if key in out and value in AGG_KEYS:
            out[key] = value
    auto = resolve_auto(date_from, date_to)
    return {k: (auto if v == "auto" else v) for k, v in out.items()}


# ---------- Spaltenauswahl (v1.67.0) ----------
# Welche Spalten eine Sektion hat, haengt von ihrer Aggregation ab: die
# Ausgaben tragen einzeln andere als monatsweise. Eine fest hinterlegte
# Spaltenliste waere deshalb entweder unvollstaendig oder falsch -- also wird
# sie aus den GEBAUTEN Zeilen gelesen. Die Vorschau baut den Export ohnehin
# und liefert sie mit; die Oberflaeche lernt daraus, was es zu waehlen gibt.
#
# Aufbau einer Sektion:
#     # SEKTION: ...        <- Kommentar, danach folgt genau ein Spalten-Header
#     Datum;Typ;Titel       <- Header
#     2026-01-05;...        <- Daten, bis Leerzeile oder naechste Marke
# Eine Sektion darf mehrere solcher Bloecke enthalten (Bons + Positionen).


def _section_columns(lines: list[str]) -> list[str]:
    """Die Spaltennamen einer Sektion, in Reihenfolge und ohne Dubletten."""
    out: list[str] = []
    expect_header = False
    for line in lines:
        if line.startswith("# SEKTION:"):
            expect_header = True
            continue
        if line.startswith("#") or not line.strip():
            continue
        if expect_header:
            for name in line.split(";"):
                name = name.strip()
                if name and name not in out:
                    out.append(name)
            expect_header = False
    return out


def _filter_columns(lines: list[str], keep: Optional[set]) -> list[str]:
    """Behaelt in jedem Block dieser Sektion nur die gewaehlten Spalten.

    Bleibt fuer einen Block nichts uebrig, bleibt er unveraendert: eine Datei
    mit einem Spalten-Header ohne Spalten waere kaputt, und die Auswahl war
    dann offensichtlich fuer den anderen Block der Sektion gemeint.
    """
    if not keep:
        return lines
    out: list[str] = []
    expect_header = False
    idx: Optional[list[int]] = None
    for line in lines:
        if line.startswith("# SEKTION:"):
            expect_header, idx = True, None
            out.append(line)
            continue
        if line.startswith("#") or not line.strip():
            out.append(line)
            continue
        if expect_header:
            names = [n.strip() for n in line.split(";")]
            picked = [i for i, n in enumerate(names) if n in keep]
            idx = picked if picked else None
            expect_header = False
        if idx is None:
            out.append(line)
        else:
            parts = line.split(";")
            out.append(";".join(parts[i] if i < len(parts) else "" for i in idx))
    return out


def clean_column_map(raw) -> dict:
    """``{sektion: {spalte, ...}}``. Leere Auswahl heisst "alle" -- dieselbe
    Regel wie bei den Sektionen, aus demselben Grund."""
    out: dict[str, set] = {}
    for key, names in (raw or {}).items():
        if key not in ALL_SECTION_KEYS:
            continue
        wanted = {str(n).strip() for n in (names or []) if str(n).strip()}
        if wanted:
            out[key] = wanted
    return out


def _count_rows(lines: list[str]) -> int:
    """Datenzeilen einer Sektion: alles ohne Kommentar und ohne Leerzeile,
    abzueglich der Spalten-Header. Jede '# SEKTION:'-Marke steht genau vor
    einem Header -- daher deren Anzahl."""
    data = sum(1 for ln in lines if ln and not ln.startswith("#"))
    headers = sum(1 for ln in lines if ln.startswith("# SEKTION:"))
    return max(0, data - headers)


# ---------- Public API ----------

async def build_full_export_csv(
    db,
    user,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    aggregate: str = "none",
    sections: Optional[list] = None,
    aggregate_map: Optional[dict] = None,
    column_map: Optional[dict] = None,
    compact_before: Optional[date] = None,
) -> str:
    """Baut die komplette CSV als String. Gibt Zeilen (``\\n``-getrennt) zurueck.

    v1.37.1: Optionale Filter/Aggregation.
      * ``date_from`` / ``date_to``: filtert alle zeitreihen-basierten
        Sektionen (Sparziel-Protokoll, Ausgaben, Health-Zeitreihen).
        Metadaten-Sektionen (Sparziele, Achievements, Wochen-/Monatsziele,
        Trophaeen, ...) bleiben ungefiltert, damit die aggregierten Zahlen
        weiter im Kontext lesbar bleiben.
      * ``aggregate``: fasst Ausgaben und Vitalwerte zu Perioden zusammen
        (Anzahl Bons + Summe je Periode, avg/min/max je Metrik). Fuer lange
        Zeitraeume (Jahre) enorm platzsparend. Erlaubt sind die Schluessel aus
        ``EXPORT_AGGREGATES``; v1.67.0 kamen Tag, Jahr und ``auto`` dazu.
        v1.40.1: Ausgaben behalten dabei zusaetzlich eine Zeile je Bon
        (Datum, Laden, Typ, Anzahl Positionen, Summe, Kategorien-Split) --
        weg fallen nur die Einzelpositionen.
      * ``column_map`` (v1.67.0): je Sektion die gewuenschten Spalten.
    """
    kopf, bloecke = await _export_teile(
        db, user, date_from, date_to, aggregate, sections, aggregate_map,
        column_map, compact_before)
    lines = list(kopf)
    for _titel, zeilen in bloecke:
        lines.extend(zeilen)
    return _compact_timestamps("\n".join(lines) + "\n")


async def _export_teile(
    db,
    user,
    date_from: "Optional[date]" = None,
    date_to: "Optional[date]" = None,
    aggregate: str = "none",
    sections: "Optional[list]" = None,
    aggregate_map: "Optional[dict]" = None,
    column_map: "Optional[dict]" = None,
    compact_before: "Optional[date]" = None,
) -> tuple:
    """``(Kopfzeilen, [(Titel, Zeilen), ...])`` -- die eine Quelle beider Formate.

    v2.10.0 herausgeloest, weil es seither zwei Ausgabeformen gibt: eine Datei
    und ein Archiv mit einer Datei je Tabelle. Beide bauen aus DIESEN Teilen.
    Zwei Bauwege waeren zwei Dateien, die dasselbe behaupten und sich beim
    naechsten Fix unterscheiden -- und man saehe es keiner von beiden an.

    Leere Bloecke fallen hier heraus und stehen dafuer namentlich im Kopf.
    Vorher standen in einem frisch benutzten Konto zwei Dutzend Ueberschriften
    ueber nichts, und wer die Datei ueberflog, suchte zwischen lauter leeren
    Bloecken nach dem einen, das etwas enthaelt.
    """
    picked = clean_sections(sections)
    agg_map = clean_aggregate_map(aggregate_map, aggregate, date_from, date_to)
    cols = clean_column_map(column_map)
    built = await _build_sections(db, user, picked, date_from, date_to, agg_map,
                                  compact_before)

    bloecke = []
    leer = []
    for key, zeilen in built:
        gefiltert = _filter_columns(zeilen, cols.get(key))
        behalten, ohne = _leere_bloecke_aussortieren(gefiltert)
        leer.extend(ohne)
        for block in _bloecke(behalten):
            bloecke.append((_block_titel(block), block))

    backlog = await _backlog_facts(db, user["id"]) if "ausgaben" in picked else None
    kopf = _export_header(user, picked, date_from, date_to, agg_map, backlog,
                          compact_before, leer)
    return kopf, bloecke


def _dateiname(titel: str, nummer: int) -> str:
    """Aus 'Gesundheit - Blutdruck' wird '06-gesundheit-blutdruck.csv'.

    Die laufende Nummer steht vorn, damit die Dateien im Archiv in derselben
    Reihenfolge liegen wie die Bloecke in der einen Datei -- alphabetisch
    sortiert stuende sonst Ausgaben vor Sparziel und Schach zwischen beidem,
    und der Zusammenhang, den die Reihenfolge traegt, waere weg.
    """
    rein = []
    for zeichen in titel.lower():
        if zeichen.isalnum():
            rein.append(zeichen)
        elif zeichen in " -_/":
            rein.append("-")
    name = "".join(rein)
    for paar in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        name = name.replace(*paar)
    while "--" in name:
        name = name.replace("--", "-")
    name = name.strip("-") or "sektion"
    return f"{nummer:02d}-{name[:60]}.csv"


async def build_export_archive(
    db,
    user,
    date_from=None,
    date_to=None,
    aggregate: str = "none",
    sections=None,
    aggregate_map=None,
    column_map=None,
    compact_before=None,
) -> dict:
    """Derselbe Export als ``{Dateiname: Inhalt}`` -- eine Datei je Tabelle.

    Die eine grosse CSV ist gut zum Auswerten und schlecht zum Ansehen: 20
    Tabellen mit verschiedener Spaltenzahl in einem Blatt kann kein
    Tabellenprogramm oeffnen. Das Archiv loest genau das und sonst nichts --
    es kommt aus ``_export_teile``, also aus denselben Zeilen.

    ``LIESMICH.txt`` traegt den Vorspann: Zeitraum, Stufen, was bewusst fehlt,
    was leer war. Ohne ihn waere ein Ordner mit CSV-Dateien eine Sammlung
    ohne Herkunft, und in einem Jahr weiss niemand mehr, welcher Zeitraum
    darin steht.
    """
    kopf, bloecke = await _export_teile(
        db, user, date_from, date_to, aggregate, sections, aggregate_map,
        column_map, compact_before)

    dateien: dict[str, str] = {}
    verzeichnis = ["Diese Datei gehoert zu einem Vexbob-Gesamtexport.", ""]
    verzeichnis.extend(z.lstrip("# ") for z in kopf)
    verzeichnis.append("")
    verzeichnis.append("Enthaltene Dateien:")

    for nummer, (titel, zeilen) in enumerate(bloecke, start=1):
        name = _dateiname(titel or f"sektion-{nummer}", nummer)
        # Die '# SEKTION:'-Ueberschrift steht schon im Dateinamen; in der
        # Datei selbst waere sie eine Zeile vor dem Spaltenkopf, an der jedes
        # Tabellenprogramm die Spalten falsch zaehlt.
        inhalt = [z for z in zeilen if not z.startswith("#")]
        while inhalt and not inhalt[-1].strip():
            inhalt.pop()
        datenzeilen = max(0, len(inhalt) - 1)
        dateien[name] = _compact_timestamps("\n".join(inhalt) + "\n")
        verzeichnis.append(f"  {name} - {titel} ({datenzeilen} Zeilen)")

    dateien["LIESMICH.txt"] = _compact_timestamps(
        "\n".join(verzeichnis) + "\n")
    return dateien


async def _sec_expense_imports(db, user_id: int) -> list[str]:
    """Protokoll der Kontoauszug-Uploads. Beantwortet ein Jahr spaeter die
    Frage, welche Datei welchen Zeitraum in den Bestand gebracht hat."""
    rows = await db.fetch(
        """SELECT id, filename, uploaded_at, date_from, date_to, rows_read,
                  rows_written, rows_skipped, rows_replaced, stores_created
             FROM expense_imports WHERE user_id=$1
            ORDER BY uploaded_at""", user_id)
    out = ["# SEKTION: Ausgaben - Protokoll der CSV-Uploads (Kontoauszuege)",
           "import_id;Hochgeladen;Datei;Zeitraum von;Zeitraum bis;Zeilen gelesen;"
           "uebernommen;uebersprungen;ersetzt;Laeden angelegt"]
    for r in rows:
        up = r["uploaded_at"].isoformat() if r["uploaded_at"] else ""
        out.append(
            f'{r["id"]};{up};{_f(r["filename"] or "")};'
            f'{r["date_from"].isoformat() if r["date_from"] else ""};'
            f'{r["date_to"].isoformat() if r["date_to"] else ""};'
            f'{r["rows_read"]};{r["rows_written"]};{r["rows_skipped"]};'
            f'{r["rows_replaced"]};{r["stores_created"]}')
    out.append("")
    return out


async def _backlog_facts(db, user_id: int) -> Optional[dict]:
    """Wie viel des Ausgaben-Bestands aus einem Kontoauszug stammt.

    Abgeleitet wird das aus ``source``, nicht aus einem festen Datum: wer
    spaeter noch einen aelteren Auszug nachreicht, bekommt trotzdem einen
    richtigen Hinweis. Gibt es keinen Import, entfaellt der Absatz ganz --
    eine Erklaerung fuer etwas, das es nicht gibt, ist Rauschen.
    """
    r = await db.fetchrow(
        """SELECT COUNT(*) AS n, MIN(purchase_date) AS von, MAX(purchase_date) AS bis,
                  COALESCE(SUM(total_amount), 0) AS summe
             FROM expenses WHERE user_id=$1 AND source='import'""", user_id)
    if not r or not r["n"]:
        return None
    eigen = await db.fetchval(
        "SELECT COUNT(*) FROM expenses WHERE user_id=$1 AND COALESCE(source,'receipt')<>'import'",
        user_id) or 0
    return {"n": r["n"], "von": r["von"], "bis": r["bis"],
            "summe": r["summe"], "eigen": eigen}


def _export_header(user, picked: list[str], date_from, date_to, agg_map: dict,
                   backlog: Optional[dict] = None,
                   compact_before: Optional[date] = None,
                   leer: Optional[list[str]] = None) -> list[str]:
    """Der Vorspann dokumentiert die Zusammenstellung in der Datei selbst --
    ein halber Export ohne diese Zeilen sieht ein Jahr spaeter aus wie
    fehlende Daten."""
    labels = {s["key"]: s["label"] for s in EXPORT_SECTIONS}
    export_dt = datetime.now(timezone.utc).isoformat()
    opt_from = date_from.isoformat() if date_from else "(offen)"
    opt_to = date_to.isoformat() if date_to else "(offen)"
    agg_txt = "; ".join(
        f'{g["label"]}={agg_map.get(g["key"], "none")}' for g in EXPORT_GROUPS)
    lines = [
        f"# Vexbob Gesamt-Export;user={_f(user['username'])};generated_at={export_dt}",
        f"# Optionen: zeitraum={opt_from} bis {opt_to}; aggregation: {agg_txt}",
        "# Enthaltene Sektionen: " + "; ".join(labels.get(k, k) for k in picked),
    ]
    if compact_before:
        # Ohne diese Zeile sieht die Datei aus, als sei sie an einer
        # willkuerlichen Stelle grober geworden.
        lines.append(
            f"# Verdichtet: alles vor {compact_before.isoformat()} steht "
            "monatsweise zusammengefasst (bei jahresweiser Aggregation "
            "jahresweise); ab diesem Tag gilt die oben genannte Stufe. "
            "Sektionen ohne Datum und solche, die sich nicht zusammenfassen "
            "lassen, sind unberuehrt.")
    if len(picked) < len(ALL_SECTION_KEYS):
        fehlt = [labels.get(k, k) for k in ALL_SECTION_KEYS if k not in picked]
        lines.append("# BEWUSST NICHT enthalten: " + "; ".join(fehlt))
    if leer:
        # Gewaehlt, aber ohne eine einzige Zeile. Der Unterschied zur Zeile
        # darueber ist der zwischen "wollte ich nicht" und "gibt es nicht".
        lines.append("# GEWAEHLT, ABER LEER (keine Daten im Zeitraum): "
                     + "; ".join(leer))
    lines.append(
        "# Jede Sektion beginnt mit einer Kommentarzeile '# SEKTION: ...' "
        "gefolgt von ihrem eigenen Spalten-Header - die Spaltenanzahl "
        "unterscheidet sich bewusst zwischen den Sektionen. Bons und "
        "Positionen sind ueber expense_id verknuepft.")
    lines.append(
        "# Konventionen: Feldtrenner ist ';'. Zeitstempel sind UTC im Format "
        "YYYY-MM-DDTHH:MM:SSZ (keine Mikrosekunden). ALLE Zahlen nutzen "
        "Punkt-Dezimal, auch Euro-Betraege. Ein leeres Feld heisst 'nicht "
        "bekannt' und nicht 'null'.")
    # v2.10.2: Diese Zeile steht hier, weil eine Auswertung genau daran
    # scheitert: derselbe Betrag taucht absichtlich auf mehreren Stufen auf,
    # und wer die Sektionen addiert, haelt das fuer doppelte Buchungen.
    lines.append(
        "# WICHTIG FUER AUSWERTUNGEN: dieselbe Ausgabe steht absichtlich "
        "auf MEHREREN Stufen in dieser Datei -- als Perioden-Summe, als "
        "Beleg und als Einzelposten. Das sind keine doppelten Buchungen. "
        "Fuer eine Gesamtsumme gilt GENAU EINE Sektion: 'Ausgaben - Bons' "
        "bzw. 'Ausgaben - Bons kompakt' (ein Eintrag je Beleg). Die "
        "Perioden-Zusammenfassung und die Bon-Positionen sind Sichten auf "
        "dieselben Belege und duerfen nicht dazugezaehlt werden. Jede "
        "betroffene Sektion sagt das noch einmal in ihrer eigenen Zeile.")
    if backlog:
        # Ohne diesen Absatz sieht der Rueckblick aus wie schlecht erfasste
        # Bons: hunderte Eintraege ohne eine einzige Position.
        von = backlog["von"].isoformat() if backlog["von"] else "?"
        bis = backlog["bis"].isoformat() if backlog["bis"] else "?"
        lines.append(
            f"# NACHTRAG (Backlog): {backlog['n']} der Buchungen stammen NICHT aus "
            f"Vexbob, sondern aus dem CSV-Export der Banking-App (C24) und decken "
            f"{von} bis {bis} ab. Sie tragen in der Spalte 'Herkunft' den Wert "
            f"'{HERKUNFT['import']}'.")
        lines.append(
            "# Diese Buchungen haben KEINE Einzelpositionen - der Kontoauszug "
            "kennt nur den Gesamtbetrag. In der Positions-Sektion steht je "
            "Buchung genau eine Sammelzeile ueber den vollen Betrag; sie ist "
            "als nicht preisvergleichbar markiert und taucht deshalb in "
            "Artikel- und Preisauswertungen bewusst nicht auf. Fehlende "
            "Positionen sind hier also die Datenlage, kein Erfassungsfehler.")
        lines.append(
            "# Ihre Spalten 'Kategorie (Bank)' und 'Unterkategorie (Bank)' sind "
            "die Vorgaben der Banking-App, NICHT die Kategorien dieser Website. "
            "Die eigene Kategorie ist bei diesen Buchungen zunaechst leer und "
            "wird in einem gesonderten Schritt zugeordnet.")
        lines.append(
            f"# Selbst erfasst (Bon gescannt oder von Hand): {backlog['eigen']} "
            f"Buchungen. Nur diese haben echte Einzelpositionen.")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Ernaehrung (v2.0.0) — zwei Module, vier Sektionen
# ---------------------------------------------------------------------------
# Das Essenstagebuch und die Naehrwerte sind zwei Module mit zwei Tabellen und
# zwei verschiedenen Genauigkeiten. Sie in EINE Sektion zu werfen hiesse,
# "Pizza, uebermaessig" und "180 g Brot" in dieselbe Spalte zu schreiben --
# und in fuenf Jahren waere nicht mehr zu erkennen, was davon gemessen und was
# notiert war. Deshalb vier Sektionen: je ein Protokoll, dazu Bestand und
# Rezepte als Stammdaten.


async def _sec_diary(db, user_id: int, date_from, date_to,
                     aggregate: str = "none") -> list[str]:
    """Essenstagebuch: was gab es, normal oder uebermaessig.

    Hier steht bewusst KEINE Kalorienzahl. Das Tagebuch kennt keine, und eine
    im Export zu ergaenzen hiesse, sie zu erfinden.

    Zusammengefasst zaehlt es: wie viele Eintraege, wie viele davon
    uebermaessig, an wie vielen Tagen ueberhaupt etwas notiert wurde. Die
    Namen der Speisen fallen dabei weg -- ueber eine Woche summiert waere
    „Pizza“ keine Kennzahl, sondern eine Liste.
    """
    bedingungen, werte = ["user_id=$1"], [user_id]
    if date_from:
        werte.append(date_from)
        bedingungen.append(f"day >= ${len(werte)}")
    if date_to:
        werte.append(date_to)
        bedingungen.append(f"day <= ${len(werte)}")
    rows = await db.fetch(
        f"SELECT day, meal, label, level, note, logged_time, meal_auto "
        f"  FROM food_diary WHERE {' AND '.join(bedingungen)} "
        f" ORDER BY day, created_at", *werte)

    if _agg_on(aggregate):
        return _diary_aggregiert(rows, aggregate)

    out = ["# SEKTION: Essenstagebuch - was gab es (ohne Mengen, ohne Naehrwerte)",
           "Datum;Mahlzeit;Was;Stufe;Uhrzeit;Mahlzeit geraten;Notiz"]
    for r in rows:
        mahlzeit = (mahlzeiten.MAHLZEIT_LABEL.get(r["meal"])
                    or mahlzeiten.OHNE_MAHLZEIT_LABEL)
        out.append(
            f'{r["day"].isoformat()};{_f(mahlzeit)};{_f(r["label"] or "")};'
            f'{_f("uebermaessig" if r["level"] == "viel" else "normal")};'
            f'{r["logged_time"].strftime("%H:%M") if r["logged_time"] else ""};'
            f'{"ja" if r["meal_auto"] else "nein"};{_f(r["note"] or "")}')
    out.append("")
    return out


def _diary_aggregiert(rows, aggregate: str) -> list[str]:
    """Je Periode eine Zeile: wie oft notiert, und wie oft uebermaessig."""
    label = _period_label(aggregate)
    toepfe: dict[str, dict] = {}
    for r in rows:
        tag = r["day"]
        b = toepfe.setdefault(_period_key(tag, aggregate), {
            "von": tag, "bis": tag, "eintraege": 0, "normal": 0, "viel": 0,
            "tage": set(),
        })
        b["von"] = min(b["von"], tag)
        b["bis"] = max(b["bis"], tag)
        b["eintraege"] += 1
        b["viel" if r["level"] == "viel" else "normal"] += 1
        b["tage"].add(tag)

    out = [f"# SEKTION: Essenstagebuch - {_period_prefix(aggregate)}-Bilanz "
           f"({_period_adverb(aggregate)} aggregiert). Was es gab, steht nur "
           "ohne Zusammenfassung in der Datei.",
           f"{label};Von;Bis;Tage mit Eintrag;Eintraege;normal;uebermaessig"]
    for key in sorted(toepfe.keys()):
        b = toepfe[key]
        out.append(
            f'{key};{b["von"].isoformat()};{b["bis"].isoformat()};'
            f'{len(b["tage"])};{b["eintraege"]};{b["normal"]};{b["viel"]}')
    out.append("")
    return out


async def _sec_track_log(db, user_id: int, date_from, date_to,
                         aggregate: str = "none") -> list[str]:
    """Naehrwerte: Mengen und was daraus folgt.

    Die Naehrwerte stehen als Zahl je Zeile und nicht als Tagessumme: eine
    Summe laesst sich aus Zeilen bilden, aus einer Summe aber keine Zeilen.
    Fehlt eine Angabe, bleibt das Feld LEER -- eine Null waere eine Behauptung.

    Zusammengefasst wird daraus je Periode eine Summe samt Tagesschnitt. Der
    Schnitt teilt durch die Tage MIT Eintrag und nicht durch die Tage der
    Periode: eine Woche mit zwei notierten Tagen haette sonst einen sehr
    gesunden Durchschnitt.
    """
    bedingungen, werte = ["l.user_id=$1"], [user_id]
    if date_from:
        werte.append(date_from)
        bedingungen.append(f"l.day >= ${len(werte)}")
    if date_to:
        werte.append(date_to)
        bedingungen.append(f"l.day <= ${len(werte)}")
    rows = await db.fetch(
        f"SELECT l.day, l.meal, l.amount, l.unit, l.grams, l.note, l.logged_time, "
        f"       d.name AS dish_name, i.name AS item_name, i.brand, "
        f"       i.kcal, i.protein_g, i.fiber_g, i.carbs_g, i.fat_g "
        f"  FROM food_log l "
        f"  LEFT JOIN food_dishes d ON d.id = l.dish_id "
        f"  LEFT JOIN food_items  i ON i.id = l.item_id "
        f" WHERE {' AND '.join(bedingungen)} ORDER BY l.day, l.created_at", *werte)

    if _agg_on(aggregate):
        return _track_log_aggregiert(rows, aggregate)

    out = ["# SEKTION: Naehrwerte - Eintraege mit Menge",
           "Datum;Mahlzeit;Was;Art;Menge;Einheit;Gramm;kcal;Eiweiss_g;"
           "Ballaststoffe_g;Kohlenhydrate_g;Fett_g;Uhrzeit;Notiz"]
    for r in rows:
        ist_gericht = r["dish_name"] is not None
        name = r["dish_name"] or r["item_name"] or ""
        if not ist_gericht and r["brand"]:
            name = f'{name} ({r["brand"]})'
        mahlzeit = (mahlzeiten.MAHLZEIT_LABEL.get(r["meal"])
                    or mahlzeiten.OHNE_MAHLZEIT_LABEL)
        gramm = float(r["grams"] or 0)
        # Ein Gericht traegt seine Naehrwerte in seinem Rezept, nicht an der
        # Zeile: sie hier je 100 g auszurechnen waere eine zweite Fassung
        # derselben Rechnung. Die Rezepte stehen in ihrer eigenen Sektion.
        werte_text = ";" * 5
        if not ist_gericht:
            stuecke = []
            for makro in ("kcal", "protein_g", "fiber_g", "carbs_g", "fat_g"):
                roh = r[makro]
                stuecke.append("" if roh is None
                               else _num(float(roh) * gramm / 100.0))
            werte_text = ";".join(stuecke)
        out.append(
            f'{r["day"].isoformat()};{_f(mahlzeit)};{_f(name)};'
            f'{"Gericht" if ist_gericht else "Lebensmittel"};'
            f'{_num(r["amount"])};{_f(r["unit"] or "")};{_num(gramm)};'
            f'{werte_text};'
            f'{r["logged_time"].strftime("%H:%M") if r["logged_time"] else ""};'
            f'{_f(r["note"] or "")}')
    out.append("")
    return out


_TRACK_MAKROS = [("kcal", "kcal"), ("protein_g", "Eiweiss_g"),
                 ("fiber_g", "Ballaststoffe_g"), ("carbs_g", "Kohlenhydrate_g"),
                 ("fat_g", "Fett_g")]


def _track_log_aggregiert(rows, aggregate: str) -> list[str]:
    """Je Periode eine Summenzeile samt Tagesschnitt.

    Ein Gericht traegt seine Naehrwerte im Rezept und nicht an der Zeile --
    genau wie in der Einzelansicht zaehlt es deshalb als Eintrag, aber nicht
    in die Summe. Wie viele das waren, sagt eine eigene Spalte: eine Summe,
    der Eintraege fehlen, ist zu niedrig, und das muss dranstehen.
    """
    label = _period_label(aggregate)
    toepfe: dict[str, dict] = {}
    for r in rows:
        tag = r["day"]
        b = toepfe.setdefault(_period_key(tag, aggregate), {
            "von": tag, "bis": tag, "eintraege": 0, "ohne": 0, "tage": set(),
            "summe": {k: 0.0 for k, _ in _TRACK_MAKROS},
        })
        b["von"] = min(b["von"], tag)
        b["bis"] = max(b["bis"], tag)
        b["eintraege"] += 1
        b["tage"].add(tag)
        if r["dish_name"] is not None or r["kcal"] is None:
            b["ohne"] += 1
            continue
        gramm = float(r["grams"] or 0)
        for makro, _spalte in _TRACK_MAKROS:
            roh = r[makro]
            if roh is not None:
                b["summe"][makro] += float(roh) * gramm / 100.0

    spalten = ";".join(s for _k, s in _TRACK_MAKROS)
    out = [f"# SEKTION: Naehrwerte - {_period_prefix(aggregate)}-Summe "
           f"({_period_adverb(aggregate)} aggregiert). Einzelne Eintraege "
           "stehen nur ohne Zusammenfassung in der Datei.",
           f"{label};Von;Bis;Tage mit Eintrag;Eintraege;{spalten};"
           "kcal je Tag;Eintraege ohne Naehrwerte"]
    for key in sorted(toepfe.keys()):
        b = toepfe[key]
        tage = len(b["tage"]) or 1
        summen = ";".join(_num(b["summe"][k]) for k, _s in _TRACK_MAKROS)
        out.append(
            f'{key};{b["von"].isoformat()};{b["bis"].isoformat()};'
            f'{len(b["tage"])};{b["eintraege"]};{summen};'
            f'{_num(b["summe"]["kcal"] / tage)};{b["ohne"]}')
    out.append("")
    return out


async def _sec_food_stock(db, user_id: int) -> list[str]:
    """Der eigene Bestand samt eigenen Groessen. Stammdaten, kein Zeitraum."""
    rows = await db.fetch(
        "SELECT i.id, i.name, i.brand, i.barcode, i.source, i.base_unit, "
        "       i.kcal, i.protein_g, i.carbs_g, i.sugar_g, i.fat_g, "
        "       i.sat_fat_g, i.fiber_g, i.salt_g, i.user_edited "
        "  FROM food_items i WHERE i.user_id=$1 ORDER BY lower(i.name)", user_id)
    groessen: dict = {}
    for g in await db.fetch(
            "SELECT s.item_id, s.label, s.grams FROM food_item_sizes s "
            "  JOIN food_items i ON i.id = s.item_id "
            " WHERE i.user_id=$1 ORDER BY s.position", user_id):
        groessen.setdefault(g["item_id"], []).append(
            f'{g["label"]}={_num(g["grams"])}')

    out = ["# SEKTION: Naehrwerte - eigener Bestand (je 100 g bzw. 100 ml)",
           "Name;Marke;Strichcode;Herkunft;Basis;kcal;Eiweiss_g;Kohlenhydrate_g;"
           "Zucker_g;Fett_g;gesaettigt_g;Ballaststoffe_g;Salz_g;Eigene Groessen;"
           "von Hand gepflegt"]
    for r in rows:
        zahlen = ";".join("" if r[m] is None else _num(r[m]) for m in (
            "kcal", "protein_g", "carbs_g", "sugar_g", "fat_g",
            "sat_fat_g", "fiber_g", "salt_g"))
        out.append(
            f'{_f(r["name"])};{_f(r["brand"] or "")};{_f(r["barcode"] or "")};'
            f'{_f("Open Food Facts" if r["source"] == "off" else "selbst angelegt")};'
            f'{_f(r["base_unit"] or "g")};{zahlen};'
            f'{_f(" ".join(groessen.get(r["id"], [])))};'
            f'{"ja" if r["user_edited"] else "nein"}')
    out.append("")
    return out


async def _sec_food_dishes(db, user_id: int) -> list[str]:
    """Die eigenen Rezepte, eine Zeile je Zutat.

    Eine Zeile je Gericht mit den Zutaten in einem Feld waere kuerzer und
    nicht auswertbar. So laesst sich die Datei nach Zutat filtern -- und
    genau dafuer exportiert man sie.
    """
    rows = await db.fetch(
        "SELECT d.id, d.name AS gericht, d.note, "
        "       z.position, z.amount, z.unit, z.grams, i.name AS zutat, i.brand "
        "  FROM food_dishes d "
        "  LEFT JOIN food_dish_items z ON z.dish_id = d.id "
        "  LEFT JOIN food_items i ON i.id = z.item_id "
        " WHERE d.user_id=$1 ORDER BY lower(d.name), z.position", user_id)
    out = ["# SEKTION: Naehrwerte - eigene Gerichte (eine Zeile je Zutat)",
           "Gericht;Zutat;Marke;Menge;Einheit;Gramm;Notiz"]
    for r in rows:
        out.append(
            f'{_f(r["gericht"])};{_f(r["zutat"] or "")};{_f(r["brand"] or "")};'
            f'{_num(r["amount"])};{_f(r["unit"] or "")};{_num(r["grams"])};'
            f'{_f(r["note"] or "")}')
    out.append("")
    return out


# ---------------------------------------------------------------------------
# Schach (v2.1.0)
# ---------------------------------------------------------------------------
# Drei Sektionen, weil es drei verschiedene Dinge sind: eine Partienliste, die
# man in einer Tabellenkalkulation auswertet; die Zugfolgen, die man in ein
# Schachprogramm laedt; und die Wertungskurve, die aus taeglichem Nachsehen
# entstanden ist und die es auf keiner Plattform gibt -- Lichess und
# Chess.com geben nur den aktuellen Stand heraus. Diese Kurve existiert
# ausschliesslich hier, und deshalb gehoert sie als Erstes in einen Export.


def _chess_zeitfilter(spalte: str, werte: list, date_from, date_to) -> str:
    """Die Zeitbedingung fuer eine der Schach-Sektionen.

    Die Platzhalternummern haengen davon ab, was schon in ``werte`` steht --
    deshalb baut das hier eine Zeichenkette und fuellt ``werte`` nebenher,
    statt feste $2/$3 anzunehmen.
    """
    teile = []
    if date_from:
        werte.append(date_from)
        teile.append(f"{spalte} >= ${len(werte)}")
    if date_to:
        werte.append(date_to)
        teile.append(f"{spalte} <= ${len(werte)}")
    return ("" if not teile else " AND " + " AND ".join(teile))


ERGEBNIS_LABEL = {"sieg": "Sieg", "remis": "Remis", "niederlage": "Niederlage"}
FARBE_LABEL = {"weiss": "Weiss", "schwarz": "Schwarz"}
PLATTFORM_LABEL = {"lichess": "Lichess", "chesscom": "Chess.com"}


async def _sec_chess_games(db, user_id: int, date_from, date_to,
                           aggregate: str = "none") -> list[str]:
    """Die Partien -- einzeln oder als Periodenbilanz.

    Ohne Aggregation eine Zeile je Partie, ohne Zugfolge (die steht nebenan).
    ``rating_diff`` bleibt leer statt null, wenn die Plattform nichts gemeldet
    hat: eine Null hiesse „unveraendert“ und waere eine Behauptung.

    Mit Aggregation je Periode eine Zeile *pro Plattform und Disziplin* --
    Anzahl der Partien und die Wertungsaenderung. Das ist die Form, in der man
    einen Verlauf liest; Gegner, Eroeffnung und Endgrund gehoeren zur einzelnen
    Partie und verschwinden mit ihr. Zusammengefasst wird NICHT ueber
    Disziplinen hinweg: Bullet und Rapid sind zwei Wertungen, und ihre Summe
    waere keine.
    """
    werte = [user_id]
    bed = _chess_zeitfilter("g.played_at::date", werte, date_from, date_to)
    rows = await db.fetch(
        "SELECT g.played_at, g.platform, a.username, g.perf, g.variant, "
        "       g.rated, g.color, g.result, g.end_reason, g.own_rating, "
        "       g.rating_diff, g.opponent, g.opponent_rating, g.opening, "
        "       g.eco, g.moves, g.url "
        "  FROM chess_games g "
        "  JOIN chess_accounts a ON a.id = g.account_id "
        f" WHERE g.user_id=$1{bed} ORDER BY g.played_at", *werte)

    if _agg_on(aggregate):
        return _chess_games_aggregiert(rows, aggregate)

    out = ["# SEKTION: Schach - Partien",
           "Gespielt am;Uhrzeit;Plattform;Konto;Disziplin;Variante;Gewertet;"
           "Farbe;Ergebnis;Ende;Eigene Wertung;Wertungsaenderung;Gegner;"
           "Wertung Gegner;Eroeffnung;ECO;Zuege;Link"]
    for r in rows:
        z = r["played_at"]
        out.append(
            f'{z.date().isoformat()};{z.strftime("%H:%M")};'
            f'{_f(PLATTFORM_LABEL.get(r["platform"], r["platform"] or ""))};'
            f'{_f(r["username"] or "")};{_f(r["perf"] or "")};'
            f'{_f(r["variant"] or "")};'
            f'{"ja" if r["rated"] else "nein" if r["rated"] is not None else ""};'
            f'{_f(FARBE_LABEL.get(r["color"], r["color"] or ""))};'
            f'{_f(ERGEBNIS_LABEL.get(r["result"], r["result"] or ""))};'
            f'{_f(r["end_reason"] or "")};'
            f'{"" if r["own_rating"] is None else r["own_rating"]};'
            f'{"" if r["rating_diff"] is None else r["rating_diff"]};'
            f'{_f(r["opponent"] or "")};'
            f'{"" if r["opponent_rating"] is None else r["opponent_rating"]};'
            f'{_f(r["opening"] or "")};{_f(r["eco"] or "")};'
            f'{"" if r["moves"] is None else r["moves"]};{_f(r["url"] or "")}')
    out.append("")
    return out


def _chess_games_aggregiert(rows, aggregate: str) -> list[str]:
    """Je Periode, Plattform und Disziplin eine Zeile.

    Die Wertungsaenderung ist die Summe der von der Plattform gemeldeten
    Differenzen. Partien, zu denen keine kam, zaehlen in einer eigenen Spalte
    -- sonst saehe eine unvollstaendige Summe aus wie eine vollstaendige.
    ``Wertung Anfang`` und ``Wertung Ende`` stehen daneben, weil sie auch dann
    noch etwas sagen, wenn Differenzen fehlen.
    """
    label = _period_label(aggregate)
    toepfe: dict[tuple, dict] = {}
    for r in rows:
        tag = r["played_at"].date()
        key = (_period_key(tag, aggregate),
               PLATTFORM_LABEL.get(r["platform"], r["platform"] or ""),
               r["perf"] or "")
        b = toepfe.setdefault(key, {
            "von": tag, "bis": tag, "partien": 0,
            "sieg": 0, "remis": 0, "niederlage": 0,
            "diff": 0, "ohne_diff": 0,
            "erste": None, "letzte": None,
        })
        b["von"] = min(b["von"], tag)
        b["bis"] = max(b["bis"], tag)
        b["partien"] += 1
        if r["result"] in ("sieg", "remis", "niederlage"):
            b[r["result"]] += 1
        if r["rating_diff"] is None:
            b["ohne_diff"] += 1
        else:
            b["diff"] += int(r["rating_diff"])
        if r["own_rating"] is not None:
            # Die Zeilen kommen nach Zeit sortiert -- die erste gesehene ist
            # die erste der Periode, die letzte gesehene die letzte.
            if b["erste"] is None:
                b["erste"] = int(r["own_rating"])
            b["letzte"] = int(r["own_rating"])

    out = [f"# SEKTION: Schach - {_period_prefix(aggregate)}-Bilanz "
           f"({_period_adverb(aggregate)} aggregiert, je Plattform und "
           "Disziplin eine Zeile). Einzelne Partien stehen nur ohne "
           "Zusammenfassung in der Datei.",
           f"{label};Von;Bis;Plattform;Disziplin;Partien;Siege;Remis;"
           "Niederlagen;Wertung Anfang;Wertung Ende;Wertungsaenderung;"
           "Partien ohne Wertungsangabe"]
    for key in sorted(toepfe.keys()):
        b = toepfe[key]
        # Eine Summe, zu der Partien fehlen, ist keine Summe. Dann bleibt die
        # Spalte leer, und die Spalte daneben sagt, wie viele fehlten.
        aenderung = "" if b["ohne_diff"] else _vorzeichen(b["diff"])
        out.append(
            f'{key[0]};{b["von"].isoformat()};{b["bis"].isoformat()};'
            f'{_f(key[1])};{_f(key[2])};{b["partien"]};'
            f'{b["sieg"]};{b["remis"]};{b["niederlage"]};'
            f'{"" if b["erste"] is None else b["erste"]};'
            f'{"" if b["letzte"] is None else b["letzte"]};'
            f'{aenderung};{b["ohne_diff"]}')
    out.append("")
    return out


def _vorzeichen(n: int) -> str:
    """Eine Wertungsaenderung traegt ihr Plus mit. ``12`` und ``-12`` sehen in
    einer Spalte sonst aus wie zwei verschiedene Arten von Zahl."""
    return f"+{n}" if n > 0 else str(n)


async def _sec_chess_pgn(db, user_id: int, date_from, date_to) -> list[str]:
    """Die Zugfolgen. Der einzige Teil, den die Spalten nebenan nicht ersetzen.

    Partien ohne PGN kommen gar nicht erst vor: eine Zeile mit leerem Feld
    saehe aus wie eine Partie ohne Zuege, und das ist keine.
    """
    werte = [user_id]
    bed = _chess_zeitfilter("played_at::date", werte, date_from, date_to)
    rows = await db.fetch(
        "SELECT played_at, platform, ext_id, pgn FROM chess_games "
        f" WHERE user_id=$1 AND pgn IS NOT NULL AND btrim(pgn) <> ''{bed} "
        " ORDER BY played_at", *werte)
    out = ["# SEKTION: Schach - Zugfolgen (PGN)",
           "Gespielt am;Plattform;Partie-ID;PGN"]
    for r in rows:
        out.append(
            f'{r["played_at"].date().isoformat()};'
            f'{_f(PLATTFORM_LABEL.get(r["platform"], r["platform"] or ""))};'
            f'{_f(r["ext_id"] or "")};{_f(r["pgn"])}')
    out.append("")
    return out


async def _sec_chess_ratings(db, user_id: int, date_from, date_to) -> list[str]:
    """Der Wertungsverlauf -- die Reihe, die es sonst nirgends gibt.

    Bestwerte (``is_best``) stehen in derselben Tabelle wie Tagesstaende, sind
    aber etwas anderes: „jemals“ gegen „heute“. Der Export sagt das in einer
    eigenen Spalte, statt beides als eine Kurve auszugeben.
    """
    werte = [user_id]
    bed = _chess_zeitfilter("r.taken_on", werte, date_from, date_to)
    rows = await db.fetch(
        "SELECT r.taken_on, a.platform, a.username, r.perf, r.rating, "
        "       r.rd, r.games, r.is_best "
        "  FROM chess_ratings r "
        "  JOIN chess_accounts a ON a.id = r.account_id "
        f" WHERE a.user_id=$1{bed} "
        " ORDER BY r.taken_on, a.platform, r.perf", *werte)
    out = ["# SEKTION: Schach - Wertungsverlauf",
           "Datum;Plattform;Konto;Disziplin;Wertung;Abweichung;Partien;Art"]
    for r in rows:
        out.append(
            f'{r["taken_on"].isoformat()};'
            f'{_f(PLATTFORM_LABEL.get(r["platform"], r["platform"] or ""))};'
            f'{_f(r["username"] or "")};{_f(r["perf"] or "")};{r["rating"]};'
            f'{"" if r["rd"] is None else r["rd"]};'
            f'{"" if r["games"] is None else r["games"]};'
            f'{_f("Bestwert" if r["is_best"] else "Tagesstand")}')
    out.append("")
    return out


# ---------------------------------------------------------------------------
# Notizen (v2.1.0)
# ---------------------------------------------------------------------------
async def _sec_notes(db, user_id: int) -> list[str]:
    """Notizen samt Text.

    Ein mehrzeiliger Text wird vom CSV-Feld auf eine Zeile gebracht -- das ist
    der Preis dieses Formats und gilt hier wie ueberall. Die Alternative waere,
    den Text wegzulassen, und dann exportiert man Ueberschriften.
    """
    rows = await db.fetch(
        "SELECT title, content, color, pinned, archived, tags, "
        "       created_at, updated_at "
        "  FROM notes WHERE user_id=$1 "
        " ORDER BY pinned DESC, updated_at DESC", user_id)
    out = ["# SEKTION: Notizen",
           "Titel;Text;Farbe;Angeheftet;Archiviert;Schlagworte;Angelegt;Geaendert"]
    for r in rows:
        out.append(
            f'{_f(r["title"] or "")};{_f(r["content"] or "")};'
            f'{_f(r["color"] or "default")};'
            f'{"ja" if r["pinned"] else "nein"};'
            f'{"ja" if r["archived"] else "nein"};'
            f'{_f(" ".join(r["tags"] or []))};'
            f'{r["created_at"].date().isoformat()};'
            f'{r["updated_at"].date().isoformat()}')
    out.append("")
    return out


# ---------- Die Verdichtungsgrenze (v2.8.0) ----------
#
# "Alles vor August 2026 monatlich" ist keine Aggregationsstufe, sondern eine
# Grenze quer durch die Zeit: davor will man eine Kurve, danach die Eintraege.
# Eine Datei, die beides kann, ist deshalb zwei Durchgaenge durch dieselben
# Sektionen mit verschiedenen Fenstern und Stufen -- und nicht eine neue Stufe
# neben `week` und `month`, die dann in jeder Sektion ein zweites Mal
# ausgerechnet werden muesste.

# Nur Sektionen, die BEIDES sind: datiert (ein Fenster greift) und
# zusammenfassbar (eine Stufe greift). Die Zugfolgen einer Partie lassen sich
# nicht verdichten, und Stammdaten haben kein Datum.
def _teilbare_sektionen() -> set:
    return {s["key"] for s in EXPORT_SECTIONS
            if s.get("dated") and s.get("aggregatable")}


def _mindestens_monat(stufe: str) -> str:
    """Die Stufe fuer den alten Teil. Groeber als der Monat bleibt groeber --
    wer jahresweise exportiert, will vor der Grenze keine feineren Zeilen."""
    return "year" if stufe == "year" else "month"


def _bloecke(zeilen: list[str]) -> list[list[str]]:
    """Zerlegt die Zeilen einer Sektion an ihren '# SEKTION:'-Ueberschriften.

    Eine Sektion ist nicht immer EIN Block: ``sparziel_meta`` bringt sechs
    (Ziele, Achievements, Wochenziele, Wuensche, Ideen, Trophaeen),
    ``ausgaben`` zwei (Bons und Positionen). Wer das uebersieht, haelt die
    zweite Ueberschrift fuer eine Datenzeile -- genau daran ging die erste
    Fassung von ``_hat_daten`` vorbei.
    """
    raus: list[list[str]] = []
    aktuell: list[str] = []
    for z in zeilen:
        if z.startswith("# SEKTION") and aktuell:
            raus.append(aktuell)
            aktuell = []
        aktuell.append(z)
    if aktuell:
        raus.append(aktuell)
    return raus


def _block_hat_daten(block: list[str]) -> bool:
    """Steht in diesem Block mehr als seine Ueberschrift und sein Spaltenkopf?"""
    kopf_gesehen = False
    for z in block:
        if not z.strip() or z.startswith("#"):
            continue
        if not kopf_gesehen:
            kopf_gesehen = True
            continue
        return True
    return False


def _block_titel(block: list[str]) -> str:
    """Die Ueberschrift eines Blocks, ohne '# SEKTION: ' und ohne Klammerzusatz.

    Sie benennt genauer als die Registerbeschriftung, was fehlt -- 'Blutzucker'
    statt 'Gesundheit', und bei ``sparziel_meta`` ueberhaupt erst etwas.
    """
    for z in block:
        if z.startswith("# SEKTION:"):
            titel = z[len("# SEKTION:"):].strip()
            return titel.split(" (")[0].split(";")[0].strip()
    return ""


def _leere_bloecke_aussortieren(zeilen: list[str]) -> tuple[list[str], list[str]]:
    """``(was bleibt, Titel dessen was leer war)``.

    Ein Block ohne eine einzige Datenzeile wird nicht abgedruckt. Er
    verschwindet aber nicht stillschweigend: sein Titel geht zurueck an den
    Kopf der Datei. Eine Luecke, die man spaeter nicht von 'nicht exportiert'
    unterscheiden kann, ist schlimmer als eine Ueberschrift ueber nichts.
    """
    behalten: list[str] = []
    leer: list[str] = []
    for block in _bloecke(zeilen):
        if _block_hat_daten(block):
            behalten.extend(block)
        else:
            titel = _block_titel(block)
            if titel:
                leer.append(titel)
    return behalten, leer


def _hat_daten(zeilen: list[str]) -> bool:
    """Steht in irgendeinem Block dieser Sektion mehr als der Kopf?"""
    return any(_block_hat_daten(b) for b in _bloecke(zeilen))


async def _build_sections(db, user, picked: list[str], date_from, date_to,
                          agg_map: dict, grenze: Optional[date] = None) -> list[tuple]:
    """Die gewaehlten Sektionen, bei gesetzter Grenze in zwei Teilen.

    Vor ``grenze`` wird monatsweise verdichtet, ab ``grenze`` gilt die
    gewaehlte Stufe. Beide Teile stehen in derselben Sektion untereinander --
    das Format traegt das, eine Sektion darf mehrere Bloecke haben.
    """
    if grenze is None or (date_from and date_from >= grenze):
        return await _build_sections_teil(db, user, picked, date_from, date_to, agg_map)
    if date_to and date_to < grenze:
        # Alles liegt vor der Grenze: ein Durchgang, monatsweise.
        alt_map = {g: _mindestens_monat(s) for g, s in agg_map.items()}
        return await _build_sections_teil(db, user, picked, date_from, date_to, alt_map)

    teilbar = _teilbare_sektionen()
    geteilt = [k for k in picked if k in teilbar]
    unteilbar = [k for k in picked if k not in teilbar]

    # Der unteilbare Rest sieht das ganze Fenster -- sonst stuende eine
    # Partie-Zugfolge zweimal unter zwei gleichen Ueberschriften.
    fertig: dict[str, list[str]] = {}
    if unteilbar:
        for key, zeilen in await _build_sections_teil(
                db, user, unteilbar, date_from, date_to, agg_map):
            fertig[key] = zeilen

    if geteilt:
        alt_map = {g: _mindestens_monat(s) for g, s in agg_map.items()}
        alt_bis = grenze - timedelta(days=1)
        if date_to and date_to < alt_bis:
            alt_bis = date_to
        alt = dict(await _build_sections_teil(
            db, user, geteilt, date_from, alt_bis, alt_map))
        neu_von = grenze if not date_from or date_from < grenze else date_from
        neu = dict(await _build_sections_teil(
            db, user, geteilt, neu_von, date_to, agg_map))
        for key in geteilt:
            teile = []
            if _hat_daten(alt.get(key, [])):
                teile.extend(alt[key])
            teile.extend(neu.get(key, []))
            fertig[key] = teile

    return [(k, fertig[k]) for k in picked if k in fertig]


async def _build_sections_teil(db, user, picked: list[str], date_from, date_to,
                               agg_map: dict) -> list[tuple]:
    """Baut die gewaehlten Sektionen einzeln. Getrennt gehalten, damit die
    Vorschau dieselben Zeilen zaehlen kann, die spaeter in der Datei stehen --
    eine zweite Schaetzformel waere garantiert irgendwann falsch."""
    want = set(picked)
    out: list[tuple] = []
    uid = user["id"]

    if "sparziel_meta" in want:
        out.append(("sparziel_meta", await _build_export_metadata(db, uid)))

    if "sparziel_log" in want:
        proto_all = await _sparziel_protocol_lines(db, uid)
        if date_from or date_to:
            proto = [ln for ln in proto_all
                     if _in_range(_date_from_iso_prefix(ln.split(";", 1)[0]),
                                  date_from, date_to)]
        else:
            proto = proto_all
        agg = agg_map.get("sparziel", "none")
        if _agg_on(agg):
            # v1.37.2: Bei Aggregation kompakte Perioden-Zusammenfassung statt
            # Einzel-Eintraege. Bei ~130 Checkins/Woche wird das sonst unlesbar.
            out.append(("sparziel_log", _sparziel_protocol_aggregated(proto, agg)))
        else:
            block = ["# SEKTION: Sparziel-Protokoll",
                     "Datum;Typ;Titel;Beschreibung;Periode;Betrag;Notiz"]
            block.extend(proto)
            block.append("")
            out.append(("sparziel_log", block))

    if "ausgaben" in want:
        out.append(("ausgaben", await _expenses_sections(
            db, uid, date_from=date_from, date_to=date_to,
            aggregate=agg_map.get("ausgaben", "none"))))

    if "expense_imports" in want:
        out.append(("expense_imports", await _sec_expense_imports(db, uid)))

    health_keys = [k for k in ("health_summary", "health_vitals", "health_bp",
                               "health_glucose", "health_sleep", "health_workouts")
                   if k in want]
    if health_keys:
        out.extend(await _health_section(
            db, uid, date_from=date_from, date_to=date_to,
            aggregate=agg_map.get("health", "none"), sections=health_keys))

    if "music_register" in want:
        out.append(("music_register", await _music_register_section(
            db, uid, date_from=date_from, date_to=date_to,
            aggregate=agg_map.get("musik", "none"))))

    if "music_imports" in want:
        out.append(("music_imports", await _music_imports_section(db, uid)))

    # Ernaehrung: zwei Protokolle mit Zeitraum, zwei Stammdaten-Sektionen ohne.
    # Beide tragen `aggregatable: True` in der Registry -- bis v2.6.0 bekamen
    # sie die gewaehlte Stufe trotzdem nicht, und "Pro Woche" liess die Datei
    # unveraendert. Eine Sektion, die eine Einstellung anbietet und ignoriert,
    # ist schlimmer als eine, die sie gar nicht hat.
    if "diary_log" in want:
        out.append(("diary_log", await _sec_diary(
            db, uid, date_from, date_to, agg_map.get("ernaehrung", "none"))))
    if "track_log" in want:
        out.append(("track_log", await _sec_track_log(
            db, uid, date_from, date_to, agg_map.get("ernaehrung", "none"))))
    if "food_stock" in want:
        out.append(("food_stock", await _sec_food_stock(db, uid)))
    if "food_dishes" in want:
        out.append(("food_dishes", await _sec_food_dishes(db, uid)))

    # Schach: alle drei mit Zeitraum. Die Wertungskurve ist datiert, obwohl
    # sie sich nicht zusammenfassen laesst -- ein Mittelwert ueber Wertungen
    # verschiedener Disziplinen waere eine Zahl ohne Bedeutung. Die Partien
    # dagegen fassen sich sehr wohl zusammen, und das ist die Form, in der man
    # sie meistens will: Anzahl und Wertungsaenderung je Disziplin.
    if "chess_games" in want:
        out.append(("chess_games",
                    await _sec_chess_games(db, uid, date_from, date_to,
                                           agg_map.get("schach", "none"))))
    if "chess_pgn" in want:
        out.append(("chess_pgn",
                    await _sec_chess_pgn(db, uid, date_from, date_to)))
    if "chess_ratings" in want:
        out.append(("chess_ratings",
                    await _sec_chess_ratings(db, uid, date_from, date_to)))

    if "notes" in want:
        out.append(("notes", await _sec_notes(db, uid)))
    return out


async def build_export_preview(
    db,
    user,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    aggregate: str = "none",
    sections: Optional[list] = None,
    aggregate_map: Optional[dict] = None,
    column_map: Optional[dict] = None,
    compact_before: Optional[date] = None,
    sample_lines: int = 40,
) -> dict:
    """Was der Export enthalten wuerde: je Sektion die Zeilenzahl und ihr
    Anteil, die Gesamtgroesse und die ersten Zeilen der echten Datei. Baut den
    Export dafuer wirklich -- eine Schaetzung waere schneller und falsch.

    Je Sektion kommen ausserdem ``columns`` mit: alle Spalten, die sie in
    DIESER Zusammenstellung hat. Die Oberflaeche baut ihre Spaltenauswahl
    daraus, statt eine zweite Liste zu fuehren, die bei jeder Aenderung an
    einer Sektion nachgepflegt werden muesste."""
    picked = clean_sections(sections)
    agg_map = clean_aggregate_map(aggregate_map, aggregate, date_from, date_to)
    cols = clean_column_map(column_map)
    built = await _build_sections(db, user, picked, date_from, date_to, agg_map,
                                  compact_before)

    header = _export_header(user, picked, date_from, date_to, agg_map, None,
                            compact_before)
    all_lines = list(header)
    labels = {s["key"]: s["label"] for s in EXPORT_SECTIONS}
    detail = []
    for key, section_lines in built:
        # Die Spaltenliste stammt aus den UNGEFILTERTEN Zeilen: sonst
        # verschwaende eine abgewaehlte Spalte aus der Auswahl und liesse
        # sich nie wieder anhaken.
        available = _section_columns(section_lines)
        shown = _filter_columns(section_lines, cols.get(key))
        text = _compact_timestamps("\n".join(shown))
        detail.append({
            "key": key,
            "label": labels.get(key, key),
            "rows": _count_rows(shown),
            "bytes": len(text.encode("utf-8")),
            "columns": available,
        })
        all_lines.extend(shown)

    csv = _compact_timestamps("\n".join(all_lines) + "\n")
    body = ("\ufeff" + csv).encode("utf-8")
    sample = csv.split("\n")[:max(1, sample_lines)]
    return {
        "sections": detail,
        "total_rows": sum(d["rows"] for d in detail),
        "bytes": len(body),
        "lines": csv.count("\n"),
        "aggregate": agg_map,
        "compact_before": compact_before.isoformat() if compact_before else None,
        "sample": "\n".join(sample),
        "truncated": csv.count("\n") > len(sample),
    }


# ---------- Auf eine Hoechstgroesse einstellen (v1.68.0) ----------
#
# "Die Datei soll unter 5 MB bleiben" ist die Frage, die man tatsaechlich
# hat -- "welche Aggregationsstufe brauche ich dafuer" ist nur der Umweg
# dorthin. Diese Funktion geht ihn.
#
# Gedreht wird ausschliesslich an der ZEIT. Sektionen oder Spalten
# stillschweigend zu streichen waere der billigere Weg zu einer kleinen Datei
# und der schlechtere: eine Luecke, die man ein Jahr spaeter nicht mehr von
# fehlenden Daten unterscheiden kann. Passt es selbst jaehrlich nicht, sagt
# das Ergebnis das -- und nennt die groesste Sektion, damit die Entscheidung
# beim Nutzer bleibt.
#
# Gemessen statt geschaetzt: jede Stufe wird wirklich gebaut. Eine Formel
# ueber Zeilenlaengen waere schneller und laege je nach Modul um Faktoren
# daneben. Damit das bezahlbar bleibt, ist die Suche binaer (~3 Bauten statt
# 5) und die Verfeinerung hart gedeckelt.

FIT_LADDER = ["none", "day", "week", "month", "year"]


def _aggregatable_groups(picked: list[str]) -> list[str]:
    """Die Gruppen, an denen Drehen ueberhaupt etwas bewirkt: nur solche mit
    mindestens einer gewaehlten, zusammenfassbaren Sektion. Stammdaten
    (Ziele, Achievements, Upload-Protokoll) aendern sich durch Aggregation
    nicht -- sie mitzudrehen kostete Bauten ohne Wirkung."""
    want = set(picked)
    out: list[str] = []
    for s in EXPORT_SECTIONS:
        if s["key"] in want and s.get("aggregatable") and s["group"] not in out:
            out.append(s["group"])
    return out


def _group_bytes(preview: dict) -> dict:
    """Byte-Anteil je Gruppe aus einer Vorschau."""
    of_section = {s["key"]: s["group"] for s in EXPORT_SECTIONS}
    out: dict[str, int] = {}
    for d in preview.get("sections", []):
        g = of_section.get(d["key"])
        if g:
            out[g] = out.get(g, 0) + int(d.get("bytes") or 0)
    return out


async def fit_export_to_size(
    db,
    user,
    max_bytes: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    sections: Optional[list] = None,
    aggregate_map: Optional[dict] = None,
    column_map: Optional[dict] = None,
    compact_before: Optional[date] = None,
    max_builds: int = 8,
) -> dict:
    """Sucht die FEINSTE Einstellung, mit der die Datei unter ``max_bytes``
    bleibt, und liefert sie samt fertiger Vorschau zurueck.

    ``fits`` sagt, ob das Ziel erreicht wurde; ``aggregate`` ist die gefundene
    Einstellung je Modul, ``builds`` die Zahl der dafuer gebauten Exporte.
    Die Oberflaeche uebernimmt ``aggregate`` in ihre Auswahlfelder -- der
    Nutzer sieht damit, was entschieden wurde, statt einer Blackbox.
    """
    picked = clean_sections(sections)
    base = clean_aggregate_map(aggregate_map, "none", date_from, date_to)
    groups = _aggregatable_groups(picked)
    builds = 0

    async def measure(agg: dict) -> dict:
        nonlocal builds
        builds += 1
        return await build_export_preview(
            db, user, date_from=date_from, date_to=date_to, sections=picked,
            aggregate_map=agg, column_map=column_map,
            compact_before=compact_before)

    def result(agg, preview, fits, note=""):
        biggest = max(preview.get("sections", []),
                      key=lambda s: s.get("bytes") or 0, default=None)
        return {
            "fits": fits,
            "max_bytes": max_bytes,
            "bytes": preview["bytes"],
            "aggregate": agg,
            "changed": {g: v for g, v in agg.items() if base.get(g) != v},
            "builds": builds,
            "note": note,
            "largest_section": ({"key": biggest["key"], "label": biggest["label"],
                                 "bytes": biggest["bytes"]} if biggest else None),
            "preview": preview,
        }

    # Vielleicht passt es schon. Das ist der haeufigste Fall und kostet
    # genau einen Bau -- danach ist auch klar, wie weit es ueberhaupt weg ist.
    current = await measure(base)
    if current["bytes"] <= max_bytes:
        return result(base, current, True, "Die aktuelle Zusammenstellung passt bereits.")

    if not groups:
        return result(base, current, False,
                      "Hier laesst sich nichts zusammenfassen: die gewaehlten "
                      "Sektionen sind Stammdaten. Kleiner wird die Datei nur "
                      "ueber einen kuerzeren Zeitraum oder weniger Sektionen.")

    # ---- Binaere Suche auf der Leiter, gleiche Stufe fuer alle Gruppen ----
    # Groeber ist immer kleiner, die Leiter ist also monoton -- damit genuegt
    # eine binaere Suche und es braucht keine fuenf Bauten.
    lo, hi = 1, len(FIT_LADDER) - 1
    best: Optional[tuple] = None
    coarsest: Optional[dict] = None
    while lo <= hi and builds < max_builds:
        mid = (lo + hi) // 2
        agg = dict(base)
        for g in groups:
            agg[g] = FIT_LADDER[mid]
        preview = await measure(agg)
        if mid == len(FIT_LADDER) - 1:
            coarsest = preview
        if preview["bytes"] <= max_bytes:
            best = (mid, agg, preview)
            hi = mid - 1
        else:
            lo = mid + 1

    if best is None:
        # Selbst jahresweise zu gross. Ehrlich sagen statt heimlich kuerzen.
        agg = dict(base)
        for g in groups:
            agg[g] = "year"
        preview = coarsest if coarsest else await measure(agg)
        return result(agg, preview, False,
                      "Auch jahresweise bleibt die Datei ueber der Grenze. "
                      "Kleiner wird sie nur noch, indem du Sektionen abwaehlst, "
                      "Spalten reduzierst oder den Zeitraum enger ziehst.")

    level, agg, preview = best

    # ---- Verfeinern: kleine Module duerfen genauer bleiben ----
    # Die eine grobe Stufe fuer alle ist selten die beste Antwort -- meist
    # traegt EIN Modul die Datei, und die uebrigen koennen genau bleiben.
    #
    # Reihum, eine Stufe je Durchgang, kleinste Gruppe zuerst: sonst
    # verbraucht das erste Modul das ganze Bau-Budget und die uebrigen
    # bleiben grob, obwohl sie fast nichts kosten. Wer einmal nicht mehr
    # passt, ist fertig -- feiner wird er danach auch nicht.
    shares = _group_bytes(preview)
    # Eine Gruppe, die nichts zur Datei beitraegt, braucht keine Messung: sie
    # feiner zu stellen kann die Datei nicht groesser machen. Sie bekommt
    # sofort die Stufe zurueck, die der Nutzer wollte, und kostet keinen Bau.
    # Ohne das verbraucht ein Modul, in dem gar nichts liegt, das Budget, und
    # die Module mit Daten bleiben grob -- beim Hinzukommen von Schach und
    # Notizen (v2.1.0) ist genau das passiert.
    order = []
    for g in groups:
        if shares.get(g, 0) > 0:
            order.append(g)
        else:
            agg[g] = base.get(g, "none")
    order.sort(key=lambda g: shares.get(g, 0))
    done: set = set()
    while builds < max_builds and len(done) < len(order):
        improved = False
        for g in order:
            if g in done or builds >= max_builds:
                continue
            idx = FIT_LADDER.index(agg[g])
            # Feiner als vom Nutzer gewuenscht wird nie -- die Einstellung
            # soll seiner Wahl entgegenkommen, sie nicht ueberschreiben.
            if idx <= FIT_LADDER.index(base.get(g, "none")) or idx == 0:
                done.add(g)
                continue
            probe = dict(agg)
            probe[g] = FIT_LADDER[idx - 1]
            got = await measure(probe)
            if got["bytes"] > max_bytes:
                done.add(g)
                continue
            agg, preview = probe, got
            improved = True
        if not improved:
            break

    # Fuer den Vermerk zaehlen nur die Gruppen, die wirklich etwas beitragen:
    # ein Modul ohne Daten wuerde sonst behaupten, es sei zusammengefasst
    # worden.
    massgeblich = order or groups
    same = all(agg[g] == agg[massgeblich[0]] for g in massgeblich)
    note = ("Zeit zusammengefasst auf %s." % _period_adverb(agg[massgeblich[0]])
            if same else "Je Modul die feinste Stufe, die noch passt.")
    return result(agg, preview, True, note)


async def build_health_export_csv(db, user) -> str:
    """Dedizierter Health-CSV-Export (nur Gesundheit). Nutzt exakt
    dieselben Sektions-Helfer wie der Gesamt-Export."""
    lines: list[str] = []
    export_dt = datetime.now(timezone.utc).isoformat()
    lines.append(
        f"# Vexbob Gesundheits-Export;user={_f(user['username'])};generated_at={export_dt}")
    lines.append(
        "# Diese Datei enthaelt alle Gesundheitsdaten des Users: eine "
        "Zusammenfassung, Vitalwerte-Zeitserien im Wide-Format (eine "
        "Zeile pro Tag, Metriken als Spalten), Blutdruck, Blutzucker, "
        "Schlaf-Naechte inkl. Phasen und Workouts inkl. Zusatzmetriken.")
    lines.append(
        "# Konvention: Zeitstempel sind UTC im Format YYYY-MM-DDTHH:MM:SSZ. "
        "Zahlen nutzen Punkt-Dezimal.")
    lines.append("")
    for _key, section_lines in await _health_section(db, user["id"]):
        lines.extend(section_lines)
    return _compact_timestamps("\n".join(lines) + "\n")


# ---------- Ausgaben (Bons + Positionen getrennt) ----------

async def _expenses_sections(
    db,
    user_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    aggregate: str = "none",
) -> list[str]:
    out: list[str] = []
    # Dynamisches WHERE fuer den Zeitraum-Filter. asyncpg-Positional-Parameter,
    # damit ohne Filter (default None) das SQL identisch zum alten Verhalten
    # bleibt und der Query-Planner denselben Plan nutzt.
    exp_where = "WHERE e.user_id=$1"
    exp_params: list = [user_id]
    if date_from:
        exp_params.append(date_from)
        exp_where += f" AND e.purchase_date >= ${len(exp_params)}"
    if date_to:
        exp_params.append(date_to)
        exp_where += f" AND e.purchase_date <= ${len(exp_params)}"

    rows = await db.fetch(
        f"""SELECT e.id, e.purchase_date, e.total_amount, e.payment_method,
                   e.expense_type, e.note, s.name AS store_name,
                   COALESCE(e.source, 'receipt') AS source, e.src_payee,
                   e.src_category, e.src_subcategory
            FROM expenses e LEFT JOIN stores s ON s.id=e.store_id
            {exp_where} ORDER BY e.purchase_date, e.id""",
        *exp_params)

    # -------- Aggregations-Modus: kompakte Wochen-/Monats-Summary --------
    # v1.40.1: Zusaetzlich zur Perioden-Summe steht jeder Einkauf einzeln in
    # der CSV -- ohne Einzelpositionen, aber mit Kategorien-Aufschluesselung.
    # Die reine Wochensumme sagt nichts darueber, wofuer das Geld ausgegeben
    # wurde; die Positionsliste macht lange Zeitraeume dagegen unlesbar.
    if _agg_on(aggregate) and rows:
        out = _expenses_aggregated_section(rows, aggregate)
        out.extend(await _expenses_compact_bons_section(db, user_id, rows, aggregate))
        return out

    # -------- Standard-Modus: Bons + Positionen (Item-Query erst hier) --------
    # Nur die Positionen der oben gefilterten Bons holen, damit sie zu den
    # Bons passen. WHERE user_id=$1 AND expense_id = ANY($2::int[]).
    expense_ids = [r["id"] for r in rows]
    if expense_ids:
        item_rows = await db.fetch(
            """SELECT ei.expense_id, ei.description, ei.quantity, ei.quantity_unit,
                      ei.unit_price, ei.total_price, ei.is_reduced, ei.original_price,
                      c.name AS category_name
               FROM expense_items ei LEFT JOIN expense_categories c ON c.id=ei.category_id
               WHERE ei.user_id=$1 AND ei.expense_id = ANY($2::int[])
               ORDER BY ei.expense_id, ei.sort_order NULLS LAST, ei.id""",
            user_id, expense_ids)
    else:
        item_rows = []

    # Bons (ein Eintrag pro Beleg, Kopfdaten NICHT mehr pro Position wiederholt)
    out.append(
        "# SEKTION: Ausgaben - Bons (ein Eintrag pro Beleg). Die Spalte "
        "'Gesamt (EUR)' ist der Betrag des ganzen Belegs; seine "
        "Einzelposten stehen in der naechsten Sektion und summieren sich "
        "wieder darauf. ACHTUNG BEIM RECHNEN: Bons UND Positionen zu "
        "addieren zaehlt jeden Euro doppelt -- fuer eine Ausgabensumme "
        "gilt DIESE Sektion, fuer eine Auswertung nach Artikeln die "
        "naechste. Verknuepft sind sie ueber expense_id.")
    out.append("expense_id;Datum;Laden;Typ;Gesamt (EUR);Zahlungsart;Notiz;"
               "Herkunft;Empfaenger (Bank);Kategorie (Bank);Unterkategorie (Bank)")
    for r in rows:
        note = _f((r["note"] or "").replace("\n", " ").replace("\r", " ")) if r["note"] else ""
        out.append(
            f'{r["id"]};'
            f'{r["purchase_date"].isoformat() if r["purchase_date"] else ""};'
            f'{_f(r["store_name"] or "")};{_f(r["expense_type"] or "")};'
            f'{_euro_de(r["total_amount"])};{_f(r["payment_method"] or "")};{note};'
            f'{HERKUNFT.get(r["source"], r["source"] or "")};'
            f'{_f(r["src_payee"] or "")};{_f(r["src_category"] or "")};'
            f'{_f(r["src_subcategory"] or "")}'
        )
    out.append("")

    # Bon-Positionen (expense_id verweist auf die Bon-Sektion oben)
    out.append(
        "# SEKTION: Ausgaben - Bon-Positionen (die Einzelposten der Bons; "
        "expense_id verweist auf die vorige Sektion). Ihre Summe je Beleg "
        "ergibt wieder dessen 'Gesamt (EUR)' -- nicht zu den Bons "
        "addieren.")
    out.append(
        "expense_id;Position;Menge;Einheit;Einzelpreis (EUR);"
        "Positionspreis (EUR);Original-Preis (EUR);Reduziert;Kategorie")
    for it in item_rows:
        out.append(
            f'{it["expense_id"]};{_f(it["description"] or "")};'
            f'{_euro_de(it["quantity"])};{_f(it["quantity_unit"] or "")};'
            f'{_euro_de(it["unit_price"])};{_euro_de(it["total_price"])};'
            f'{_euro_de(it["original_price"])};'
            f'{"ja" if it["is_reduced"] else ""};{_f(it["category_name"] or "")}'
        )
    out.append("")
    return out


# ---------- Ausgaben-Aggregation (v1.37.1) ----------

def _expenses_aggregated_section(rows, aggregate: str) -> list[str]:
    """Fasst Bons zu Wochen- oder Monats-Buckets zusammen.

    Ausgabe: eine kompakte Sektion statt Bons + Positionen. Enthaelt pro
    Periode: Anzahl Bons, Summe (EUR), durchschnittlicher Bon,
    Anzahl unterschiedlicher Laeden, Aufschluesselung nach Typ.
    Bei einem Jahres-Export mit ~1000 Bons reduziert das die Ausgaben-
    Sektion von ~1000 auf ~12-52 Zeilen -- massiv besser lesbar.
    """
    label = _period_label(aggregate)
    prefix = _period_prefix(aggregate)
    buckets: dict[str, dict] = {}
    for r in rows:
        pd = r["purchase_date"]
        if not pd:
            continue
        key = _period_key(pd, aggregate)
        b = buckets.setdefault(key, {
            "count": 0, "sum": 0.0, "stores": set(), "types": {}, "min_d": pd, "max_d": pd,
        })
        b["count"] += 1
        try:
            b["sum"] += float(r["total_amount"] or 0)
        except (TypeError, ValueError):
            pass
        if r["store_name"]:
            b["stores"].add(r["store_name"])
        t = r["expense_type"] or "other"
        b["types"][t] = b["types"].get(t, 0) + 1
        if pd < b["min_d"]:
            b["min_d"] = pd
        if pd > b["max_d"]:
            b["max_d"] = pd

    out: list[str] = []
    out.append(
        f"# SEKTION: Ausgaben - {prefix}-Zusammenfassung (aggregiert). "
        "ACHTUNG BEIM RECHNEN: die Summe einer Zeile enthaelt genau die "
        "Bons, die in 'Ausgaben - Bons kompakt' NOCH EINMAL einzeln "
        "stehen. Das ist dieselbe Ausgabe auf zwei Stufen, keine zweite "
        "Ausgabe -- wer beide Sektionen addiert, zaehlt jeden Euro "
        "doppelt. Die Einzelpositionen der Bons bleiben in diesem Modus "
        "bewusst weg, damit lange Zeitraeume kompakt bleiben.")
    out.append(
        f"{label};Von;Bis;Anzahl Bons;Summe (EUR);"
        "Durchschnitt Bon (EUR);Verschiedene Laeden;Typen-Aufteilung")
    for key in sorted(buckets.keys()):
        b = buckets[key]
        avg = b["sum"] / b["count"] if b["count"] else 0.0
        types_str = ", ".join(
            f"{t}:{n}" for t, n in sorted(b["types"].items(), key=lambda x: -x[1])
        )
        out.append(
            f'{key};{b["min_d"].isoformat()};{b["max_d"].isoformat()};'
            f'{b["count"]};{_euro_de(b["sum"])};{_euro_de(avg)};'
            f'{len(b["stores"])};{_f(types_str)}'
        )
    out.append("")
    return out


async def _expenses_compact_bons_section(db, user_id: int, rows, aggregate: str) -> list[str]:
    """Ein Eintrag je Einkauf - ohne Einzelpositionen, aber mit Kategorien.

    Ergaenzt im Aggregations-Modus die reine Perioden-Summe: pro Bon Datum,
    Laden, Typ, Anzahl Positionen, Gesamtbetrag und welche Produktkategorien
    mit wievielen Positionen und welchem Betrag drin waren. Damit bleibt
    erkennbar, WOFUER das Geld einer Woche ausgegeben wurde, ohne die
    komplette Positionsliste (bei einem Jahr schnell >10.000 Zeilen)
    mitzuschleppen: ~1000 Bons statt ~15.000 Positionszeilen.

    Die Perioden-Spalte (``Woche``/``Monat``) wiederholt den Schluessel aus
    der Zusammenfassung, damit sich beide Sektionen in Excel/Sheets ueber ein
    gemeinsames Feld verknuepfen oder pivotieren lassen.
    """
    label = _period_label(aggregate)
    expense_ids = [r["id"] for r in rows]
    cat_rows = []
    if expense_ids:
        cat_rows = await db.fetch(
            """SELECT ei.expense_id,
                      COALESCE(c.name, 'Ohne Kategorie') AS category_name,
                      COUNT(*)                            AS item_count,
                      COALESCE(SUM(ei.total_price), 0)    AS category_sum
               FROM expense_items ei
               LEFT JOIN expense_categories c ON c.id=ei.category_id
               WHERE ei.user_id=$1 AND ei.expense_id = ANY($2::int[])
               GROUP BY ei.expense_id, COALESCE(c.name, 'Ohne Kategorie')""",
            user_id, expense_ids)

    per_expense: dict[int, list] = {}
    for cr in cat_rows:
        per_expense.setdefault(cr["expense_id"], []).append(cr)

    out: list[str] = []
    out.append(
        "# SEKTION: Ausgaben - Bons kompakt (ein Eintrag pro Einkauf, ohne "
        "Einzelpositionen). Das sind die Einzelposten der Perioden-Summen "
        "aus der vorigen Sektion -- dieselben Betraege, nur feiner. NICHT "
        "zu ihnen addieren. Kategorien-Spalte: 'Kategorie:Anzahl/Betrag', "
        "mehrere Kategorien mit ' | ' getrennt, absteigend nach Betrag.")
    out.append(
        f"{label};Datum;Laden;Typ;Anzahl Positionen;Gesamt (EUR);"
        "Kategorien (Anzahl/EUR)")
    for r in rows:
        pd = r["purchase_date"]
        cats = per_expense.get(r["id"], [])
        # Bons ohne erfasste Positionen (Schnelleingabe) bleiben drin - dort
        # zaehlt nur der Gesamtbetrag, die Kategorie-Spalte ist leer.
        item_count = sum(int(c["item_count"] or 0) for c in cats)
        cats_sorted = sorted(cats, key=lambda c: (-float(c["category_sum"] or 0),
                                                  c["category_name"] or ""))
        cats_str = " | ".join(
            f'{c["category_name"]}:{int(c["item_count"] or 0)}/{_euro_de(c["category_sum"])}'
            for c in cats_sorted)
        out.append(
            f'{_period_key(pd, aggregate) if pd else ""};'
            f'{pd.isoformat() if pd else ""};'
            f'{_f(r["store_name"] or "")};{_f(r["expense_type"] or "")};'
            f'{item_count};{_euro_de(r["total_amount"])};{_f(cats_str)}'
        )
    out.append("")
    return out


# ---------- Sparziel-Protokoll-Aggregation (v1.37.2) ----------

def _sparziel_protocol_aggregated(proto_lines: list[str], aggregate: str) -> list[str]:
    """Aggregiert die vom Helper gebauten Protokoll-Zeilen zu Wochen/Monaten.

    Format der Eingabe-Zeilen (aus helpers._sparziel_protocol_lines):
      ``Datum;Typ;Titel;Beschreibung;Periode;Betrag;Notiz``

    Ausgabe pro Periode:
      Anzahl Check-ins, Anzahl Meilensteine, Anzahl Streak-Bonus,
      Summe ausgezahlter Belohnungen, Titel der erreichten Meilensteine.
    """
    prefix = _period_prefix(aggregate)
    label = _period_label(aggregate)
    buckets: dict[str, dict] = {}
    for ln in proto_lines:
        parts = ln.split(";")
        if len(parts) < 6:
            continue
        d = _date_from_iso_prefix(parts[0])
        if d is None:
            continue
        key = _period_key(d, aggregate)
        b = buckets.setdefault(key, {
            "checkins": 0, "milestones": 0, "streaks": 0, "transfers": 0,
            "initials": 0, "reward_sum": 0.0, "transfer_sum": 0.0,
            "milestone_titles": [],
        })
        row_type = parts[1]
        title = parts[2].strip('"') if len(parts) > 2 else ""
        try:
            amount = float(parts[5] or 0)
        except (TypeError, ValueError):
            amount = 0.0

        if row_type == "checkin":
            b["checkins"] += 1
            if amount > 0:                       # Wochenziel-Auszahlung
                b["reward_sum"] += amount
        elif row_type == "milestone":
            b["milestones"] += 1
            b["reward_sum"] += amount
            if title:
                b["milestone_titles"].append(title)
        elif row_type == "streak_bonus":
            b["streaks"] += 1
            b["reward_sum"] += amount
        elif row_type == "transfer":
            b["transfers"] += 1
            b["transfer_sum"] += amount
        elif row_type == "initial":
            b["initials"] += 1
            b["transfer_sum"] += amount

    out: list[str] = []
    out.append(
        f"# SEKTION: Sparziel-Protokoll - {prefix}-Zusammenfassung (aggregiert; "
        "Einzel-Eintraege sind in diesem Aggregations-Modus bewusst NICHT enthalten)")
    out.append(
        f"{label};Anzahl Check-ins;Anzahl Meilensteine;Streak-Boni;"
        "Transfers;Summe Belohnungen (EUR);Transfer-Summe (EUR);"
        "Erreichte Meilensteine")
    for key in sorted(buckets.keys()):
        b = buckets[key]
        titles = ", ".join(sorted(set(b["milestone_titles"])))
        out.append(
            f'{key};{b["checkins"]};{b["milestones"]};{b["streaks"]};'
            f'{b["transfers"] + b["initials"]};{_euro_de(b["reward_sum"])};'
            f'{_euro_de(b["transfer_sum"])};{_f(titles)}'
        )
    out.append("")
    return out


# ---------- Gesundheit ----------

async def _health_summary_section(db, user_id: int) -> list[str]:
    """Kompakte Kennzahlen als eigene erste Sektion, damit man beim
    Oeffnen der CSV sofort einen Ueberblick hat."""
    out: list[str] = ["# SEKTION: Gesundheit - Zusammenfassung",
                       "Kennzahl;Wert"]
    metric_cnt = int(await db.fetchval(
        "SELECT COUNT(*) FROM health_metric_samples WHERE user_id=$1", user_id) or 0)
    bp_cnt = int(await db.fetchval(
        "SELECT COUNT(*) FROM health_blood_pressure WHERE user_id=$1", user_id) or 0)
    gl_cnt = int(await db.fetchval(
        "SELECT COUNT(*) FROM health_blood_glucose WHERE user_id=$1", user_id) or 0)
    sl_cnt = int(await db.fetchval(
        "SELECT COUNT(*) FROM health_sleep WHERE user_id=$1", user_id) or 0)
    wk_cnt = int(await db.fetchval(
        "SELECT COUNT(*) FROM health_workouts WHERE user_id=$1", user_id) or 0)
    date_range = await db.fetchrow(
        "SELECT MIN(sample_date) AS mn, MAX(sample_date) AS mx "
        "FROM health_metric_samples WHERE user_id=$1", user_id)
    mn = date_range["mn"].isoformat() if date_range and date_range["mn"] else ""
    mx = date_range["mx"].isoformat() if date_range and date_range["mx"] else ""
    out.append(f"Zeitraum Vitalwerte;{mn} bis {mx}" if mn else "Zeitraum Vitalwerte;(keine Daten)")
    out.append(f"Vitalwert-Datenpunkte;{metric_cnt}")
    out.append(f"Blutdruck-Messungen;{bp_cnt}")
    out.append(f"Blutzucker-Messungen;{gl_cnt}")
    out.append(f"Schlaf-Naechte;{sl_cnt}")
    out.append(f"Workouts;{wk_cnt}")
    last_rows = await db.fetch(
        """SELECT DISTINCT ON (metric_type)
                  metric_type, recorded_at, qty, unit
             FROM health_metric_samples
            WHERE user_id=$1
            ORDER BY metric_type, recorded_at DESC""", user_id)
    for r in last_rows:
        unit = (r["unit"] or "").strip()
        unit_str = f" {unit}" if unit else ""
        ts = r["recorded_at"].isoformat() if r["recorded_at"] else ""
        out.append(
            f'Letzter Wert: {r["metric_type"]};'
            f'{_num(r["qty"])}{unit_str} @ {ts}'
        )
    out.append("")
    return out


async def _health_vitals_wide_section(
    db,
    user_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    aggregate: str = "none",
) -> list[str]:
    """Vitalwerte im Wide-Format: eine Zeile pro Tag, Metriken als
    Spalten. Fuer Metriken mit Aggregaten (min/max) werden zusaetzliche
    ``<metrik>_min`` / ``<metrik>_max`` Spalten angelegt - aber nur wenn
    es tatsaechlich Aggregat-Daten gibt.

    Effekt: ~50 % kleiner als das alte Long-Format, weil weder Datum
    noch Metrik-Name pro Wert wiederholt werden. Fuer eine KI zusaetzlich
    leichter lesbar, weil Tages-Zusammenhaenge in einer Zeile sichtbar
    sind (z. B. Zusammenhang steps <-> weight <-> hrv am selben Tag).

    v1.37.1: Zeitraum-Filter via ``date_from``/``date_to`` (auf
    ``recorded_at::date``) und Wochen-/Monats-Aggregation."""
    where = "WHERE user_id=$1"
    params: list = [user_id]
    if date_from:
        params.append(date_from)
        where += f" AND recorded_at::date >= ${len(params)}"
    if date_to:
        params.append(date_to)
        where += f" AND recorded_at::date <= ${len(params)}"
    rows = await db.fetch(
        f"SELECT metric_type, recorded_at, qty, min_value, max_value, "
        f"avg_value, unit, source FROM health_metric_samples "
        f"{where} ORDER BY recorded_at, metric_type",
        *params)

    if not rows:
        return ["# SEKTION: Gesundheit - Vitalwerte (taeglich, wide format)",
                "Datum", ""]

    metrics: set[str] = set()
    has_aggregate: set[str] = set()
    units: dict[str, set[str]] = {}
    sources: set[str] = set()
    per_day: dict[str, dict[str, dict]] = {}

    for r in rows:
        m = r["metric_type"]
        if not m:
            continue
        metrics.add(m)
        if r["min_value"] is not None or r["max_value"] is not None:
            has_aggregate.add(m)
        u = (r["unit"] or "").strip()
        if u:
            units.setdefault(m, set()).add(u)
        s = (r["source"] or "").strip()
        if s:
            sources.add(s)
        rec = r["recorded_at"]
        if rec is None:
            continue
        # Vitalwerte sind Tageswerte -> Key ist nur das Datum
        day = rec.date().isoformat()
        cell = per_day.setdefault(day, {}).setdefault(m, {})
        cell["qty"] = r["qty"]
        if r["min_value"] is not None:
            cell["min"] = r["min_value"]
        if r["max_value"] is not None:
            cell["max"] = r["max_value"]

    metrics_sorted = sorted(metrics)

    out: list[str] = []
    header_first_col = "Datum"
    period_label = ""
    # v1.37.1: Optionale Wochen-/Monats-Aggregation.
    # Wir aggregieren pro Metrik die Tageswerte per Mittelwert (fuer Vitals
    # das sinnvollste Default), zusaetzlich min/max ueber die Periode.
    aggregated_per_period: dict[str, dict[str, dict]] = {}
    if _agg_on(aggregate):
        period_label = _period_label(aggregate)
        header_first_col = period_label
        for day_str, day_data in per_day.items():
            try:
                d = date.fromisoformat(day_str)
            except ValueError:
                continue
            key = _period_key(d, aggregate)
            bucket = aggregated_per_period.setdefault(key, {})
            for m, cell in day_data.items():
                q = cell.get("qty")
                if q is None:
                    continue
                try:
                    q = float(q)
                except (TypeError, ValueError):
                    continue
                mb = bucket.setdefault(m, {"sum": 0.0, "n": 0, "min": q, "max": q})
                mb["sum"] += q
                mb["n"] += 1
                if q < mb["min"]:
                    mb["min"] = q
                if q > mb["max"]:
                    mb["max"] = q

    if _agg_on(aggregate):
        out.append(
            f"# SEKTION: Gesundheit - Vitalwerte ({_period_adverb(aggregate)} "
            "aggregiert; pro Metrik durchschnittlicher Tageswert; _min/_max "
            "ueber alle Tage der Periode)")
    else:
        out.append(
            "# SEKTION: Gesundheit - Vitalwerte (taeglich, wide format; eine "
            "Zeile pro Tag, Metriken als Spalten)")
    # Konstante Metadaten in Kommentarzeilen, nicht in jede Datenzeile
    if len(sources) == 1:
        out.append(f"# Quelle aller Vitalwerte: {next(iter(sources))}")
    elif sources:
        out.append(f"# Quellen: {', '.join(sorted(sources))}")
    unit_notes = [
        f"{m}={next(iter(us))}" for m, us in sorted(units.items()) if len(us) == 1
    ]
    if unit_notes:
        out.append(f"# Einheiten: {'; '.join(unit_notes)}")

    header_cols = [header_first_col]
    for m in metrics_sorted:
        header_cols.append(m)
        # Im Aggregations-Modus haben ALLE Metriken min/max (ueber die
        # Periode berechnet), nicht nur die urspruenglich aggregierten.
        if _agg_on(aggregate) or m in has_aggregate:
            header_cols.append(f"{m}_min")
            header_cols.append(f"{m}_max")
    out.append(";".join(header_cols))

    if _agg_on(aggregate):
        for key in sorted(aggregated_per_period.keys()):
            row_cells = [key]
            bucket = aggregated_per_period[key]
            for m in metrics_sorted:
                mb = bucket.get(m)
                if mb and mb["n"]:
                    row_cells.append(_num(mb["sum"] / mb["n"]))
                    row_cells.append(_num(mb["min"]))
                    row_cells.append(_num(mb["max"]))
                else:
                    row_cells.append("")
                    row_cells.append("")
                    row_cells.append("")
            out.append(";".join(row_cells))
    else:
        for day in sorted(per_day.keys()):
            row_cells = [day]
            day_data = per_day[day]
            for m in metrics_sorted:
                cell = day_data.get(m, {})
                row_cells.append(_num(cell.get("qty")))
                if m in has_aggregate:
                    row_cells.append(_num(cell.get("min")))
                    row_cells.append(_num(cell.get("max")))
            out.append(";".join(row_cells))
    out.append("")
    return out


def _build_range_where(col: str, base_param_start: int, date_from, date_to):
    """Baut ein dynamisches ' AND col::date ...' Suffix + Parameter-Liste.
    ``col`` ist der DB-Spaltenname (z. B. ``recorded_at`` oder ``sleep_date``);
    ``base_param_start`` ist der bereits belegte Parameter-Index (typisch 1
    fuer user_id), das erste Datum wird also $2, das zweite $3.
    """
    where = ""
    params: list = []
    if date_from:
        params.append(date_from)
        where += f" AND {col}::date >= ${base_param_start + len(params)}"
    if date_to:
        params.append(date_to)
        where += f" AND {col}::date <= ${base_param_start + len(params)}"
    return where, params


# ---------- Health-Aggregation (v1.37.2) ----------

def _bp_aggregated(rows, aggregate: str) -> list[str]:
    """Blutdruck pro Woche/Monat: Ø + min/max fuer sys/dia, Anzahl Messungen."""
    prefix = _period_prefix(aggregate); label = _period_label(aggregate)
    buckets: dict[str, dict] = {}
    for r in rows:
        rec = r["recorded_at"]
        if not rec: continue
        key = _period_key(rec.date(), aggregate)
        b = buckets.setdefault(key, {"n": 0, "sys": [], "dia": [], "unit": ""})
        b["n"] += 1
        if r["systolic"] is not None: b["sys"].append(float(r["systolic"]))
        if r["diastolic"] is not None: b["dia"].append(float(r["diastolic"]))
        if r["unit"]: b["unit"] = r["unit"].strip()
    out = [f"# SEKTION: Gesundheit - Blutdruck ({_period_adverb(aggregate)} aggregiert)",
           f"{label};Anzahl Messungen;Systolisch Ø;Systolisch min;Systolisch max;"
           "Diastolisch Ø;Diastolisch min;Diastolisch max;Einheit"]
    for key in sorted(buckets.keys()):
        b = buckets[key]
        s, d = b["sys"], b["dia"]
        out.append(
            f'{key};{b["n"]};'
            f'{_num(sum(s)/len(s)) if s else ""};{_num(min(s)) if s else ""};{_num(max(s)) if s else ""};'
            f'{_num(sum(d)/len(d)) if d else ""};{_num(min(d)) if d else ""};{_num(max(d)) if d else ""};'
            f'{b["unit"]}'
        )
    out.append("")
    return out


def _gl_aggregated(rows, aggregate: str) -> list[str]:
    """Blutzucker pro Woche/Monat: Ø + min/max, Anzahl Messungen."""
    prefix = _period_prefix(aggregate); label = _period_label(aggregate)
    buckets: dict[str, dict] = {}
    for r in rows:
        rec = r["recorded_at"]
        if not rec: continue
        key = _period_key(rec.date(), aggregate)
        b = buckets.setdefault(key, {"n": 0, "vals": [], "unit": ""})
        b["n"] += 1
        if r["value"] is not None:
            try: b["vals"].append(float(r["value"]))
            except (TypeError, ValueError): pass
        if r["unit"]: b["unit"] = r["unit"].strip()
    out = [f"# SEKTION: Gesundheit - Blutzucker ({_period_adverb(aggregate)} aggregiert)",
           f"{label};Anzahl Messungen;Wert Ø;Wert min;Wert max;Einheit"]
    for key in sorted(buckets.keys()):
        b = buckets[key]; v = b["vals"]
        out.append(
            f'{key};{b["n"]};'
            f'{_num(sum(v)/len(v)) if v else ""};{_num(min(v)) if v else ""};{_num(max(v)) if v else ""};'
            f'{b["unit"]}'
        )
    out.append("")
    return out


def _sleep_aggregated(rows, aggregate: str) -> list[str]:
    """Schlaf pro Woche/Monat: Anzahl Naechte, Ø-Phasen (in Minuten)."""
    label = _period_label(aggregate)
    buckets: dict[str, dict] = {}
    keys_num = ("in_bed_minutes", "asleep_minutes", "core_minutes",
                "deep_minutes", "rem_minutes", "awake_minutes")
    for r in rows:
        d = r["sleep_date"]
        if not d: continue
        key = _period_key(d, aggregate)
        b = buckets.setdefault(key, {"n": 0, **{k: [] for k in keys_num}})
        b["n"] += 1
        for k in keys_num:
            v = r[k]
            if v is None: continue
            try: b[k].append(float(v))
            except (TypeError, ValueError): pass
    out = [f"# SEKTION: Gesundheit - Schlaf ({_period_adverb(aggregate)} aggregiert; "
           "Ø-Phasen in Minuten pro Nacht der Periode)",
           f"{label};Anzahl Naechte;Im Bett Ø;Geschlafen Ø;Core Ø;Deep Ø;REM Ø;Wach Ø"]
    for key in sorted(buckets.keys()):
        b = buckets[key]
        def avg(k):
            xs = b[k]
            return _num(sum(xs)/len(xs)) if xs else ""
        out.append(
            f'{key};{b["n"]};{avg("in_bed_minutes")};{avg("asleep_minutes")};'
            f'{avg("core_minutes")};{avg("deep_minutes")};{avg("rem_minutes")};{avg("awake_minutes")}'
        )
    out.append("")
    return out


def _workouts_aggregated(rows, aggregate: str) -> list[str]:
    """Workouts pro Woche/Monat: Anzahl, Summen Dauer/Energie/Distanz, Typ-Split."""
    label = _period_label(aggregate)
    buckets: dict[str, dict] = {}
    for r in rows:
        s = r["start_at"]
        if not s: continue
        key = _period_key(s.date(), aggregate)
        b = buckets.setdefault(key, {
            "n": 0, "dur": 0.0, "kcal_act": 0.0, "kcal_tot": 0.0,
            "dist": 0.0, "elev": 0.0, "types": {},
        })
        b["n"] += 1
        for tgt, col in (("dur", "duration_min"), ("kcal_act", "active_energy_kcal"),
                          ("kcal_tot", "total_energy_kcal"), ("dist", "distance_m"),
                          ("elev", "elevation_m")):
            v = r[col]
            if v is None: continue
            try: b[tgt] += float(v)
            except (TypeError, ValueError): pass
        t = r["workout_type"] or "unknown"
        b["types"][t] = b["types"].get(t, 0) + 1
    out = [f"# SEKTION: Gesundheit - Workouts ({_period_adverb(aggregate)} aggregiert; "
           "Summen ueber die Periode)",
           f"{label};Anzahl Workouts;Summe Dauer (min);Summe aktive Energie (kcal);"
           "Summe Gesamt-Energie (kcal);Summe Distanz (m);Summe Hoehenmeter (m);"
           "Typen-Aufteilung"]
    for key in sorted(buckets.keys()):
        b = buckets[key]
        types_str = ", ".join(f"{t}:{n}" for t, n in sorted(b["types"].items(), key=lambda x: -x[1]))
        out.append(
            f'{key};{b["n"]};{_num(b["dur"])};{_num(b["kcal_act"])};'
            f'{_num(b["kcal_tot"])};{_num(b["dist"])};{_num(b["elev"])};{_f(types_str)}'
        )
    out.append("")
    return out


async def _health_section(
    db,
    user_id: int,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    aggregate: str = "none",
    sections: Optional[list] = None,
) -> list:
    """Liefert Paare ``(sektions-schluessel, zeilen)``.

    Ohne ``sections`` sind alle Gesundheits-Sektionen dabei -- so bleibt der
    Health-Einzelexport, der dieselbe Funktion benutzt, unveraendert.
    """
    want = set(sections) if sections else {
        "health_summary", "health_vitals", "health_bp",
        "health_glucose", "health_sleep", "health_workouts"}
    result: list = []
    agg_on = _agg_on(aggregate)

    if "health_summary" in want:
        # Zusammenfassung bleibt unveraendert (keys/counts ueber den gesamten
        # Bestand), damit man beim Oeffnen der CSV den Ueberblick sieht.
        result.append(("health_summary", await _health_summary_section(db, user_id)))

    if "health_vitals" in want:
        result.append(("health_vitals", await _health_vitals_wide_section(
            db, user_id, date_from=date_from, date_to=date_to, aggregate=aggregate)))

    if "health_bp" in want:
        out: list[str] = []
        bp_where, bp_params = _build_range_where("recorded_at", 1, date_from, date_to)
        bp_rows = await db.fetch(
            f"SELECT recorded_at, systolic, diastolic, unit FROM health_blood_pressure "
            f"WHERE user_id=$1{bp_where} ORDER BY recorded_at", user_id, *bp_params)
        if agg_on:
            out.extend(_bp_aggregated(bp_rows, aggregate))
        else:
            out.append("# SEKTION: Gesundheit - Blutdruck")
            out.append("Zeitpunkt;Systolisch;Diastolisch;Einheit")
            for r in bp_rows:
                unit = (r["unit"] or "").strip()
                out.append(
                    f'{r["recorded_at"].isoformat() if r["recorded_at"] else ""};'
                    f'{_num(r["systolic"])};{_num(r["diastolic"])};{unit}'
                )
            out.append("")
        result.append(("health_bp", out))

    if "health_glucose" in want:
        out = []
        gl_where, gl_params = _build_range_where("recorded_at", 1, date_from, date_to)
        gl_rows = await db.fetch(
            f"SELECT recorded_at, value, unit FROM health_blood_glucose "
            f"WHERE user_id=$1{gl_where} ORDER BY recorded_at", user_id, *gl_params)
        if agg_on:
            out.extend(_gl_aggregated(gl_rows, aggregate))
        else:
            out.append("# SEKTION: Gesundheit - Blutzucker")
            out.append("Zeitpunkt;Wert;Einheit")
            for r in gl_rows:
                unit = (r["unit"] or "").strip()
                out.append(
                    f'{r["recorded_at"].isoformat() if r["recorded_at"] else ""};'
                    f'{_num(r["value"])};{unit}'
                )
            out.append("")
        result.append(("health_glucose", out))

    if "health_sleep" in want:
        out = []
        sl_where, sl_params = _build_range_where("sleep_date", 1, date_from, date_to)
        sl_rows = await db.fetch(
            f"SELECT sleep_date, sleep_start, sleep_end, in_bed_minutes, asleep_minutes, "
            f"core_minutes, deep_minutes, rem_minutes, awake_minutes FROM health_sleep "
            f"WHERE user_id=$1{sl_where} ORDER BY sleep_date", user_id, *sl_params)
        if agg_on:
            out.extend(_sleep_aggregated(sl_rows, aggregate))
        else:
            out.append("# SEKTION: Gesundheit - Schlaf (Phasen in Minuten)")
            out.append("Datum;Schlafbeginn;Schlafende;Im Bett (min);Geschlafen (min);"
                       "Core (min);Deep (min);REM (min);Wach (min)")
            for r in sl_rows:
                out.append(
                    f'{r["sleep_date"].isoformat() if r["sleep_date"] else ""};'
                    f'{r["sleep_start"].isoformat() if r["sleep_start"] else ""};'
                    f'{r["sleep_end"].isoformat() if r["sleep_end"] else ""};'
                    f'{_num(r["in_bed_minutes"])};{_num(r["asleep_minutes"])};'
                    f'{_num(r["core_minutes"])};{_num(r["deep_minutes"])};'
                    f'{_num(r["rem_minutes"])};{_num(r["awake_minutes"])}'
                )
            out.append("")
        result.append(("health_sleep", out))

    if "health_workouts" in want:
        out = []
        wk_where, wk_params = _build_range_where("start_at", 1, date_from, date_to)
        wk_rows = await db.fetch(
            f"SELECT id, start_at, end_at, workout_type, duration_min, active_energy_kcal, "
            f"total_energy_kcal, distance_m, elevation_m, avg_heart_rate, max_heart_rate, "
            f"min_heart_rate "
            f"FROM health_workouts WHERE user_id=$1{wk_where} ORDER BY start_at",
            user_id, *wk_params)
        workout_ids: list[int] = [r["id"] for r in wk_rows]
        if agg_on:
            out.extend(_workouts_aggregated(wk_rows, aggregate))
        else:
            out.append("# SEKTION: Gesundheit - Workouts (ohne Routendaten)")
            out.append("ID;Start;Ende;Typ;Dauer (min);Aktive Energie (kcal);Gesamt-Energie (kcal);"
                       "Distanz (m);Hoehenmeter (m);O-Herzfrequenz;Max-Herzfrequenz;"
                       "Min-Herzfrequenz")
            for r in wk_rows:
                out.append(
                    f'{r["id"]};'
                    f'{r["start_at"].isoformat() if r["start_at"] else ""};'
                    f'{r["end_at"].isoformat() if r["end_at"] else ""};'
                    f'{_f(r["workout_type"] or "")};'
                    f'{_num(r["duration_min"])};{_num(r["active_energy_kcal"])};'
                    f'{_num(r["total_energy_kcal"])};{_num(r["distance_m"])};'
                    f'{_num(r["elevation_m"])};{_num(r["avg_heart_rate"])};'
                    f'{_num(r["max_heart_rate"])};{_num(r["min_heart_rate"])}'
                )
            out.append("")

            # Workout-Zusatzmetriken referenzieren einzelne Workout-IDs; im
            # Aggregations-Modus sind diese IDs nicht mehr in der CSV -> die
            # Sektion bleibt dort bewusst weg statt "haengende" Referenzen zu
            # produzieren.
            out.append("# SEKTION: Gesundheit - Workout-Zusatzmetriken (Kadenz, "
                       "Schwimmzuege, Temperatur, ...); Workout-ID verweist auf die "
                       "vorige Sektion")
            out.append("Workout-ID;Metrik;Wert;Einheit")
            if workout_ids:
                for r in await db.fetch(
                    "SELECT workout_id, metric_key, value, unit FROM health_workout_metrics "
                    "WHERE workout_id = ANY($1::int[]) ORDER BY workout_id, metric_key",
                    workout_ids):
                    unit = (r["unit"] or "").strip()
                    out.append(
                        f'{r["workout_id"]};{_f(r["metric_key"])};'
                        f'{_num(r["value"])};{unit}'
                    )
            out.append("")
        result.append(("health_workouts", out))

    return result


# ---------- Musik (v1.67.0) ----------
# Das Register ist bereits zusammengefasst in die Datenbank gekommen -- je
# Zeile eine Periode und eine Gruppe (Titel, Interpret, Album). Der Export
# fasst deshalb hoechstens noch WEITER zusammen: aus Wochen werden Monate,
# aus Monaten Jahre. Der umgekehrte Weg existiert nicht; die Rohwiedergaben
# hat nur das Export-Programm, aus dem die CSV stammt.

_MUSIC_GRAIN_LABEL = {"tag": "täglich", "woche": "wöchentlich",
                      "monat": "monatlich", "jahr": "jährlich"}


async def _music_register_section(db, user_id: int, date_from=None, date_to=None,
                                  aggregate: str = "none") -> list[str]:
    where = "WHERE user_id=$1"
    params: list = [user_id]
    # Eine Periode gehoert dazu, sobald sie den Zeitraum beruehrt -- eine
    # Jahreszeile 2024 faellt bei "ab Juli 2024" sonst raus, obwohl sie die
    # gesuchte Zeit enthaelt.
    if date_from:
        params.append(date_from)
        where += f" AND period_end >= ${len(params)}"
    if date_to:
        params.append(date_to)
        where += f" AND period_start <= ${len(params)}"

    rows = await db.fetch(
        "SELECT grain, period_key, period_start, period_end, group_by, kind, "
        "       artist, title, album, plays, ms_played, skipped, block "
        f"  FROM music_entries {where} "
        " ORDER BY period_start, plays DESC NULLS LAST", *params)

    out: list[str] = []
    if not _agg_on(aggregate):
        out.append(
            "# SEKTION: Musik - Hoerregister (eine Zeile je Periode und Gruppe, "
            "so wie sie aus dem Spotify-Export gekommen ist). Die Spalte "
            "'Raster' sagt, wie fein die Zeile ist - aeltere Zeitraeume liegen "
            "bewusst groeber vor.")
        out.append("Periode;Raster;Von;Bis;Art;Interpret;Titel;Album;"
                   "Wiedergaben;Minuten;Übersprungen;Block")
        for r in rows:
            minutes = _num(r["ms_played"] / 60000) if r["ms_played"] is not None else ""
            out.append(
                f'{r["period_key"]};{_MUSIC_GRAIN_LABEL.get(r["grain"], r["grain"])};'
                f'{r["period_start"].isoformat()};{r["period_end"].isoformat()};'
                f'{_f(r["kind"])};{_f(r["artist"])};{_f(r["title"])};{_f(r["album"])};'
                f'{r["plays"]};{minutes};'
                f'{"" if r["skipped"] is None else r["skipped"]};{_f(r["block"])}'
            )
        out.append("")
        return out

    label = _period_label(aggregate)
    prefix = _period_prefix(aggregate)
    buckets: dict[tuple, dict] = {}
    coarser = 0
    finer_than = AGG_LEVELS.index(aggregate) if aggregate in AGG_LEVELS else -1
    grain_rank = {"tag": 0, "woche": 1, "monat": 2, "jahr": 3}
    for r in rows:
        key = (_period_key(r["period_start"], aggregate), r["kind"],
               r["artist"], r["title"], r["album"])
        b = buckets.setdefault(key, {"plays": 0, "ms": None, "skipped": 0,
                                     "von": r["period_start"], "bis": r["period_end"]})
        b["plays"] += int(r["plays"] or 0)
        if r["ms_played"] is not None:
            b["ms"] = (b["ms"] or 0) + int(r["ms_played"])
        b["skipped"] += int(r["skipped"] or 0)
        b["von"] = min(b["von"], r["period_start"])
        b["bis"] = max(b["bis"], r["period_end"])
        if grain_rank.get(r["grain"], 0) > finer_than:
            coarser += 1

    out.append(
        f"# SEKTION: Musik - Hoerregister, {prefix}-Zusammenfassung "
        f"({_period_adverb(aggregate)} aggregiert; Interpret und Titel bleiben "
        "erhalten, nur die Zeit wird groeber)")
    if coarser:
        out.append(
            f"# Hinweis: {coarser} Zeile(n) liegen groeber vor als '{label}' und "
            "zaehlen in die Periode ihres ersten Tages. Feiner als importiert "
            "laesst sich nicht aufteilen - die Einzelwiedergaben stehen nur im "
            "Spotify-Export selbst.")
    out.append(f"{label};Von;Bis;Art;Interpret;Titel;Album;Wiedergaben;Minuten;Übersprungen")
    for key in sorted(buckets.keys(), key=lambda k: (k[0], -buckets[k]["plays"])):
        b = buckets[key]
        period, kind, artist, title, album = key
        out.append(
            f'{period};{b["von"].isoformat()};{b["bis"].isoformat()};'
            f'{_f(kind)};{_f(artist)};{_f(title)};{_f(album)};'
            f'{b["plays"]};{_num(b["ms"] / 60000) if b["ms"] is not None else ""};'
            f'{b["skipped"]}'
        )
    out.append("")
    return out


async def _music_imports_section(db, user_id: int) -> list[str]:
    """Wann welche Datei hochgeladen wurde. Stammdaten: ohne dieses Protokoll
    sieht ein ersetzter Zeitraum spaeter aus wie ein Datenverlust."""
    rows = await db.fetch(
        "SELECT uploaded_at, filename, size_bytes, rows_read, rows_written, "
        "       rows_skipped, rows_replaced, blocks "
        "  FROM music_imports WHERE user_id=$1 ORDER BY uploaded_at", user_id)
    out = [
        "# SEKTION: Musik - Protokoll der CSV-Uploads (Herkunft der Zeilen im "
        "Hoerregister). 'Ersetzt' sind Zeilen, die dieser Upload aus seinem "
        "Zeitraum entfernt hat.",
        "Hochgeladen;Datei;Größe (Byte);Zeilen gelesen;Übernommen;"
        "Übersprungen;Ersetzt;Blöcke",
    ]
    for r in rows:
        blocks = r["blocks"]
        if isinstance(blocks, str):
            try:
                blocks = json.loads(blocks)
            except ValueError:
                blocks = []
        summary = " | ".join(
            f'{b.get("label", "?")} ({b.get("replace_from", "?")} bis {b.get("replace_to", "?")})'
            for b in (blocks or []))
        out.append(
            f'{r["uploaded_at"].isoformat() if r["uploaded_at"] else ""};'
            f'{_f(r["filename"] or "")};{r["size_bytes"]};{r["rows_read"]};'
            f'{r["rows_written"]};{r["rows_skipped"]};{r["rows_replaced"]};'
            f'{_f(summary)}'
        )
    out.append("")
    return out
