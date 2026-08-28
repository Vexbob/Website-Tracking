"""Health-Ingest-Service — verarbeitet den JSON-Payload der Auto-Health-Export-App
(iPhone) und schreibt ihn in die typ-spezifischen Health-Tabellen.

Payload-Format (Original-Struktur der App, siehe
https://github.com/Lybron/health-auto-export/wiki):

    {
      "data": {
        "metrics": [
          {"name": "heart_rate", "units": "bpm",
           "data": [{"date": "...", "qty": 72, "Min": 60, "Max": 90, "Avg": 72, "source": "..."}]},
          {"name": "step_count", "units": "count",
           "data": [{"date": "...", "qty": 4321}]},
          {"name": "sleep_analysis", "units": "hr",
           "data": [{"date": "...", "asleep": 7.2, "inBed": 7.8,
                      "sleepStart": "...", "sleepEnd": "...",
                      "core": 4.1, "deep": 1.2, "rem": 1.5, "awake": 0.6}]},
          ...
        ],
        "workouts": [
          {"id": "...", "name": "Running", "start": "...", "end": "...",
           "duration": 1800, "activeEnergy": {"qty": 250, "units": "kcal"},
           "totalEnergy": {"qty": 300, "units": "kcal"},
           "distance": {"qty": 5000, "units": "m"},
           "avgHeartRate": {"qty": 145}, "maxHeartRate": {"qty": 172},
           "elevationAscended": {"qty": 30, "units": "m"},
           "heartRateRecovery": [...], "swimCadence": {...}, ...}
        ]
      }
    }

Regelbasiertes Mapping deckt alle vom User gewuenschten Metriken ab. Ist ein
``metric_type`` unbekannt, greift optional ``services.ai_health_parser``
(Gemini) als Fallback — analog zum Kassenbon-Parser. Schlaegt auch das fehl,
wird der Datenpunkt uebersprungen und geloggt statt den ganzen Batch zu
verwerfen.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("vexbob.health_ingest")

# Gemeinsamer Source-Wert fuer JSON-API-Sync UND manuellen CSV-Import: beide
# stammen letztlich aus derselben App, nur unterschiedlich exportiert. Gleicher
# Source-Wert sorgt dafuer, dass ein spaeterer automatisierter Sync denselben
# Tag ueberschreibt statt einen doppelten Datenpunkt anzulegen.
CSV_SOURCE = "auto_health_export"


# ---------------------------------------------------------------------------
# Metric-Mapping: Auto-Health-Export-Name -> interner metric_type
# ---------------------------------------------------------------------------
# Deckt exakt die vom User gewuenschten Gesundheitsmetriken ab (Namen laut
# Auto-Health-Export-Doku). Blutdruck/Blutzucker/Schlaf werden separat
# behandelt (eigene Tabellen), weil sie strukturell anders aufgebaut sind.
SIMPLE_METRIC_MAP = {
    "active_energy": "active_energy",
    "heart_rate": "heart_rate",
    "walking_heart_rate_average": "walking_hr_avg",
    "weight_body_mass": "weight",
    "heart_rate_variability": "hrv",
    "cardio_recovery": "cardio_recovery",
    "resting_heart_rate": "resting_hr",
    "step_count": "steps",
    "swimming_distance": "swim_distance",
    "vo2_max": "vo2_max",
}

# Auto-Health-Export nutzt fuer Blutdruck zwei getrennte Metriken
# (systolisch/diastolisch), die zeitlich zusammengefuehrt werden muessen.
BP_SYSTOLIC_NAME = "blood_pressure_systolic"
BP_DIASTOLIC_NAME = "blood_pressure_diastolic"
GLUCOSE_NAME = "blood_glucose"
SLEEP_NAME = "sleep_analysis"

KNOWN_METRIC_NAMES = set(SIMPLE_METRIC_MAP) | {
    BP_SYSTOLIC_NAME, BP_DIASTOLIC_NAME, GLUCOSE_NAME, SLEEP_NAME,
}


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        s2 = s.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(s2, fmt)
            except ValueError:
                continue
        return datetime.fromisoformat(s2.replace("Z", "+00:00"))
    except Exception:
        return None


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def ingest_payload(db, user_id: int, payload: dict) -> dict:
    """Nimmt den Auto-Health-Export-Payload entgegen und schreibt alle
    enthaltenen Metriken/Workouts idempotent in die DB.

    Returns ein Statistik-Dict mit importierten/uebersprungenen Zaehlern.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"metrics_imported": 0, "workouts_imported": 0, "sleep_imported": 0,
                "bp_imported": 0, "glucose_imported": 0, "skipped": ["invalid_payload"]}

    stats = {"metrics_imported": 0, "workouts_imported": 0, "sleep_imported": 0,
              "bp_imported": 0, "glucose_imported": 0, "skipped": []}

    # Blutdruck-Paare werden ueber den Zeitstempel zusammengefuehrt
    bp_pending: dict = {}

    for metric in (data.get("metrics") or []):
        if not isinstance(metric, dict):
            continue
        name = (metric.get("name") or "").strip()
        unit = metric.get("units")
        points = metric.get("data") or []

        if name == SLEEP_NAME:
            for p in points:
                if await _ingest_sleep_point(db, user_id, p):
                    stats["sleep_imported"] += 1
                else:
                    stats["skipped"].append(f"sleep:{p.get('date')}")
            continue

        if name in (BP_SYSTOLIC_NAME, BP_DIASTOLIC_NAME):
            for p in points:
                dt = _parse_dt(p.get("date"))
                if not dt:
                    stats["skipped"].append(f"{name}:invalid_date")
                    continue
                key = dt.isoformat()
                entry = bp_pending.setdefault(key, {"recorded_at": dt})
                entry["systolic" if name == BP_SYSTOLIC_NAME else "diastolic"] = _num(p.get("qty"))
            continue

        if name == GLUCOSE_NAME:
            for p in points:
                if await _ingest_glucose_point(db, user_id, p, unit):
                    stats["glucose_imported"] += 1
                else:
                    stats["skipped"].append(f"glucose:{p.get('date')}")
            continue

        metric_type = SIMPLE_METRIC_MAP.get(name)
        if not metric_type:
            resolved = await _resolve_unknown_metric(name)
            if resolved:
                metric_type = resolved
            else:
                stats["skipped"].append(f"unknown_metric:{name}")
                continue

        for p in points:
            if await _ingest_metric_point(db, user_id, metric_type, p, unit):
                stats["metrics_imported"] += 1
            else:
                stats["skipped"].append(f"{metric_type}:{p.get('date')}")

    for key, entry in bp_pending.items():
        if await _ingest_bp_point(db, user_id, entry):
            stats["bp_imported"] += 1
        else:
            stats["skipped"].append(f"blood_pressure:{key}")

    for w in (data.get("workouts") or []):
        if isinstance(w, dict) and await _ingest_workout(db, user_id, w):
            stats["workouts_imported"] += 1
        else:
            stats["skipped"].append(f"workout:{w.get('id') or w.get('name')}")

    return stats


