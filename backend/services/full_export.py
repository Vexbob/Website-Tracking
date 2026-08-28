"""Gesamt-Export: Sparziel + Ausgaben + Gesundheit in einer einzigen CSV.

Baut eine einzige, semikolon-getrennte CSV mit erklärenden Kommentar-
Zeilen (``# ...``) vor jeder Sektion. Wiederverwendet dieselben Row-Level-
Helfer wie die einzelnen Modul-Exports (``helpers.py`` fuer Sparziel,
gleiche Euro-/CSV-Feld-Konventionen fuer Ausgaben/Gesundheit), damit alle
drei Bereiche im selben Dokument konsistent formatiert sind.

Aufbau (jede Sektion beginnt mit ``# SEKTION: ...`` + eigenem Header):
  1. Sparziele, Achievements, Wochen-/Monatsziele, Wunsch-Anschaffungen,
     Zukunftsideen, Trophäen (Metadaten wie im Sparziel-Export)
  2. Sparziel-Protokoll (Check-ins, Meilensteine, Transaktionen)
  3. Ausgaben (Bons + Positionen)
  4. Gesundheit: Vitalwerte-Zeitserien, Blutdruck, Blutzucker, Schlaf, Workouts
"""
from __future__ import annotations

from datetime import datetime, timezone

from helpers import (
    _export_csv_field as _f,
    _export_amt as _amt,
    _build_export_metadata,
    _sparziel_protocol_lines,
)


def _euro_de(v) -> str:
    """Deutsches Euro-Format (Komma statt Punkt), wie im Ausgaben-Export."""
    if v is None:
        return ""
    try:
        return f"{float(v):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return ""


async def build_full_export_csv(db, user) -> str:
    """Baut die komplette CSV als String. Gibt Zeilen (``\\n``-getrennt) zurück."""
    lines: list[str] = []
    export_dt = datetime.now(timezone.utc).isoformat()
    lines.append(
        f"# Vexbob Gesamt-Export;user={_f(user['username'])};generated_at={export_dt}")
    lines.append(
        "# Diese Datei enthaelt ALLE Vexbob-Module in einer CSV: Sparziel "
        "(Ziele, Achievements, Wochen-/Monatsziele, Protokoll), Ausgaben "
        "(Bons + Positionen) und Gesundheit (Vitalwerte, Blutdruck, "
        "Blutzucker, Schlaf, Workouts). Jede Sektion beginnt mit einer "
        "Kommentarzeile '# SEKTION: ...' gefolgt von ihrem eigenen "
        "Spalten-Header - die Spaltenanzahl unterscheidet sich bewusst "
        "zwischen den Sektionen, da es sich um unterschiedliche Datentypen "
        "handelt (Excel/Sheets: Import als Text, nicht als starre Tabelle).")
    lines.append("")

    # ---------- 1) Sparziel-Metadaten (Ziele, Achievements, Wochenziele, ...) ----------
    lines.extend(await _build_export_metadata(db, user["id"]))

    # ---------- 2) Sparziel-Protokoll ----------
    lines.append("# SEKTION: Sparziel-Protokoll")
    lines.append("Datum;Typ;Titel;Beschreibung;Periode;Betrag;Notiz")
    lines.extend(await _sparziel_protocol_lines(db, user["id"]))
    lines.append("")

    # ---------- 3) Ausgaben ----------
    lines.extend(await _expenses_section(db, user["id"]))

    # ---------- 4) Gesundheit ----------
    lines.extend(await _health_section(db, user["id"]))

    return "\n".join(lines) + "\n"


async def _expenses_section(db, user_id: int) -> list[str]:
    out = [
        "# SEKTION: Ausgaben (ein Eintrag pro Position; Bons ohne Positionen "
        "erscheinen mit einer Zeile)",
        "Datum;Laden;Typ;Gesamt (EUR);Zahlungsart;Position;Menge;Einheit;"
        "Einzelpreis (EUR);Positionspreis (EUR);Original-Preis (EUR);"
        "Reduziert;Kategorie;Notiz",
    ]
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
    items_by_exp: dict = {}
    for it in item_rows:
        items_by_exp.setdefault(it["expense_id"], []).append(it)

    for r in rows:
        base = (
            f'{r["purchase_date"].isoformat() if r["purchase_date"] else ""};'
            f'{_f(r["store_name"] or "")};{_f(r["expense_type"] or "")};'
            f'{_euro_de(r["total_amount"])};{_f(r["payment_method"] or "")}'
        )
        note = _f((r["note"] or "").replace("\n", " ").replace("\r", " "))
        items = items_by_exp.get(r["id"], [])
        if not items:
            out.append(f'{base};;;;;;;;{note}')
            continue
        for it in items:
            out.append(
                f'{base};{_f(it["description"] or "")};{_euro_de(it["quantity"])};'
                f'{_f(it["quantity_unit"] or "")};{_euro_de(it["unit_price"])};'
                f'{_euro_de(it["total_price"])};{_euro_de(it["original_price"])};'
                f'{"ja" if it["is_reduced"] else ""};{_f(it["category_name"] or "")};{note}'
            )
    out.append("")
    return out


