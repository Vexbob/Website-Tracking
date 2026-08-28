"""Health-Router — Sync-Endpoint fuer Auto Health Export (iPhone) + Frontend-API.

Endpoints:
  POST   /api/health/import              — Ingest-Endpoint fuer die App (API-Key-Auth)
  POST   /api/health/import-file         — Manueller JSON-Upload im Frontend (JWT-Auth)
  POST   /api/health/import-csv          — Manueller CSV-Multi-Upload im Frontend (JWT-Auth)
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

Hinweis: Bewusst OHNE ``from __future__ import annotations`` — FastAPI 0.109.0
kann ``UploadFile = File(...)`` sonst nicht als Pydantic-Feld aufloesen
(Forward-Ref-Fehler beim Start), siehe auch blog_router.py/expenses_router.py,
die aus demselben Grund ebenfalls darauf verzichten.
"""
import json
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import Response

from database import get_db
from auth import get_current_user, get_user_from_health_api_key, generate_health_api_key
from deps import logger, limiter, LIMIT_HEALTH_IMPORT, LIMIT_WRITE_RARE, LIMIT_WRITE_STANDARD, _ser_exp
from services.health_ingest import ingest_payload, ingest_csv_file, SIMPLE_METRIC_MAP
from services.full_export import build_health_export_csv

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


@router.post("/api/health/import-csv")
@limiter.limit(LIMIT_WRITE_RARE)
async def import_health_csv(request: Request, files: List[UploadFile] = File(...),
                             db=Depends(get_db), user=Depends(get_current_user)):
    """Nimmt eine oder mehrere per Hand exportierte Auto-Health-Export-CSV-
    Dateien entgegen (Tages-Gesundheitsmetriken + Workouts-Uebersicht).
    Deutlich kleiner als das JSON-Format, daher fuer groessere Backfills
    (z.B. ein ganzer Monat) besser geeignet. Erkennt den Dateityp automatisch
    am Header; nicht erkannte Dateien (z.B. die vielen Pro-Workout-Einzel-
    metrik-CSVs) werden uebersprungen und im Ergebnis aufgelistet."""
    total = {"metrics_imported": 0, "workouts_imported": 0, "sleep_imported": 0,
             "bp_imported": 0, "glucose_imported": 0, "skipped": [], "files_processed": 0}
    for f in files:
        raw = await f.read()
        stats = await ingest_csv_file(db, user["id"], f.filename or "unknown.csv", raw)
        for key in ("metrics_imported", "workouts_imported", "sleep_imported",
                    "bp_imported", "glucose_imported"):
            total[key] += stats.get(key, 0)
        total["skipped"].extend(stats.get("skipped", []))
        total["files_processed"] += 1
    logger.info("Health-CSV-Import fuer user_id=%s: %s Dateien, %s", user["id"], total["files_processed"], total)
    return total


# ---------- CSV-Export (v1.27.0) ----------
@router.get("/api/health/export")
async def export_health_csv(db=Depends(get_db), user=Depends(get_current_user)):
    """Dediziertes CSV-Backup aller Gesundheitsdaten des eingeloggten Users
    (Zusammenfassung, Vitalwerte-Zeitserien, Blutdruck, Blutzucker, Schlaf,
    Workouts inkl. Zusatzmetriken). Selbe Sektions-Struktur wie im
    Gesamt-Export ``/api/export/all``, aber nur der Health-Anteil."""
    csv = await build_health_export_csv(db, user)
    # UTF-8 mit BOM, damit Excel Umlaute (ä/ö/ü/ß) korrekt darstellt
    content = ("\ufeff" + csv).encode("utf-8")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="vexbob-health-export.csv"',
            "Cache-Control": "no-store",
        },
    )


# ---------- Datensaetze loeschen (v1.28.0) ----------
# Erlaubte Bereiche fuer den Bulk-Delete-Endpoint. Werte mappen auf
# (Tabelle, Zeitspalte). ``all`` loescht in allen Tabellen.
_HEALTH_DELETE_SCOPES = {
    "metrics":         ("health_metric_samples", "sample_date"),
    "blood_pressure":  ("health_blood_pressure", "recorded_at"),
    "blood_glucose":   ("health_blood_glucose",  "recorded_at"),
    "sleep":           ("health_sleep",          "sleep_date"),
    "workouts":        ("health_workouts",       "start_at"),
}


def _parse_iso_date(s: Optional[str], field: str) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise HTTPException(400, f"{field}: ungueltiges Datum (erwartet YYYY-MM-DD)")