async def _ingest_metric_point(db, user_id: int, metric_type: str, p: dict, unit: Optional[str]) -> bool:
    dt = _parse_dt(p.get("date"))
    if not dt:
        return False
    qty = _num(p.get("qty"))
    mn = _num(p.get("Min") or p.get("min"))
    mx = _num(p.get("Max") or p.get("max"))
    avg = _num(p.get("Avg") or p.get("avg"))
    source = (p.get("source") or "auto_health_export")[:120]
    try:
        await db.execute(
            "INSERT INTO health_metric_samples "
            "(user_id, metric_type, recorded_at, sample_date, qty, min_value, max_value, avg_value, unit, source) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) "
            "ON CONFLICT (user_id, metric_type, recorded_at, source) DO UPDATE SET "
            "qty=EXCLUDED.qty, min_value=EXCLUDED.min_value, max_value=EXCLUDED.max_value, "
            "avg_value=EXCLUDED.avg_value, unit=EXCLUDED.unit",
            user_id, metric_type, dt, dt.date(), qty, mn, mx, avg, unit, source)
        return True
    except Exception as e:
        logger.warning("Health-Metric-Insert fehlgeschlagen (%s): %s", metric_type, e)
        return False


async def _ingest_bp_point(db, user_id: int, entry: dict) -> bool:
    dt = entry.get("recorded_at")
    if not dt:
        return False
    try:
        await db.execute(
            "INSERT INTO health_blood_pressure (user_id, recorded_at, systolic, diastolic, source) "
            "VALUES ($1,$2,$3,$4,'auto_health_export') "
            "ON CONFLICT (user_id, recorded_at, source) DO UPDATE SET "
            "systolic=COALESCE(EXCLUDED.systolic, health_blood_pressure.systolic), "
            "diastolic=COALESCE(EXCLUDED.diastolic, health_blood_pressure.diastolic)",
            user_id, dt, entry.get("systolic"), entry.get("diastolic"))
        return True
    except Exception as e:
        logger.warning("Blutdruck-Insert fehlgeschlagen: %s", e)
        return False