async def _health_section(db, user_id: int) -> list[str]:
    out: list[str] = []

    out.append(
        "# SEKTION: Gesundheit - Vitalwerte (aktive Energie, Herzfrequenz, "
        "Gewicht, HRV, Ruhepuls, Schritte, Schwimmdistanz, VO2max, ...)")
    out.append("Zeitpunkt;Metrik;Wert;Min;Max;Durchschnitt;Einheit;Quelle")
    for r in await db.fetch(
        "SELECT metric_type, recorded_at, qty, min_value, max_value, avg_value, unit, source "
        "FROM health_metric_samples WHERE user_id=$1 ORDER BY metric_type, recorded_at",
        user_id):
        out.append(
            f'{r["recorded_at"].isoformat() if r["recorded_at"] else ""};'
            f'{_f(r["metric_type"])};{_amt(r["qty"]) if r["qty"] is not None else ""};'
            f'{_amt(r["min_value"]) if r["min_value"] is not None else ""};'
            f'{_amt(r["max_value"]) if r["max_value"] is not None else ""};'
            f'{_amt(r["avg_value"]) if r["avg_value"] is not None else ""};'
            f'{_f(r["unit"] or "")};{_f(r["source"] or "")}'
        )
    out.append("")

    out.append("# SEKTION: Gesundheit - Blutdruck")
    out.append("Zeitpunkt;Systolisch;Diastolisch;Einheit")
    for r in await db.fetch(
        "SELECT recorded_at, systolic, diastolic, unit FROM health_blood_pressure "
        "WHERE user_id=$1 ORDER BY recorded_at", user_id):
        out.append(
            f'{r["recorded_at"].isoformat() if r["recorded_at"] else ""};'
            f'{_amt(r["systolic"]) if r["systolic"] is not None else ""};'
            f'{_amt(r["diastolic"]) if r["diastolic"] is not None else ""};{_f(r["unit"] or "")}'
        )
    out.append("")

    out.append("# SEKTION: Gesundheit - Blutzucker")
    out.append("Zeitpunkt;Wert;Einheit")
    for r in await db.fetch(
        "SELECT recorded_at, value, unit FROM health_blood_glucose "
        "WHERE user_id=$1 ORDER BY recorded_at", user_id):
        out.append(
            f'{r["recorded_at"].isoformat() if r["recorded_at"] else ""};'
            f'{_amt(r["value"]) if r["value"] is not None else ""};{_f(r["unit"] or "")}'
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
            f'{_amt(r["in_bed_minutes"]) if r["in_bed_minutes"] is not None else ""};'
            f'{_amt(r["asleep_minutes"]) if r["asleep_minutes"] is not None else ""};'
            f'{_amt(r["core_minutes"]) if r["core_minutes"] is not None else ""};'
            f'{_amt(r["deep_minutes"]) if r["deep_minutes"] is not None else ""};'
            f'{_amt(r["rem_minutes"]) if r["rem_minutes"] is not None else ""};'
            f'{_amt(r["awake_minutes"]) if r["awake_minutes"] is not None else ""}'
        )
    out.append("")

    out.append("# SEKTION: Gesundheit - Workouts (ohne Routendaten)")
    out.append("Start;Ende;Typ;Dauer (min);Aktive Energie (kcal);Gesamt-Energie (kcal);"
                "Distanz (m);Ø-Herzfrequenz;Max-Herzfrequenz")
    for r in await db.fetch(
        "SELECT start_at, end_at, workout_type, duration_min, active_energy_kcal, "
        "total_energy_kcal, distance_m, avg_heart_rate, max_heart_rate "
        "FROM health_workouts WHERE user_id=$1 ORDER BY start_at", user_id):
        out.append(
            f'{r["start_at"].isoformat() if r["start_at"] else ""};'
            f'{r["end_at"].isoformat() if r["end_at"] else ""};{_f(r["workout_type"] or "")};'
            f'{_amt(r["duration_min"]) if r["duration_min"] is not None else ""};'
            f'{_amt(r["active_energy_kcal"]) if r["active_energy_kcal"] is not None else ""};'
            f'{_amt(r["total_energy_kcal"]) if r["total_energy_kcal"] is not None else ""};'
            f'{_amt(r["distance_m"]) if r["distance_m"] is not None else ""};'
            f'{_amt(r["avg_heart_rate"]) if r["avg_heart_rate"] is not None else ""};'
            f'{_amt(r["max_heart_rate"]) if r["max_heart_rate"] is not None else ""}'
        )
    out.append("")

    return out
