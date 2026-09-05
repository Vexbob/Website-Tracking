"""Health-Router — Sync-Endpoint fuer Auto Health Export (iPhone) + Frontend-API.

Endpoints:
  POST   /api/health/import              — Ingest-Endpoint fuer die App (API-Key-Auth,
                                            akzeptiert JSON *und* CSV, siehe Doku am Endpoint)
  POST   /api/health/import-file         — Manueller JSON-Upload im Frontend (JWT-Auth)
  POST   /api/health/import-csv          — Manueller CSV-Multi-Upload im Frontend (JWT-Auth)
  GET    /api/health/imports             — Protokoll der letzten Sync-Aufrufe (JWT-Auth)
  GET    /api/health/imports/{id}/download — Roh-Payload eines Sync-Aufrufs herunterladen
  DELETE /api/health/imports/{id}        — einzelnen Protokoll-Eintrag loeschen
  DELETE /api/health/imports             — komplettes Protokoll leeren
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
  GET    /api/health/metric-order        — gespeicherte Reihenfolge der Vitalwerte-Diagramme
  PUT    /api/health/metric-order        — Reihenfolge speichern (Drag & Drop im Frontend)

Hinweis: Bewusst OHNE ``from __future__ import annotations`` — FastAPI 0.109.0
kann ``UploadFile = File(...)`` sonst nicht als Pydantic-Feld aufloesen
(Forward-Ref-Fehler beim Start), siehe auch blog_router.py/expenses_router.py,
die aus demselben Grund ebenfalls darauf verzichten.
"""
import json
import os
import re as _re
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import Response

from database import get_db
from auth import get_current_user, get_user_from_health_api_key, generate_health_api_key
from deps import logger, limiter, LIMIT_HEALTH_IMPORT, LIMIT_WRITE_RARE, LIMIT_WRITE_STANDARD, _ser_exp
from schemas import MetricOrderBody
from services.health_ingest import ingest_payload, ingest_csv_file, SIMPLE_METRIC_MAP, merge_ingest_stats
from services.full_export import build_health_export_csv

router = APIRouter(tags=["health"])

ALLOWED_METRIC_TYPES = sorted(set(SIMPLE_METRIC_MAP.values()))

# ---------- Import-Protokoll (v1.40.0) ----------
# Jeder Sync-Aufruf der iPhone-App wird mit seinem Roh-Payload gespeichert,
# damit er im Frontend heruntergeladen und gegen die importierten Werte
# geprueft werden kann. Zwei ENV-Stellschrauben begrenzen den Platzbedarf:
HEALTH_IMPORT_LOG_KEEP = int(os.getenv("HEALTH_IMPORT_LOG_KEEP") or 200)
HEALTH_IMPORT_LOG_MAX_BYTES = int(os.getenv("HEALTH_IMPORT_LOG_MAX_BYTES") or 5 * 1024 * 1024)