async def _ingest_glucose_point(db, user_id: int, p: dict, unit: Optional[str]) -> bool:
    dt = _parse_dt(p.get("date"))
    if not dt:
        return False
    try:
        await db.execute(
            "INSERT INTO health_blood_glucose (user_id, recorded_at, value, unit, source) "
            "VALUES ($1,$2,$3,$4,'auto_health_export') "
            "ON CONFLICT (user_id, recorded_at, source) DO UPDATE SET value=EXCLUDED.value",
            user_id, dt, _num(p.get("qty")), unit or "mg/dL")
        return True
    except Exception as e:
        logger.warning("Blutzucker-Insert fehlgeschlagen: %s", e)
        return False


def _hours_to_min(v) -> Optional[float]:
    """Auto Health Export liefert Schlafphasen in Stunden -> Minuten fuer
    feingranulare Anzeige im Frontend."""
    n = _num(v)
    return None if n is None else round(n * 60, 1)


async def _ingest_sleep_point(db, user_id: int, p: dict) -> bool:
    sleep_start = _parse_dt(p.get("sleepStart"))
    sleep_end = _parse_dt(p.get("sleepEnd"))
    d = _parse_dt(p.get("date"))
    sample_date = sleep_start or d
    if not sample_date:
        return False
    try:
        await db.execute(
            "INSERT INTO health_sleep "
            "(user_id, sleep_date, sleep_start, sleep_end, in_bed_minutes, asleep_minutes, "
            "core_minutes, deep_minutes, rem_minutes, awake_minutes, source) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'auto_health_export') "
            "ON CONFLICT (user_id, sleep_date, source) DO UPDATE SET "
            "sleep_start=EXCLUDED.sleep_start, sleep_end=EXCLUDED.sleep_end, "
            "in_bed_minutes=EXCLUDED.in_bed_minutes, asleep_minutes=EXCLUDED.asleep_minutes, "
            "core_minutes=EXCLUDED.core_minutes, deep_minutes=EXCLUDED.deep_minutes, "
            "rem_minutes=EXCLUDED.rem_minutes, awake_minutes=EXCLUDED.awake_minutes",
            user_id, sample_date.date(), sleep_start, sleep_end,
            _hours_to_min(p.get("inBed")), _hours_to_min(p.get("asleep")),
            _hours_to_min(p.get("core")), _hours_to_min(p.get("deep")),
            _hours_to_min(p.get("rem")), _hours_to_min(p.get("awake")))
        return True
    except Exception as e:
        logger.warning("Schlaf-Insert fehlgeschlagen: %s", e)
        return False


