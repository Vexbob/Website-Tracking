"""Health-Shortcut-Router — Beta-Strecke "Apple Health per iPhone-Kurzbefehl".

Zweiter, unabhaengiger Weg neben der bestehenden Auto-Health-Export-Anbindung.
Ein Kurzbefehl auf dem iPhone POSTet einmal taeglich die letzten drei Tage; ein
ausgefallener Lauf wird damit vom naechsten nachgeholt, derselbe Tag kommt also
mehrfach an und ueberschreibt sich selbst statt Dubletten anzulegen.

Endpoints:
  POST   /api/health/shortcut/import   — Ingest (API-Key-Auth, derselbe Key wie
                                          fuer Auto Health Export)
  GET    /api/health/shortcut/samples  — Rohdaten fuer den Beta-Reiter (JWT)
  GET    /api/health/shortcut/metrics  — vorhandene Metriken + Anzahl (JWT)
  DELETE /api/health/shortcut/samples  — Testdaten wegraeumen (JWT)

Bewusst eine eigene Datei statt einer Erweiterung von ``health_router.py``:
die Strecke ist ein Versuch, dessen Format sich nach den ersten Testlaeufen
noch aendert. So bleibt sie in einem Stueck aenderbar -- und im Zweifel in
einem Stueck entfernbar -- ohne den produktiven Health-Router anzufassen.

Der Roh-Payload landet im vorhandenen ``health_import_log`` (``kind``
``shortcut-<format>``). Damit gelten automatisch die schon gebaute
Aufbewahrungsgrenze (``HEALTH_IMPORT_LOG_KEEP``), die Groessenkappung
(``HEALTH_IMPORT_LOG_MAX_BYTES``) und der Download-Endpoint
``/api/health/imports/{id}/download``. Nebenwirkung, die man kennen muss: die
Aufbewahrungsgrenze gilt fuer beide Strecken zusammen.

Hinweis: Bewusst OHNE ``from __future__ import annotations`` -- gleiche
Begruendung wie in ``health_router.py`` (FastAPI 0.109.0 und Forward-Refs).
"""
from typing import Optional

from fastapi import APIRouter, Depends, Request

from database import get_db
from auth import get_current_user, get_user_from_health_api_key
from deps import (logger, limiter, request_id_ctx, _ser_exp, _parse_iso_date,
                  LIMIT_SHORTCUT_IMPORT, LIMIT_WRITE_RARE)
# Absichtlich der private Helfer aus dem Health-Router: Aufbewahrung und
# Truncation des Import-Protokolls sollen an genau EINER Stelle stehen. Eine
# Kopie hier wuerde bei der naechsten Aenderung an den ENV-Grenzen auseinander
# laufen.
from routers.health_router import _store_import_log
from services.health_shortcut import (
    MAX_POINTS, MAX_REPORT_ITEMS, SHORTCUT_METRICS, SHORTCUT_SOURCE,
    build_summary, cap, extract_points, local_tz, metric_label,
    normalize_metric_key, normalize_point,
)

router = APIRouter(tags=["health-shortcut"])

_UPSERT_SQL = (
    "INSERT INTO health_shortcut_samples "
    "(user_id, metric_key, bucket, bucket_start, sample_date, value, unit, raw_date, source) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
    "ON CONFLICT (user_id, metric_key, bucket, bucket_start) DO UPDATE SET "
    "  value=EXCLUDED.value, unit=EXCLUDED.unit, raw_date=EXCLUDED.raw_date, "
    "  sample_date=EXCLUDED.sample_date, updated_at=NOW() "
    # xmax=0 gilt nur fuer eine frisch eingefuegte Zeile -- damit unterscheidet
    # die Antwort "neu" von "ueberschrieben", ohne vorher lesen zu muessen.
    "RETURNING (xmax = 0) AS inserted"
)


