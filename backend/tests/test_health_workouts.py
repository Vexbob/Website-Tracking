"""Tests fuer den JSON-Workout-Ingest (v1.50.0). Run: pytest backend/tests/

Auto Health Export schickt dasselbe Workout in zwei Exportvarianten mit je
eigener id und komplementaeren Feldern (Details im Kopf von health_ingest.py).
Getestet wird deshalb vor allem: Einheiten-Normalisierung und dass die zweite
Variante die erste ERGAENZT statt sie zu ueberschreiben -- egal in welcher
Reihenfolge sie ankommen.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from services.health_ingest import (  # noqa: E402
    _hr_samples, _ingest_workout, _workout_distance_m, _workout_elevation,
    _workout_heart_rate, _workout_lap_length_m, _workout_speed_kmh,
)


# ---------------------------------------------------------------------------
# Beispiel-Workouts: gekuerzte, aber feldgetreue Auszuege echter Payloads
# ---------------------------------------------------------------------------
SWIM_START = "2026-09-03 19:32:34 +0200"
SWIM_END = "2026-09-03 20:49:24 +0200"


def swim_variant_a() -> dict:
    """Variante mit Pulswerten, Minutenreihe und km-Distanz."""
    return {
        "id": "009520A9-7B00-4A4A-9B65-2B47361B5F4C",
        "name": "Schwimmbad Schwimmen",
        "start": SWIM_START, "end": SWIM_END, "duration": 4610.7383010387421,
        "location": "Schwimmbad", "isIndoor": True,
        "distance": {"qty": 1.825, "units": "km"},
        "speed": {"units": "m/hr", "qty": 1.4249344835988329},
        "activeEnergyBurned": {"qty": 1568.2132056920739, "units": "kcal"},
        "avgHeartRate": {"qty": 134.39944037444036, "units": "bpm"},
        "maxHeartRate": {"qty": 164, "units": "bpm"},
        "heartRate": {"min": {"qty": 106, "units": "bpm"},
                      "avg": {"qty": 134.39944037444036, "units": "bpm"},
                      "max": {"qty": 164, "units": "bpm"}},
        "lapLength": {"units": "m", "qty": 0.025},
        "intensity": {"units": "kcal/hr·kg", "qty": 9.8715383895611346},
        "heartRateData": [
            {"date": "2026-09-03 19:32:00 +0200", "Min": 122, "Max": 126, "Avg": 124.16, "units": "bpm"},
            {"date": "2026-09-03 19:33:00 +0200", "Min": 118, "Max": 128, "Avg": 124.25, "units": "bpm"},
        ],
        "heartRateRecovery": [
            {"date": "2026-09-03 20:49:27 +0200", "Min": 132, "Max": 132, "Avg": 132, "units": "bpm"},
        ],
        "metadata": {},
    }


def swim_variant_b() -> dict:
    """Dasselbe Workout, andere id: Rohmeter, Schwimmzuege, Gesamtenergie --
    aber alle Pulsfelder auf 0 und leere Arrays."""
    return {
        "id": "D8C445F5-97C0-4621-854F-CBB629A107CC",
        "name": "Schwimmbad Schwimmen",
        "start": SWIM_START, "end": SWIM_END, "duration": 4610.7383010387421,
        "location": "Schwimmbad", "isIndoor": False,
        "distance": {"units": "m", "qty": 1825},
        "speed": {"qty": 1424.9344835988327, "units": "m/hr"},
        "activeEnergy": {"units": "kcal", "qty": 1568.2132056920739},
        "totalEnergy": {"qty": 1568.2132056920739, "units": "kcal"},
        "avgHeartRate": {"units": "bpm", "qty": 0},
        "maxHeartRate": {"units": "bpm", "qty": 0},
        "heartRateData": [], "heartRateRecovery": [], "route": [],
        "totalSwimmingStrokeCount": {"qty": 1935, "units": "count"},
        "swimCadence": {"qty": 25.180349093732801, "units": "spm"},
        "stepCount": {"units": "steps", "qty": 0},
        "stepCadence": {"units": "spm", "qty": 0},
        "flightsClimbed": {"units": "count", "qty": 0},
        "elevation": {"ascent": 0, "descent": 0, "units": "m"},
        "intensity": {"qty": 9.8715383895611346, "units": "kcal/hr·kg"},
        "humidity": {"qty": 0, "units": "%"},
        "temperature": {"qty": 0, "units": "degC"},
    }


def walk_variant_a() -> dict:
    return {
        "id": "ACEDF40A-FACF-4194-9E5F-AE99E39FB78B", "name": "Outdoor Spaziergang",
        "start": "2026-09-04 16:21:47 +0200", "end": "2026-09-04 17:32:08 +0200",
        "duration": 4221.3327068090439,
        "distance": {"qty": 5.0272061512161743, "units": "km"},
        "speed": {"qty": 4.2872579351980722, "units": "km/hr"},
        "elevationUp": {"qty": 59.700000000000003, "units": "m"},
        "activeEnergyBurned": {"qty": 603.50431177314033, "units": "kcal"},
        "avgHeartRate": {"qty": 140.50612798142507, "units": "bpm"},
        "maxHeartRate": {"units": "bpm", "qty": 179},
        "heartRate": {"min": {"units": "bpm", "qty": 107}},
        "temperature": {"units": "degC", "qty": 25.853172302243706},
        "humidity": {"qty": 57.999999999999993, "units": "%"},
    }


def walk_variant_b() -> dict:
    return {
        "id": "98F0D60E-DAA1-4684-BA7A-866A6372EE83", "name": "Outdoor Spaziergang",
        "start": "2026-09-04 16:21:47 +0200", "end": "2026-09-04 17:32:08 +0200",
        "duration": 4221.3327068090439,
        "distance": {"units": "km", "qty": 5.0272061512161743},
        "speed": {"qty": 4.2872579351980713, "units": "km/hr"},
        "elevation": {"ascent": 59.700000000000003, "units": "m", "descent": 0},
        "activeEnergy": {"qty": 603.50431177314033, "units": "kcal"},
        "totalEnergy": {"qty": 603.50431177314033, "units": "kcal"},
        "avgHeartRate": {"qty": 0, "units": "bpm"},
        "maxHeartRate": {"units": "bpm", "qty": 0},
        "heartRateData": [], "heartRateRecovery": [],
        "stepCount": {"units": "steps", "qty": 0},
        "flightsClimbed": {"qty": 0, "units": "count"},
        "totalSwimmingStrokeCount": {"qty": 0, "units": "count"},
    }


# ---------------------------------------------------------------------------
# Einheiten
# ---------------------------------------------------------------------------
def test_distance_beide_varianten_ergeben_dieselben_meter():
    assert _workout_distance_m(swim_variant_a()) == 1825
    assert _workout_distance_m(swim_variant_b()) == 1825
    assert round(_workout_distance_m(walk_variant_a())) == 5027
    assert round(_workout_distance_m(walk_variant_b())) == 5027


def test_distance_km_etikett_mit_rohmetern():
    # Ueber 300 "km" gibt es keine Trainingseinheit -- das sind Meter.
    assert _workout_distance_m({"distance": {"qty": 1825, "units": "km"}}) == 1825


def test_speed_m_pro_stunde_wird_kmh():
    a = _workout_speed_kmh(swim_variant_a())
    b = _workout_speed_kmh(swim_variant_b())
    assert round(a, 4) == round(b, 4) == 1.4249
    assert round(_workout_speed_kmh(walk_variant_a()), 3) == 4.287


def test_lap_length_wird_meter():
    assert _workout_lap_length_m(swim_variant_a()) == 25
    assert _workout_lap_length_m({"lapLength": {"qty": 50, "units": "m"}}) == 50
    assert _workout_lap_length_m({}) is None


def test_elevation_aus_beiden_schreibweisen():
    assert _workout_elevation(walk_variant_a()) == (59.700000000000003, None)
    # ascent/descent-Objekt: 0 Abstieg gilt als "nicht gemessen"
    assert _workout_elevation(walk_variant_b()) == (59.700000000000003, None)


# ---------------------------------------------------------------------------
# Puls
# ---------------------------------------------------------------------------
def test_puls_der_leeren_variante_bleibt_leer():
    w = swim_variant_b()
    assert _hr_samples(w) == []
    assert _workout_heart_rate(w, []) == (None, None, None)


def test_puls_aus_aggregaten_und_minutenreihe():
    w = swim_variant_a()
    samples = _hr_samples(w)
    assert [s["kind"] for s in samples] == ["recovery", "workout", "workout"]
    avg, mx, mn = _workout_heart_rate(w, samples)
    assert round(avg, 2) == 134.40 and mx == 164 and mn == 106


def test_puls_faellt_auf_die_minutenreihe_zurueck():
    w = {k: v for k, v in swim_variant_a().items()
         if k not in ("avgHeartRate", "maxHeartRate", "heartRate")}
    avg, mx, mn = _workout_heart_rate(w, _hr_samples(w))
    assert abs(avg - 124.205) < 1e-6 and mx == 128 and mn == 118


def test_unplausible_pulspunkte_werden_verworfen():
    w = {"heartRateData": [
        {"date": "2026-09-03 19:32:00 +0200", "Avg": 900},
        {"date": "2026-09-03 19:33:00 +0200", "Avg": 0},
        {"date": "kein datum", "Avg": 120},
        {"date": "2026-09-03 19:34:00 +0200", "Min": 110, "Max": 130},
    ]}
    samples = _hr_samples(w)
    assert len(samples) == 1
    assert samples[0]["avg"] == 120  # Mittel aus Min/Max, wenn Avg fehlt


# ---------------------------------------------------------------------------
# Zusammenfuehrung beider Varianten
# ---------------------------------------------------------------------------
class FakeDB:
    """Minimaler asyncpg-Ersatz: haelt Workouts, Zusatzmetriken und
    Pulspunkte im Speicher und bildet die COALESCE-Semantik der beiden
    Upsert-Statements nach."""

    HEAD_COLS = ["workout_type", "end_at", "duration_min", "active_energy_kcal",
                 "total_energy_kcal", "distance_m", "avg_heart_rate",
                 "max_heart_rate", "min_heart_rate", "elevation_m"]

    def __init__(self):
        self.workouts: dict = {}
        self.metrics: dict = {}
        self.hr: dict = {}
        self._next_id = 1

    async def fetchrow(self, sql, *args):
        assert "SELECT id FROM health_workouts" in sql
        user_id, lo, hi, wtype, start_at = args
        best = None
        for wid, w in self.workouts.items():
            if w["user_id"] != user_id or not (lo <= w["start_at"] <= hi):
                continue
            if w["workout_type"] and wtype and w["workout_type"] != wtype:
                continue
            delta = abs((w["start_at"] - start_at).total_seconds())
            if best is None or delta < best[0]:
                best = (delta, wid)
        return {"id": best[1]} if best else None

    async def fetchval(self, sql, *args):
        assert "INSERT INTO health_workouts" in sql
        user_id, external_id, wtype, start_at = args[:4]
        for wid, w in self.workouts.items():
            if w["user_id"] == user_id and w["external_id"] == external_id:
                for col, val in zip(self.HEAD_COLS[1:], args[4:]):
                    if val is not None:
                        w[col] = val
                return wid
        wid = self._next_id
        self._next_id += 1
        row = {"id": wid, "user_id": user_id, "external_id": external_id,
               "workout_type": wtype, "start_at": start_at}
        row.update(dict(zip(self.HEAD_COLS[1:], args[4:])))
        self.workouts[wid] = row
        return wid

    async def execute(self, sql, *args):
        if "UPDATE health_workouts" in sql:
            w = self.workouts[args[0]]
            for col, val in zip(self.HEAD_COLS, args[1:]):
                if col == "workout_type":
                    w[col] = w[col] or val
                elif val is not None:
                    w[col] = val
            return "UPDATE 1"
        if "INSERT INTO health_workout_metrics" in sql:
            wid, key, val = args
            self.metrics[(wid, key)] = val
            return "INSERT 1"
        raise AssertionError("unerwartetes Statement: " + sql)

    async def executemany(self, sql, rows):
        assert "health_workout_hr_samples" in sql
        for wid, kind, at, mn, mx, av in rows:
            self.hr[(wid, kind, at)] = (mn, mx, av)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _ingest_both(order):
    db = FakeDB()
    for w in order:
        assert _run(_ingest_workout(db, 1, w)) is True
    return db


def _assert_swim_merged(db):
    assert len(db.workouts) == 1, "beide Varianten muessen dieselbe Zeile fuellen"
    w = list(db.workouts.values())[0]
    assert w["distance_m"] == 1825
    assert round(w["avg_heart_rate"], 2) == 134.40   # nur Variante A
    assert w["max_heart_rate"] == 164
    assert w["min_heart_rate"] == 106
    assert round(w["total_energy_kcal"]) == 1568     # nur Variante B
    assert round(w["duration_min"], 1) == 76.8
    wid = w["id"]
    assert db.metrics[(wid, "swim_stroke_count")] == 1935
    assert round(db.metrics[(wid, "swim_cadence_spm")], 2) == 25.18
    assert db.metrics[(wid, "lap_length_m")] == 25
    assert round(db.metrics[(wid, "avg_speed_kmh")], 4) == 1.4249
    # 0-Werte der leeren Variante legen keine Metrik an
    assert (wid, "step_count") not in db.metrics
    assert (wid, "flights_climbed") not in db.metrics
    assert len(db.hr) == 3
    assert sorted({k[1] for k in db.hr}) == ["recovery", "workout"]


def test_beide_varianten_ergeben_ein_workout():
    _assert_swim_merged(_ingest_both([swim_variant_a(), swim_variant_b()]))


def test_reihenfolge_der_varianten_egal():
    _assert_swim_merged(_ingest_both([swim_variant_b(), swim_variant_a()]))


def test_erneuter_import_ueberschreibt_nichts_mit_null():
    db = _ingest_both([swim_variant_a(), swim_variant_b(), swim_variant_b()])
    _assert_swim_merged(db)


def test_verschiedene_workouts_bleiben_getrennt():
    db = _ingest_both([swim_variant_a(), swim_variant_b(),
                       walk_variant_a(), walk_variant_b()])
    assert len(db.workouts) == 2
    walk = [w for w in db.workouts.values() if w["workout_type"] == "Outdoor Spaziergang"][0]
    assert round(walk["distance_m"]) == 5027
    assert walk["elevation_m"] == 59.700000000000003
    assert round(walk["avg_heart_rate"], 2) == 140.51


def test_zeitfenster_ordnet_nur_denselben_start_zu():
    """Ein zweites Training zwei Stunden spaeter ist ein eigenes Workout."""
    later = swim_variant_b()
    start = datetime(2026, 9, 3, 21, 32, 34, tzinfo=timezone(timedelta(hours=2)))
    later["start"] = start.strftime("%Y-%m-%d %H:%M:%S %z")
    later["id"] = "spaeter"
    db = _ingest_both([swim_variant_a(), later])
    assert len(db.workouts) == 2