async def _ingest_workout(db, user_id: int, w: dict) -> bool:
    """Kopf-Tabelle + flexible Zusatzmetriken. Bewusst OHNE Routendaten
    (GPS-Punkte werden vom Payload ignoriert, falls die App sie mitschickt)."""
    external_id = f"{w.get('id') or w.get('name') or ''}:{w.get('start') or ''}"
    start_at = _parse_dt(w.get("start"))
    if external_id.strip(":") == "" or not start_at:
        return False
    end_at = _parse_dt(w.get("end"))
    duration_raw = _num(w.get("duration"))
    # Auto Health Export liefert die Dauer in Sekunden
    duration_min = None if duration_raw is None else round(duration_raw / 60, 1)

    def _qty(key):
        v = w.get(key)
        return _num(v.get("qty")) if isinstance(v, dict) else _num(v)

    try:
        wid = await db.fetchval(
            "INSERT INTO health_workouts "
            "(user_id, external_id, workout_type, start_at, end_at, duration_min, "
            "active_energy_kcal, total_energy_kcal, distance_m, avg_heart_rate, max_heart_rate, "
            "elevation_m, source) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'auto_health_export') "
            "ON CONFLICT (user_id, external_id) DO UPDATE SET "
            "end_at=EXCLUDED.end_at, duration_min=EXCLUDED.duration_min, "
            "active_energy_kcal=EXCLUDED.active_energy_kcal, total_energy_kcal=EXCLUDED.total_energy_kcal, "
            "distance_m=EXCLUDED.distance_m, avg_heart_rate=EXCLUDED.avg_heart_rate, "
            "max_heart_rate=EXCLUDED.max_heart_rate, elevation_m=EXCLUDED.elevation_m "
            "RETURNING id",
            user_id, external_id, w.get("name"), start_at, end_at, duration_min,
            _qty("activeEnergy"), _qty("totalEnergy"), _qty("distance"),
            _qty("avgHeartRate"), _qty("maxHeartRate"), _qty("elevationAscended"))
    except Exception as e:
        logger.warning("Workout-Insert fehlgeschlagen: %s", e)
        return False

    if not wid:
        return False

    # Zusatzmetriken (je Sportart unterschiedlich) als Key/Value-Zeilen
    extra_keys = [
        "swimCadence", "cyclingCadence", "cyclingSpeed", "cyclingPower",
        "flightsClimbed", "stepCount", "intensity", "humidity", "temperature",
    ]
    for k in extra_keys:
        v = w.get(k)
        if v is None:
            continue
        val = _num(v.get("qty")) if isinstance(v, dict) else _num(v)
        u = v.get("units") if isinstance(v, dict) else None
        if val is None:
            continue
        try:
            await db.execute(
                "INSERT INTO health_workout_metrics (workout_id, metric_key, value, unit) "
                "VALUES ($1,$2,$3,$4) "
                "ON CONFLICT (workout_id, metric_key) DO UPDATE SET value=EXCLUDED.value, unit=EXCLUDED.unit",
                wid, k, val, u)
        except Exception as e:
            logger.warning("Workout-Metric-Insert fehlgeschlagen (%s): %s", k, e)
    return True


