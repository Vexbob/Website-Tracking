"""Utility-Funktionen fuer Sparziel/Ausgaben/Backend.

Wurden mit v1.15.1 aus ``main.py`` in ein eigenes Modul ausgelagert.
Enthalten sind:
  - ``ser`` : allgemeine Row->Dict Serialisierung mit ISO-Datumsformat
  - ``fmt_de_num`` : deutsche Zahlformatierung (Komma statt Punkt)
  - ``_milestones_at`` : zaehlt erreichte Meilensteine (inkl. Float-Toleranz
    und v1.15.1 strikt-drunter-Semantik bei ``direction="decrease"``)
  - ``_active_goal_id`` : aktives Sparziel eines Users
  - ``_streak`` : aktuelle Streak-Laenge fuer ein Progress-Goal
  - ``_build_export_header`` + ``_build_export_metadata`` : Vorspann
    fuer den Sparziel-CSV-Export (Metadaten aller Ziele/Achievements/...)
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from database import period_key, prev_period


# ---------- Row-Serialisierung / Formatierung ----------
def ser(row) -> dict:
    """Serialisiert eine asyncpg-Row zu dict mit ISO-Datumsformat."""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


def fmt_de_num(v) -> str:
    """Deutsche Zahlformatierung: ``5`` -> ``"5"``, ``2.5`` -> ``"2,5"``."""
    f = float(v)
    if f == int(f):
        return str(int(f))
    return f"{f:.2f}".rstrip("0").rstrip(".").replace(".", ",")


# ---------- Achievements ----------
def _milestones_at(sv, cv, inc, direction):
    """Zaehlt, wieviele Meilenstein-Schwellen bei ``cv`` bereits erreicht sind.

    Semantik:
      - ``increase``: Meilenstein #k gilt als erreicht, sobald ``cv >= sv + k*inc``.
        (Ein Meilenstein auf der Schwelle zaehlt bereits als erreicht.)
      - ``decrease``: Meilenstein #k gilt erst als erreicht, wenn ``cv < sv - k*inc``.
        (Auf der Schwelle stehen reicht NICHT — User muss echt drunter sein.)
        — v1.15.1: bewusst asymmetrisch, siehe User-Request.

    Beide Richtungen sind gegen Fliesskomma-Rauschen abgesichert
    (Bugfix v1.15.0): eine relative Toleranz von 1e-6·inc verhindert
    Off-by-One-Fehler durch akkumulierte 0.1+0.1+...-Rundungsfehler.
    """
    if inc <= 0:
        return 0
    inc = float(inc)
    eps = inc * 1e-6
    if direction == "increase":
        raw = (float(cv) - float(sv) + eps) / inc
    else:
        raw = (float(sv) - float(cv) - eps) / inc
    return max(0, int(math.floor(raw)))


# ---------- Sparziel: aktives Ziel ----------
async def _active_goal_id(db, user_id: int) -> Optional[int]:
    """Gibt die ID des aktiven Sparziels zurueck (oder None)."""
    return await db.fetchval(
        "SELECT id FROM savings_goals WHERE user_id=$1 AND is_active=TRUE ORDER BY id DESC LIMIT 1",
        user_id)


# ---------- Progress-Goals: Streak-Berechnung ----------
async def _streak(db, gid: int, user_id: int, rhythm: str, target: int) -> int:
    """Zaehlt die Anzahl aufeinanderfolgender erfolgreicher Perioden.

    Der aktuelle Zeitraum zaehlt nur mit, wenn er selbst schon erfuellt
    ist — sonst wird nur die Kette der abgeschlossenen Vorperioden
    gezaehlt (typische Streak-Semantik: die laufende Periode killt die
    Streak nicht sofort). Iteration ist auf 520 Perioden begrenzt
    (10 Jahre Wochen) — Sicherheitsanschlag.
    """
    from datetime import date as _date
    col = "month_key" if rhythm == "monthly" else "week_key"
    rows = await db.fetch(
        f"SELECT {col} AS k, COUNT(*) AS c FROM progress_logs "
        f"WHERE progress_goal_id=$1 AND user_id=$2 GROUP BY {col}",
        gid, user_id)
    fulfilled = {r["k"] for r in rows if r["c"] >= target}
    streak = 0
    cursor = _date.today()
    if period_key(rhythm, cursor) not in fulfilled:
        cursor = prev_period(rhythm, cursor)
    for _ in range(520):
        if period_key(rhythm, cursor) in fulfilled:
            streak += 1
            cursor = prev_period(rhythm, cursor)
        else:
            break
    return streak


# ---------- Export-Helfer (Sparziel-CSV) ----------
def _export_csv_field(s: str) -> str:
    s = (s or "").replace('"', '""').replace(';', ',').replace('\n', ' ').replace('\r', ' ')
    return f'"{s}"'


def _export_amt(v) -> str:
    try:
        return f"{float(v):.2f}"
    except Exception:
        return ""


def _build_export_header(user) -> list[str]:
    export_dt = datetime.now(timezone.utc).isoformat()
    return [
        f"# Vexbob Sparziel-Export;user={_export_csv_field(user['username'])};generated_at={export_dt}",
        "",
    ]


async def _build_export_metadata(db, user_id: int) -> list[str]:
    """Baut den Metadaten-Vorspann des Sparziel-CSV-Exports.

    Enthaelt: Sparziele, Achievements, Wochen-/Monatsziele, Wunsch-
    Anschaffungen, Zukunftsideen und Trophaeen. Jede Sektion beginnt
    mit ``# SEKTION: ...`` und ihrem eigenen Spalten-Header.
    """
    out: list[str] = []

    # Sparziele
    out.append("# SEKTION: Sparziele")
    out.append("id;name;target_amount;is_active;created_at")
    for r in await db.fetch(
        "SELECT id, name, target_amount, is_active, created_at FROM savings_goals "
        "WHERE user_id=$1 ORDER BY is_active DESC, id", user_id):
        created = r["created_at"].isoformat() if r["created_at"] else ""
        out.append(
            f'{r["id"]};{_export_csv_field(r["name"] or "")};{_export_amt(r["target_amount"])};'
            f'{"true" if r["is_active"] else "false"};{created}'
        )
    out.append("")

    # Achievements
    out.append("# SEKTION: Achievements")
    out.append("id;title;unit;start_value;current_value;threshold_increment;step_amount;target_value;direction;reward_amount;credited_milestones;is_completed")
    for r in await db.fetch(
        "SELECT id, title, unit, start_value, current_value, threshold_increment, step_amount, "
        "target_value, direction, reward_amount, credited_milestones, is_completed "
        "FROM achievements WHERE user_id=$1 ORDER BY sort_order NULLS LAST, id", user_id):
        out.append(
            f'{r["id"]};{_export_csv_field(r["title"] or "")};{_export_csv_field(r["unit"] or "")};'
            f'{_export_amt(r["start_value"])};{_export_amt(r["current_value"])};'
            f'{_export_amt(r["threshold_increment"])};{_export_amt(r["step_amount"])};'
            f'{_export_amt(r["target_value"]) if r["target_value"] is not None else ""};'
            f'{r["direction"] or ""};{_export_amt(r["reward_amount"])};'
            f'{int(r["credited_milestones"] or 0)};'
            f'{"true" if r["is_completed"] else "false"}'
        )
    out.append("")

    # Wochen-/Monatsziele
    out.append("# SEKTION: Wochen-/Monatsziele")
    out.append("id;title;rhythm_type;target_count;reward_amount;streak_bonus_amount;streak_bonus_threshold")
    for r in await db.fetch(
        "SELECT id, title, rhythm_type, target_count, reward_amount, "
        "streak_bonus_amount, streak_bonus_threshold "
        "FROM progress_goals WHERE user_id=$1 ORDER BY sort_order NULLS LAST, id", user_id):
        out.append(
            f'{r["id"]};{_export_csv_field(r["title"] or "")};{r["rhythm_type"] or "weekly"};'
            f'{int(r["target_count"] or 0)};{_export_amt(r["reward_amount"])};'
            f'{_export_amt(r["streak_bonus_amount"])};{int(r["streak_bonus_threshold"] or 0)}'
        )
    out.append("")

    # Wunsch-Anschaffungen
    out.append("# SEKTION: Wunsch-Anschaffungen")
    out.append("id;name;estimated_price")
    for r in await db.fetch(
        "SELECT id, name, estimated_price FROM potential_goals "
        "WHERE user_id=$1 ORDER BY id", user_id):
        out.append(
            f'{r["id"]};{_export_csv_field(r["name"] or "")};'
            f'{_export_amt(r["estimated_price"]) if r["estimated_price"] is not None else ""}'
        )
    out.append("")

    return streak

    # Zukuenftige Ideen
    out.append("# SEKTION: Zukuenftige Ideen")
    out.append("id;title;category")
    for r in await db.fetch(
        "SELECT id, title, category FROM future_ideas "
        "WHERE user_id=$1 ORDER BY id", user_id):
        out.append(
            f'{r["id"]};{_export_csv_field(r["title"] or "")};{_export_csv_field(r["category"] or "")}'
        )
    out.append("")

    # Trophaeen
    out.append("# SEKTION: Trophaeen (abgeschlossene Sparziele)")
    out.append("id;name;target_amount;final_amount;started_at;completed_at;duration_days;icon;note")
    for r in await db.fetch(
        "SELECT id, name, target_amount, final_amount, started_at, completed_at, "
        "duration_days, icon, note FROM completed_goals WHERE user_id=$1 ORDER BY completed_at",
        user_id):
        started = r["started_at"].isoformat() if r["started_at"] else ""
        completed = r["completed_at"].isoformat() if r["completed_at"] else ""
        out.append(
            f'{r["id"]};{_export_csv_field(r["name"] or "")};{_export_amt(r["target_amount"])};'
            f'{_export_amt(r["final_amount"])};{started};{completed};'
            f'{int(r["duration_days"] or 0) if r["duration_days"] is not None else ""};'
            f'{_export_csv_field(r["icon"] or "")};{_export_csv_field(r["note"] or "")}'
        )
    out.append("")

    return out

