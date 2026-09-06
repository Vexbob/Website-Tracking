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
           "elevation": {"ascent": 30, "descent": 12, "units": "m"},
           "heartRateData": [...], "heartRateRecovery": [...],
           "swimCadence": {...}, ...}
        ]
        # Workouts kommen in ZWEI Exportvarianten mit unterschiedlichen
        # Feldnamen und je eigener id -- siehe Abschnitt "Workouts (JSON)".
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
from datetime import date, datetime, timedelta, timezone
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
    # v1.44.0 nachgezogen, nachdem der User sie im Export aktiviert hat:
    "blood_oxygen_saturation": "blood_oxygen",
    "walking_running_distance": "walking_distance",
    "walking_speed": "walking_speed",
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


def merge_ingest_stats(total: dict, sub: dict) -> dict:
    """Summiert die Zaehler eines Sub-Stats-Dicts in ein Total-Dict.

    Wird sowohl vom Multi-File-CSV-Router als auch vom universellen Sync-
    Endpoint benutzt, damit beide dieselben Feldnamen aggregieren."""
    if not isinstance(sub, dict):
        return total
    for key in ("metrics_imported", "workouts_imported", "sleep_imported",
                "bp_imported", "glucose_imported"):
        total[key] = total.get(key, 0) + int(sub.get(key, 0) or 0)
    skipped = sub.get("skipped") or []
    if skipped:
        total.setdefault("skipped", []).extend(skipped)
    return total


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
    # v1.44.0: ``sleepDate`` erlaubt es dem Aufrufer, das Nacht-Datum explizit
    # vorzugeben. Noetig fuer die Schlaf-CSV: dort beginnt eine Nacht oft vor
    # Mitternacht (Start 31.08. 20:38 gehoert zur Nacht auf den 01.09.). Aus
    # ``sleep_start`` abgeleitet landete sie auf dem 31.08. und haette die
    # Vornacht ueberschrieben (UNIQUE user_id, sleep_date, source).
    explicit = p.get("sleepDate")
    if isinstance(explicit, date) and not isinstance(explicit, datetime):
        sample_date = explicit
    else:
        base = sleep_start or d
        if not base:
            return False
        sample_date = base.date()
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
            user_id, sample_date, sleep_start, sleep_end,
            _hours_to_min(p.get("inBed")), _hours_to_min(p.get("asleep")),
            _hours_to_min(p.get("core")), _hours_to_min(p.get("deep")),
            _hours_to_min(p.get("rem")), _hours_to_min(p.get("awake")))
        return True
    except Exception as e:
        logger.warning("Schlaf-Insert fehlgeschlagen: %s", e)
        return False


# ---------------------------------------------------------------------------
# Workouts (JSON) — zwei Exportvarianten desselben Trainings
# ---------------------------------------------------------------------------
# Auto Health Export liefert dasselbe Workout je nach Exporteinstellung in zwei
# Auspraegungen. Beide tragen identische Start- und Endzeiten, aber jeweils eine
# EIGENE, zufaellige "id" -- und jede enthaelt Felder, die der anderen fehlen:
#
#   Variante A: avgHeartRate/maxHeartRate/heartRate{min,avg,max}, die
#               Minutenreihe heartRateData + heartRateRecovery,
#               activeEnergyBurned, elevationUp, lapLength.
#   Variante B: activeEnergy + totalEnergy, elevation{ascent,descent},
#               stepCount/stepCadence/flightsClimbed, swimCadence und
#               totalSwimmingStrokeCount -- dafuer alle Pulswerte auf 0.
#
# Die App-id ist deshalb KEINE Identitaet: zugeordnet wird ueber (Nutzer, Typ,
# Startzeit), damit beide Exporte dieselbe Zeile fuellen statt zwei halbe
# anzulegen. Beim Zusammenfuehren gewinnt der belegte Wert; eine fehlende
# Groesse kommt als 0 oder als leeres Array an und darf einen bereits
# importierten Wert nie ueberschreiben.
#
# Zeitfenster der Zuordnung: beide Varianten liefern die Startzeit auf die
# Sekunde gleich, die zwei Minuten fangen nur Rundungen der App ab. Groesser
# darf es nicht werden -- zwei echte Trainings koennen dicht aufeinander folgen.
_WORKOUT_MATCH_WINDOW = timedelta(seconds=120)


def _pos(v: Optional[float]) -> Optional[float]:
    """None fuer 0. In beiden Exporten heisst 0 "nicht gemessen" (die
    Puls-Felder der einen Variante stehen durchgehend auf 0, Schrittzahlen
    beim Schwimmen ebenso). Ein echter Messwert 0 geht dabei verloren -- das
    ist gewollt, sonst ueberschreibt die leere Variante die volle."""
    if v is None:
        return None
    return None if abs(v) < 1e-9 else v


def _qty_unit(w: dict, *keys) -> tuple:
    """Erster belegter Schluessel als (Wert, Einheit). Mehrere Namen, weil die
    Varianten dieselbe Groesse unterschiedlich nennen (activeEnergy vs.
    activeEnergyBurned)."""
    for k in keys:
        v = w.get(k)
        if isinstance(v, dict):
            n = _pos(_num(v.get("qty")))
            if n is not None:
                return n, (v.get("units") or None)
        elif v is not None:
            n = _pos(_num(v))
            if n is not None:
                return n, None
    return None, None