@router.post("/api/health/delete")
@limiter.limit(LIMIT_WRITE_RARE)
async def bulk_delete_health(request: Request, body: dict,
                              db=Depends(get_db), user=Depends(get_current_user)):
    """Bulk-Delete fuer Health-Datensaetze. Body:
        {
          "scope": "all" | "metrics" | "blood_pressure" | "blood_glucose"
                    | "sleep" | "workouts",
          "metric_type": "steps",           # nur bei scope=metrics (optional)
          "workout_type": "Running",         # nur bei scope=workouts (optional)
          "from_date": "YYYY-MM-DD",         # optional (inkl.)
          "to_date":   "YYYY-MM-DD"          # optional (inkl.)
        }

    Antwort: pro Sektion die Anzahl geloeschter Zeilen und die Summe. Die
    Loeschung ist idempotent — ist der Filter zu eng, werden 0 Zeilen
    geloescht ohne Fehler.
    """
    scope = (body.get("scope") or "").strip()
    if scope not in _HEALTH_DELETE_SCOPES and scope != "all":
        raise HTTPException(400, f"Unbekannter scope: {scope}")

    from_d = _parse_iso_date(body.get("from_date"), "from_date")
    to_d   = _parse_iso_date(body.get("to_date"),   "to_date")
    if from_d and to_d and from_d > to_d:
        raise HTTPException(400, "from_date liegt hinter to_date")

    metric_type  = (body.get("metric_type") or "").strip() or None
    workout_type = (body.get("workout_type") or "").strip() or None
    if metric_type and metric_type not in ALLOWED_METRIC_TYPES:
        raise HTTPException(400, f"Unbekannter metric_type: {metric_type}")

    scopes = list(_HEALTH_DELETE_SCOPES.keys()) if scope == "all" else [scope]
    deleted: dict[str, int] = {}
    async with db.transaction():
        for s in scopes:
            table, date_col = _HEALTH_DELETE_SCOPES[s]
            params: list = [user["id"]]
            where = "user_id=$1"
            if from_d is not None:
                params.append(from_d); where += f" AND {date_col} >= ${len(params)}"
            if to_d is not None:
                params.append(to_d);   where += f" AND {date_col} <= ${len(params)}"
            if s == "metrics" and metric_type:
                params.append(metric_type); where += f" AND metric_type = ${len(params)}"
            if s == "workouts" and workout_type:
                params.append(workout_type); where += f" AND workout_type = ${len(params)}"
            tag = await db.execute(f"DELETE FROM {table} WHERE {where}", *params)
            try:
                deleted[s] = int(tag.rsplit(" ", 1)[-1])
            except (ValueError, AttributeError):
                deleted[s] = 0
    total = sum(deleted.values())
    logger.info("Health-Delete fuer user_id=%s scope=%s from=%s to=%s: %s",
                user["id"], scope, from_d, to_d, deleted)
    return {"deleted": deleted, "total": total}


@router.delete("/api/health/workouts/{wid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def delete_workout(request: Request, wid: int,
                          db=Depends(get_db), user=Depends(get_current_user)):
    """Loescht ein einzelnes Workout inkl. seiner Zusatzmetriken (die per
    ON DELETE CASCADE oder via expliziter Zeile mitgeloescht werden)."""
    row = await db.fetchrow(
        "SELECT id FROM health_workouts WHERE id=$1 AND user_id=$2", wid, user["id"])
    if not row:
        raise HTTPException(404, "Workout nicht gefunden")
    async with db.transaction():
        # Zusatzmetriken zuerst, falls die Tabelle keinen CASCADE hat
        await db.execute(
            "DELETE FROM health_workout_metrics WHERE workout_id=$1", wid)
        await db.execute(
            "DELETE FROM health_workouts WHERE id=$1 AND user_id=$2", wid, user["id"])
    logger.info("User %s deleted workout %s", user["id"], wid)
    return {"status": "deleted"}


@router.delete("/api/health/sleep/{sid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def delete_sleep(request: Request, sid: int,
                        db=Depends(get_db), user=Depends(get_current_user)):
    """Loescht eine einzelne Schlaf-Nacht."""
    tag = await db.execute(
        "DELETE FROM health_sleep WHERE id=$1 AND user_id=$2", sid, user["id"])
    if tag.endswith(" 0"):
        raise HTTPException(404, "Schlaf-Eintrag nicht gefunden")
    return {"status": "deleted"}


@router.delete("/api/health/blood-pressure/{bid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def delete_blood_pressure(request: Request, bid: int,
                                 db=Depends(get_db), user=Depends(get_current_user)):
    tag = await db.execute(
        "DELETE FROM health_blood_pressure WHERE id=$1 AND user_id=$2", bid, user["id"])
    if tag.endswith(" 0"):
        raise HTTPException(404, "Blutdruck-Eintrag nicht gefunden")
    return {"status": "deleted"}


@router.delete("/api/health/blood-glucose/{bid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def delete_blood_glucose(request: Request, bid: int,
                                db=Depends(get_db), user=Depends(get_current_user)):
    tag = await db.execute(
        "DELETE FROM health_blood_glucose WHERE id=$1 AND user_id=$2", bid, user["id"])
    if tag.endswith(" 0"):
        raise HTTPException(404, "Blutzucker-Eintrag nicht gefunden")
    return {"status": "deleted"}


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
