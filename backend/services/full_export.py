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

import re
from datetime import date, datetime, timezone
from typing import Optional

from helpers import (
    _export_csv_field as _f,
    _export_amt as _amt,  # noqa: F401  (kompatibel gehalten fuer moegliche Reimporte)
    _build_export_metadata,
    _sparziel_protocol_lines,
)


# ---------- v1.37.1 Zeitraum- + Aggregations-Helfer ----------

def _period_key(d: date, mode: str) -> str:
    """Liefert einen Sortier- und Anzeige-freundlichen Perioden-Key.

    ``week``  -> ISO-Woche ``YYYY-Www`` (z. B. ``2024-W03``)
    ``month`` -> ``YYYY-MM``
    """
    if mode == "week":
        iso = d.isocalendar()
        return f"{iso[0]:04d}-W{iso[1]:02d}"
    return f"{d.year:04d}-{d.month:02d}"


def _period_label(mode: str) -> str:
    """Singular-Label fuer eine Periode (``Woche`` / ``Monat``)."""
    return "Woche" if mode == "week" else ("Monat" if mode == "month" else "Periode")


def _period_prefix(mode: str) -> str:
    """Wortstamm fuer Substantiv-Zusammensetzungen wie ``Wochen-Zusammenfassung``
    oder ``Monats-Zusammenfassung``. Vermeidet den frueheren Bug ``Woches-...``.
    """
    return "Wochen" if mode == "week" else ("Monats" if mode == "month" else "Perioden")