# ---------------------------------------------------------------------------
# CSV-Import (manueller Backfill) — deutlich kompakter als JSON-Export.
# Auto Health Export exportiert im CSV-Modus zwei relevante Dateitypen:
#   1) Eine Tages-CSV mit allen einfachen Gesundheitsmetriken als Spalten
#      (Header beginnt mit "Datum/Uhrzeit").
#   2) Eine Workouts-Uebersichts-CSV mit einer Zeile pro Workout (Header
#      beginnt mit "Workout Type").
# Die vielen einzelnen Pro-Workout-Metrik-CSVs (Herzfrequenz/Aktive Energie
# je Workout) werden bewusst NICHT eingelesen — ihre relevanten Aggregate
# (Ø/Max-HF, Distanz, Energie, ...) stecken bereits in der Workouts-CSV.
# ---------------------------------------------------------------------------
def _parse_csv_dt(s: Optional[str]) -> Optional[datetime]:
    """Wie _parse_dt, ergaenzt aber fehlende Zeitzone um UTC (CSV-Zeitstempel
    sind lokale Geraetezeit ohne Offset; TIMESTAMPTZ-Spalten brauchen eine
    tz-aware datetime, sonst lehnt asyncpg den Wert ab)."""
    dt = _parse_dt(s)
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _csv_date_str(s: Optional[str]) -> Optional[str]:
    """Haengt ein UTC-Offset an einen CSV-Zeitstempel an (der keine Zeitzone
    enthaelt), damit die bestehenden Insert-Helfer (die intern ``_parse_dt``
    nutzen, welches wiederum ein Offset erwartet) den Wert tz-aware
    interpretieren. Ohne Offset wuerde asyncpg eine naive datetime an eine
    TIMESTAMPTZ-Spalte fehlerhaft/uneindeutig weiterreichen."""
    if not s:
        return None
    s = s.strip()
    return s if not s else f"{s} +0000"


def _find_col(header: list, *keywords: str) -> Optional[int]:
    """Findet die Spalte, deren Header-Zelle ALLE Keywords enthaelt
    (case-insensitive). Robust gegen leicht abweichende Einheiten-Suffixe."""
    for i, cell in enumerate(header):
        low = cell.lower()
        if all(kw.lower() in low for kw in keywords):
            return i
    return None