# ---------- Sync-Ingest (API-Key-Auth, kein JWT) ----------
@router.post("/api/health/import")
@limiter.limit(LIMIT_HEALTH_IMPORT)
async def import_health_data(request: Request,
                              db=Depends(get_db),
                              user=Depends(get_user_from_health_api_key)):
    """Universeller Sync-Ingest fuer die Auto-Health-Export-App.

    Akzeptiert bewusst mehrere Body-Formate, weil die App je nach Version und
    gewaehltem Export-Format (JSON / CSV) unterschiedlich POSTet:

      * ``application/json``                  -> JSON-Payload direkt (Original-Struktur)
      * ``text/csv`` / ``application/csv``    -> Roh-CSV im Body (eine Datei)
      * ``multipart/form-data``               -> eine oder mehrere Dateien (JSON und/oder CSV)
      * kein/anderer Content-Type             -> Body wird zuerst als JSON, dann als
                                                 CSV-Fallback interpretiert

    Der Endpoint erkennt das Format anhand von Content-Type + Body-Inhalt und
    delegiert an ``ingest_payload`` (JSON) bzw. ``ingest_csv_file`` (CSV).
    Antwort ist immer das gleiche Stats-Dict wie beim JSON-Sync.
    """
    ctype = (request.headers.get("content-type") or "").lower()
    stats = {"metrics_imported": 0, "workouts_imported": 0, "sleep_imported": 0,
             "bp_imported": 0, "glucose_imported": 0, "skipped": [], "files_processed": 0}

    # ---- Multipart (eine oder mehrere Dateien ODER Text-Felder) ----
    # Auto Health Export schickt in manchen Versionen den CSV-/JSON-Inhalt als
    # gewoehnliches Form-Field ("payload", "data", "csv" o.ae.) statt als echte
    # Datei mit filename. Wir akzeptieren daher beides: UploadFile UND String-Werte.
    if ctype.startswith("multipart/form-data"):
        # Rohbody VOR dem Form-Parsing lesen, damit wir bei Parser-Problemen
        # noch Zugriff auf den Original-Inhalt haben (starlette cached die
        # Bytes nach body(), form() nutzt dann den Cache).
        raw_all = await request.body()
        _log_incoming("multipart-raw", ctype, request.headers, [("full.bin", raw_all)], user["id"])

        pseudo_files: list[tuple[str, bytes]] = []
        try:
            form = await request.form()
            for key, value in form.multi_items():
                if isinstance(value, UploadFile):
                    raw_part = await value.read()
                    pseudo_files.append((value.filename or f"{key}.bin", raw_part))
                elif isinstance(value, str):
                    pseudo_files.append((f"{key}.txt", value.encode("utf-8")))
        except Exception as e:
            logger.warning("Multipart-Parsing fehlgeschlagen user_id=%s: %s", user["id"], e)

        _log_incoming("multipart-parts", ctype, request.headers, pseudo_files, user["id"])

        # Fallback: wenn Starlettes Form-Parser keine Parts fand, aber der
        # Rohbody nicht leer ist, machen wir das Multipart-Splitting selbst.
        # Auto Health Export produziert Multipart-Bodies, die manche Parser
        # nicht mundgerecht bekommen (Whitespace-/CRLF-Eigenheiten). Der
        # manuelle Parser hier trennt ueber die im Content-Type deklarierte
        # Boundary und extrahiert pro Part den reinen Inhalt hinter dem
        # doppelten CRLF (Header-Ende).
        if not pseudo_files and raw_all:
            manual = _manual_multipart_split(raw_all, ctype)
            logger.info("Manueller Multipart-Split user_id=%s: %d Parts gefunden",
                        user["id"], len(manual))
            _log_incoming("multipart-manual", ctype, request.headers, manual, user["id"])
            if manual:
                for fname, raw_part in manual:
                    sub = await _ingest_auto(db, user["id"], raw_part, fname)
                    merge_ingest_stats(stats, sub)
                    stats["files_processed"] += 1
                    await _store_import_log(db, user["id"], "multipart-manual", fname,
                                            ctype, request.headers, raw_part, sub)
                logger.info("Health-Import (multipart-manual) fuer user_id=%s: %s", user["id"], stats)
                return stats
            # Letzter Versuch: Rohbody direkt als JSON/CSV interpretieren.
            logger.info("Manueller Split ergab 0 Parts, versuche Rohbody direkt user_id=%s", user["id"])
            sub = await _ingest_auto(db, user["id"], raw_all, "sync-multipart.bin")
            merge_ingest_stats(stats, sub)
            stats["files_processed"] = 1
            await _store_import_log(db, user["id"], "multipart-raw", "sync-multipart.bin",
                                    ctype, request.headers, raw_all, sub)
            logger.info("Health-Import (multipart-rawfallback) fuer user_id=%s: %s", user["id"], stats)
            return stats

        if not pseudo_files:
            logger.info("Health-Import: leerer Multipart-Body user_id=%s -> 200 no-op", user["id"])
            stats["skipped"].append("empty_multipart")
            await _store_import_log(db, user["id"], "empty", None, ctype, request.headers,
                                    b"", {"skipped": ["empty_multipart"]})
            return stats
        for fname, raw_part in pseudo_files:
            sub = await _ingest_auto(db, user["id"], raw_part, fname)
            merge_ingest_stats(stats, sub)
            stats["files_processed"] += 1
            await _store_import_log(db, user["id"], "multipart", fname,
                                    ctype, request.headers, raw_part, sub)
        logger.info("Health-Import (multipart) fuer user_id=%s: %s", user["id"], stats)
        return stats

    # ---- Raw-Body (JSON oder CSV) ----
    raw = await request.body()
    _log_incoming("raw", ctype, request.headers, [("body.bin", raw)], user["id"])
    if not raw:
        # Leerer Body: viele Apps machen einen "Ping" bevor sie den echten
        # Payload schicken. Wir antworten mit 200 statt 400, damit die App
        # nicht als "Netzwerkfehler" abbricht.
        logger.info("Health-Import: leerer Body user_id=%s -> 200 no-op", user["id"])
        stats["skipped"].append("empty_body")
        await _store_import_log(db, user["id"], "empty", None, ctype, request.headers,
                                b"", {"skipped": ["empty_body"]})
        return stats

    # Explizit als CSV markiert?
    if "csv" in ctype:
        sub = await _ingest_csv_bytes(db, user["id"], raw, "sync.csv")
        merge_ingest_stats(stats, sub)
        stats["files_processed"] = 1
        await _store_import_log(db, user["id"], "csv", "sync.csv", ctype, request.headers, raw, sub)
        logger.info("Health-Import (csv) fuer user_id=%s: %s", user["id"], stats)
        return stats

    # Ansonsten: erst JSON versuchen, dann CSV-Fallback.
    payload = None
    try:
        payload = json.loads(raw)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        sub = await ingest_payload(db, user["id"], payload)
        merge_ingest_stats(stats, sub)
        await _store_import_log(db, user["id"], "json", "sync.json", ctype, request.headers, raw, sub)
        logger.info("Health-Import (json) fuer user_id=%s: %s", user["id"], stats)
        return stats

    # Fallback: als CSV interpretieren (die App schickt bei CSV-Automations
    # oft ohne sauberen Content-Type).
    sub = await _ingest_csv_bytes(db, user["id"], raw, "sync.csv")
    merge_ingest_stats(stats, sub)
    stats["files_processed"] = 1
    await _store_import_log(db, user["id"], "csv-fallback", "sync.csv", ctype, request.headers, raw, sub)
    logger.info("Health-Import (csv-fallback) fuer user_id=%s: %s", user["id"], stats)
    return stats