def _workout_distance_m(w: dict) -> Optional[float]:
    """Distanz in Metern. Das Einheitenfeld wechselt je Variante und Sportart:
    dasselbe Bahnschwimmen kommt einmal als 1,825 km und einmal als 1825 m."""
    qty, unit = _qty_unit(w, "distance")
    if qty is None:
        return None
    if (unit or "").strip().lower() in ("m", "meter", "meters"):
        return qty
    # Default km -- ausser die Zahl ist dafuer zu gross: ueber 300 km gibt es
    # keine einzelne Trainingseinheit mehr, dann sind es schon Meter (vgl.
    # Migration 026, dieselbe Verwechslung im CSV-Export).
    return qty if qty > _CSV_DIST_KM_MAX else qty * 1000


def _workout_speed_kmh(w: dict) -> Optional[float]:
    """O-Geschwindigkeit in km/h. Beim Schwimmen tragen BEIDE Varianten das
    Etikett "m/hr", die eine liefert aber echte Meter pro Stunde (1424,9), die
    andere denselben Wert bereits in km/h (1,42)."""
    qty, unit = _qty_unit(w, "speed")
    if qty is None:
        return None
    if (unit or "").strip().lower().startswith("km"):
        return qty
    return qty / 1000 if qty > _CSV_SPEED_KMH_MAX else qty


def _workout_lap_length_m(w: dict) -> Optional[float]:
    """Bahnlaenge in Metern. Etikett "m", Wert 0,025 -- gemeint sind
    Kilometer, also eine 25-m-Bahn."""
    qty, _unit = _qty_unit(w, "lapLength")
    if qty is None:
        return None
    return qty * 1000 if qty < 1 else qty


def _workout_energy_kcal(w: dict, *keys) -> Optional[float]:
    qty, unit = _qty_unit(w, *keys)
    if qty is None:
        return None
    return round(qty / 4.184, 1) if (unit or "").strip().lower() == "kj" else qty


def _workout_elevation(w: dict) -> tuple:
    """(Aufstieg, Abstieg) in Metern. Variante A liefert elevationUp als
    einzelnen Wert, Variante B ein Objekt mit ascent/descent."""
    el = w.get("elevation")
    if isinstance(el, dict):
        up = _pos(_num(el.get("ascent")))
        down = _pos(_num(el.get("descent")))
        if up is not None or down is not None:
            return up, down
    up, _u = _qty_unit(w, "elevationUp", "elevationAscended")
    down, _d = _qty_unit(w, "elevationDown", "elevationDescended")
    return up, down


def _nested_qty(obj, key) -> Optional[float]:
    """heartRate: {"avg": {"qty": 134, "units": "bpm"}} -- eine Ebene tiefer
    als avgHeartRate, sonst identisch."""
    v = obj.get(key) if isinstance(obj, dict) else None
    if isinstance(v, dict):
        return _pos(_num(v.get("qty")))
    return _pos(_num(v))


def _hr_samples(w: dict) -> list:
    """Puls-Minutenreihe als Liste von Dicts. heartRateData deckt das Training
    ab, heartRateRecovery die Sekunden danach -- beide mit denselben Feldern
    (Min/Max/Avg), aber getrennt gehalten, weil die Erholungswerte nach dem
    Workout-Ende liegen und den Verlauf sonst verzerren."""
    out: dict = {}
    for key, kind in (("heartRateData", "workout"), ("heartRateRecovery", "recovery")):
        for e in (w.get(key) or []):
            if not isinstance(e, dict):
                continue
            at = _parse_dt(e.get("date"))
            if at is None:
                continue
            mn = _plausible_hr(_pos(_num(e.get("Min", e.get("min")))))
            mx = _plausible_hr(_pos(_num(e.get("Max", e.get("max")))))
            av = _plausible_hr(_pos(_num(e.get("Avg", e.get("avg")))))
            if mn is None and mx is None and av is None:
                continue
            if av is None:
                av = mx if mn is None else (mn if mx is None else (mn + mx) / 2)
            out[(kind, at)] = {"kind": kind, "at": at, "min": mn, "max": mx, "avg": av}
    return sorted(out.values(), key=lambda s: (s["kind"], s["at"]))


def _workout_heart_rate(w: dict, samples: list) -> tuple:
    """(O, Max, Min) in bpm. Fehlen die Aggregate, werden sie aus der
    Minutenreihe gerechnet -- ungewichtet, was bei einem Messpunkt je Minute
    dem Mittel entspricht."""
    hr = w.get("heartRate") if isinstance(w.get("heartRate"), dict) else {}
    avg = _qty_unit(w, "avgHeartRate")[0]
    if avg is None:
        avg = _nested_qty(hr, "avg")
    mx = _qty_unit(w, "maxHeartRate")[0]
    if mx is None:
        mx = _nested_qty(hr, "max")
    mn = _qty_unit(w, "minHeartRate")[0]
    if mn is None:
        mn = _nested_qty(hr, "min")

    during = [s for s in samples if s["kind"] == "workout"]
    if during:
        if avg is None:
            vals = [s["avg"] for s in during if s["avg"] is not None]
            avg = sum(vals) / len(vals) if vals else None
        if mx is None:
            vals = [v for v in (s["max"] if s["max"] is not None else s["avg"]
                                for s in during) if v is not None]
            mx = max(vals) if vals else None
        if mn is None:
            vals = [v for v in (s["min"] if s["min"] is not None else s["avg"]
                                for s in during) if v is not None]
            mn = min(vals) if vals else None
    return _plausible_hr(avg), _plausible_hr(mx), _plausible_hr(mn)