def _row_num(row: list, idx: Optional[int]) -> Optional[float]:
    if idx is None or idx >= len(row):
        return None
    v = (row[idx] or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _row_str(row: list, idx: Optional[int]) -> Optional[str]:
    if idx is None or idx >= len(row):
        return None
    v = (row[idx] or "").strip()
    return v or None


def detect_csv_kind(header: list) -> Optional[str]:
    """Erkennt anhand der ersten Spalte, ob es sich um die Tages-Gesundheits-
    CSV oder die Workouts-Uebersicht handelt. Gibt None zurueck, wenn keines
    von beidem erkannt wird (Datei wird dann komplett uebersprungen)."""
    if not header:
        return None
    first = header[0].strip().lower()
    if "workout type" in first:
        return "workouts"
    if "datum" in first or "date" in first:
        return "health_metrics"
    return None


async def ingest_csv_file(db, user_id: int, filename: str, raw: bytes) -> dict:
    """Liest eine einzelne CSV-Datei ein und delegiert an den passenden
    Parser. Gibt ein Statistik-Dict zurueck (gleiche Struktur wie
    ``ingest_payload``, jeweils nur die relevanten Zaehler befuellt)."""
    empty_stats = {"metrics_imported": 0, "workouts_imported": 0, "sleep_imported": 0,
                    "bp_imported": 0, "glucose_imported": 0, "skipped": []}
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except Exception as e:
            empty_stats["skipped"].append(f"{filename}:decode_error:{e}")
            return empty_stats

    reader = list(csv.reader(io.StringIO(text), delimiter=";"))
    if not reader:
        empty_stats["skipped"].append(f"{filename}:empty_file")
        return empty_stats
    header = [c.strip() for c in reader[0]]
    kind = detect_csv_kind(header)
    rows = reader[1:]

    if kind == "health_metrics":
        return await _ingest_health_metrics_csv(db, user_id, header, rows)
    if kind == "workouts":
        return await _ingest_workouts_csv(db, user_id, header, rows)
    empty_stats["skipped"].append(f"{filename}:unrecognized_csv_format")
    return empty_stats


async def _ingest_health_metrics_csv(db, user_id: int, header: list, rows: list) -> dict:
    stats = {"metrics_imported": 0, "workouts_imported": 0, "sleep_imported": 0,
              "bp_imported": 0, "glucose_imported": 0, "skipped": []}

    col = {
        "active_energy": _find_col(header, "Aktive Energie"),
        "bp_sys": _find_col(header, "Blutdruck", "Systolisch"),
        "bp_dia": _find_col(header, "Blutdruck", "Diastolisch"),
        "glucose": _find_col(header, "Blutzucker"),
        "walking_hr": _find_col(header, "Herzfrequenz beim Gehen"),
        "weight": _find_col(header, "Gewicht"),
        "hr_min": _find_col(header, "Herzfrequenz [Min]"),
        "hr_max": _find_col(header, "Herzfrequenz [Max]"),
        "hr_avg": _find_col(header, "Herzfrequenz [Durchschn"),
        "hrv": _find_col(header, "Herzfrequenzvariabilität"),
        "cardio_recovery": _find_col(header, "Kardiorespiratorische Erholung"),
        "resting_hr": _find_col(header, "Ruhepuls"),
        "sleep_asleep": _find_col(header, "Schlafanalyse [Schlafend]"),
        "sleep_inbed": _find_col(header, "Schlafanalyse [Im Bett]"),
        "sleep_core": _find_col(header, "Schlafanalyse [Kern]"),
        "sleep_deep": _find_col(header, "Schlafanalyse [Tief]"),
        "sleep_rem": _find_col(header, "Schlafanalyse [REM]"),
        "sleep_awake": _find_col(header, "Schlafanalyse [Wach]"),
        "steps": _find_col(header, "Schrittzählung"),
        "swim_distance": _find_col(header, "Schwimmdistanz"),
        "vo2_max": _find_col(header, "VO2 max"),
    }

    for row in rows:
        if not row or not (row[0] or "").strip():
            continue
        date_str = _csv_date_str(row[0])
        dt = _parse_csv_dt(row[0])
        if not dt:
            stats["skipped"].append(f"health_metrics_csv:invalid_date:{row[0]}")
            continue

        simple_cols = [
            ("active_energy", "active_energy"), ("walking_hr", "walking_hr_avg"),
            ("weight", "weight"), ("hrv", "hrv"), ("cardio_recovery", "cardio_recovery"),
            ("resting_hr", "resting_hr"), ("steps", "steps"),
            ("swim_distance", "swim_distance"), ("vo2_max", "vo2_max"),
        ]
        for col_key, metric_type in simple_cols:
            val = _row_num(row, col.get(col_key))
            if val is None:
                continue
            p = {"date": date_str, "qty": val}
            if await _ingest_metric_point(db, user_id, metric_type, p, None):
                stats["metrics_imported"] += 1
            else:
                stats["skipped"].append(f"{metric_type}:{row[0]}")

        hr_min = _row_num(row, col.get("hr_min"))
        hr_max = _row_num(row, col.get("hr_max"))
        hr_avg = _row_num(row, col.get("hr_avg"))
        if hr_min is not None or hr_max is not None or hr_avg is not None:
            p = {"date": date_str, "qty": hr_avg, "Min": hr_min, "Max": hr_max, "Avg": hr_avg}
            if await _ingest_metric_point(db, user_id, "heart_rate", p, None):
                stats["metrics_imported"] += 1
            else:
                stats["skipped"].append(f"heart_rate:{row[0]}")

        sys_v = _row_num(row, col.get("bp_sys"))
        dia_v = _row_num(row, col.get("bp_dia"))
        if sys_v is not None or dia_v is not None:
            entry = {"recorded_at": dt, "systolic": sys_v, "diastolic": dia_v}
            if await _ingest_bp_point(db, user_id, entry):
                stats["bp_imported"] += 1
            else:
                stats["skipped"].append(f"blood_pressure:{row[0]}")

        glucose_v = _row_num(row, col.get("glucose"))
        if glucose_v is not None:
            if await _ingest_glucose_point(db, user_id, {"date": date_str, "qty": glucose_v}, "mmol/L"):
                stats["glucose_imported"] += 1
            else:
                stats["skipped"].append(f"blood_glucose:{row[0]}")

        sleep_vals = {k: _row_num(row, col.get(f"sleep_{k}")) for k in
                      ("asleep", "inbed", "core", "deep", "rem", "awake")}
        if any(v is not None for v in sleep_vals.values()):
            p = {
                "date": date_str, "sleepStart": None, "sleepEnd": None,
                "asleep": sleep_vals["asleep"], "inBed": sleep_vals["inbed"],
                "core": sleep_vals["core"], "deep": sleep_vals["deep"],
                "rem": sleep_vals["rem"], "awake": sleep_vals["awake"],
            }
            if await _ingest_sleep_point(db, user_id, p):
                stats["sleep_imported"] += 1
            else:
                stats["skipped"].append(f"sleep:{row[0]}")

    return stats


def _parse_duration_hms(s: Optional[str]) -> Optional[float]:
    """Wandelt 'HH:MM:SS' (Workouts-CSV) in Minuten (float) um."""
    if not s:
        return None
    parts = s.strip().split(":")
    try:
        if len(parts) == 3:
            h, m, sec = (float(p) for p in parts)
            return round(h * 60 + m + sec / 60, 1)
        if len(parts) == 2:
            m, sec = (float(p) for p in parts)
            return round(m + sec / 60, 1)
    except ValueError:
        return None
    return None


async def _ingest_workouts_csv(db, user_id: int, header: list, rows: list) -> dict:
    stats = {"metrics_imported": 0, "workouts_imported": 0, "sleep_imported": 0,
              "bp_imported": 0, "glucose_imported": 0, "skipped": []}

    col = {
        "start": _find_col(header, "Start"),
        "end": _find_col(header, "End"),
        "duration": _find_col(header, "Duration"),
        "active_energy": _find_col(header, "Aktive Energie"),
        "resting_energy": _find_col(header, "Ruheeinträge"),
        "intensity": _find_col(header, "Intensität"),
        "max_hr": _find_col(header, "Max.", "Herzfrequenz"),
        "avg_hr": _find_col(header, "Durchschn.", "Herzfrequenz"),
        "distance_km": _find_col(header, "Distanz"),
        "max_speed": _find_col(header, "Max. Geschwindigkeit"),
        "avg_speed": _find_col(header, "Durchschnittsgeschwindigkeit"),
        "flights": _find_col(header, "Etagen gestiegen"),
        "elevation_up": _find_col(header, "Aufgestiegene Höhe"),
        "elevation_down": _find_col(header, "Abgestiegene Höhe"),
        "step_count": _find_col(header, "Schrittzählung"),
        "cadence": _find_col(header, "Schrittfrequenz"),
        "swim_strokes": _find_col(header, "Anzahl der Schwimmzüge"),
        "swim_cadence": _find_col(header, "Schwimmkadenz"),
        "lap_length": _find_col(header, "Rundenlänge"),
        "swolf": _find_col(header, "SWOLF"),
        "temperature": _find_col(header, "Temperatur"),
        "humidity": _find_col(header, "Luftfeuchtigkeit"),
    }

    for row in rows:
        if not row or not (row[0] or "").strip():
            continue
        workout_type = _row_str(row, 0)
        start_at = _parse_csv_dt(_row_str(row, col.get("start")))
        if not start_at:
            stats["skipped"].append(f"workout_csv:invalid_start:{row[:2]}")
            continue
        end_at = _parse_csv_dt(_row_str(row, col.get("end")))
        duration_min = _parse_duration_hms(_row_str(row, col.get("duration")))
        active_kcal = _row_num(row, col.get("active_energy"))
        resting_kcal = _row_num(row, col.get("resting_energy"))
        total_kcal = None
        if active_kcal is not None or resting_kcal is not None:
            total_kcal = (active_kcal or 0) + (resting_kcal or 0)
        distance_km = _row_num(row, col.get("distance_km"))
        distance_m = None if distance_km is None else distance_km * 1000

        external_id = f"{workout_type or 'workout'}:{start_at.isoformat()}"
        try:
            wid = await db.fetchval(
                "INSERT INTO health_workouts "
                "(user_id, external_id, workout_type, start_at, end_at, duration_min, "
                "active_energy_kcal, total_energy_kcal, distance_m, avg_heart_rate, max_heart_rate, "
                "elevation_m, source) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) "
                "ON CONFLICT (user_id, external_id) DO UPDATE SET "
                "end_at=EXCLUDED.end_at, duration_min=EXCLUDED.duration_min, "
                "active_energy_kcal=EXCLUDED.active_energy_kcal, total_energy_kcal=EXCLUDED.total_energy_kcal, "
                "distance_m=EXCLUDED.distance_m, avg_heart_rate=EXCLUDED.avg_heart_rate, "
                "max_heart_rate=EXCLUDED.max_heart_rate, elevation_m=EXCLUDED.elevation_m "
                "RETURNING id",
                user_id, external_id, workout_type, start_at, end_at, duration_min,
                active_kcal, total_kcal, distance_m,
                _row_num(row, col.get("avg_hr")), _row_num(row, col.get("max_hr")),
                _row_num(row, col.get("elevation_up")), CSV_SOURCE)
        except Exception as e:
            logger.warning("Workout-CSV-Insert fehlgeschlagen: %s", e)
            stats["skipped"].append(f"workout:{external_id}")
            continue

        if not wid:
            stats["skipped"].append(f"workout:{external_id}")
            continue
        stats["workouts_imported"] += 1

        extra = {
            "resting_energy_kcal": resting_kcal,
            "intensity_kcal_h_kg": _row_num(row, col.get("intensity")),
            "max_speed_kmh": _row_num(row, col.get("max_speed")),
            "avg_speed_kmh": _row_num(row, col.get("avg_speed")),
            "flights_climbed": _row_num(row, col.get("flights")),
            "elevation_descended_m": _row_num(row, col.get("elevation_down")),
            "step_count": _row_num(row, col.get("step_count")),
            "cadence_spm": _row_num(row, col.get("cadence")),
            "swim_stroke_count": _row_num(row, col.get("swim_strokes")),
            "swim_cadence_spm": _row_num(row, col.get("swim_cadence")),
            "lap_length_m": _row_num(row, col.get("lap_length")),
            "swolf": _row_num(row, col.get("swolf")),
            "temperature_c": _row_num(row, col.get("temperature")),
            "humidity_pct": _row_num(row, col.get("humidity")),
        }
        for key, val in extra.items():
            if not val:
                continue
            try:
                await db.execute(
                    "INSERT INTO health_workout_metrics (workout_id, metric_key, value, unit) "
                    "VALUES ($1,$2,$3,NULL) "
                    "ON CONFLICT (workout_id, metric_key) DO UPDATE SET value=EXCLUDED.value",
                    wid, key, val)
            except Exception as e:
                logger.warning("Workout-CSV-Metric-Insert fehlgeschlagen (%s): %s", key, e)

    return stats


async def _resolve_unknown_metric(name: str) -> Optional[str]:
    """Optionaler AI-Fallback fuer unbekannte Metric-Namen (z.B. nach einem
    App-Update mit neuer Bezeichnung). Nutzt denselben Gemini-Client wie
    der Kassenbon-Parser. Gibt bei Erfolg einen internen metric_type aus
    SIMPLE_METRIC_MAP zurueck, sonst None (Datenpunkt wird uebersprungen)."""
    try:
        from services.ai_health_parser import resolve_metric_name
        return await resolve_metric_name(name, sorted(set(SIMPLE_METRIC_MAP.values())))
    except Exception as e:
        logger.info("AI-Metric-Resolver nicht verfuegbar/fehlgeschlagen fuer '%s': %s", name, e)
        return None