async def _store_import_log(db, user_id: int, kind: str, filename: Optional[str],
                            ctype: str, headers, raw: Optional[bytes],
                            stats: Optional[dict]) -> Optional[int]:
    """Legt einen Sync-Aufruf mitsamt Roh-Payload im Import-Protokoll ab.

    Wird pro *Teil* aufgerufen (ein Multipart-Part = ein Eintrag), damit sich
    ein spaeter auffaelliger Wert genau der Datei zuordnen laesst, die ihn
    geliefert hat. ``stats`` ist das Ingest-Ergebnis dieses Teils.

    Schluckt bewusst jeden Fehler: das Protokoll ist Diagnose-Beiwerk und darf
    einen laufenden Sync nie scheitern lassen.

    Gibt die ID des Eintrags zurueck (None, wenn das Schreiben scheiterte).
    Genutzt von der Kurzbefehl-Strecke, die die ID in ihrer Antwort mitschickt,
    damit ein Testlauf direkt auf seinen Roh-Payload zeigen kann.
    """
    try:
        data = raw or b""
        size = len(data)
        truncated = size > HEALTH_IMPORT_LOG_MAX_BYTES
        blob = data[:HEALTH_IMPORT_LOG_MAX_BYTES] if data else None
        ua = (headers.get("user-agent") if headers else None) or None
        row = await db.fetchrow(
            "INSERT INTO health_import_log "
            "(user_id, kind, filename, content_type, user_agent, size_bytes, truncated, payload, stats) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb) RETURNING id",
            user_id, kind[:60], (filename or None) and filename[:255],
            (ctype or None) and ctype[:255], ua and ua[:255],
            size, truncated, blob, json.dumps(stats or {}))
        # Aufbewahrung begrenzen: nur die letzten N Eintraege je User behalten.
        await db.execute(
            "DELETE FROM health_import_log WHERE user_id=$1 AND id NOT IN ("
            "  SELECT id FROM health_import_log WHERE user_id=$1 "
            "  ORDER BY created_at DESC, id DESC LIMIT $2)",
            user_id, HEALTH_IMPORT_LOG_KEEP)
        return row["id"] if row else None
    except Exception as e:
        logger.warning("Import-Protokoll konnte nicht geschrieben werden user_id=%s: %s", user_id, e)
        return None


