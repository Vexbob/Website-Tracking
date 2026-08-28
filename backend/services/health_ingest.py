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

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("vexbob.health_ingest")


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