async def _upsert_workout_head(db, user_id: int, external_id: str, wtype: Optional[str],
                                start_at: datetime, end_at: Optional[datetime],
                                duration_min: Optional[float], active_kcal: Optional[float],
                                total_kcal: Optional[float], distance_m: Optional[float],
                                avg_hr: Optional[float], max_hr: Optional[float],
                                min_hr: Optional[float], elevation_m: Optional[float]):
    """Sucht das Workout ueber (Nutzer, Typ, Startzeit) und fuellt nur die
    Luecken; existiert keines, wird es angelegt. COALESCE in dieser Richtung
    heisst: ein neu gelieferter Wert gewinnt, ein fehlender laesst den
    bestehenden stehen."""
    row = await db.fetchrow(
        "SELECT id FROM health_workouts "
        "WHERE user_id=$1 AND start_at BETWEEN $2 AND $3 "
        "  AND (workout_type IS NOT DISTINCT FROM $4::text "
        "       OR workout_type IS NULL OR $4::text IS NULL) "
        "ORDER BY ABS(EXTRACT(EPOCH FROM (start_at - $5::timestamptz))) LIMIT 1",
        user_id, start_at - _WORKOUT_MATCH_WINDOW, start_at + _WORKOUT_MATCH_WINDOW,
        wtype, start_at)

    if row:
        await db.execute(
            "UPDATE health_workouts SET "
            "workout_type=COALESCE(workout_type,$2), end_at=COALESCE($3,end_at), "
            "duration_min=COALESCE($4,duration_min), "
            "active_energy_kcal=COALESCE($5,active_energy_kcal), "
            "total_energy_kcal=COALESCE($6,total_energy_kcal), "
            "distance_m=COALESCE($7,distance_m), "
            "avg_heart_rate=COALESCE($8,avg_heart_rate), "
            "max_heart_rate=COALESCE($9,max_heart_rate), "
            "min_heart_rate=COALESCE($10,min_heart_rate), "
            "elevation_m=COALESCE($11,elevation_m) "
            "WHERE id=$1",
            row["id"], wtype, end_at, duration_min, active_kcal, total_kcal,
            distance_m, avg_hr, max_hr, min_hr, elevation_m)
        return row["id"]

    return await db.fetchval(
        "INSERT INTO health_workouts "
        "(user_id, external_id, workout_type, start_at, end_at, duration_min, "
        "active_energy_kcal, total_energy_kcal, distance_m, avg_heart_rate, "
        "max_heart_rate, min_heart_rate, elevation_m, source) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,'auto_health_export') "
        "ON CONFLICT (user_id, external_id) DO UPDATE SET "
        "end_at=COALESCE(EXCLUDED.end_at, health_workouts.end_at), "
        "duration_min=COALESCE(EXCLUDED.duration_min, health_workouts.duration_min), "
        "active_energy_kcal=COALESCE(EXCLUDED.active_energy_kcal, health_workouts.active_energy_kcal), "
        "total_energy_kcal=COALESCE(EXCLUDED.total_energy_kcal, health_workouts.total_energy_kcal), "
        "distance_m=COALESCE(EXCLUDED.distance_m, health_workouts.distance_m), "
        "avg_heart_rate=COALESCE(EXCLUDED.avg_heart_rate, health_workouts.avg_heart_rate), "
        "max_heart_rate=COALESCE(EXCLUDED.max_heart_rate, health_workouts.max_heart_rate), "
        "min_heart_rate=COALESCE(EXCLUDED.min_heart_rate, health_workouts.min_heart_rate), "
        "elevation_m=COALESCE(EXCLUDED.elevation_m, health_workouts.elevation_m) "
        "RETURNING id",
        user_id, external_id, wtype, start_at, end_at, duration_min,
        active_kcal, total_kcal, distance_m, avg_hr, max_hr, min_hr, elevation_m)