def _period_adverb(mode: str) -> str:
    """Adverb fuer Beschreibungen wie ``wochenweise aggregiert``."""
    return "wochenweise" if mode == "week" else ("monatsweise" if mode == "month" else "periodenweise")


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
    ``resting_hr`` pro Zeile 3 Zeichen)."""
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
    """Deutsches Euro-Format (Komma statt Punkt) fuer die Ausgaben-Sektion."""
    if v is None:
        return ""
    try:
        return f"{float(v):.2f}".replace(".", ",")
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

EXPORT_SECTIONS: list[dict] = [
    {"key": "sparziel_meta", "group": "sparziel", "aggregatable": False, "dated": False,
     "label": "Ziele, Achievements, Wochenziele, Trophaeen"},
    {"key": "sparziel_log", "group": "sparziel", "aggregatable": True, "dated": True,
     "label": "Protokoll (Check-ins, Meilensteine, Auszahlungen)"},
    {"key": "ausgaben", "group": "ausgaben", "aggregatable": True, "dated": True,
     "label": "Bons und ihre Positionen"},
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
]

EXPORT_GROUPS: list[dict] = [
    {"key": "sparziel", "label": "Sparziel"},
    {"key": "ausgaben", "label": "Ausgaben"},
    {"key": "health", "label": "Gesundheit"},
]

ALL_SECTION_KEYS = [s["key"] for s in EXPORT_SECTIONS]


def clean_sections(raw) -> list[str]:
    """Bekannte Schluessel in der Reihenfolge der Registry. Leer heisst alle --
    ein Export ohne Sektionen waere eine leere Datei, und die will niemand."""
    if not raw:
        return list(ALL_SECTION_KEYS)
    wanted = {str(x).strip() for x in raw if str(x).strip()}
    picked = [k for k in ALL_SECTION_KEYS if k in wanted]
    return picked or list(ALL_SECTION_KEYS)


def clean_aggregate_map(raw, fallback: str = "none") -> dict:
    """Aggregation je Modul. Was fehlt oder unbekannt ist, bekommt den
    Gesamtwert -- so bleibt der alte Aufruf mit nur ``aggregate`` gueltig."""
    fallback = fallback if fallback in ("none", "week", "month") else "none"
    out = {g["key"]: fallback for g in EXPORT_GROUPS}
    for key, value in (raw or {}).items():
        if key in out and value in ("none", "week", "month"):
            out[key] = value
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
) -> str:
    """Baut die komplette CSV als String. Gibt Zeilen (``\\n``-getrennt) zurueck.

    v1.37.1: Optionale Filter/Aggregation.
      * ``date_from`` / ``date_to``: filtert alle zeitreihen-basierten
        Sektionen (Sparziel-Protokoll, Ausgaben, Health-Zeitreihen).
        Metadaten-Sektionen (Sparziele, Achievements, Wochen-/Monatsziele,
        Trophaeen, ...) bleiben ungefiltert, damit die aggregierten Zahlen
        weiter im Kontext lesbar bleiben.
      * ``aggregate`` = ``none|week|month``: fasst Ausgaben und Vitalwerte
        zu Perioden zusammen (Anzahl Bons + Summe je Woche/Monat, avg/min/max
        je Metrik). Fuer lange Zeitraeume (Jahre) enorm platzsparend.
        v1.40.1: Ausgaben behalten dabei zusaetzlich eine Zeile je Bon
        (Datum, Laden, Typ, Anzahl Positionen, Summe, Kategorien-Split) --
        weg fallen nur die Einzelpositionen.
    """
    picked = clean_sections(sections)
    agg_map = clean_aggregate_map(aggregate_map, aggregate)
    built = await _build_sections(db, user, picked, date_from, date_to, agg_map)

    lines = _export_header(user, picked, date_from, date_to, agg_map)
    for _key, section_lines in built:
        lines.extend(section_lines)
    return _compact_timestamps("\n".join(lines) + "\n")


def _export_header(user, picked: list[str], date_from, date_to, agg_map: dict) -> list[str]:
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
    if len(picked) < len(ALL_SECTION_KEYS):
        fehlt = [labels.get(k, k) for k in ALL_SECTION_KEYS if k not in picked]
        lines.append("# BEWUSST NICHT enthalten: " + "; ".join(fehlt))
    lines.append(
        "# Jede Sektion beginnt mit einer Kommentarzeile '# SEKTION: ...' "
        "gefolgt von ihrem eigenen Spalten-Header - die Spaltenanzahl "
        "unterscheidet sich bewusst zwischen den Sektionen. Bons und "
        "Positionen sind ueber expense_id verknuepft.")
    lines.append(
        "# Konventionen: Zeitstempel sind UTC im Format YYYY-MM-DDTHH:MM:SSZ "
        "(keine Mikrosekunden). Gesundheitswerte nutzen Punkt-Dezimal, "
        "Euro-Betraege in der Ausgaben-Sektion nutzen Komma-Dezimal.")
    lines.append("")
    return lines


async def _build_sections(db, user, picked: list[str], date_from, date_to,
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
        if agg in ("week", "month"):
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

    health_keys = [k for k in ("health_summary", "health_vitals", "health_bp",
                               "health_glucose", "health_sleep", "health_workouts")
                   if k in want]
    if health_keys:
        out.extend(await _health_section(
            db, uid, date_from=date_from, date_to=date_to,
            aggregate=agg_map.get("health", "none"), sections=health_keys))
    return out


async def build_export_preview(
    db,
    user,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    aggregate: str = "none",
    sections: Optional[list] = None,
    aggregate_map: Optional[dict] = None,
    sample_lines: int = 40,
) -> dict:
    """Was der Export enthalten wuerde: je Sektion die Zeilenzahl und ihr
    Anteil, die Gesamtgroesse und die ersten Zeilen der echten Datei. Baut den
    Export dafuer wirklich -- eine Schaetzung waere schneller und falsch."""
    picked = clean_sections(sections)
    agg_map = clean_aggregate_map(aggregate_map, aggregate)
    built = await _build_sections(db, user, picked, date_from, date_to, agg_map)

    header = _export_header(user, picked, date_from, date_to, agg_map)
    all_lines = list(header)
    labels = {s["key"]: s["label"] for s in EXPORT_SECTIONS}
    detail = []
    for key, section_lines in built:
        text = _compact_timestamps("\n".join(section_lines))
        detail.append({
            "key": key,
            "label": labels.get(key, key),
            "rows": _count_rows(section_lines),
            "bytes": len(text.encode("utf-8")),
        })
        all_lines.extend(section_lines)

    csv = _compact_timestamps("\n".join(all_lines) + "\n")
    body = ("\ufeff" + csv).encode("utf-8")
    sample = csv.split("\n")[:max(1, sample_lines)]
    return {
        "sections": detail,
        "total_rows": sum(d["rows"] for d in detail),
        "bytes": len(body),
        "lines": csv.count("\n"),
        "sample": "\n".join(sample),
        "truncated": csv.count("\n") > len(sample),
    }


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
                   e.expense_type, e.note, s.name AS store_name
            FROM expenses e LEFT JOIN stores s ON s.id=e.store_id
            {exp_where} ORDER BY e.purchase_date, e.id""",
        *exp_params)

    # -------- Aggregations-Modus: kompakte Wochen-/Monats-Summary --------
    # v1.40.1: Zusaetzlich zur Perioden-Summe steht jeder Einkauf einzeln in
    # der CSV -- ohne Einzelpositionen, aber mit Kategorien-Aufschluesselung.
    # Die reine Wochensumme sagt nichts darueber, wofuer das Geld ausgegeben
    # wurde; die Positionsliste macht lange Zeitraeume dagegen unlesbar.
    if aggregate in ("week", "month") and rows:
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
        "# SEKTION: Ausgaben - Bons (ein Eintrag pro Beleg; Positionen in "
        "naechster Sektion, verknuepft ueber expense_id)")
    out.append("expense_id;Datum;Laden;Typ;Gesamt (EUR);Zahlungsart;Notiz")
    for r in rows:
        note = _f((r["note"] or "").replace("\n", " ").replace("\r", " ")) if r["note"] else ""
        out.append(
            f'{r["id"]};'
            f'{r["purchase_date"].isoformat() if r["purchase_date"] else ""};'
            f'{_f(r["store_name"] or "")};{_f(r["expense_type"] or "")};'
            f'{_euro_de(r["total_amount"])};{_f(r["payment_method"] or "")};{note}'
        )
    out.append("")

    # Bon-Positionen (expense_id verweist auf die Bon-Sektion oben)
    out.append(
        "# SEKTION: Ausgaben - Bon-Positionen (expense_id verweist auf vorige Sektion)")
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
        f"# SEKTION: Ausgaben - {prefix}-Zusammenfassung (aggregiert; die "
        "einzelnen Bons folgen kompakt in der naechsten Sektion, die "
        "Einzelpositionen der Bons bleiben in diesem Modus bewusst "
        "weg, damit lange Zeitraeume kompakt bleiben)")
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
        "Einzelpositionen). Kategorien-Spalte: 'Kategorie:Anzahl/Betrag', "
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
    if aggregate in ("week", "month"):
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

    if aggregate in ("week", "month"):
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
        if aggregate in ("week", "month") or m in has_aggregate:
            header_cols.append(f"{m}_min")
            header_cols.append(f"{m}_max")
    out.append(";".join(header_cols))

    if aggregate in ("week", "month"):
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
    agg_on = aggregate in ("week", "month")

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