def _log_incoming(kind: str, ctype: str, headers, parts: list, user_id: int) -> None:
    """Diagnose-Log: schreibt Content-Type, User-Agent, Anzahl Parts und einen
    kurzen Vorschau-Snippet aus jedem Part ins Log. Damit sehen wir bei den
    naechsten Sync-Aufrufen der App exakt, welches Format wirklich reinkommt,
    ohne den kompletten Body zu loggen (Privacy + Log-Volumen)."""
    try:
        ua = headers.get("user-agent") or "-"
        for idx, (name, data) in enumerate(parts):
            size = len(data) if data else 0
            preview = ""
            if data:
                try:
                    preview = data[:160].decode("utf-8", errors="replace").replace("\n", " ")
                except Exception:
                    preview = "<binary>"
            logger.info("Health-Import DEBUG user=%s kind=%s ctype=%r ua=%r part[%d]=%r size=%d preview=%r",
                        user_id, kind, ctype, ua, idx, name, size, preview)
    except Exception as e:
        logger.warning("Health-Import DEBUG log fehlgeschlagen: %s", e)


async def _ingest_auto(db, user_id: int, raw: bytes, filename: str) -> dict:
    """Waehlt anhand des Dateinamens / Inhalts JSON- oder CSV-Ingest."""
    name = (filename or "").lower()
    # Klarer JSON-Hinweis -> JSON versuchen
    if name.endswith(".json"):
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                return await ingest_payload(db, user_id, payload)
        except Exception:
            pass
    # Sonst CSV probieren
    if name.endswith(".csv") or _looks_like_csv(raw):
        return await _ingest_csv_bytes(db, user_id, raw, filename or "upload.csv")
    # Letzter Versuch: JSON
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return await ingest_payload(db, user_id, payload)
    except Exception:
        pass
    return {"metrics_imported": 0, "workouts_imported": 0, "sleep_imported": 0,
            "bp_imported": 0, "glucose_imported": 0,
            "skipped": [f"unrecognized_format:{filename or 'body'}"]}


async def _ingest_csv_bytes(db, user_id: int, raw: bytes, filename: str) -> dict:
    return await ingest_csv_file(db, user_id, filename, raw)


