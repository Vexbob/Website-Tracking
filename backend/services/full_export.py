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
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from helpers import (
    _export_csv_field as _f,
    _export_amt as _amt,  # noqa: F401  (kompatibel gehalten fuer moegliche Reimporte)
    _build_export_metadata,
    _sparziel_protocol_lines,
)


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



# ---------- Public API ----------

async def build_full_export_csv(db, user) -> str:
    """Baut die komplette CSV als String. Gibt Zeilen (``\\n``-getrennt) zurueck."""
    lines: list[str] = []
    export_dt = datetime.now(timezone.utc).isoformat()
    lines.append(
        f"# Vexbob Gesamt-Export;user={_f(user['username'])};generated_at={export_dt}")
    lines.append(
        "# Diese Datei enthaelt ALLE Vexbob-Module in einer CSV: Sparziel "
        "(Ziele, Achievements, Wochen-/Monatsziele, Protokoll), Ausgaben "
        "(Bons + Positionen als getrennte Sektionen, verknuepft ueber "
        "expense_id) und Gesundheit (Vitalwerte im Wide-Format, Blutdruck, "
        "Blutzucker, Schlaf, Workouts). Jede Sektion beginnt mit einer "
        "Kommentarzeile '# SEKTION: ...' gefolgt von ihrem eigenen "
        "Spalten-Header - die Spaltenanzahl unterscheidet sich bewusst "
        "zwischen den Sektionen.")
    lines.append(
        "# Konventionen: Zeitstempel sind UTC im Format YYYY-MM-DDTHH:MM:SSZ "
        "(keine Mikrosekunden). Gesundheitswerte nutzen Punkt-Dezimal, "
        "Euro-Betraege in der Ausgaben-Sektion nutzen Komma-Dezimal.")
    lines.append("")

    # ---------- 1) Sparziel-Metadaten ----------
    lines.extend(await _build_export_metadata(db, user["id"]))

    # ---------- 2) Sparziel-Protokoll ----------
    lines.append("# SEKTION: Sparziel-Protokoll")
    lines.append("Datum;Typ;Titel;Beschreibung;Periode;Betrag;Notiz")
    lines.extend(await _sparziel_protocol_lines(db, user["id"]))
    lines.append("")

    # ---------- 3) Ausgaben ----------
    lines.extend(await _expenses_sections(db, user["id"]))

    # ---------- 4) Gesundheit ----------
    lines.extend(await _health_section(db, user["id"]))

    return _compact_timestamps("\n".join(lines) + "\n")


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
    lines.extend(await _health_section(db, user["id"]))
    return _compact_timestamps("\n".join(lines) + "\n")


# ---------- Ausgaben (Bons + Positionen getrennt) ----------

async def _expenses_sections(db, user_id: int) -> list[str]:
    out: list[str] = []
    rows = await db.fetch(
        """SELECT e.id, e.purchase_date, e.total_amount, e.payment_method,
                  e.expense_type, e.note, s.name AS store_name
           FROM expenses e LEFT JOIN stores s ON s.id=e.store_id
           WHERE e.user_id=$1 ORDER BY e.purchase_date, e.id""",
        user_id)
    item_rows = await db.fetch(
        """SELECT ei.expense_id, ei.description, ei.quantity, ei.quantity_unit,
                  ei.unit_price, ei.total_price, ei.is_reduced, ei.original_price,
                  c.name AS category_name
           FROM expense_items ei LEFT JOIN expense_categories c ON c.id=ei.category_id
           WHERE ei.user_id=$1 ORDER BY ei.expense_id, ei.sort_order NULLS LAST, ei.id""",
        user_id)

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


async def _health_vitals_wide_section(db, user_id: int) -> list[str]:
    """Vitalwerte im Wide-Format: eine Zeile pro Tag, Metriken als
    Spalten. Fuer Metriken mit Aggregaten (min/max) werden zusaetzliche
    ``<metrik>_min`` / ``<metrik>_max`` Spalten angelegt - aber nur wenn
    es tatsaechlich Aggregat-Daten gibt.

    Effekt: ~50 % kleiner als das alte Long-Format, weil weder Datum
    noch Metrik-Name pro Wert wiederholt werden. Fuer eine KI zusaetzlich
    leichter lesbar, weil Tages-Zusammenhaenge in einer Zeile sichtbar
    sind (z. B. Zusammenhang steps <-> weight <-> hrv am selben Tag)."""
    rows = await db.fetch(
        "SELECT metric_type, recorded_at, qty, min_value, max_value, "
        "avg_value, unit, source FROM health_metric_samples "
        "WHERE user_id=$1 ORDER BY recorded_at, metric_type",
        user_id)

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

    header_cols = ["Datum"]
    for m in metrics_sorted:
        header_cols.append(m)
        if m in has_aggregate:
            header_cols.append(f"{m}_min")
            header_cols.append(f"{m}_max")
    out.append(";".join(header_cols))

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