async def _ingest_workout(db, user_id: int, w: dict) -> bool:
    """Kopf-Tabelle + Zusatzmetriken + Puls-Minutenreihe. Bewusst OHNE
    Routendaten (das ``route``-Array wird ignoriert, auch wenn die App es
    mitschickt)."""
    start_at = _parse_dt(w.get("start"))
    if not start_at:
        return False
    wtype = (w.get("name") or "").strip() or None
    external_id = f"{w.get('id') or wtype or 'workout'}:{w.get('start') or ''}"
    end_at = _parse_dt(w.get("end"))
    duration_raw = _num(w.get("duration"))
    # Auto Health Export liefert die Dauer in Sekunden
    duration_min = None if duration_raw is None else round(duration_raw / 60, 1)

    samples = _hr_samples(w)
    avg_hr, max_hr, min_hr = _workout_heart_rate(w, samples)
    elev_up, elev_down = _workout_elevation(w)
    active_kcal = _workout_energy_kcal(w, "activeEnergy", "activeEnergyBurned")
    total_kcal = _workout_energy_kcal(w, "totalEnergy", "totalEnergyBurned")

    try:
        wid = await _upsert_workout_head(
            db, user_id, external_id, wtype, start_at, end_at, duration_min,
            active_kcal, total_kcal, _workout_distance_m(w),
            avg_hr, max_hr, min_hr, elev_up)
    except Exception as e:
        logger.warning("Workout-Insert fehlgeschlagen: %s", e)
        return False

    if not wid:
        return False

    # Zusatzmetriken (je Sportart unterschiedlich) unter denselben kanonischen
    # Schluesseln wie beim CSV-Import -- sonst stuende dieselbe Groesse je nach
    # Importweg unter zwei Namen in derselben Tabelle.
    extras = {
        "resting_energy_kcal": (None if (total_kcal is None or active_kcal is None)
                                else round(total_kcal - active_kcal, 1)),
        "intensity_kcal_h_kg": _qty_unit(w, "intensity")[0],
        "avg_speed_kmh": _workout_speed_kmh(w),
        "elevation_descended_m": elev_down,
        "flights_climbed": _qty_unit(w, "flightsClimbed")[0],
        "step_count": _qty_unit(w, "stepCount")[0],
        "cadence_spm": _qty_unit(w, "stepCadence", "cyclingCadence")[0],
        "swim_stroke_count": _qty_unit(w, "totalSwimmingStrokeCount", "swimStrokeCount")[0],
        "swim_cadence_spm": _qty_unit(w, "swimCadence")[0],
        "lap_length_m": _workout_lap_length_m(w),
        "cycling_speed_kmh": _qty_unit(w, "cyclingSpeed")[0],
        "cycling_power_w": _qty_unit(w, "cyclingPower")[0],
        "temperature_c": _qty_unit(w, "temperature")[0],
        "humidity_pct": _qty_unit(w, "humidity")[0],
    }
    for key, val in extras.items():
        if not val:
            continue
        try:
            await db.execute(
                "INSERT INTO health_workout_metrics (workout_id, metric_key, value, unit) "
                "VALUES ($1,$2,$3,NULL) "
                "ON CONFLICT (workout_id, metric_key) DO UPDATE SET "
                "value=EXCLUDED.value, unit=NULL",
                wid, key, val)
        except Exception as e:
            logger.warning("Workout-Metric-Insert fehlgeschlagen (%s): %s", key, e)

    if samples:
        try:
            await db.executemany(
                "INSERT INTO health_workout_hr_samples "
                "(workout_id, kind, recorded_at, min_bpm, max_bpm, avg_bpm) "
                "VALUES ($1,$2,$3,$4,$5,$6) "
                "ON CONFLICT (workout_id, kind, recorded_at) DO UPDATE SET "
                "min_bpm=EXCLUDED.min_bpm, max_bpm=EXCLUDED.max_bpm, avg_bpm=EXCLUDED.avg_bpm",
                [(wid, s["kind"], s["at"], s["min"], s["max"], s["avg"]) for s in samples])
        except Exception as e:
            # Der Rest des Workouts steht bereits -- eine fehlgeschlagene
            # Minutenreihe darf den Import nicht als gescheitert melden.
            logger.warning("Workout-Pulsreihe fehlgeschlagen (%s Punkte): %s",
                           len(samples), e)
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


def _find_col(header: list, *keywords: str, exclude: tuple = ()) -> Optional[int]:
    """Findet die Spalte, deren Header-Zelle ALLE Keywords enthaelt
    (case-insensitive). Robust gegen leicht abweichende Einheiten-Suffixe.

    ``exclude`` blendet Spalten aus, die eines der Stichworte enthalten —
    noetig bei Headern, die einander als Teilstring enthalten (siehe
    ``_HR_EXCLUDE``).
    """
    for i, cell in enumerate(header):
        low = cell.lower()
        if any(x.lower() in low for x in exclude):
            continue
        if all(kw.lower() in low for kw in keywords):
            return i
    return None


# "Durchschn. Herzfrequenzvariabilitaet (ms)" enthaelt sowohl "Durchschn."
# als auch "Herzfrequenz" und wurde daher als Ø-Puls eingelesen, sobald die
# Spalte im Export vor der echten Puls-Spalte stand — der Ø-Puls lag danach
# bei ~8 (ms statt bpm). Fuer die Puls-Spalten des Workout-Imports werden
# HRV-Header deshalb explizit uebersprungen.
_HR_EXCLUDE = ("variabilit", "variability", "hrv")

# Zweite Verteidigungslinie zur Header-Auswahl: selbst wenn eine Spalte als
# Puls durchgeht, ist ein Trainings-Puls ausserhalb 30-240 bpm nicht
# erklaerbar (HRV-Millisekunden liegen typisch bei 5-80). Solche Werte werden
# verworfen statt gespeichert -- lieber kein Puls als ein falscher, der jeden
# Durchschnitt daruber kippt.
_HR_MIN, _HR_MAX = 30.0, 240.0


def _plausible_hr(v: Optional[float]) -> Optional[float]:
    """Gibt ``v`` zurueck, wenn es als Herzfrequenz plausibel ist, sonst None."""
    if v is None:
        return None
    return v if _HR_MIN <= float(v) <= _HR_MAX else None


