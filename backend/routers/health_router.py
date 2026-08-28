"""Health-Router — Sync-Endpoint fuer Auto Health Export (iPhone) + Frontend-API.

Endpoints:
  POST   /api/health/import              — Ingest-Endpoint fuer die App (API-Key-Auth)
  POST   /api/health/import-file         — Manueller JSON-Upload im Frontend (JWT-Auth)
  GET    /api/health/api-keys            — eigene Keys auflisten (JWT-Auth)
  POST   /api/health/api-keys            — neuen Key erzeugen (Klartext nur hier sichtbar)
  DELETE /api/health/api-keys/{kid}      — Key widerrufen
  GET    /api/health/summary             — Dashboard-Kacheln (heute/7 Tage)
  GET    /api/health/metrics/{type}      — Zeitserie einer einfachen Metrik
  GET    /api/health/blood-pressure      — Blutdruck-Zeitserie
  GET    /api/health/blood-glucose       — Blutzucker-Zeitserie
  GET    /api/health/sleep               — Schlaf-Naechte
  GET    /api/health/workouts            — Workout-Liste (Filter nach Typ)
  GET    /api/health/workouts/{wid}      — Workout-Detail inkl. Zusatzmetriken
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File

from database import get_db
from auth import get_current_user, get_user_from_health_api_key, generate_health_api_key
from deps import logger, limiter, LIMIT_HEALTH_IMPORT, LIMIT_WRITE_RARE, LIMIT_WRITE_STANDARD, _ser_exp
from services.health_ingest import ingest_payload, SIMPLE_METRIC_MAP

router = APIRouter(tags=["health"])

ALLOWED_METRIC_TYPES = sorted(set(SIMPLE_METRIC_MAP.values()))


# ---------- Sync-Ingest (API-Key-Auth, kein JWT) ----------
@router.post("/api/health/import")
@limiter.limit(LIMIT_HEALTH_IMPORT)
async def import_health_data(request: Request, body: dict,
                              db=Depends(get_db),
                              user=Depends(get_user_from_health_api_key)):
    stats = await ingest_payload(db, user["id"], body)
    logger.info("Health-Import fuer user_id=%s: %s", user["id"], stats)
    return stats


# ---------- Manueller Datei-Upload (JWT-Auth, fuer Backfill/Nachimport) ----------
@router.post("/api/health/import-file")
@limiter.limit(LIMIT_WRITE_RARE)
async def import_health_file(request: Request, file: UploadFile = File(...),
                              db=Depends(get_db), user=Depends(get_current_user)):
    """Nimmt eine per Hand hochgeladene Auto-Health-Export-JSON-Datei entgegen
    (z.B. fuer einen einmaligen Backfill vergangener Monate, ohne dafuer eine
    Automation einzurichten). Nutzt denselben Ingest wie der automatisierte
    Sync-Endpoint, aber mit normaler JWT-Auth statt API-Key."""
    raw = await file.read()
    try:
        payload = json.loads(raw)
    except Exception as e:
        raise HTTPException(400, f"Datei ist kein valides JSON: {e}")
    if not isinstance(payload, dict):
        raise HTTPException(400, "JSON-Root muss ein Objekt sein")
    stats = await ingest_payload(db, user["id"], payload)
    logger.info("Health-Datei-Import fuer user_id=%s: %s", user["id"], stats)
    return stats


# ---------- API-Key-Verwaltung (JWT-Auth) ----------
@router.get("/api/health/api-keys")
async def list_api_keys(db=Depends(get_db), user=Depends(get_current_user)):
    rows = await db.fetch(
        "SELECT id, label, created_at, last_used_at, revoked_at FROM health_api_keys "
        "WHERE user_id=$1 ORDER BY created_at DESC", user["id"])
    return [_ser_exp(r) for r in rows]


@router.post("/api/health/api-keys")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def create_api_key(request: Request, body: dict,
                          db=Depends(get_db), user=Depends(get_current_user)):
    label = (body.get("label") or "").strip() or "Auto Health Export"
    raw_key, key_hash = generate_health_api_key(user["id"])
    row = await db.fetchrow(
        "INSERT INTO health_api_keys (user_id, key_hash, label) VALUES ($1,$2,$3) "
        "RETURNING id, label, created_at",
        user["id"], key_hash, label)
    out = _ser_exp(row)
    out["api_key"] = raw_key  # nur bei Erzeugung sichtbar, wird nicht persistiert
    return out


@router.delete("/api/health/api-keys/{kid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def revoke_api_key(request: Request, kid: int,
                          db=Depends(get_db), user=Depends(get_current_user)):
    r = await db.execute(
        "UPDATE health_api_keys SET revoked_at=NOW() WHERE id=$1 AND user_id=$2 AND revoked_at IS NULL",
        kid, user["id"])
    if r == "UPDATE 0":
        raise HTTPException(404, "Key nicht gefunden")
    return {"status": "revoked"}


# ---------- Dashboard-Summary ----------
@router.get("/api/health/summary")
async def health_summary(db=Depends(get_db), user=Depends(get_current_user)):
    """Kompakte Kacheln fuer den Dashboard-Tab: letzter Wert je Metrik +
    Summe der letzten 7 Tage fuer kumulative Metriken (Schritte, aktive Energie)."""
    today = date.today()
    week_ago = today - timedelta(days=7)
    out = {}
    for mtype in ALLOWED_METRIC_TYPES:
        last = await db.fetchrow(
            "SELECT qty, unit, recorded_at FROM health_metric_samples "
            "WHERE user_id=$1 AND metric_type=$2 ORDER BY recorded_at DESC LIMIT 1",
            user["id"], mtype)
        week_sum = await db.fetchval(
            "SELECT COALESCE(SUM(qty),0) FROM health_metric_samples "
            "WHERE user_id=$1 AND metric_type=$2 AND sample_date>=$3",
            user["id"], mtype, week_ago)
        out[mtype] = {
            "last": _ser_exp(last) if last else None,
            "week_sum": float(week_sum) if week_sum is not None else 0.0,
        }
    last_sleep = await db.fetchrow(
        "SELECT * FROM health_sleep WHERE user_id=$1 ORDER BY sleep_date DESC LIMIT 1",
        user["id"])
    last_bp = await db.fetchrow(
        "SELECT * FROM health_blood_pressure WHERE user_id=$1 ORDER BY recorded_at DESC LIMIT 1",
        user["id"])
    workouts_week = int(await db.fetchval(
        "SELECT COUNT(*) FROM health_workouts WHERE user_id=$1 AND start_at>=$2",
        user["id"], week_ago) or 0)
    out["sleep_last"] = _ser_exp(last_sleep) if last_sleep else None
    out["blood_pressure_last"] = _ser_exp(last_bp) if last_bp else None
    out["workouts_this_week"] = workouts_week
    return out


# ---------- Zeitserien (Vitalwerte-Tab) ----------
@router.get("/api/health/metrics/{metric_type}")
async def get_metric_series(metric_type: str, days: Optional[int] = 30,
                             db=Depends(get_db), user=Depends(get_current_user)):
    if metric_type not in ALLOWED_METRIC_TYPES:
        raise HTTPException(404, "Unbekannter Metric-Typ")
    since = date.today() - timedelta(days=max(1, min(int(days or 30), 3650)))
    rows = await db.fetch(
        "SELECT * FROM health_metric_samples WHERE user_id=$1 AND metric_type=$2 "
        "AND sample_date>=$3 ORDER BY recorded_at",
        user["id"], metric_type, since)
    return [_ser_exp(r) for r in rows]


@router.get("/api/health/blood-pressure")
async def get_blood_pressure(days: Optional[int] = 30,
                              db=Depends(get_db), user=Depends(get_current_user)):
    since = date.today() - timedelta(days=max(1, min(int(days or 30), 3650)))
    rows = await db.fetch(
        "SELECT * FROM health_blood_pressure WHERE user_id=$1 AND recorded_at>=$2 ORDER BY recorded_at",
        user["id"], since)
    return [_ser_exp(r) for r in rows]


@router.get("/api/health/blood-glucose")
async def get_blood_glucose(days: Optional[int] = 30,
                             db=Depends(get_db), user=Depends(get_current_user)):
    since = date.today() - timedelta(days=max(1, min(int(days or 30), 3650)))
    rows = await db.fetch(
        "SELECT * FROM health_blood_glucose WHERE user_id=$1 AND recorded_at>=$2 ORDER BY recorded_at",
        user["id"], since)
    return [_ser_exp(r) for r in rows]


# ---------- Schlaf-Tab ----------
@router.get("/api/health/sleep")
async def get_sleep(days: Optional[int] = 30,
                     db=Depends(get_db), user=Depends(get_current_user)):
    since = date.today() - timedelta(days=max(1, min(int(days or 30), 3650)))
    rows = await db.fetch(
        "SELECT * FROM health_sleep WHERE user_id=$1 AND sleep_date>=$2 ORDER BY sleep_date",
        user["id"], since)
    return [_ser_exp(r) for r in rows]


# ---------- Workouts-Tab ----------
@router.get("/api/health/workouts")
async def list_workouts(workout_type: Optional[str] = None, limit: Optional[int] = 100,
                         db=Depends(get_db), user=Depends(get_current_user)):
    lim = max(1, min(int(limit or 100), 500))
    if workout_type:
        rows = await db.fetch(
            "SELECT * FROM health_workouts WHERE user_id=$1 AND workout_type=$2 "
            "ORDER BY start_at DESC LIMIT $3",
            user["id"], workout_type, lim)
    else:
        rows = await db.fetch(
            "SELECT * FROM health_workouts WHERE user_id=$1 ORDER BY start_at DESC LIMIT $2",
            user["id"], lim)
    return [_ser_exp(r) for r in rows]


@router.get("/api/health/workouts/{wid}")
async def get_workout_detail(wid: int, db=Depends(get_db), user=Depends(get_current_user)):
    w = await db.fetchrow("SELECT * FROM health_workouts WHERE id=$1 AND user_id=$2", wid, user["id"])
    if not w:
        raise HTTPException(404, "Workout nicht gefunden")
    metrics = await db.fetch(
        "SELECT metric_key, value, unit FROM health_workout_metrics WHERE workout_id=$1", wid)
    out = _ser_exp(w)
    out["extra_metrics"] = [dict(m) for m in metrics]
    return out