def _manual_multipart_split(raw: bytes, ctype: str) -> list[tuple[str, bytes]]:
    """Manueller Multipart-Parser als Fallback fuer Starlettes Form-Parser.

    Liest die Boundary aus dem Content-Type-Header, trennt den Body an
    ``--boundary``-Markern und extrahiert je Part einen (filename, content)-
    Tupel. Sehr tolerant gegenueber CRLF-/Whitespace-Eigenheiten, weil
    verschiedene iOS-App-Versionen die Multipart-Struktur leicht anders
    formatieren.
    """
    if not raw or "boundary=" not in ctype:
        return []
    # Boundary aus Content-Type extrahieren (kann in "" stehen)
    try:
        bnd = ctype.split("boundary=", 1)[1].split(";", 1)[0].strip().strip('"')
    except Exception:
        return []
    if not bnd:
        return []
    # RFC-strikt waere die Boundary case-sensitive, aber die Auto-Health-Export-
    # App (iOS, "Auto Export/...") deklariert die Boundary im Content-Type-
    # Header teilweise klein und schreibt sie im Body groß. Daher splitten wir
    # case-insensitive per Regex.
    import re
    marker_pat = re.compile(
        b"--" + re.escape(bnd.encode("latin-1")),
        re.IGNORECASE,
    )
    parts = marker_pat.split(raw)
    result: list[tuple[str, bytes]] = []
    for i, part in enumerate(parts):
        # Erstes Segment vor erstem Marker + Endsegment nach "--" ignorieren
        if i == 0:
            continue
        stripped = part.lstrip(b"\r\n")
        if stripped.startswith(b"--"):  # Abschluss-Marker
            break
        # Header und Body sind normal durch \r\n\r\n getrennt. Die Auto-Health-
        # Export-App benutzt aber teils *nur einzelne \r* (Mac Classic-Style!)
        # -- deshalb pruefen wir mehrere Varianten in Reihenfolge der Wahr-
        # scheinlichkeit.
        header_body_seps = (b"\r\n\r\n", b"\n\n", b"\r\r", b"\r\n\r", b"\r\n")
        pos = -1
        sep_len = 0
        for candidate in header_body_seps:
            p = stripped.find(candidate)
            if p >= 0:
                pos = p
                sep_len = len(candidate)
                break
        if pos < 0:
            continue
        headers_bytes = stripped[:pos]
        body_bytes = stripped[pos + sep_len:]
        # Trailing CR/LF vor naechstem Boundary-Marker entfernen
        while body_bytes and body_bytes[-1:] in (b"\r", b"\n"):
            body_bytes = body_bytes[:-1]
        # Filename aus Content-Disposition, falls vorhanden
        fname = f"part{i}.bin"
        try:
            hdrs_text = headers_bytes.decode("latin-1", errors="replace")
            # Normalisiere alle Zeilenumbrueche zu \n (Mac Classic \r -> \n)
            hdrs_text = hdrs_text.replace("\r\n", "\n").replace("\r", "\n")
            for line in hdrs_text.split("\n"):
                low = line.lower().strip()
                if low.startswith("content-disposition"):
                    if "filename=" in line:
                        raw_fn = line.split("filename=", 1)[1].strip().strip(";").strip('"').strip()
                        # iOS liefert filename als "file:///private/.../foo.csv"
                        # -> nur den Basename behalten, damit .csv-Endung fuer
                        # _ingest_auto erkennbar bleibt
                        base = raw_fn.rsplit("/", 1)[-1]
                        fname = base or raw_fn
                    elif "name=" in line:
                        n = line.split("name=", 1)[1].strip().strip(";").strip('"').strip()
                        fname = f"{n}.bin"
                    break
        except Exception:
            pass
        if body_bytes:
            result.append((fname, body_bytes))
    return result


def _looks_like_csv(raw: bytes) -> bool:
    """Heuristik: startet der Body mit einer typischen Auto-Health-Export-CSV-
    Header-Zeile? Prueft die ersten paar hundert Bytes, damit wir auch bei
    fehlendem Content-Type CSV zuverlaessig erkennen."""
    try:
        head = raw[:512].decode("utf-8-sig", errors="replace").lstrip().lower()
    except Exception:
        return False
    if not head:
        return False
    first_line = head.splitlines()[0] if head else ""
    return ("workout type" in first_line
            or first_line.startswith("datum")
            or first_line.startswith("date"))


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
        merge_ingest_stats(total, stats)
        total["files_processed"] += 1
    logger.info("Health-CSV-Import fuer user_id=%s: %s Dateien, %s", user["id"], total["files_processed"], total)
    return total


# ---------- Import-Protokoll (v1.40.0, JWT-Auth) ----------
@router.get("/api/health/imports")
async def list_import_log(limit: Optional[int] = 50, kind: Optional[str] = None,
                          db=Depends(get_db), user=Depends(get_current_user)):
    """Listet die letzten Sync-Aufrufe der App — Zeitpunkt, Format, Groesse,
    Ingest-Ergebnis und die ersten Zeichen des Payloads als Vorschau. Der
    komplette Body haengt an ``/api/health/imports/{id}/download``.

    ``kind`` filtert per Praefix (v1.47.0): ``?kind=shortcut`` zeigt nur die
    Aufrufe der Kurzbefehl-Beta-Strecke, deren Eintraege als
    ``shortcut-<format>`` abgelegt werden. Ohne den Parameter bleibt das
    Verhalten unveraendert -- die Liste zeigt beide Strecken, weil sie sich das
    Protokoll teilen."""
    lim = max(1, min(int(limit or 50), 200))
    sql = ("SELECT id, created_at, kind, filename, content_type, user_agent, size_bytes, "
           "       truncated, stats, substring(payload from 1 for 240) AS head "
           "FROM health_import_log WHERE user_id=$1")
    args = [user["id"]]
    if kind:
        args.append(kind[:60] + "%")
        sql += f" AND kind LIKE ${len(args)}"
    args.append(lim)
    rows = await db.fetch(
        sql + f" ORDER BY created_at DESC, id DESC LIMIT ${len(args)}", *args)
    out = []
    for r in rows:
        d = _ser_exp(r)
        head = d.pop("head", None)
        if isinstance(head, (bytes, bytearray)):
            head = head.decode("utf-8", errors="replace")
        d["preview"] = (head or "").replace("\r", " ").replace("\n", " ").strip()
        if isinstance(d.get("stats"), str):
            try:
                d["stats"] = json.loads(d["stats"])
            except Exception:
                d["stats"] = None
        out.append(d)
    return out