# ---------- Ingest (API-Key-Auth, kein JWT) ----------
@router.post("/api/health/shortcut/import")
@limiter.limit(LIMIT_SHORTCUT_IMPORT)
async def shortcut_import(request: Request, metric: Optional[str] = None,
                          db=Depends(get_db),
                          user=Depends(get_user_from_health_api_key)):
    """Nimmt die Werte des iPhone-Kurzbefehls entgegen.

    Antwortet **immer mit HTTP 200** (Ausnahmen: 401 bei ungueltigem Key, 429
    bei Rate-Limit). Ein 4xx wuerde den Kurzbefehl mit einem Fehler abbrechen
    lassen, bevor der Antworttext sichtbar wird -- und genau der ist beim
    Einrichten das Werkzeug. Ein leerer oder unlesbarer Body ist deshalb kein
    Fehler, sondern eine Antwort, die sagt, was fehlt.

    ``?metric=steps`` setzt die Metrik fuer Punkte, die selbst keine
    mitbringen. Damit genuegt als Body im einfachsten Fall ``2026-09-05;8421``.
    """
    raw = await request.body()
    ctype = (request.headers.get("content-type") or "")[:255]
    default_metric = normalize_metric_key(metric) if metric else None

    fmt, points, skipped = extract_points(raw, ctype, default_metric)
    accepted = []
    warnings = []

    if len(points) > MAX_POINTS:
        warnings.append(f"{len(points)} Punkte empfangen — nur die ersten "
                        f"{MAX_POINTS} verarbeitet")
        points = points[:MAX_POINTS]

    tz = local_tz()
    for p in points:
        norm, skip, warns = normalize_point(p, default_metric, tz)
        warnings.extend(warns)
        if skip is not None:
            skipped.append(skip)
            continue
        try:
            row = await db.fetchrow(
                _UPSERT_SQL, user["id"], norm["metric_key"], norm["bucket"],
                norm["bucket_start"], norm["sample_date"], norm["value"],
                norm["unit"], norm["raw_date"], SHORTCUT_SOURCE)
            action = "inserted" if (row and row["inserted"]) else "updated"
        except Exception as e:
            # Ein kaputter Punkt darf die uebrigen nicht mitreissen.
            logger.warning("Shortcut-Insert fehlgeschlagen user_id=%s metric=%s: %s",
                           user["id"], norm["metric_key"], e)
            skipped.append({"reason": "db_error",
                            "raw": {"metric": norm["metric_key"],
                                    "date": norm["sample_date"].isoformat()},
                            "detail": str(e)[:160]})
            continue
        accepted.append({
            "metric": norm["metric_key"],
            "date": norm["sample_date"].isoformat(),
            "value": norm["value"],
            "unit": norm["unit"],
            "action": action,
        })

    uniq_warnings = sorted(set(warnings))
    if len(uniq_warnings) > 10:
        uniq_warnings = uniq_warnings[:10] + [f"und {len(uniq_warnings) - 10} weitere Hinweise"]

    report = {
        "ok": True,
        "summary": build_summary(accepted, skipped, fmt),
        "received": {
            "format": fmt,
            "content_type": ctype or None,
            "bytes": len(raw),
            "points_found": len(points),
            "default_metric": default_metric,
        },
        "imported": len(accepted),
        "skipped_count": len(skipped),
        "accepted": cap(accepted, MAX_REPORT_ITEMS),
        "skipped": cap(skipped, MAX_REPORT_ITEMS),
        "warnings": uniq_warnings,
        "request_id": request_id_ctx.get(),
    }

    # Roh-Payload IMMER protokollieren -- auch (und gerade) wenn nichts davon
    # lesbar war. Der Helfer schluckt jeden Fehler; das Protokoll darf einen
    # Lauf nie scheitern lassen.
    report["log_id"] = await _store_import_log(
        db, user["id"], f"shortcut-{fmt}", None, ctype, request.headers, raw, report)

    logger.info("Shortcut-Import user_id=%s fmt=%s bytes=%d: %s",
                user["id"], fmt, len(raw), report["summary"])
    if fmt in ("unreadable", "empty"):
        preview = raw[:160].decode("utf-8", errors="replace").replace("\n", " ")
        logger.warning("Shortcut-Import unlesbar user_id=%s ctype=%r preview=%r",
                       user["id"], ctype, preview)
    return report


