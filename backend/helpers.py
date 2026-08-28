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


async def _general_goal_id(db, user_id: int) -> Optional[int]:
    """ID des ``Allgemein``-Kontos fuer einen User (v1.18.2).

    Wird beim ersten Aufruf idempotent nachgezogen, falls die Migration
    das Konto (aus welchem Grund auch immer) noch nicht angelegt hat.
    """
    gid = await db.fetchval(
        "SELECT id FROM savings_goals WHERE user_id=$1 AND is_general=TRUE LIMIT 1",
        user_id)
    if gid:
        return gid
    try:
        return await db.fetchval(
            "INSERT INTO savings_goals (user_id, name, target_amount, is_active, is_general) "
            "VALUES ($1, 'Allgemein', 0, FALSE, TRUE) RETURNING id",
            user_id)
    except Exception:
        return None


async def _reward_goal_for(db, user_id: int, preferred_goal_id: Optional[int],
                             reward_amount: float) -> Optional[int]:
    """Entscheidet, in welches Sparziel eine Meilenstein-/Streak-Belohnung
    verbucht wird (v1.18.2 Reward-Routing).

    Prioritaeten:
      1. Explizit zugeordnetes Ziel (``preferred_goal_id`` z.B. aus
         ``achievements.reward_goal_id``) — sofern es existiert, dem User
         gehoert, nicht abgeschlossen ist und noch Platz hat.
      2. Aktives Sparziel — sofern es noch nicht ueberzogen wird
         (``saved + reward <= target * 1.001`` mit kleiner Toleranz).
         Wenn die Belohnung das aktive Ziel „ueberzahlen" wuerde, faellt
         die Auszahlung auf das Allgemein-Konto.
      3. Allgemein-Konto (``is_general=TRUE``) — Puffer, dahin gehen alle
         Belohnungen, die sonst nirgends passen. Wird bei Bedarf angelegt.

    Wichtig: Diese Funktion garantiert, dass IMMER eine goal_id zurueckkommt
    (oder None nur, wenn selbst das Allgemein-Konto nicht erstellt werden
    konnte — dann bleibt savings_transactions.savings_goal_id = NULL, was
    aber weiterhin ein gueltiger Zustand ist).
    """
    async def _room_left(goal_id: int) -> Optional[float]:
        row = await db.fetchrow(
            "SELECT target_amount FROM savings_goals "
            "WHERE id=$1 AND user_id=$2 AND is_general=FALSE",
            goal_id, user_id)
        if not row:
            return None
        target = float(row["target_amount"] or 0)
        if target <= 0:
            return float("inf")
        saved = float(await db.fetchval(
            "SELECT COALESCE(SUM(amount),0) FROM savings_transactions "
            "WHERE user_id=$1 AND savings_goal_id=$2",
            user_id, goal_id) or 0)
        return max(0.0, target - saved)

    reward = float(reward_amount or 0)
    tol = 0.005  # kleine Toleranz gegen Float-Rauschen

    # 1) explizit zugeordnetes Ziel
    if preferred_goal_id:
        room = await _room_left(preferred_goal_id)
        if room is not None and room + tol >= reward:
            return preferred_goal_id
        # Wenn zugewiesenes Ziel voll ist, wandert die Belohnung zum Allgemein-Konto

    # 2) aktives Sparziel — nur wenn genug Platz
    active = await _active_goal_id(db, user_id)
    if active:
        room = await _room_left(active)
        if room is not None and room + tol >= reward:
            return active

    # 3) Allgemein-Konto (Puffer, immer aufnahmefaehig)
    gen = await _general_goal_id(db, user_id)
    return gen


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


async def _sparziel_protocol_lines(db, user_id: int) -> list[str]:
    """Baut die Protokoll-Zeilen (Check-ins, Meilensteine, Transaktionen)
    fuer den Sparziel-Export. Ausgelagert (v1.23.0), damit sowohl der
    einzelne Sparziel-Export (``/api/savings-transactions/export``) als
    auch der kombinierte Gesamt-Export (``services/full_export.py``)
    dieselbe Logik ohne Duplikation nutzen."""
    log_body: list[str] = []

    ci_rows = await db.fetch(
        """SELECT pl.log_date, pl.week_key, pl.month_key, pl.created_at, pl.note,
                  pg.title, pg.reward_amount, pg.rhythm_type, pg.target_count, pl.progress_goal_id, pl.id
           FROM progress_logs pl JOIN progress_goals pg ON pg.id = pl.progress_goal_id
           WHERE pl.user_id=$1
           ORDER BY pl.created_at""",
        user_id)
    for r in ci_rows:
        rhythm = r["rhythm_type"] or "weekly"
        pk = r["month_key"] if rhythm == "monthly" else r["week_key"]
        col = "month_key" if rhythm == "monthly" else "week_key"
        cnt_upto = int(await db.fetchval(
            f"SELECT COUNT(*) FROM progress_logs WHERE progress_goal_id=$1 AND user_id=$2 AND {col}=$3 AND id <= $4",
            r["progress_goal_id"], user_id, pk, r["id"]))
        target = int(r["target_count"])
        just_fulfilled = cnt_upto == target
        amt = float(r["reward_amount"]) if just_fulfilled else 0.0
        d = r["created_at"].isoformat() if r["created_at"] else ""
        desc = f"{cnt_upto}/{target}"
        log_body.append(f'{d};checkin;{_export_csv_field(r["title"])};{_export_csv_field(desc)};{pk or ""};{amt:.2f};{_export_csv_field(r["note"] or "")}')

    ml_rows = await db.fetch(
        """SELECT al.achieved_value, al.reward_amount, al.date_achieved, al.note, a.title, a.unit
           FROM achievement_logs al JOIN achievements a ON a.id = al.achievement_id
           WHERE al.user_id=$1
           ORDER BY al.date_achieved""",
        user_id)
    for r in ml_rows:
        d = r["date_achieved"].isoformat() if r["date_achieved"] else ""
        unit = r["unit"] or ""
        desc = f"Bei {fmt_de_num(r['achieved_value'])} {unit}".strip()
        log_body.append(f'{d};milestone;{_export_csv_field(r["title"])};{_export_csv_field(desc)};;{float(r["reward_amount"]):.2f};{_export_csv_field(r["note"] or "")}')

    tx_rows = await db.fetch(
        """SELECT created_at, amount, source_type, source_id, description, period_key, note
           FROM savings_transactions WHERE user_id=$1 ORDER BY created_at""",
        user_id)
    for r in tx_rows:
        st = r["source_type"]
        pk = r["period_key"] or ""
        is_streak_bonus = st == "progress" and "-streak-" in pk
        if st == "progress" and not is_streak_bonus:
            continue
        if st == "achievement":
            continue
        d = r["created_at"].isoformat() if r["created_at"] else ""
        row_type = "streak_bonus" if is_streak_bonus else st
        desc = r["description"] or ""
        title = "Anfangsbestand" if st == "initial" else (desc[:40] or st)
        log_body.append(f'{d};{row_type};{_export_csv_field(title)};{_export_csv_field(desc)};{pk};{float(r["amount"]):.2f};{_export_csv_field(r["note"] or "")}')

    return sorted(log_body)


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