def _first_col(header: list, *variants) -> Optional[int]:
    """Erste Spalte, die zu einer der Header-Varianten passt.

    Jede Variante ist entweder ein einzelnes Stichwort oder ein Tupel von
    Stichworten, die alle in derselben Header-Zelle vorkommen muessen. Deckt
    deutsche und englische Exportvarianten in einem Aufruf ab.
    """
    for kws in variants:
        if isinstance(kws, str):
            kws = (kws,)
        idx = _find_col(header, *kws)
        if idx is not None:
            return idx
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
    """Erkennt anhand des Headers, um welches CSV-Format es sich handelt.

    Unterstuetzte Formate:
      * ``workouts``        — Workouts-Uebersicht (deutsch/manueller Export)
      * ``health_metrics``  — Tages-Gesundheitsmetriken (deutsch/manueller Export)
      * ``long``            — Long-Format aus der REST-API-Automation der App
                              (name/date/qty pro Zeile)
    """
    if not header:
        return None
    low = [c.strip().lower() for c in header]
    first = low[0] if low else ""
    # Workouts-CSV: deutsche Version hat "Workout Type" als erste Spalte,
    # die REST-API-Automation der App verwendet englisch nur "Type". In beiden
    # Faellen sind Start/End/Duration typisch, was uns von Long-Format unterscheidet.
    if "workout type" in first:
        return "workouts"
    has_start = any(c == "start" or c.startswith("start ") for c in low)
    has_end = any(c == "end" or c.startswith("end ") for c in low)
    has_duration = any(c == "duration" or c == "dauer" for c in low)
    if first == "type" and has_start and has_end and has_duration:
        return "workouts"
    # Long-Format nur wenn "name"/"qty"/"date" alle vorhanden sind (eine Zeile
    # pro Datenpunkt). Wichtig: "type" allein reicht NICHT (Workouts-CSV hat
    # eine "Type"-Spalte, ist aber kein Long-Format).
    has_name = any(c in ("name", "metric") for c in low)
    has_value = any(c in ("qty", "value", "quantity", "amount") for c in low)
    has_date = any(("date" in c) or ("datum" in c) or ("time" in c) or ("zeit" in c) for c in low)
    if has_name and has_value and has_date:
        return "long"
    # Schlaf-CSV: eigene Datei mit Start/Ende und den Phasen als eigene
    # Spalten ("Gesamtschlaf", "Kern", "Tief", "REM", "Wach"). Abgrenzung zur
    # Tages-CSV, die dieselben Phasen als "Schlafanalyse [REM]" o.ae. NEBEN
    # allen anderen Vitalwerten fuehrt — dort greift weiterhin der bestehende
    # Metrik-Parser.
    if not any("schlafanalyse" in c for c in low):
        has_total = any(("gesamtschlaf" in c) or ("total sleep" in c) for c in low)
        has_phases = (any(c.startswith("rem") for c in low)
                      and any(("kern" in c) or ("core" in c) or ("im bett" in c)
                              or ("in bed" in c) for c in low))
        if has_total or has_phases:
            return "sleep"
    if "datum" in first or "date" in first:
        return "health_metrics"
    return None