# ---------- Leseseite fuer den Beta-Reiter (JWT-Auth) ----------
def _enrich(row) -> dict:
    d = _ser_exp(row)
    key = row["metric_key"]
    d["label"] = metric_label(key)
    d["known"] = key in SHORTCUT_METRICS
    return d


@router.get("/api/health/shortcut/samples")
async def list_shortcut_samples(days: Optional[int] = 30, metric: Optional[str] = None,
                                limit: Optional[int] = 500, db=Depends(get_db),
                                user=Depends(get_current_user)):
    """Rohdaten der Kurzbefehl-Strecke. ``days=0`` bedeutet Gesamt -- gleiche
    Konvention wie bei den uebrigen Health-Zeitreihen."""
    lim = max(1, min(int(limit or 500), 2000))
    where = ["user_id=$1"]
    args = [user["id"]]
    if days is not None and int(days) > 0:
        args.append(int(days))
        where.append(f"sample_date >= CURRENT_DATE - ${len(args)}::int")
    if metric:
        args.append(normalize_metric_key(metric))
        where.append(f"metric_key=${len(args)}")
    args.append(lim)
    rows = await db.fetch(
        "SELECT id, metric_key, bucket, bucket_start, sample_date, value, unit, "
        "       raw_date, source, created_at, updated_at "
        "FROM health_shortcut_samples WHERE " + " AND ".join(where) +
        " ORDER BY sample_date DESC, metric_key ASC, bucket_start DESC "
        f"LIMIT ${len(args)}", *args)
    return [_enrich(r) for r in rows]


@router.get("/api/health/shortcut/metrics")
async def list_shortcut_metrics(db=Depends(get_db), user=Depends(get_current_user)):
    """Welche Metriken sind tatsaechlich angekommen — fuellt den Filter im
    Beta-Reiter. ``known=false`` heisst: der Kurzbefehl hat einen Namen
    geschickt, den die Registry nicht kennt. Das ist erlaubt und der Wert ist
    gespeichert, faellt hier aber auf."""
    rows = await db.fetch(
        "SELECT metric_key, COUNT(*) AS count, MIN(sample_date) AS first_date, "
        "       MAX(sample_date) AS last_date, MAX(updated_at) AS last_seen "
        "FROM health_shortcut_samples WHERE user_id=$1 "
        "GROUP BY metric_key ORDER BY metric_key", user["id"])
    return [_enrich(r) for r in rows]


@router.delete("/api/health/shortcut/samples")
@limiter.limit(LIMIT_WRITE_RARE)
async def delete_shortcut_samples(request: Request, metric: Optional[str] = None,
                                  date_from: Optional[str] = None,
                                  date_to: Optional[str] = None,
                                  db=Depends(get_db), user=Depends(get_current_user)):
    """Loescht Rohdaten der Kurzbefehl-Strecke — ohne Filter alles.

    Gedacht fuer den Testbetrieb: aendert sich das Format des Kurzbefehls, soll
    der Datenmuell davor wegraeumbar sein, ohne die Tabelle zu droppen. Ruehrt
    ausschliesslich ``health_shortcut_samples`` an, nie die Daten der
    Auto-Health-Export-Strecke.
    """
    where = ["user_id=$1"]
    args = [user["id"]]
    if metric:
        args.append(normalize_metric_key(metric))
        where.append(f"metric_key=${len(args)}")
    d_from = _parse_iso_date(date_from)
    if d_from:
        args.append(d_from)
        where.append(f"sample_date >= ${len(args)}")
    d_to = _parse_iso_date(date_to)
    if d_to:
        args.append(d_to)
        where.append(f"sample_date <= ${len(args)}")
    result = await db.execute(
        "DELETE FROM health_shortcut_samples WHERE " + " AND ".join(where), *args)
    try:
        deleted = int(str(result).split()[-1])
    except (ValueError, IndexError):
        deleted = 0
    logger.info("Shortcut-Daten geloescht user_id=%s metric=%r von=%s bis=%s -> %d",
                user["id"], metric, d_from, d_to, deleted)
    return {"status": "deleted", "deleted": deleted}