async def _health_section(db, user_id: int) -> list[str]:
    out: list[str] = []
    out.extend(await _health_summary_section(db, user_id))
    out.extend(await _health_vitals_wide_section(db, user_id))

    out.append("# SEKTION: Gesundheit - Blutdruck")
    out.append("Zeitpunkt;Systolisch;Diastolisch;Einheit")
    for r in await db.fetch(
        "SELECT recorded_at, systolic, diastolic, unit FROM health_blood_pressure "
        "WHERE user_id=$1 ORDER BY recorded_at", user_id):
        unit = (r["unit"] or "").strip()
        out.append(
            f'{r["recorded_at"].isoformat() if r["recorded_at"] else ""};'
            f'{_num(r["systolic"])};{_num(r["diastolic"])};{unit}'
        )
    out.append("")

    out.append("# SEKTION: Gesundheit - Blutzucker")
    out.append("Zeitpunkt;Wert;Einheit")
    for r in await db.fetch(
        "SELECT recorded_at, value, unit FROM health_blood_glucose "
        "WHERE user_id=$1 ORDER BY recorded_at", user_id):
        unit = (r["unit"] or "").strip()
        out.append(
            f'{r["recorded_at"].isoformat() if r["recorded_at"] else ""};'
            f'{_num(r["value"])};{unit}'
        )
    out.append("")

    out.append("# SEKTION: Gesundheit - Schlaf (Phasen in Minuten)")
    out.append("Datum;Schlafbeginn;Schlafende;Im Bett (min);Geschlafen (min);"
                "Core (min);Deep (min);REM (min);Wach (min)")
    for r in await db.fetch(
        "SELECT sleep_date, sleep_start, sleep_end, in_bed_minutes, asleep_minutes, "
        "core_minutes, deep_minutes, rem_minutes, awake_minutes FROM health_sleep "
        "WHERE user_id=$1 ORDER BY sleep_date", user_id):
        out.append(
            f'{r["sleep_date"].isoformat() if r["sleep_date"] else ""};'
            f'{r["sleep_start"].isoformat() if r["sleep_start"] else ""};'
            f'{r["sleep_end"].isoformat() if r["sleep_end"] else ""};'
            f'{_num(r["in_bed_minutes"])};{_num(r["asleep_minutes"])};'
            f'{_num(r["core_minutes"])};{_num(r["deep_minutes"])};'
            f'{_num(r["rem_minutes"])};{_num(r["awake_minutes"])}'
        )
    out.append("")

    out.append("# SEKTION: Gesundheit - Workouts (ohne Routendaten)")
    out.append("ID;Start;Ende;Typ;Dauer (min);Aktive Energie (kcal);Gesamt-Energie (kcal);"
                "Distanz (m);Hoehenmeter (m);O-Herzfrequenz;Max-Herzfrequenz")
    workout_ids: list[int] = []
    for r in await db.fetch(
        "SELECT id, start_at, end_at, workout_type, duration_min, active_energy_kcal, "
        "total_energy_kcal, distance_m, elevation_m, avg_heart_rate, max_heart_rate "
        "FROM health_workouts WHERE user_id=$1 ORDER BY start_at", user_id):
        workout_ids.append(r["id"])
        out.append(
            f'{r["id"]};'
            f'{r["start_at"].isoformat() if r["start_at"] else ""};'
            f'{r["end_at"].isoformat() if r["end_at"] else ""};'
            f'{_f(r["workout_type"] or "")};'
            f'{_num(r["duration_min"])};{_num(r["active_energy_kcal"])};'
            f'{_num(r["total_energy_kcal"])};{_num(r["distance_m"])};'
            f'{_num(r["elevation_m"])};{_num(r["avg_heart_rate"])};'
            f'{_num(r["max_heart_rate"])}'
        )
    out.append("")

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

    return out

    out.append("")
    return out