def _sniff_delimiter(sample: str) -> str:
    """Findet den wahrscheinlichsten Trenner. Manueller Export nutzt ``;``,
    REST-API-Automation typischerweise ``,``."""
    first_line = sample.split("\n", 1)[0]
    counts = {d: first_line.count(d) for d in (";", ",", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


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

    delimiter = _sniff_delimiter(text[:2048])
    reader = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not reader:
        empty_stats["skipped"].append(f"{filename}:empty_file")
        return empty_stats
    header = [c.strip() for c in reader[0]]
    kind = detect_csv_kind(header)
    rows = reader[1:]
    logger.info("CSV-Ingest %s delimiter=%r kind=%r header=%s rows=%d",
                filename, delimiter, kind, header[:6], len(rows))

    if kind == "health_metrics":
        return await _ingest_health_metrics_csv(db, user_id, header, rows)
    if kind == "workouts":
        return await _ingest_workouts_csv(db, user_id, header, rows)
    if kind == "sleep":
        return await _ingest_sleep_csv(db, user_id, header, rows)
    if kind == "long":
        return await _ingest_long_csv(db, user_id, header, rows)
    empty_stats["skipped"].append(f"{filename}:unrecognized_csv_format:header={header[:5]}")
    return empty_stats


async def _ingest_health_metrics_csv(db, user_id: int, header: list, rows: list) -> dict:
    stats = {"metrics_imported": 0, "workouts_imported": 0, "sleep_imported": 0,
              "bp_imported": 0, "glucose_imported": 0, "skipped": []}

    col = {
        "active_energy": _find_col(header, "Aktive Energie"),
        "bp_sys": _find_col(header, "Blutdruck", "Systolisch"),
        "bp_dia": _find_col(header, "Blutdruck", "Diastolisch"),
        "glucose": _find_col(header, "Blutzucker"),
        "blood_oxygen": _find_col(header, "Blutsauerstoff"),
        "walking_distance": _first_col(header, "Laufstrecke", ("Walking", "Distance")),
        "walking_speed": _first_col(header, "Gehgeschwindigkeit", ("Walking", "Speed")),
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

        # v1.29.0: Werte werden 1:1 aus der CSV uebernommen (frueher wurden
        # Schritte/Aktive Energie/Schwimmdistanz um Faktor 1000 skaliert,
        # weil eine fruehere fehlerhafte Beispiel-CSV das nahegelegt hat —
        # aktuelle Auto-Health-Export-Versionen liefern die Rohwerte
        # bereits korrekt, siehe User-Feedback).
        simple_cols = [
            ("active_energy", "active_energy"),
            ("walking_hr", "walking_hr_avg"),
            ("weight", "weight"),
            ("hrv", "hrv"),
            ("cardio_recovery", "cardio_recovery"),
            ("resting_hr", "resting_hr"),
            ("steps", "steps"),
            ("swim_distance", "swim_distance"),
            ("vo2_max", "vo2_max"),
            ("blood_oxygen", "blood_oxygen"),
            ("walking_distance", "walking_distance"),
            ("walking_speed", "walking_speed"),
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


# Auto Health Export beschriftet die Distanz-Spalte der Workouts-CSV immer mit
# "(km)" und die Geschwindigkeit mit "(km/Std.)", schreibt fuer Schwimm-Workouts
# aber die HealthKit-Rohwerte in Metern bzw. m/Std. hinein. Ein 1800-m-Bahn-
# schwimmen landete dadurch als 1800 km in der DB und die Pace im Frontend bei
# 0:02 min/km. Erkennbar ist der Fall allein an der Groessenordnung: eine
# einzelne Trainingseinheit ueber 300 km bzw. eine Durchschnitts-
# geschwindigkeit ueber 100 km/h gibt es nicht, also war die Zahl in Metern
# gemeint und die ganze Zeile muss durch 1000 geteilt werden (Distanz und
# Geschwindigkeit stammen aus derselben Umrechnung, deshalb ein gemeinsamer
# Faktor).
_CSV_DIST_KM_MAX = 300.0
_CSV_SPEED_KMH_MAX = 100.0


def _csv_metric_scale(distance_raw: Optional[float],
                      avg_speed_raw: Optional[float]) -> float:
    """1.0 = Spalten sind wirklich km/kmh, 0.001 = es sind in Wahrheit Meter."""
    if distance_raw is not None and distance_raw > _CSV_DIST_KM_MAX:
        return 0.001
    if avg_speed_raw is not None and avg_speed_raw > _CSV_SPEED_KMH_MAX:
        return 0.001
    return 1.0


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


async def _ingest_sleep_csv(db, user_id: int, header: list, rows: list) -> dict:
    """Parser fuer die separate Schlafanalyse-CSV (v1.44.0).

    Auto Health Export legt den Schlaf inzwischen als eigene Datei ab, statt
    ihn als "Schlafanalyse [...]"-Spalten in die Tages-CSV zu mischen:

        Datum/Uhrzeit;Start;Ende;Gesamtschlaf (Std.);Schlafend (Std.);
        Im Bett (Std.);Kern (Std.);Tief (Std.);REM (Std.);Wach (Std.);Quellen

    Zwei Eigenheiten des Formats:

    * ``Gesamtschlaf`` ist die tatsaechlich geschlafene Zeit und enthaelt
      neben Kern/Tief/REM auch den Anteil ohne Phasen-Zuordnung, den die
      Spalte ``Schlafend`` separat ausweist. Sie wandert deshalb nach
      ``asleep_minutes`` — ``Schlafend`` allein waere zu wenig (in der
      Beispielwoche 0,0-1,3 h statt 4,6-10,1 h).
    * ``Im Bett`` ist 0, wenn kein eigenes inBed-Sample existiert. Eine
      Liegezeit von 0 h neben 10 h Schlaf ist keine Messung, sondern eine
      Luecke — sie wird als NULL gespeichert, das Frontend leitet die
      Liegezeit dann aus Schlaf + Wachzeit bzw. Start/Ende ab.
    """
    stats = {"metrics_imported": 0, "workouts_imported": 0, "sleep_imported": 0,
              "bp_imported": 0, "glucose_imported": 0, "skipped": []}

    col = {
        "start": _first_col(header, "Start"),
        "end": _first_col(header, "Ende", "End"),
        "total": _first_col(header, "Gesamtschlaf", ("Total", "Sleep")),
        "unspecified": _first_col(header, "Schlafend", "Asleep"),
        "in_bed": _first_col(header, "Im Bett", "In Bed"),
        "core": _first_col(header, "Kern", "Core"),
        "deep": _first_col(header, "Tief", "Deep"),
        "rem": _first_col(header, "REM"),
        "awake": _first_col(header, "Wach", "Awake"),
    }

    for row in rows:
        if not row or not (row[0] or "").strip():
            continue
        dt = _parse_csv_dt(row[0])
        if not dt:
            stats["skipped"].append(f"sleep_csv:invalid_date:{row[0]}")
            continue

        total_h = _row_num(row, col["total"])
        unspec_h = _row_num(row, col["unspecified"])
        core_h = _row_num(row, col["core"])
        deep_h = _row_num(row, col["deep"])
        rem_h = _row_num(row, col["rem"])
        awake_h = _row_num(row, col["awake"])
        in_bed_h = _row_num(row, col["in_bed"])

        if total_h is None:
            parts = [v for v in (unspec_h, core_h, deep_h, rem_h) if v is not None]
            total_h = sum(parts) if parts else None
        if in_bed_h is not None and in_bed_h <= 0:
            in_bed_h = None

        if all(v is None for v in (total_h, core_h, deep_h, rem_h, awake_h)):
            stats["skipped"].append(f"sleep_csv:no_values:{row[0]}")
            continue

        p = {
            "sleepDate": dt.date(),
            "date": _csv_date_str(row[0]),
            "sleepStart": _row_str(row, col["start"]),
            "sleepEnd": _row_str(row, col["end"]),
            "asleep": total_h, "inBed": in_bed_h,
            "core": core_h, "deep": deep_h, "rem": rem_h, "awake": awake_h,
        }
        if await _ingest_sleep_point(db, user_id, p):
            stats["sleep_imported"] += 1
        else:
            stats["skipped"].append(f"sleep_csv:{row[0]}")

    return stats


async def _ingest_workouts_csv(db, user_id: int, header: list, rows: list) -> dict:
    stats = {"metrics_imported": 0, "workouts_imported": 0, "sleep_imported": 0,
              "bp_imported": 0, "glucose_imported": 0, "skipped": []}

    # Zwei Spalten-Varianten: deutsch (manueller Export, "Aktive Energie") und
    # englisch (REST-API-Automation der App, "Active Energy"). Wir versuchen
    # fuer jeden logischen Wert nacheinander mehrere Header-Muster. Wie
    # ``_first_col``, kann zusaetzlich aber Header ausschliessen (``exclude``).
    def _first(*variants, exclude: tuple = ()):
        for kws in variants:
            if isinstance(kws, str):
                kws = (kws,)
            idx = _find_col(header, *kws, exclude=exclude)
            if idx is not None:
                return idx
        return None

    col = {
        "start": _first("Start"),
        "end": _first("End"),
        "duration": _first("Duration", "Dauer"),
        "active_energy": _first("Aktive Energie", "Active Energy"),
        "resting_energy": _first("Ruheeinträge", ("Resting", "Energy")),
        "total_energy": _first(("Total", "Energy"), ("Gesamt", "Energie")),
        "intensity": _first("Intensität", "Intensity"),
        "max_hr": _first(("Max.", "Herzfrequenz"), ("Max", "Heart", "Rate"),
                         exclude=_HR_EXCLUDE),
        "avg_hr": _first(("Durchschn.", "Herzfrequenz"), ("Avg", "Heart", "Rate"),
                         exclude=_HR_EXCLUDE),
        "distance_km": _first("Distanz", "Distance"),
        "max_speed": _first("Max. Geschwindigkeit", ("Max", "Speed")),
        "avg_speed": _first("Durchschnittsgeschwindigkeit", ("Avg", "Speed")),
        "flights": _first("Etagen gestiegen", "Flights Climbed", "Flights"),
        "elevation_up": _first("Aufgestiegene Höhe", ("Elevation", "Ascended"), ("Elevation", "Up")),
        "elevation_down": _first("Abgestiegene Höhe", ("Elevation", "Descended"), ("Elevation", "Down")),
        "step_count": _first("Schrittzählung", "Step Count", "Steps"),
        "cadence": _first("Schrittfrequenz", "Cadence"),
        "swim_strokes": _first("Anzahl der Schwimmzüge", ("Swim", "Strokes"), "Stroke Count"),
        "swim_cadence": _first("Schwimmkadenz", "Swim Cadence"),
        "lap_length": _first("Rundenlänge", "Lap Length"),
        "swolf": _first("SWOLF"),
        "temperature": _first("Temperatur", "Temperature"),
        "humidity": _first("Luftfeuchtigkeit", "Humidity"),
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
        total_kcal = _row_num(row, col.get("total_energy"))
        if total_kcal is None and (active_kcal is not None or resting_kcal is not None):
            total_kcal = (active_kcal or 0) + (resting_kcal or 0)
        distance_km = _row_num(row, col.get("distance_km"))
        avg_speed = _row_num(row, col.get("avg_speed"))
        max_speed = _row_num(row, col.get("max_speed"))
        scale = _csv_metric_scale(distance_km, avg_speed)
        if scale != 1.0:
            distance_km = None if distance_km is None else distance_km * scale
            avg_speed = None if avg_speed is None else avg_speed * scale
            max_speed = None if max_speed is None else max_speed * scale
            logger.info("Workout-CSV: Distanz-/Geschwindigkeitsspalte in Metern "
                        "erkannt (%s), Zeile umgerechnet", workout_type)
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
                _plausible_hr(_row_num(row, col.get("avg_hr"))),
                _plausible_hr(_row_num(row, col.get("max_hr"))),
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
            "max_speed_kmh": max_speed,
            "avg_speed_kmh": avg_speed,
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


# ---------------------------------------------------------------------------
# Long-Format CSV (REST-API-Automation der Auto-Health-Export-App)
# ---------------------------------------------------------------------------
# Typischer Header (englisch, Komma-getrennt):
#   name,units,date,qty,source     — oder Variationen davon.
# Eine Zeile pro Datenpunkt. Metric-Namen entsprechen der JSON-API-Struktur
# (siehe SIMPLE_METRIC_MAP + Spezialfaelle). Blutdruck kommt als zwei
# getrennte Zeilen (blood_pressure_systolic/diastolic) mit gleichem Timestamp
# und wird ueber den Zeitstempel zusammengefuehrt.
async def _ingest_long_csv(db, user_id: int, header: list, rows: list) -> dict:
    stats = {"metrics_imported": 0, "workouts_imported": 0, "sleep_imported": 0,
              "bp_imported": 0, "glucose_imported": 0, "skipped": []}

    low = [c.strip().lower() for c in header]

    def _col(*candidates):
        for c in candidates:
            if c in low:
                return low.index(c)
        return None

    idx_name = _col("name", "metric", "type")
    idx_date = _col("date", "datum", "timestamp", "startdate")
    idx_qty = _col("qty", "value", "quantity", "amount")
    idx_unit = _col("units", "unit")
    idx_source = _col("source")
    idx_sys = _col("systolic", "sys")
    idx_dia = _col("diastolic", "dia")
    idx_inbed = _col("inbed", "in_bed")
    idx_asleep = _col("asleep")
    idx_core = _col("core")
    idx_deep = _col("deep")
    idx_rem = _col("rem")
    idx_awake = _col("awake")
    idx_start = _col("sleepstart", "sleep_start", "start")
    idx_end = _col("sleepend", "sleep_end", "end")

    if idx_name is None or idx_date is None:
        stats["skipped"].append(f"long_csv:missing_columns:header={header[:6]}")
        return stats

    bp_pending: dict = {}

    for row in rows:
        if not row:
            continue
        name = _row_str(row, idx_name)
        if not name:
            continue
        raw_date = _row_str(row, idx_date)
        date_str = _csv_date_str(raw_date) if raw_date else None
        qty = _row_num(row, idx_qty)
        unit = _row_str(row, idx_unit)

        # Blutdruck (getrennte Zeilen) — nach Timestamp zusammenfuehren
        if name in (BP_SYSTOLIC_NAME, BP_DIASTOLIC_NAME):
            dt = _parse_csv_dt(raw_date)
            if not dt:
                stats["skipped"].append(f"{name}:invalid_date")
                continue
            key = dt.isoformat()
            entry = bp_pending.setdefault(key, {"recorded_at": dt})
            entry["systolic" if name == BP_SYSTOLIC_NAME else "diastolic"] = qty
            continue

        # Blutdruck (kombinierte Zeile mit systolic/diastolic-Spalten)
        if name == "blood_pressure" and (idx_sys is not None or idx_dia is not None):
            dt = _parse_csv_dt(raw_date)
            if dt:
                entry = {"recorded_at": dt,
                         "systolic": _row_num(row, idx_sys),
                         "diastolic": _row_num(row, idx_dia)}
                if await _ingest_bp_point(db, user_id, entry):
                    stats["bp_imported"] += 1
                else:
                    stats["skipped"].append(f"blood_pressure:{raw_date}")
            continue

        # Blutzucker
        if name == GLUCOSE_NAME:
            if await _ingest_glucose_point(db, user_id, {"date": date_str, "qty": qty}, unit):
                stats["glucose_imported"] += 1
            else:
                stats["skipped"].append(f"glucose:{raw_date}")
            continue

        # Schlaf
        if name == SLEEP_NAME:
            p = {
                "date": date_str,
                "sleepStart": _csv_date_str(_row_str(row, idx_start)) if idx_start is not None else None,
                "sleepEnd": _csv_date_str(_row_str(row, idx_end)) if idx_end is not None else None,
                "asleep": _row_num(row, idx_asleep),
                "inBed": _row_num(row, idx_inbed),
                "core": _row_num(row, idx_core),
                "deep": _row_num(row, idx_deep),
                "rem": _row_num(row, idx_rem),
                "awake": _row_num(row, idx_awake),
            }
            if p["asleep"] is None and qty is not None:
                p["asleep"] = qty
            if any(p.get(k) is not None for k in ("asleep", "inBed", "core", "deep", "rem")):
                if await _ingest_sleep_point(db, user_id, p):
                    stats["sleep_imported"] += 1
                else:
                    stats["skipped"].append(f"sleep:{raw_date}")
            continue

        # Einfache Zeitreihen
        metric_type = SIMPLE_METRIC_MAP.get(name)
        if not metric_type:
            resolved = await _resolve_unknown_metric(name)
            if resolved:
                metric_type = resolved
            else:
                stats["skipped"].append(f"unknown_metric:{name}")
                continue
        if qty is None:
            stats["skipped"].append(f"{metric_type}:no_qty:{raw_date}")
            continue
        p = {"date": date_str, "qty": qty, "source": _row_str(row, idx_source)}
        if await _ingest_metric_point(db, user_id, metric_type, p, unit):
            stats["metrics_imported"] += 1
        else:
            stats["skipped"].append(f"{metric_type}:{raw_date}")

    for _key, entry in bp_pending.items():
        if await _ingest_bp_point(db, user_id, entry):
            stats["bp_imported"] += 1
        else:
            stats["skipped"].append("blood_pressure:merge_failed")

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