def _import_log_filename(row) -> str:
    """Baut einen sicheren Download-Dateinamen aus Eintrags-ID und Originalname."""
    base = (row["filename"] or "").rsplit("/", 1)[-1].strip()
    base = _re.sub(r"[^A-Za-z0-9._-]", "_", base)[:80]
    if not base or base in (".", ".."):
        kind = (row["kind"] or "").lower()
        ext = ".json" if "json" in kind else (".csv" if "csv" in kind else ".bin")
        base = f"payload{ext}"
    ts = row["created_at"].strftime("%Y-%m-%d_%H%M") if row["created_at"] else "unbekannt"
    return f"health-sync_{ts}_{row['id']}_{base}"


@router.get("/api/health/imports/{lid}/download")
async def download_import_log(lid: int, db=Depends(get_db), user=Depends(get_current_user)):
    """Liefert den unveraenderten Roh-Payload eines Sync-Aufrufs als Download —
    genau die Bytes, die die App geschickt hat (ggf. auf
    ``HEALTH_IMPORT_LOG_MAX_BYTES`` gekuerzt, siehe ``truncated`` in der Liste)."""
    row = await db.fetchrow(
        "SELECT id, created_at, kind, filename, content_type, payload "
        "FROM health_import_log WHERE id=$1 AND user_id=$2", lid, user["id"])
    if not row:
        raise HTTPException(404, "Import-Eintrag nicht gefunden")
    payload = row["payload"] or b""
    fname = _import_log_filename(row)
    if fname.endswith(".json"):
        media = "application/json; charset=utf-8"
    elif fname.endswith(".csv"):
        media = "text/csv; charset=utf-8"
    else:
        media = "application/octet-stream"
    return Response(
        content=payload,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("/api/health/imports/{lid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def delete_import_log_entry(request: Request, lid: int, db=Depends(get_db),
                                  user=Depends(get_current_user)):
    r = await db.execute("DELETE FROM health_import_log WHERE id=$1 AND user_id=$2",
                         lid, user["id"])
    if r.endswith(" 0"):
        raise HTTPException(404, "Import-Eintrag nicht gefunden")
    return {"status": "deleted"}


@router.delete("/api/health/imports")
@limiter.limit(LIMIT_WRITE_RARE)
async def clear_import_log(request: Request, db=Depends(get_db),
                           user=Depends(get_current_user)):
    """Leert das komplette Protokoll des eingeloggten Users. Loescht nur die
    Roh-Payloads — die daraus importierten Gesundheitsdaten bleiben."""
    r = await db.execute("DELETE FROM health_import_log WHERE user_id=$1", user["id"])
    deleted = int(r.rsplit(" ", 1)[-1]) if r.rsplit(" ", 1)[-1].isdigit() else 0
    return {"status": "cleared", "deleted": deleted}


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


# ---------- Anordnung der Vitalwerte-Diagramme (v1.46.1) ----------
METRIC_ORDER_PREF = "health_metric_order"


@router.get("/api/health/metric-order")
async def get_metric_order(db=Depends(get_db), user=Depends(get_current_user)):
    """Vom Nutzer per Drag & Drop festgelegte Reihenfolge der Metrik-Karten.

    Leere Liste heisst "noch nie sortiert" — das Frontend nimmt dann seine
    eigene Default-Reihenfolge. Unbekannte Eintraege (z.B. eine Metrik, die es
    nicht mehr gibt) werden hier schon herausgefiltert, damit das Frontend sich
    darum nicht kuemmern muss.
    """
    raw = await db.fetchval(
        "SELECT value FROM user_prefs WHERE user_id=$1 AND key=$2",
        user["id"], METRIC_ORDER_PREF)
    order: List[str] = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                seen = set()
                for x in parsed:
                    k = str(x)
                    if k in ALLOWED_METRIC_TYPES and k not in seen:
                        seen.add(k)
                        order.append(k)
        except (ValueError, TypeError):
            logger.warning("Ungueltige Metrik-Reihenfolge fuer User %s", user["id"])
    return {"order": order}


@router.put("/api/health/metric-order")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def set_metric_order(request: Request, b: MetricOrderBody,
                            db=Depends(get_db), user=Depends(get_current_user)):
    seen = set()
    order = []
    for x in b.order:
        k = str(x)
        if k not in ALLOWED_METRIC_TYPES:
            raise HTTPException(400, f"Unbekannter metric_type: {k}")
        if k not in seen:
            seen.add(k)
            order.append(k)
    await db.execute(
        "INSERT INTO user_prefs (user_id, key, value) VALUES ($1, $2, $3) "
        "ON CONFLICT (user_id, key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
        user["id"], METRIC_ORDER_PREF, json.dumps(order))
    return {"status": "ok", "order": order}


# ---------- Zeitserien (Vitalwerte-Tab) ----------
def _series_since(days: Optional[int]):
    """Startdatum fuer einen Zeitraum-Filter -- oder ``None`` fuer "Gesamt".

    v1.46.0: Alle Zeitraum-Chips im Frontend bieten einheitlich
    7 / 30 / 90 / 365 Tage und "Gesamt" an. "Gesamt" kommt als ``days=0``
    an und darf dann eben NICHT auf einen Tag zusammenschnurren (vorher
    haette ``max(1, 0)`` genau das getan).
    """
    d = int(days if days is not None else 30)
    if d <= 0:
        return None
    return date.today() - timedelta(days=min(d, 3650))


@router.get("/api/health/metrics/{metric_type}")
async def get_metric_series(metric_type: str, days: Optional[int] = 30,
                             db=Depends(get_db), user=Depends(get_current_user)):
    if metric_type not in ALLOWED_METRIC_TYPES:
        raise HTTPException(404, "Unbekannter Metric-Typ")
    since = _series_since(days)
    if since is None:
        rows = await db.fetch(
            "SELECT * FROM health_metric_samples WHERE user_id=$1 AND metric_type=$2 "
            "ORDER BY recorded_at", user["id"], metric_type)
    else:
        rows = await db.fetch(
            "SELECT * FROM health_metric_samples WHERE user_id=$1 AND metric_type=$2 "
            "AND sample_date>=$3 ORDER BY recorded_at",
            user["id"], metric_type, since)
    return [_ser_exp(r) for r in rows]


@router.get("/api/health/blood-pressure")
async def get_blood_pressure(days: Optional[int] = 30,
                              db=Depends(get_db), user=Depends(get_current_user)):
    since = _series_since(days)
    if since is None:
        rows = await db.fetch(
            "SELECT * FROM health_blood_pressure WHERE user_id=$1 ORDER BY recorded_at",
            user["id"])
    else:
        rows = await db.fetch(
            "SELECT * FROM health_blood_pressure WHERE user_id=$1 AND recorded_at>=$2 ORDER BY recorded_at",
            user["id"], since)
    return [_ser_exp(r) for r in rows]


@router.get("/api/health/blood-glucose")
async def get_blood_glucose(days: Optional[int] = 30,
                             db=Depends(get_db), user=Depends(get_current_user)):
    since = _series_since(days)
    if since is None:
        rows = await db.fetch(
            "SELECT * FROM health_blood_glucose WHERE user_id=$1 ORDER BY recorded_at",
            user["id"])
    else:
        rows = await db.fetch(
            "SELECT * FROM health_blood_glucose WHERE user_id=$1 AND recorded_at>=$2 ORDER BY recorded_at",
            user["id"], since)
    return [_ser_exp(r) for r in rows]


# ---------- Schlaf-Tab ----------
@router.get("/api/health/sleep")
async def get_sleep(days: Optional[int] = 30,
                     db=Depends(get_db), user=Depends(get_current_user)):
    since = _series_since(days)
    if since is None:
        rows = await db.fetch(
            "SELECT * FROM health_sleep WHERE user_id=$1 ORDER BY sleep_date", user["id"])
    else:
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
