import os
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import date, timedelta, datetime, timezone
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request, status, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import asyncpg
import secrets

import database as db_module
from database import (
    get_db, get_pool, close_pool, init_db,
    week_key_for, month_key_for, period_key, prev_period,
    _seed_empty_user,
)
from auth import (
    authenticate, create_token, get_current_user, require_admin, pwd_context,
    _invalidate_user_cache, verify_password_ct,
)
from services.backup import create_snapshot, restore_snapshot, prune_snapshots

# Zentrale Utilities & Konstanten (auch von routers/* genutzt)
from deps import (
    logger, limiter,
    LIMIT_LOGIN, LIMIT_WRITE_FREQUENT, LIMIT_WRITE_STANDARD, LIMIT_WRITE_RARE,
    RequestIdFilter, request_id_ctx,
)

# Ausgelagerte Pydantic-Models (v1.15.1)
from schemas import (
    SavGoalUpd, SavGoalCreate, SavGoalTransfer, AchCreate, AchUpd, AchEdit,
    PGCreate, PGUpd, CheckinBody, NoteBody,
    PotCreate, FICreate, ReorderBody, RestoreBody,
    UserCreate, UserPasswordReset, UserCreateInvite, ActivateBody, TrophyCreate,
)

# Ausgelagerte Utility-Funktionen (v1.15.1)
from helpers import (
    ser, fmt_de_num, _milestones_at, _active_goal_id, _streak,
    _general_goal_id, _reward_goal_for,
    _build_export_header, _build_export_metadata, _sparziel_protocol_lines,
)

# v1.34.0: Log-Format enthaelt jetzt die per Middleware gesetzte request_id.
# Bei Log-Zeilen ausserhalb eines Requests (Startup, Backup-Loop, ...) steht
# dort einfach ``-`` -- der Filter unten sorgt dafuer.
# v1.35.0: optionaler Sentry-Hook. Nur wenn SENTRY_DSN gesetzt UND sentry_sdk
# installiert ist -- ohne DSN passiert absolut nichts, sentry_sdk wird nicht
# einmal importiert. So bleibt es eine reine Opt-In-Abhaengigkeit ohne
# Impact auf bestehende Deploys.
_SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if _SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.asyncio import AsyncioIntegration

        sentry_sdk.init(
            dsn=_SENTRY_DSN,
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
            environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
            release=os.getenv("SENTRY_RELEASE") or None,
            integrations=[FastApiIntegration(), AsyncioIntegration()],
            # PII (User-Emails, IPs) NICHT senden -- ist eine private App.
            send_default_pii=False,
        )
    except ImportError:
        # sentry_sdk nicht installiert -- OK, wird bewusst optional gehalten.
        pass
    except Exception as _e:
        # Sentry-Init darf niemals den Startup killen.
        logging.getLogger("vexbob").warning(f"Sentry init failed: {_e}")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s',
)
_req_filter = RequestIdFilter()
for _h in logging.getLogger().handlers:
    _h.addFilter(_req_filter)
# Auch uvicorn.access / uvicorn.error explizit einhaengen -- die haben nach
# uvicorn --reload eigene Handler, die sonst weiter das Default-Format nutzen.
for _name in ("uvicorn", "uvicorn.error", "uvicorn.access", "vexbob", "vexbob.backup", "vexbob.migrations"):
    for _h in logging.getLogger(_name).handlers:
        _h.addFilter(_req_filter)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """v1.33.0: sauberer Startup/Shutdown ohne @app.on_event (deprecated).

    - init_db() (Migrationen anwenden)
    - Bootstrap-Admin per ENV, falls die users-Tabelle leer ist
    - Brand-Seed fuer alle User idempotent nachziehen
    - Achievement-Meilenstein-Repair (v1.18.0)
    - Auto-Backup-Task starten
    Beim Shutdown wird der Pool sauber geschlossen.
    """
    logger.info("Startup: initializing DB")
    await init_db()

    # ---- Bootstrap-Admin (v1.33.0) ----
    # Wird NUR angelegt, wenn (a) beide ENVs gesetzt sind UND (b) noch kein
    # einziger User in der DB existiert. Damit ist Neu-Deployen mit einem
    # frischen Postgres reproduzierbar, ohne dass wir bei einer bestehenden
    # Installation etwas ueberschreiben. Doku dazu im README.
    try:
        adm_user = os.getenv("ADMIN_BOOTSTRAP_USERNAME", "").strip()
        adm_pw = os.getenv("ADMIN_BOOTSTRAP_PASSWORD", "")
        if adm_user and adm_pw:
            pool = await get_pool()
            async with pool.acquire() as conn:
                any_user = await conn.fetchval("SELECT 1 FROM users LIMIT 1")
                if not any_user:
                    hash_ = pwd_context.hash(adm_pw)
                    row = await conn.fetchrow(
                        "INSERT INTO users (username, password_hash, is_admin) "
                        "VALUES ($1, $2, TRUE) RETURNING id",
                        adm_user, hash_)
                    await _seed_empty_user(conn, row["id"])
                    logger.info(
                        f"Bootstrap-Admin '{adm_user}' angelegt "
                        "(users-Tabelle war leer)")
    except Exception as e:
        logger.warning(f"Bootstrap-Admin fehlgeschlagen: {e}")

    # v1.16.0: Marken-Seed fuer alle vorhandenen User nachziehen (idempotent).
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            user_ids = [r["id"] for r in await conn.fetch("SELECT id FROM users")]
            for uid in user_ids:
                try:
                    await _seed_empty_user(conn, uid)
                except Exception as e:
                    logger.warning(f"Brand-seed for user {uid} failed: {e}")
        if user_ids:
            logger.info(f"Brand-seed nachgezogen fuer {len(user_ids)} User")
    except Exception as e:
        logger.warning(f"Brand-seed at startup failed: {e}")

    # v1.18.0: Achievement-Meilenstein-Repair
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            repaired = await _repair_achievement_milestones(conn)
        if repaired:
            logger.info(f"Achievement-Repair: {repaired} fehlende Meilensteine nachgetragen")
    except Exception as e:
        logger.warning(f"Achievement-Repair at startup failed: {e}")

    logger.info(f"Startup complete. CORS origins: {CORS_ORIGINS}")
    backup_task = asyncio.create_task(_auto_backup_loop())
    try:
        yield
    finally:
        backup_task.cancel()
        try:
            await backup_task
        except (asyncio.CancelledError, Exception):
            pass
        await close_pool()
        logger.info("Shutdown complete")


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS-Origins via ENV konfigurierbar (Komma-getrennt).
# Default deckt lokale Entwicklung ab.
_cors_env = os.getenv("CORS_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500")
CORS_ORIGINS = [o.strip() for o in _cors_env.split(",") if o.strip()]

app.add_middleware(CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# v1.21.1: GZip-Kompression fuer alle Responses ab 1 KB. JSON-Listen (z.B.
# /api/expenses/products, /api/brands) sind hochgradig repetitiv und schrumpfen
# damit typischerweise auf 20-30% ihrer Rohgroesse -> spuerbar schnellere
# Ladezeiten, vor allem auf Mobilfunk.
app.add_middleware(GZipMiddleware, minimum_size=1000)


# v1.34.0: Request-ID-Middleware. Setzt fuer jeden Request eine ContextVar,
# damit ``logger.info(...)``-Aufrufe automatisch die ID im Log-Format
# ausgeben. Falls der Client selbst ``X-Request-ID`` mitschickt (nuetzlich
# fuer Frontend->Backend-Correlation), respektieren wir sie -- sonst
# generieren wir eine kurze zufaellige. Response spiegelt sie im Header
# zurueck, damit man sie im Browser-Devtools sofort greifen kann.
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("x-request-id", "").strip()
    if not rid or len(rid) > 64:
        rid = secrets.token_hex(6)  # 12-Zeichen-Hex, kompakt fuer Logs
    token = request_id_ctx.set(rid)
    try:
        response = await call_next(request)
    finally:
        request_id_ctx.reset(token)
    response.headers["X-Request-ID"] = rid
    return response

async def _auto_backup_loop():
    while True:
        try:
            now = datetime.now(timezone.utc)
            target = now.replace(hour=2, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            sleep_s = (target - now).total_seconds()
            logger.info(f"Next auto-backup in {int(sleep_s/60)} min")
            await asyncio.sleep(sleep_s)
            pool = await get_pool()
            async with pool.acquire() as conn:
                # Global-Snapshot (user_id NULL) — nur Admin kann drauf zugreifen
                await create_snapshot(conn, trigger_type="auto_daily", user_id=None)
                if datetime.now(timezone.utc).weekday() == 6:
                    await create_snapshot(conn, trigger_type="auto_weekly", user_id=None)
                await prune_snapshots(conn)
        except Exception as e:
            logger.exception(f"Auto-backup failed: {e}")
            await asyncio.sleep(3600)

# v1.33.0: Der frueher hier stehende @app.on_event("startup")-Handler ist auf
# den ``lifespan``-Context-Manager oben umgezogen (FastAPI 0.109+ deprecated
# on_event). Init-Logik, Backup-Task und Repair-Job laufen jetzt dort.


async def _repair_achievement_milestones(conn) -> int:
    """Traegt fehlende Meilenstein-Auszahlungen nach.

    Fuer jedes Achievement wird ``_milestones_at(sv, cv, inc, dir)`` neu
    berechnet. Wenn diese Zahl groesser ist als ``credited_milestones`` und
    groesser als die bereits vorhandenen ``savings_transactions``, werden
    die fehlenden Meilensteine mit Note ``"Nachtrag v1.18: Meilenstein-Reparatur"``
    nachgetragen (achievement_logs + savings_transactions) und
    ``credited_milestones`` aktualisiert.

    Rueckgabewert: Anzahl nachgetragener Meilensteine (ueber alle User).
    """
    achs = await conn.fetch(
        "SELECT id, user_id, title, unit, start_value, current_value, "
        "threshold_increment, reward_amount, direction, credited_milestones, target_value, "
        "reward_goal_id "
        "FROM achievements")
    total_added = 0
    for a in achs:
        try:
            sv = float(a["start_value"] or 0)
            cv = float(a["current_value"] or 0)
            inc = float(a["threshold_increment"] or 0)
            if inc <= 0:
                continue
            dirn = a["direction"] or "increase"
            rew = float(a["reward_amount"] or 0)
            cred = int(a["credited_milestones"] or 0)
            tm = _milestones_at(sv, cv, inc, dirn)
            # Bereits ausgezahlte Meilensteine anhand tatsächlicher Transaktionen zählen
            paid = int(await conn.fetchval(
                "SELECT COUNT(*) FROM savings_transactions "
                "WHERE user_id=$1 AND source_type='achievement' AND source_id=$2",
                a["user_id"], a["id"]) or 0)
            baseline = max(cred, paid)
            if tm <= baseline:
                # Nur credited_milestones konsistent zu paid halten
                if cred != baseline:
                    await conn.execute(
                        "UPDATE achievements SET credited_milestones=$1 WHERE id=$2",
                        baseline, a["id"])
                continue
            # Explicit-preferred Ziel aus reward_goal_id (falls Spalte existiert)
            try:
                pref_goal = a["reward_goal_id"]
            except (KeyError, IndexError):
                pref_goal = None
            note = "Nachtrag v1.18: Meilenstein-Reparatur"
            for step in range(baseline + 1, tm + 1):
                milestone_value = sv + step * inc if dirn == "increase" else sv - step * inc
                desc = f"Meilenstein: {a['title']} ({fmt_de_num(milestone_value)} {a['unit'] or ''})"
                sg_id = await _reward_goal_for(conn, a["user_id"], pref_goal, rew)
                await conn.execute(
                    "INSERT INTO achievement_logs (user_id,achievement_id,achieved_value,reward_amount,note) "
                    "VALUES ($1,$2,$3,$4,$5)",
                    a["user_id"], a["id"], milestone_value, rew, note)
                await conn.execute(
                    "INSERT INTO savings_transactions "
                    "(user_id,amount,source_type,source_id,description,note,savings_goal_id) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                    a["user_id"], rew, "achievement", a["id"], desc, note, sg_id)
                total_added += 1
            # is_completed neu evaluieren
            tv = a["target_value"]
            comp = False
            if tv is not None:
                if dirn == "increase" and cv >= float(tv):
                    comp = True
                elif dirn == "decrease" and cv <= float(tv):
                    comp = True
            await conn.execute(
                "UPDATE achievements SET credited_milestones=$1, is_completed=$2 WHERE id=$3",
                tm, comp, a["id"])
            logger.info(
                f"Repair: Achievement {a['id']} ('{a['title']}', user {a['user_id']}): "
                f"{tm - baseline} Meilenstein(e) nachgetragen (baseline={baseline}→{tm})")
        except Exception as e:
            logger.warning(f"Repair fehlgeschlagen fuer Achievement {a['id']}: {e}")
    return total_added

# Pydantic-Models leben in ``schemas.py`` (ausgelagert v1.15.1)
# Utility-Funktionen (``ser``, ``fmt_de_num``, ``_milestones_at``,
# ``_active_goal_id``, ``_streak``, Export-Helfer) leben in ``helpers.py``.

# ---------- Auth ----------
@app.post("/token")
@limiter.limit(LIMIT_LOGIN)
async def login(request: Request,
                form: OAuth2PasswordRequestForm = Depends(),
                conn: asyncpg.Connection = Depends(get_db)):
    # v1.33.0: constant-time Password-Check gegen User-Enumeration (Timing-Attack).
    row = await conn.fetchrow("SELECT * FROM users WHERE username = $1", form.username)
    pw_hash = row["password_hash"] if row else None
    if not verify_password_ct(form.password, pw_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falsche Credentials")
    return {"access_token": create_token(row["username"]), "token_type": "bearer"}

@app.get("/api/me")
async def me(user=Depends(get_current_user)):
    return {"username": user["username"], "is_admin": user["is_admin"], "id": user["id"]}

BACKEND_VERSION = "1.35.0"


@app.get("/api/health")
async def health():
    """Liveness-Probe: bewusst OHNE DB-Zugriff. Wird von Railway/Uptime-Robot
    aufgerufen um zu wissen, ob der Uvicorn-Worker ueberhaupt Requests
    annimmt. Fuer "kann das Backend die DB erreichen?" gibt es seit v1.34.0
    den separaten ``/api/readiness``-Endpoint."""
    return {
        "status": "ok",
        "backend_version": BACKEND_VERSION,
        "routes": sum(1 for r in app.routes if hasattr(r, "endpoint")),
        "expenses_router": True,
        "notes_router": True,
    }


@app.get("/api/readiness")
async def readiness():
    """Readiness-Probe (v1.34.0): pruft ob die DB erreichbar ist und wie viele
    Migrationen angewendet wurden. Antwortet mit HTTP 503, wenn der DB-Ping
    fehlschlaegt -- so kann Railway einen unhealthy Container automatisch
    neu starten, statt Traffic auf einen halbtoten Worker zu routen.

    Der Endpoint ist bewusst unauthentifiziert (kein PII), aber liefert
    keine Details ueber Tabellen-Inhalte -- nur harte Infrastruktur-Signale.
    """
    from fastapi.responses import JSONResponse
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
            migrations = await conn.fetchval(
                "SELECT COUNT(*) FROM schema_migrations")
        return {
            "status": "ready",
            "backend_version": BACKEND_VERSION,
            "db": "ok",
            "migrations_applied": int(migrations or 0),
        }
    except Exception as e:
        logger.warning(f"Readiness check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "not-ready",
                "backend_version": BACKEND_VERSION,
                "db": "error",
                "error": str(e)[:200],
            },
        )

# ---------- Admin: User-Management (Invite-Flow) ----------
INVITE_EXPIRES_HOURS = 24 * 7  # 7 Tage

@app.get("/api/admin/users")
async def admin_list_users(db=Depends(get_db), admin=Depends(require_admin)):
    rows = await db.fetch(
        """SELECT u.id, u.username, u.is_admin, u.created_at,
                  (u.password_hash IS NOT NULL) AS activated,
                  (SELECT token FROM invite_tokens
                    WHERE user_id=u.id AND used_at IS NULL AND expires_at > NOW()
                    ORDER BY created_at DESC LIMIT 1) AS pending_token,
                  (SELECT expires_at FROM invite_tokens
                    WHERE user_id=u.id AND used_at IS NULL AND expires_at > NOW()
                    ORDER BY created_at DESC LIMIT 1) AS pending_expires
           FROM users u
           ORDER BY u.is_admin DESC, u.id""")
    return [ser(r) for r in rows]

@app.post("/api/admin/users")
@limiter.limit(LIMIT_WRITE_RARE)
async def admin_create_user(request: Request, b: UserCreateInvite, db=Depends(get_db), admin=Depends(require_admin)):
    uname = (b.username or "").strip()
    if not uname or len(uname) < 2:
        raise HTTPException(400, "Username zu kurz")
    if await db.fetchval("SELECT 1 FROM users WHERE username=$1", uname):
        raise HTTPException(400, "Username existiert bereits")
    # User ohne Passwort anlegen
    row = await db.fetchrow(
        "INSERT INTO users (username, password_hash, is_admin) VALUES ($1, NULL, FALSE) "
        "RETURNING id, username, is_admin, created_at",
        uname)
    # Grundstruktur seeden
    await _seed_empty_user(db, row["id"])
    # Invite-Token erstellen
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=INVITE_EXPIRES_HOURS)
    await db.execute(
        "INSERT INTO invite_tokens (token, user_id, expires_at) VALUES ($1, $2, $3)",
        token, row["id"], expires)
    logger.info(f"Admin {admin['username']} created invite for {uname}")
    return {**ser(row), "invite_token": token, "invite_expires_at": expires.isoformat()}

@app.post("/api/admin/users/{uid}/regenerate-invite")
@limiter.limit(LIMIT_WRITE_RARE)
async def admin_regenerate_invite(request: Request, uid: int, db=Depends(get_db), admin=Depends(require_admin)):
    target = await db.fetchrow("SELECT id, username, password_hash FROM users WHERE id=$1", uid)
    if not target:
        raise HTTPException(404, "User nicht gefunden")
    # Alte offene Tokens invalidieren
    await db.execute(
        "UPDATE invite_tokens SET used_at=NOW() WHERE user_id=$1 AND used_at IS NULL",
        uid)
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=INVITE_EXPIRES_HOURS)
    await db.execute(
        "INSERT INTO invite_tokens (token, user_id, expires_at) VALUES ($1, $2, $3)",
        token, uid, expires)
    logger.info(f"Admin {admin['username']} regenerated invite for {target['username']}")
    return {"invite_token": token, "invite_expires_at": expires.isoformat()}

@app.post("/api/admin/users/{uid}/password")
@limiter.limit(LIMIT_WRITE_RARE)
async def admin_reset_password(request: Request, uid: int, b: UserPasswordReset, db=Depends(get_db), admin=Depends(require_admin)):
    # v1.33.0: Mindestlaenge von 6 -> 10 angehoben. Bestehende (kuerzere)
    # Passwoerter bleiben gueltig, nur ein aktives Setzen erzwingt die Regel.
    if not b.password or len(b.password) < 10:
        raise HTTPException(400, "Passwort mindestens 10 Zeichen")
    target = await db.fetchrow("SELECT id, username FROM users WHERE id=$1", uid)
    if not target:
        raise HTTPException(404, "User nicht gefunden")
    hash_ = pwd_context.hash(b.password)
    await db.execute("UPDATE users SET password_hash=$1 WHERE id=$2", hash_, uid)
    # Cache-Invalidation: neuer Passwort-Hash wuerde erst nach TTL greifen.
    _invalidate_user_cache(target["username"])
    logger.info(f"Admin {admin['username']} reset password for {target['username']}")
    return {"status": "ok"}

@app.delete("/api/admin/users/{uid}")
@limiter.limit(LIMIT_WRITE_RARE)
async def admin_delete_user(request: Request, uid: int, db=Depends(get_db), admin=Depends(require_admin)):
    if uid == admin["id"]:
        raise HTTPException(400, "Du kannst dich nicht selbst löschen")
    target = await db.fetchrow("SELECT id, username, is_admin FROM users WHERE id=$1", uid)
    if not target:
        raise HTTPException(404, "User nicht gefunden")
    if target["is_admin"]:
        raise HTTPException(400, "Admin-Accounts können nicht gelöscht werden")
    await db.execute("DELETE FROM users WHERE id=$1", uid)
    _invalidate_user_cache(target["username"])
    logger.info(f"Admin {admin['username']} deleted user {target['username']}")
    return {"status": "deleted"}

# ---------- Public: Invite-Aktivierung ----------
@app.get("/api/invite/{token}")
@limiter.limit("10/minute")
async def invite_info(request: Request, token: str, db=Depends(get_db)):
    row = await db.fetchrow(
        """SELECT it.expires_at, it.used_at, u.username
           FROM invite_tokens it JOIN users u ON u.id = it.user_id
           WHERE it.token=$1""", token)
    if not row:
        raise HTTPException(404, "Ungültiger Einladungs-Link")
    if row["used_at"] is not None:
        raise HTTPException(410, "Einladungs-Link wurde bereits verwendet")
    if row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(410, "Einladungs-Link ist abgelaufen")
    return {"username": row["username"], "expires_at": row["expires_at"].isoformat()}

@app.post("/api/invite/activate")
@limiter.limit("5/minute")
async def invite_activate(request: Request, b: ActivateBody, db=Depends(get_db)):
    # v1.33.0: Mindestlaenge 6 -> 10.
    if not b.password or len(b.password) < 10:
        raise HTTPException(400, "Passwort mindestens 10 Zeichen")
    row = await db.fetchrow(
        "SELECT user_id, expires_at, used_at FROM invite_tokens WHERE token=$1", b.token)
    if not row:
        raise HTTPException(404, "Ungültiger Einladungs-Link")
    if row["used_at"] is not None:
        raise HTTPException(410, "Einladungs-Link wurde bereits verwendet")
    if row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(410, "Einladungs-Link ist abgelaufen")
    async with db.transaction():
        hash_ = pwd_context.hash(b.password)
        await db.execute("UPDATE users SET password_hash=$1 WHERE id=$2", hash_, row["user_id"])
        await db.execute("UPDATE invite_tokens SET used_at=NOW() WHERE token=$1", b.token)
    user = await db.fetchrow("SELECT username FROM users WHERE id=$1", row["user_id"])
    logger.info(f"User {user['username']} activated account via invite")
    return {"access_token": create_token(user["username"]), "token_type": "bearer"}

# ---------- Savings Goal ----------
# ``_active_goal_id`` lebt in ``helpers.py`` (ausgelagert v1.15.1)

@app.get("/api/savings-goal")
async def get_sg(db=Depends(get_db), user=Depends(get_current_user)):
    row = await db.fetchrow(
        "SELECT * FROM savings_goals WHERE user_id=$1 AND is_active=TRUE ORDER BY id DESC LIMIT 1",
        user["id"])
    if row:
        total = await db.fetchval(
            "SELECT COALESCE(SUM(amount),0) FROM savings_transactions "
            "WHERE user_id=$1 AND savings_goal_id=$2", user["id"], row["id"])
    else:
        total = 0
    return {"goal": ser(row) if row else None, "total_saved": float(total)}

@app.get("/api/savings-goals")
async def list_sg(db=Depends(get_db), user=Depends(get_current_user)):
    """Alle Sparziele des Users (aktiv + pausiert), inkl. Saldo pro Ziel."""
    rows = await db.fetch(
        """SELECT sg.*,
                  COALESCE((SELECT SUM(amount) FROM savings_transactions
                            WHERE savings_goal_id = sg.id AND user_id = sg.user_id), 0) AS saved_amount
             FROM savings_goals sg
            WHERE sg.user_id = $1
            ORDER BY sg.is_active DESC, sg.id DESC""",
        user["id"])
    out = []
    for r in rows:
        d = ser(r)
        d["saved_amount"] = float(r["saved_amount"] or 0)
        out.append(d)
    return out

@app.post("/api/savings-goals")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def create_sg(request: Request, b: SavGoalCreate, db=Depends(get_db), user=Depends(get_current_user)):
    name = (b.name or "").strip()
    if not name:
        raise HTTPException(400, "Name fehlt")
    if b.target_amount is None or b.target_amount <= 0:
        raise HTTPException(400, "Zielbetrag muss > 0 sein")
    async with db.transaction():
        if b.activate:
            await db.execute(
                "UPDATE savings_goals SET is_active=FALSE WHERE user_id=$1 AND is_active=TRUE",
                user["id"])
        row = await db.fetchrow(
            "INSERT INTO savings_goals (user_id, name, target_amount, is_active) "
            "VALUES ($1, $2, $3, $4) RETURNING *",
            user["id"], name, float(b.target_amount), bool(b.activate))
    return ser(row)

@app.post("/api/savings-goals/{gid}/activate")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def activate_sg(request: Request, gid: int, db=Depends(get_db), user=Depends(get_current_user)):
    row = await db.fetchrow(
        "SELECT is_general FROM savings_goals WHERE id=$1 AND user_id=$2", gid, user["id"])
    if not row:
        raise HTTPException(404, "Sparziel nicht gefunden")
    if bool(row["is_general"]):
        raise HTTPException(400, "Das Allgemein-Konto kann nicht als Sparziel aktiviert werden")
    async with db.transaction():
        await db.execute(
            "UPDATE savings_goals SET is_active=FALSE WHERE user_id=$1", user["id"])
        await db.execute(
            "UPDATE savings_goals SET is_active=TRUE WHERE id=$1 AND user_id=$2",
            gid, user["id"])
    logger.info(f"User {user['id']} activated savings_goal {gid}")
    return ser(await db.fetchrow("SELECT * FROM savings_goals WHERE id=$1", gid))

@app.post("/api/savings-goals/{gid}/transfer-from-buffer")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def transfer_from_buffer(request: Request, gid: int, b: SavGoalTransfer,
                                db=Depends(get_db), user=Depends(get_current_user)):
    """v1.26.0: Ueberweist Geld vom Allgemein-Konto (Puffer) auf das
    angegebene Sparziel. Erzeugt atomar zwei ``savings_transactions``-Zeilen
    (-amount vom Puffer, +amount aufs Ziel), gemeinsame ``source_id`` haelt
    das Paar zusammen (fuer eine spaetere Rueckbuchung/Loeschung).

    Validierung:
      * ``amount`` > 0
      * Zielziel existiert, gehoert dem User, ist kein Puffer und nicht bereits
        ueberzahlt (Restweg > 0 wenn ``target_amount`` gesetzt).
      * Puffer hat genug Deckung.
    """
    if b.amount is None or b.amount <= 0:
        raise HTTPException(400, "Betrag muss > 0 sein")
    amount = round(float(b.amount), 2)
    # Zielziel laden
    target = await db.fetchrow(
        "SELECT id, name, target_amount, is_general FROM savings_goals "
        "WHERE id=$1 AND user_id=$2", gid, user["id"])
    if not target:
        raise HTTPException(404, "Sparziel nicht gefunden")
    if bool(target["is_general"]):
        raise HTTPException(400, "Ziel-Konto darf nicht das Allgemein-Konto sein")
    # Puffer-Konto ermitteln
    buffer_id = await db.fetchval(
        "SELECT id FROM savings_goals WHERE user_id=$1 AND is_general=TRUE LIMIT 1",
        user["id"])
    if buffer_id is None:
        raise HTTPException(400, "Kein Puffer-Konto vorhanden")
    if buffer_id == gid:
        raise HTTPException(400, "Quelle und Ziel duerfen nicht identisch sein")
    # Deckung pruefen
    buffer_balance = float(await db.fetchval(
        "SELECT COALESCE(SUM(amount),0) FROM savings_transactions "
        "WHERE user_id=$1 AND savings_goal_id=$2", user["id"], buffer_id) or 0)
    if amount > buffer_balance + 1e-9:
        raise HTTPException(400,
            f"Nicht genug im Puffer (verfuegbar: {buffer_balance:.2f} €)")
    # Ueberzahlung verhindern
    target_saved = float(await db.fetchval(
        "SELECT COALESCE(SUM(amount),0) FROM savings_transactions "
        "WHERE user_id=$1 AND savings_goal_id=$2", user["id"], gid) or 0)
    tgt_amt = float(target["target_amount"] or 0)
    if tgt_amt > 0 and target_saved + amount > tgt_amt + 1e-9:
        remaining = max(0.0, tgt_amt - target_saved)
        raise HTTPException(400,
            f"Betrag ueberschreitet Zielrest ({remaining:.2f} € frei)")

    note = (b.note or "").strip() or None
    desc = f"Übertrag Puffer → {target['name']}"
    async with db.transaction():
        # 1) Abbuchung vom Puffer, RETURNING id als Paar-ID
        pair_id = await db.fetchval(
            "INSERT INTO savings_transactions "
            "(user_id, amount, source_type, source_id, description, note, savings_goal_id) "
            "VALUES ($1, $2, 'transfer', NULL, $3, $4, $5) RETURNING id",
            user["id"], -amount, desc, note, buffer_id)
        # 2) Zubuchung aufs Ziel, source_id = pair_id -> paart die Zeilen
        await db.execute(
            "INSERT INTO savings_transactions "
            "(user_id, amount, source_type, source_id, description, note, savings_goal_id) "
            "VALUES ($1, $2, 'transfer', $3, $4, $5, $6)",
            user["id"], amount, pair_id, desc, note, gid)
        # 3) Puffer-Seite: source_id auf sich selbst setzen (Marker "ist Quelle des Paares")
        await db.execute(
            "UPDATE savings_transactions SET source_id=$1 WHERE id=$1",
            pair_id)
    logger.info("User %s transferred %.2f from buffer %s to goal %s",
                user["id"], amount, buffer_id, gid)
    return {
        "status": "ok",
        "amount": amount,
        "buffer_id": buffer_id,
        "target_id": gid,
        "pair_id": pair_id,
    }


@app.delete("/api/savings-goals/{gid}")
@limiter.limit(LIMIT_WRITE_RARE)
async def del_sg(request: Request, gid: int, db=Depends(get_db), user=Depends(get_current_user)):
    row = await db.fetchrow("SELECT * FROM savings_goals WHERE id=$1 AND user_id=$2", gid, user["id"])
    if not row:
        raise HTTPException(404, "Sparziel nicht gefunden")
    if bool(row["is_general"]):
        raise HTTPException(400, "Das Allgemein-Konto kann nicht gelöscht werden")
    other = await db.fetchval(
        "SELECT COUNT(*) FROM savings_goals WHERE user_id=$1 AND id<>$2 AND is_general=FALSE",
        user["id"], gid)
    if int(other) == 0:
        raise HTTPException(400, "Das letzte Sparziel kann nicht gelöscht werden")
    was_active = bool(row["is_active"])
    removed_sum = float(await db.fetchval(
        "SELECT COALESCE(SUM(amount),0) FROM savings_transactions "
        "WHERE user_id=$1 AND savings_goal_id=$2", user["id"], gid) or 0)
    async with db.transaction():
        await db.execute(
            "DELETE FROM savings_transactions WHERE user_id=$1 AND savings_goal_id=$2",
            user["id"], gid)
        await db.execute("DELETE FROM savings_goals WHERE id=$1 AND user_id=$2", gid, user["id"])
        if was_active:
            # neuestes anderes als aktiv setzen
            nxt = await db.fetchval(
                "SELECT id FROM savings_goals WHERE user_id=$1 ORDER BY id DESC LIMIT 1",
                user["id"])
            if nxt:
                await db.execute("UPDATE savings_goals SET is_active=TRUE WHERE id=$1", nxt)
    return {"status": "deleted", "removed_sum": removed_sum}

@app.put("/api/savings-goal/{gid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def upd_sg(request: Request, gid: int, b: SavGoalUpd, db=Depends(get_db), user=Depends(get_current_user)):
    owned = await db.fetchval("SELECT 1 FROM savings_goals WHERE id=$1 AND user_id=$2", gid, user["id"])
    if not owned:
        raise HTTPException(404, "Not found")
    if b.name:
        await db.execute("UPDATE savings_goals SET name=$1 WHERE id=$2 AND user_id=$3", b.name, gid, user["id"])
    if b.target_amount is not None:
        await db.execute("UPDATE savings_goals SET target_amount=$1 WHERE id=$2 AND user_id=$3",
                         b.target_amount, gid, user["id"])
    return ser(await db.fetchrow("SELECT * FROM savings_goals WHERE id=$1", gid))

# ---------- Achievements ----------
# ``_milestones_at`` lebt in ``helpers.py`` (ausgelagert v1.15.1)

@app.get("/api/achievements")
async def list_ach(db=Depends(get_db), user=Depends(get_current_user)):
    return [ser(r) for r in await db.fetch(
        "SELECT * FROM achievements WHERE user_id=$1 ORDER BY sort_order NULLS LAST, id",
        user["id"])]

@app.post("/api/achievements")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def create_ach(request: Request, b: AchCreate, db=Depends(get_db), user=Depends(get_current_user)):
    if b.threshold_increment <= 0:
        raise HTTPException(400, "Meilenstein-Schwelle muss > 0 sein")
    step = float(b.step_amount) if b.step_amount is not None else float(b.threshold_increment)
    if step <= 0:
        raise HTTPException(400, "Schrittweite pro Klick muss > 0 sein")
    # v1.18.2: reward_goal_id validieren (muss dem User gehören, falls gesetzt)
    rgid = None
    if b.reward_goal_id is not None:
        ok = await db.fetchval(
            "SELECT 1 FROM savings_goals WHERE id=$1 AND user_id=$2",
            b.reward_goal_id, user["id"])
        if not ok:
            raise HTTPException(400, "reward_goal_id gehört nicht zum User")
        rgid = b.reward_goal_id
    return ser(await db.fetchrow(
        "INSERT INTO achievements "
        "(user_id,title,reward_amount,unit,current_value,start_value,threshold_increment,step_amount,target_value,direction,reward_goal_id) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING *",
        user["id"], b.title, b.reward_amount, b.unit, b.start_value, b.start_value,
        b.threshold_increment, step, b.target_value, b.direction, rgid))

@app.put("/api/achievements/{aid}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def upd_ach(request: Request, aid: int, b: AchUpd, db=Depends(get_db), user=Depends(get_current_user)):
    a = await db.fetchrow("SELECT * FROM achievements WHERE id=$1 AND user_id=$2", aid, user["id"])
    if not a:
        raise HTTPException(404, "Not found")
    inc = float(a["threshold_increment"])
    if inc <= 0:
        raise HTTPException(400, "Schrittweite muss > 0 sein")
    nv = float(b.current_value); sv = float(a["start_value"]); rew = float(a["reward_amount"])
    dirn = a["direction"]; cred = int(a["credited_milestones"]); tv = a["target_value"]

    when = None
    if b.achieved_at:
        try:
            parsed = datetime.fromisoformat(b.achieved_at)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            when = parsed
        except ValueError:
            raise HTTPException(400, "achieved_at muss ISO-Format sein (YYYY-MM-DD)")
        if when > datetime.now(timezone.utc):
            raise HTTPException(400, "achieved_at darf nicht in der Zukunft liegen")

    note_val = (b.note or "").strip() or None
    tm = _milestones_at(sv, nv, inc, dirn)
    logger.info(
        f"upd_ach: aid={aid} user={user['id']} title='{a['title']}' "
        f"dir={dirn} sv={sv} cv_old={a['current_value']} cv_new={nv} inc={inc} "
        f"cred_old={cred} tm={tm} → {'MILESTONE' if tm > cred else 'no-op'}")
    if tm > cred:
        # Notiz nur an den zuletzt erreichten Meilenstein hängen
        # (falls mehrere in einem Rutsch erreicht werden)
        last_step = tm
        # v1.18.2: Ziel-Routing pro Meilenstein — jede Auszahlung landet
        # entweder im zugewiesenen Ziel, im aktiven Ziel (falls Platz) oder
        # im Allgemein-Konto (Puffer).
        pref_goal = a["reward_goal_id"] if "reward_goal_id" in a.keys() else None
        for step in range(cred + 1, tm + 1):
            milestone_value = sv + step * inc if dirn == "increase" else sv - step * inc
            desc = f"Meilenstein: {a['title']} ({fmt_de_num(milestone_value)} {a['unit']})"
            step_note = note_val if step == last_step else None
            sg_id = await _reward_goal_for(db, user["id"], pref_goal, rew)
            if when:
                await db.execute(
                    "INSERT INTO achievement_logs (user_id,achievement_id,achieved_value,reward_amount,date_achieved,note) "
                    "VALUES ($1,$2,$3,$4,$5,$6)",
                    user["id"], aid, milestone_value, rew, when, step_note)
                await db.execute(
                    "INSERT INTO savings_transactions "
                    "(user_id,amount,source_type,source_id,description,created_at,note,savings_goal_id) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                    user["id"], rew, "achievement", aid, desc, when, step_note, sg_id)
            else:
                await db.execute(
                    "INSERT INTO achievement_logs (user_id,achievement_id,achieved_value,reward_amount,note) "
                    "VALUES ($1,$2,$3,$4,$5)",
                    user["id"], aid, milestone_value, rew, step_note)
                await db.execute(
                    "INSERT INTO savings_transactions "
                    "(user_id,amount,source_type,source_id,description,note,savings_goal_id) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                    user["id"], rew, "achievement", aid, desc, step_note, sg_id)
        new_cred = tm
    else:
        new_cred = cred

    # v1.41.0: Jede Wertaenderung kommt ins Fortschritts-Journal — auch die,
    # die keinen Meilenstein ausloest. Vorher blieb ein "+x"-Klick unter der
    # Schwelle voellig unsichtbar, weil nur ``current_value`` ueberschrieben
    # wurde. Die Notiz haengt am Meilenstein, falls einer erreicht wurde,
    # sonst an dieser Zeile.
    old_val = float(a["current_value"] or 0)
    delta = nv - old_val
    if abs(delta) > 1e-9:
        try:
            await db.execute(
                "INSERT INTO achievement_progress_logs "
                "(user_id, achievement_id, old_value, new_value, delta, hit_milestone, note, created_at) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,COALESCE($8::timestamptz, NOW()))",
                user["id"], aid, old_val, nv, delta, tm > cred,
                None if tm > cred else note_val, when)
        except Exception as e:
            # Historie ist wichtig, aber nicht wichtiger als die Wertaenderung
            # selbst — im Zweifel lieber der Eintrag fehlt als der Klick.
            logger.warning(f"Fortschritts-Log fehlgeschlagen (aid={aid}): {e}")

    comp = False
    if tv is not None:
        if dirn == "increase" and nv >= float(tv):
            comp = True
        elif dirn == "decrease" and nv <= float(tv):
            comp = True
    await db.execute(
        "UPDATE achievements SET current_value=$1, credited_milestones=$2, is_completed=$3 WHERE id=$4 AND user_id=$5",
        nv, new_cred, comp, aid, user["id"])
    return ser(await db.fetchrow("SELECT * FROM achievements WHERE id=$1", aid))

@app.put("/api/achievements/{aid}/edit")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def edit_ach(request: Request, aid: int, b: AchEdit, db=Depends(get_db), user=Depends(get_current_user)):
    old = await db.fetchrow("SELECT * FROM achievements WHERE id=$1 AND user_id=$2", aid, user["id"])
    if not old:
        raise HTTPException(404, "Not found")
    sets = []; vals = []; idx = 1; milestone_affecting = False
    # Bugfix v1.15.0: Vorher wurde ``if val is not None`` genutzt — damit
    # war es unmoeglich, ``target_value`` (Zielwert) durch Uebergabe von
    # ``null`` zu loeschen. Wir unterscheiden jetzt "Feld nicht mitgeschickt"
    # (via ``model_fields_set``) von "Feld explizit auf None gesetzt".
    provided = b.model_fields_set
    for field in ["title","reward_amount","unit","start_value","threshold_increment","step_amount","target_value","direction","reward_goal_id"]:
        if field not in provided:
            continue
        val = getattr(b, field)
        # target_value + reward_goal_id duerfen via null geleert werden;
        # alle anderen bleiben Pflichtwerte (weiter "None ignorieren").
        if val is None and field not in ("target_value", "reward_goal_id"):
            continue
        if val is not None:
            if field == "threshold_increment" and float(val) <= 0:
                raise HTTPException(400, "Meilenstein-Schwelle muss > 0 sein")
            if field == "step_amount" and float(val) <= 0:
                raise HTTPException(400, "Schrittweite pro Klick muss > 0 sein")
        if field in ("start_value","threshold_increment","direction"):
            milestone_affecting = True
        sets.append(f"{field}=${idx}"); vals.append(val); idx += 1
    if sets:
        vals.append(aid); vals.append(user["id"])
        await db.execute(
            f"UPDATE achievements SET {','.join(sets)} WHERE id=${idx} AND user_id=${idx+1}",
            *vals)
    if milestone_affecting:
        a = await db.fetchrow("SELECT * FROM achievements WHERE id=$1", aid)
        sv = float(a["start_value"]); inc = float(a["threshold_increment"]); cv = float(a["current_value"])
        new_tm = _milestones_at(sv, cv, inc, a["direction"])
        paid = int(await db.fetchval(
            "SELECT COUNT(*) FROM savings_transactions WHERE user_id=$1 AND source_type='achievement' AND source_id=$2",
            user["id"], aid))
        new_cred = max(paid, new_tm)
        await db.execute("UPDATE achievements SET credited_milestones=$1 WHERE id=$2", new_cred, aid)
    return ser(await db.fetchrow("SELECT * FROM achievements WHERE id=$1", aid))

@app.post("/api/achievements/{aid}/reset")
@limiter.limit(LIMIT_WRITE_RARE)
async def reset_ach(request: Request, aid: int, db=Depends(get_db), user=Depends(get_current_user)):
    a = await db.fetchrow("SELECT * FROM achievements WHERE id=$1 AND user_id=$2", aid, user["id"])
    if not a:
        raise HTTPException(404, "Not found")
    removed = int(await db.fetchval(
        "SELECT COUNT(*) FROM savings_transactions WHERE user_id=$1 AND source_type='achievement' AND source_id=$2",
        user["id"], aid))
    removed_sum = float(await db.fetchval(
        "SELECT COALESCE(SUM(amount),0) FROM savings_transactions WHERE user_id=$1 AND source_type='achievement' AND source_id=$2",
        user["id"], aid))
    await db.execute("DELETE FROM achievement_logs WHERE achievement_id=$1 AND user_id=$2", aid, user["id"])
    await db.execute(
        "DELETE FROM achievement_progress_logs WHERE achievement_id=$1 AND user_id=$2",
        aid, user["id"])
    await db.execute(
        "DELETE FROM savings_transactions WHERE user_id=$1 AND source_type='achievement' AND source_id=$2",
        user["id"], aid)
    await db.execute(
        "UPDATE achievements SET current_value=start_value, credited_milestones=0, is_completed=FALSE WHERE id=$1",
        aid)
    logger.info(f"Reset achievement {aid} (user {user['id']}): removed {removed} tx, {removed_sum}€")
    return {"removed_count": removed, "removed_sum": removed_sum,
            "achievement": ser(await db.fetchrow("SELECT * FROM achievements WHERE id=$1", aid))}

@app.delete("/api/achievements/{aid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def del_ach(request: Request, aid: int, db=Depends(get_db), user=Depends(get_current_user)):
    owned = await db.fetchval("SELECT 1 FROM achievements WHERE id=$1 AND user_id=$2", aid, user["id"])
    if not owned:
        raise HTTPException(404, "Not found")
    removed = int(await db.fetchval(
        "SELECT COUNT(*) FROM savings_transactions WHERE user_id=$1 AND source_type='achievement' AND source_id=$2",
        user["id"], aid))
    removed_sum = float(await db.fetchval(
        "SELECT COALESCE(SUM(amount),0) FROM savings_transactions WHERE user_id=$1 AND source_type='achievement' AND source_id=$2",
        user["id"], aid))
    await db.execute(
        "DELETE FROM savings_transactions WHERE user_id=$1 AND source_type='achievement' AND source_id=$2",
        user["id"], aid)
    await db.execute("DELETE FROM achievements WHERE id=$1 AND user_id=$2", aid, user["id"])
    return {"status": "deleted", "removed_count": removed, "removed_sum": removed_sum}

@app.delete("/api/achievement-progress-logs/{log_id}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def del_ach_progress_log(request: Request, log_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    """Nimmt einen Fortschritts-Eintrag zurueck (Vertipper, Fehlklick auf "+x").

    Bewusst nur fuer die JEWEILS LETZTE Aenderung eines Ziels und nur, wenn
    sie keinen Meilenstein ausgeloest hat: nur dann laesst sich der Wert
    eindeutig zurueckrechnen, ohne dass spaetere Aenderungen oder bereits
    ausgezahlte Meilensteine inkonsistent werden. Einen Meilenstein nimmt man
    ueber dessen eigenen Log-Eintrag zurueck.
    """
    log = await db.fetchrow(
        "SELECT * FROM achievement_progress_logs WHERE id=$1 AND user_id=$2", log_id, user["id"])
    if not log:
        raise HTTPException(404, "Not found")
    if log["hit_milestone"]:
        raise HTTPException(400, "Diese Änderung hat einen Meilenstein ausgelöst — "
                                 "bitte den Meilenstein-Eintrag löschen.")
    latest = await db.fetchval(
        "SELECT MAX(id) FROM achievement_progress_logs WHERE achievement_id=$1 AND user_id=$2",
        log["achievement_id"], user["id"])
    if latest != log["id"]:
        raise HTTPException(400, "Nur die letzte Änderung eines Ziels kann zurückgenommen werden.")
    a = await db.fetchrow("SELECT * FROM achievements WHERE id=$1 AND user_id=$2",
                          log["achievement_id"], user["id"])
    old_value = float(log["old_value"])
    if a:
        tv = a["target_value"]
        comp = False
        if tv is not None:
            comp = (old_value >= float(tv)) if a["direction"] == "increase" else (old_value <= float(tv))
        await db.execute(
            "UPDATE achievements SET current_value=$1, is_completed=$2 WHERE id=$3 AND user_id=$4",
            old_value, comp, log["achievement_id"], user["id"])
    await db.execute("DELETE FROM achievement_progress_logs WHERE id=$1 AND user_id=$2",
                     log_id, user["id"])
    logger.info(f"Deleted achievement_progress_log {log_id} (user {user['id']}, "
                f"achievement {log['achievement_id']}) → current_value={old_value}")
    return {"status": "deleted", "current_value": old_value,
            "achievement": ser(a) if a else None}

@app.delete("/api/achievement-logs/{log_id}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def del_achievement_log(request: Request, log_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    log = await db.fetchrow("SELECT * FROM achievement_logs WHERE id=$1 AND user_id=$2", log_id, user["id"])
    if not log:
        raise HTTPException(404, "Not found")
    aid = log["achievement_id"]
    reward = float(log["reward_amount"] or 0)
    tx = await db.fetchrow(
        """SELECT id FROM savings_transactions
           WHERE user_id=$1 AND source_type='achievement' AND source_id=$2 AND amount=$3
           ORDER BY ABS(EXTRACT(EPOCH FROM (created_at - $4))) ASC LIMIT 1""",
        user["id"], aid, reward, log["date_achieved"])
    payout_removed = False
    if tx:
        await db.execute("DELETE FROM savings_transactions WHERE id=$1 AND user_id=$2", tx["id"], user["id"])
        payout_removed = True
    await db.execute("DELETE FROM achievement_logs WHERE id=$1 AND user_id=$2", log_id, user["id"])
    a = await db.fetchrow("SELECT * FROM achievements WHERE id=$1 AND user_id=$2", aid, user["id"])
    if a:
        cv = float(a["current_value"])
        paid = int(await db.fetchval(
            "SELECT COUNT(*) FROM savings_transactions WHERE user_id=$1 AND source_type='achievement' AND source_id=$2",
            user["id"], aid))
        remaining_logs = int(await db.fetchval(
            "SELECT COUNT(*) FROM achievement_logs WHERE user_id=$1 AND achievement_id=$2",
            user["id"], aid))
        new_cred = max(paid, remaining_logs)
        comp = bool(a["is_completed"])
        tv = a["target_value"]
        if tv is not None:
            if a["direction"] == "increase":
                comp = cv >= float(tv)
            else:
                comp = cv <= float(tv)
        await db.execute(
            "UPDATE achievements SET credited_milestones=$1, is_completed=$2 WHERE id=$3",
            new_cred, comp, aid)
    logger.info(f"Deleted achievement_log {log_id} (user {user['id']}, achievement {aid}), payout_removed={payout_removed}")
    return {"status": "deleted", "payout_removed": payout_removed}

# ---------- Progress Goals ----------
# ``_streak`` lebt in ``helpers.py`` (ausgelagert v1.15.1)

@app.get("/api/progress-goals")
async def list_pg(db=Depends(get_db), user=Depends(get_current_user)):
    goals = await db.fetch(
        "SELECT * FROM progress_goals WHERE user_id=$1 ORDER BY sort_order NULLS LAST, id",
        user["id"])
    out = []
    for g in goals:
        rhythm = g["rhythm_type"] or "weekly"
        pk = period_key(rhythm, date.today())
        col = "month_key" if rhythm == "monthly" else "week_key"
        logs = await db.fetch(
            f"SELECT log_date FROM progress_logs WHERE progress_goal_id=$1 AND user_id=$2 AND {col}=$3 ORDER BY log_date",
            g["id"], user["id"], pk)
        d = ser(g)
        d["current_count"] = len(logs)
        d["current_period_key"] = pk
        d["current_dates"] = [l["log_date"].isoformat() for l in logs]
        d["streak"] = await _streak(db, g["id"], user["id"], rhythm, int(g["target_count"]))
        out.append(d)
    return out

@app.post("/api/progress-goals")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def create_pg(request: Request, b: PGCreate, db=Depends(get_db), user=Depends(get_current_user)):
    if b.rhythm_type not in ("weekly","monthly"):
        raise HTTPException(400, "rhythm_type ungültig")
    if b.target_count <= 0:
        raise HTTPException(400, "target_count muss > 0 sein")
    if b.streak_bonus_threshold < 0 or b.streak_bonus_amount < 0:
        raise HTTPException(400, "Streak-Bonus-Werte müssen >= 0 sein")
    rgid = None
    if b.reward_goal_id is not None:
        ok = await db.fetchval(
            "SELECT 1 FROM savings_goals WHERE id=$1 AND user_id=$2",
            b.reward_goal_id, user["id"])
        if not ok:
            raise HTTPException(400, "reward_goal_id gehört nicht zum User")
        rgid = b.reward_goal_id
    return ser(await db.fetchrow(
        "INSERT INTO progress_goals (user_id,title,reward_amount,rhythm_type,target_count,streak_bonus_amount,streak_bonus_threshold,reward_goal_id) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *",
        user["id"], b.title, b.reward_amount, b.rhythm_type, b.target_count,
        b.streak_bonus_amount, b.streak_bonus_threshold, rgid))

@app.put("/api/progress-goals/{gid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def upd_pg(request: Request, gid: int, b: PGUpd, db=Depends(get_db), user=Depends(get_current_user)):
    owned = await db.fetchval("SELECT 1 FROM progress_goals WHERE id=$1 AND user_id=$2", gid, user["id"])
    if not owned:
        raise HTTPException(404, "Not found")
    if b.title is not None:
        await db.execute("UPDATE progress_goals SET title=$1 WHERE id=$2", b.title, gid)
    if b.reward_amount is not None:
        await db.execute("UPDATE progress_goals SET reward_amount=$1 WHERE id=$2", b.reward_amount, gid)
    if b.target_count is not None:
        if b.target_count <= 0:
            raise HTTPException(400, "target_count muss > 0 sein")
        await db.execute("UPDATE progress_goals SET target_count=$1 WHERE id=$2", b.target_count, gid)
    if b.rhythm_type is not None:
        if b.rhythm_type not in ("weekly","monthly"):
            raise HTTPException(400, "rhythm_type ungültig")
        await db.execute("UPDATE progress_goals SET rhythm_type=$1 WHERE id=$2", b.rhythm_type, gid)
    if b.streak_bonus_amount is not None:
        if b.streak_bonus_amount < 0:
            raise HTTPException(400, "streak_bonus_amount muss >= 0 sein")
        await db.execute("UPDATE progress_goals SET streak_bonus_amount=$1 WHERE id=$2", b.streak_bonus_amount, gid)
    if b.streak_bonus_threshold is not None:
        if b.streak_bonus_threshold < 0:
            raise HTTPException(400, "streak_bonus_threshold muss >= 0 sein")
        await db.execute("UPDATE progress_goals SET streak_bonus_threshold=$1 WHERE id=$2", b.streak_bonus_threshold, gid)
    # v1.18.2: reward_goal_id via null-Setz-Semantik behandeln
    if "reward_goal_id" in b.model_fields_set:
        if b.reward_goal_id is None:
            await db.execute("UPDATE progress_goals SET reward_goal_id=NULL WHERE id=$1", gid)
        else:
            ok = await db.fetchval(
                "SELECT 1 FROM savings_goals WHERE id=$1 AND user_id=$2",
                b.reward_goal_id, user["id"])
            if not ok:
                raise HTTPException(400, "reward_goal_id gehört nicht zum User")
            await db.execute("UPDATE progress_goals SET reward_goal_id=$1 WHERE id=$2",
                              b.reward_goal_id, gid)
    return ser(await db.fetchrow("SELECT * FROM progress_goals WHERE id=$1", gid))

@app.put("/api/reorder/achievements")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def reorder_ach(request: Request, b: ReorderBody, db=Depends(get_db), user=Depends(get_current_user)):
    for idx, aid in enumerate(b.order):
        await db.execute(
            "UPDATE achievements SET sort_order=$1 WHERE id=$2 AND user_id=$3",
            idx, aid, user["id"])
    return {"status": "ok", "count": len(b.order)}

@app.put("/api/reorder/progress-goals")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def reorder_pg(request: Request, b: ReorderBody, db=Depends(get_db), user=Depends(get_current_user)):
    for idx, gid in enumerate(b.order):
        await db.execute(
            "UPDATE progress_goals SET sort_order=$1 WHERE id=$2 AND user_id=$3",
            idx, gid, user["id"])
    return {"status": "ok", "count": len(b.order)}

@app.delete("/api/progress-goals/{gid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def del_pg(request: Request, gid: int, db=Depends(get_db), user=Depends(get_current_user)):
    owned = await db.fetchval("SELECT 1 FROM progress_goals WHERE id=$1 AND user_id=$2", gid, user["id"])
    if not owned:
        raise HTTPException(404, "Not found")
    removed = int(await db.fetchval(
        "SELECT COUNT(*) FROM savings_transactions WHERE user_id=$1 AND source_type='progress' AND source_id=$2",
        user["id"], gid))
    removed_sum = float(await db.fetchval(
        "SELECT COALESCE(SUM(amount),0) FROM savings_transactions WHERE user_id=$1 AND source_type='progress' AND source_id=$2",
        user["id"], gid))
    await db.execute(
        "DELETE FROM savings_transactions WHERE user_id=$1 AND source_type='progress' AND source_id=$2",
        user["id"], gid)
    await db.execute("DELETE FROM progress_goals WHERE id=$1 AND user_id=$2", gid, user["id"])
    return {"status": "deleted", "removed_count": removed, "removed_sum": removed_sum}

@app.post("/api/progress-goals/{gid}/checkin")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def checkin(request: Request, gid: int, body: Optional[CheckinBody] = None, db=Depends(get_db), user=Depends(get_current_user)):
    pg = await db.fetchrow("SELECT * FROM progress_goals WHERE id=$1 AND user_id=$2", gid, user["id"])
    if not pg:
        raise HTTPException(404, "Not found")
    rhythm = pg["rhythm_type"] or "weekly"
    d = date.today()
    if body and body.log_date:
        try:
            d = date.fromisoformat(body.log_date)
        except ValueError:
            raise HTTPException(400, "log_date muss ISO-Format sein (YYYY-MM-DD)")
        if d > date.today():
            raise HTTPException(400, "log_date darf nicht in der Zukunft liegen")
    wk = week_key_for(d); mk = month_key_for(d)
    pk = period_key(rhythm, d)
    col = "month_key" if rhythm == "monthly" else "week_key"
    note_val = (body.note or "").strip() if body else None
    note_val = note_val or None

    await db.execute(
        "INSERT INTO progress_logs (user_id,progress_goal_id,log_date,week_key,month_key,note) "
        "VALUES ($1,$2,$3,$4,$5,$6)",
        user["id"], gid, d, wk, mk, note_val)
    cnt = await db.fetchval(
        f"SELECT COUNT(*) FROM progress_logs WHERE progress_goal_id=$1 AND user_id=$2 AND {col}=$3",
        gid, user["id"], pk)
    tgt = int(pg["target_count"])
    fulfilled = cnt >= tgt

    paid = False; bonus_paid = False; streak = 0
    if fulfilled:
        # v1.18.2: Belohnung ins zugewiesene Ziel oder Puffer routen
        pref_goal = pg["reward_goal_id"] if "reward_goal_id" in pg.keys() else None
        reward = float(pg["reward_amount"] or 0)
        ex = await db.fetchval(
            "SELECT COUNT(*) FROM savings_transactions WHERE user_id=$1 AND source_type='progress' AND source_id=$2 AND period_key=$3",
            user["id"], gid, pk)
        if ex == 0 and reward > 0:
            sg_id = await _reward_goal_for(db, user["id"], pref_goal, reward)
            await db.execute(
                "INSERT INTO savings_transactions "
                "(user_id,amount,source_type,source_id,description,period_key,savings_goal_id) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                user["id"], reward, "progress", gid, f"{pg['title']} ({pk})", pk, sg_id)
            paid = True
        bonus_amount = float(pg["streak_bonus_amount"] or 0)
        bonus_threshold = int(pg["streak_bonus_threshold"] or 0)
        if bonus_amount > 0 and bonus_threshold > 0:
            streak = await _streak(db, gid, user["id"], rhythm, tgt)
            if streak > 0 and streak % bonus_threshold == 0:
                bonus_pk = f"{pk}-streak-{streak}"
                bonus_ex = await db.fetchval(
                    "SELECT COUNT(*) FROM savings_transactions WHERE user_id=$1 AND source_type='progress' AND source_id=$2 AND period_key=$3",
                    user["id"], gid, bonus_pk)
                if bonus_ex == 0:
                    bonus_sg_id = await _reward_goal_for(db, user["id"], pref_goal, bonus_amount)
                    await db.execute(
                        "INSERT INTO savings_transactions "
                        "(user_id,amount,source_type,source_id,description,period_key,savings_goal_id) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                        user["id"], bonus_amount, "progress", gid,
                        f"Streak-Bonus {streak}×: {pg['title']}", bonus_pk, bonus_sg_id)
                    bonus_paid = True
    return {"current_count": cnt, "target_count": tgt, "fulfilled": fulfilled,
            "period_key": pk, "paid_out": paid, "streak_bonus_paid": bonus_paid, "streak": streak}

@app.delete("/api/progress-goals/{gid}/checkout")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def checkout(request: Request, gid: int, db=Depends(get_db), user=Depends(get_current_user)):
    pg = await db.fetchrow("SELECT * FROM progress_goals WHERE id=$1 AND user_id=$2", gid, user["id"])
    if not pg:
        raise HTTPException(404, "Not found")
    rhythm = pg["rhythm_type"] or "weekly"
    pk = period_key(rhythm, date.today())
    col = "month_key" if rhythm == "monthly" else "week_key"
    last = await db.fetchrow(
        f"SELECT * FROM progress_logs WHERE progress_goal_id=$1 AND user_id=$2 AND {col}=$3 ORDER BY id DESC LIMIT 1",
        gid, user["id"], pk)
    if not last:
        raise HTTPException(400, "Kein Check-in zum Entfernen")
    await db.execute("DELETE FROM progress_logs WHERE id=$1 AND user_id=$2", last["id"], user["id"])
    cnt = await db.fetchval(
        f"SELECT COUNT(*) FROM progress_logs WHERE progress_goal_id=$1 AND user_id=$2 AND {col}=$3",
        gid, user["id"], pk)
    tgt = int(pg["target_count"])
    if cnt < tgt:
        await db.execute(
            "DELETE FROM savings_transactions WHERE user_id=$1 AND source_type='progress' AND source_id=$2 AND period_key=$3",
            user["id"], gid, pk)
    return {"current_count": cnt, "target_count": tgt, "fulfilled": cnt >= tgt}

# ---------- Notizen zu Log-Einträgen ----------
@app.put("/api/progress-logs/{log_id}/note")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def upd_progress_log_note(request: Request, log_id: int, b: NoteBody, db=Depends(get_db), user=Depends(get_current_user)):
    owned = await db.fetchval("SELECT 1 FROM progress_logs WHERE id=$1 AND user_id=$2", log_id, user["id"])
    if not owned:
        raise HTTPException(404, "Not found")
    note_val = (b.note or "").strip() or None
    await db.execute(
        "UPDATE progress_logs SET note=$1 WHERE id=$2 AND user_id=$3",
        note_val, log_id, user["id"])
    return {"status": "ok", "note": note_val or ""}

@app.put("/api/achievement-logs/{log_id}/note")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def upd_achievement_log_note(request: Request, log_id: int, b: NoteBody, db=Depends(get_db), user=Depends(get_current_user)):
    owned = await db.fetchval("SELECT 1 FROM achievement_logs WHERE id=$1 AND user_id=$2", log_id, user["id"])
    if not owned:
        raise HTTPException(404, "Not found")
    note_val = (b.note or "").strip() or None
    await db.execute(
        "UPDATE achievement_logs SET note=$1 WHERE id=$2 AND user_id=$3",
        note_val, log_id, user["id"])
    return {"status": "ok", "note": note_val or ""}

@app.put("/api/achievement-progress-logs/{log_id}/note")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def upd_ach_progress_note(request: Request, log_id: int, b: NoteBody, db=Depends(get_db), user=Depends(get_current_user)):
    owned = await db.fetchval(
        "SELECT 1 FROM achievement_progress_logs WHERE id=$1 AND user_id=$2", log_id, user["id"])
    if not owned:
        raise HTTPException(404, "Not found")
    note_val = (b.note or "").strip() or None
    await db.execute(
        "UPDATE achievement_progress_logs SET note=$1 WHERE id=$2 AND user_id=$3",
        note_val, log_id, user["id"])
    return {"status": "ok", "note": note_val or ""}

@app.put("/api/savings-transactions/{tid}/note")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def upd_savings_tx_note(request: Request, tid: int, b: NoteBody, db=Depends(get_db), user=Depends(get_current_user)):
    owned = await db.fetchval("SELECT 1 FROM savings_transactions WHERE id=$1 AND user_id=$2", tid, user["id"])
    if not owned:
        raise HTTPException(404, "Not found")
    note_val = (b.note or "").strip() or None
    await db.execute(
        "UPDATE savings_transactions SET note=$1 WHERE id=$2 AND user_id=$3",
        note_val, tid, user["id"])
    return {"status": "ok", "note": note_val or ""}

@app.delete("/api/progress-logs/{log_id}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def del_progress_log(request: Request, log_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    log = await db.fetchrow("SELECT * FROM progress_logs WHERE id=$1 AND user_id=$2", log_id, user["id"])
    if not log:
        raise HTTPException(404, "Not found")
    pg = await db.fetchrow("SELECT * FROM progress_goals WHERE id=$1 AND user_id=$2",
                           log["progress_goal_id"], user["id"])
    if not pg:
        raise HTTPException(404, "Wochenziel nicht mehr vorhanden")
    rhythm = pg["rhythm_type"] or "weekly"
    col = "month_key" if rhythm == "monthly" else "week_key"
    pk = log[col]
    await db.execute("DELETE FROM progress_logs WHERE id=$1 AND user_id=$2", log_id, user["id"])
    cnt = int(await db.fetchval(
        f"SELECT COUNT(*) FROM progress_logs WHERE progress_goal_id=$1 AND user_id=$2 AND {col}=$3",
        pg["id"], user["id"], pk))
    tgt = int(pg["target_count"])
    payout_removed = False
    if cnt < tgt:
        r = await db.execute(
            "DELETE FROM savings_transactions WHERE user_id=$1 AND source_type='progress' AND source_id=$2 AND period_key=$3",
            user["id"], pg["id"], pk)
        payout_removed = r != "DELETE 0"
    return {"status": "deleted", "period_still_fulfilled": cnt >= tgt, "payout_removed": payout_removed}

@app.get("/api/progress-goals/{gid}/history")
async def pg_history(gid: int, limit: int = 12, db=Depends(get_db), user=Depends(get_current_user)):
    """Verlauf der letzten N Perioden (Wochen / Monate) für ein Progress-Goal.

    v1.18.0: Limit auf max. 52 erhöht (1 Jahr Wochen bzw. >4 Jahre Monate),
    liefert zusätzlich ``log_dates`` (Datumsliste der Check-ins) pro Periode
    für die Detail-Anzeige im Frontend.
    """
    limit = max(1, min(int(limit or 12), 52))
    pg = await db.fetchrow("SELECT * FROM progress_goals WHERE id=$1 AND user_id=$2", gid, user["id"])
    if not pg:
        raise HTTPException(404, "Not found")
    rhythm = pg["rhythm_type"] or "weekly"
    target = int(pg["target_count"])
    today = date.today()
    periods = []; cur = today; seen = set()
    for _ in range(limit):
        pk = period_key(rhythm, cur)
        if pk in seen:
            cur = prev_period(rhythm, cur); continue
        seen.add(pk)
        if rhythm == "monthly":
            start = date(cur.year, cur.month, 1)
            end = date(cur.year, 12, 31) if cur.month == 12 else date(cur.year, cur.month+1, 1) - timedelta(days=1)
            col = "month_key"
        else:
            start = cur - timedelta(days=cur.weekday())
            end = start + timedelta(days=6)
            col = "week_key"
        logs = await db.fetch(
            f"SELECT log_date FROM progress_logs WHERE progress_goal_id=$1 AND user_id=$2 AND {col}=$3 ORDER BY log_date",
            gid, user["id"], pk)
        cnt = len(logs)
        paid = int(await db.fetchval(
            "SELECT COUNT(*) FROM savings_transactions WHERE user_id=$1 AND source_type='progress' AND source_id=$2 AND period_key=$3",
            user["id"], gid, pk))
        periods.append({"period_key": pk, "start": start.isoformat(), "end": end.isoformat(),
            "current_count": cnt, "target_count": target, "fulfilled": cnt >= target,
            "paid_out": paid > 0, "is_current": pk == period_key(rhythm, today),
            "log_dates": [l["log_date"].isoformat() for l in logs]})
        cur = prev_period(rhythm, cur)
    return periods

# ---------- Health-Modul (v1.22.0) — ausgelagert in routers/health_router.py ----------

# ---------- Potential Goals & Future Ideas ----------
@app.get("/api/potential-goals")
async def list_pot(db=Depends(get_db), user=Depends(get_current_user)):
    return [ser(r) for r in await db.fetch(
        "SELECT * FROM potential_goals WHERE user_id=$1 ORDER BY id", user["id"])]

@app.post("/api/potential-goals")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def create_pot(request: Request, b: PotCreate, db=Depends(get_db), user=Depends(get_current_user)):
    return ser(await db.fetchrow(
        "INSERT INTO potential_goals (user_id,name,estimated_price) VALUES ($1,$2,$3) RETURNING *",
        user["id"], b.name, b.estimated_price))

@app.delete("/api/potential-goals/{pid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def del_pot(request: Request, pid: int, db=Depends(get_db), user=Depends(get_current_user)):
    await db.execute("DELETE FROM potential_goals WHERE id=$1 AND user_id=$2", pid, user["id"])
    return {"status": "deleted"}

@app.get("/api/future-ideas")
async def list_fi(db=Depends(get_db), user=Depends(get_current_user)):
    return [ser(r) for r in await db.fetch(
        "SELECT * FROM future_ideas WHERE user_id=$1 ORDER BY id", user["id"])]

@app.post("/api/future-ideas")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def create_fi(request: Request, b: FICreate, db=Depends(get_db), user=Depends(get_current_user)):
    return ser(await db.fetchrow(
        "INSERT INTO future_ideas (user_id,title,category) VALUES ($1,$2,$3) RETURNING *",
        user["id"], b.title, b.category))

@app.delete("/api/future-ideas/{iid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def del_fi(request: Request, iid: int, db=Depends(get_db), user=Depends(get_current_user)):
    await db.execute("DELETE FROM future_ideas WHERE id=$1 AND user_id=$2", iid, user["id"])
    return {"status": "deleted"}

# ---------- Savings Transactions ----------
@app.get("/api/savings-transactions")
async def list_st(source_type: Optional[str] = None, from_date: Optional[str] = None, to_date: Optional[str] = None,
                  db=Depends(get_db), user=Depends(get_current_user)):
    q = "SELECT * FROM savings_transactions WHERE user_id=$1"
    params = [user["id"]]
    if source_type:
        params.append(source_type); q += f" AND source_type=${len(params)}"
    if from_date:
        try:
            fd = date.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(400, "from_date ungültig")
        params.append(fd); q += f" AND created_at >= ${len(params)}"
    if to_date:
        try:
            td = date.fromisoformat(to_date) + timedelta(days=1)
        except ValueError:
            raise HTTPException(400, "to_date ungültig")
        params.append(td); q += f" AND created_at < ${len(params)}"
    q += " ORDER BY created_at DESC"
    return [ser(r) for r in await db.fetch(q, *params)]

@app.delete("/api/savings-transactions/{tid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def del_st(request: Request, tid: int, db=Depends(get_db), user=Depends(get_current_user)):
    # v1.26.0: Bei Transfers (source_type='transfer') haengt die Gegenseite
    # ueber ``source_id`` an der Puffer-Zeile (deren source_id == eigene id).
    # Beide Zeilen des Paares muessen zusammen weg, sonst gibt es eine
    # unbalancierte Bewegung im Log.
    row = await db.fetchrow(
        "SELECT id, source_type, source_id FROM savings_transactions "
        "WHERE id=$1 AND user_id=$2", tid, user["id"])
    if not row:
        return {"status": "deleted"}
    if row["source_type"] == "transfer" and row["source_id"] is not None:
        pair_id = int(row["source_id"])
        # pair_id == id der Puffer-Zeile; loesche beide (Puffer + Ziel).
        async with db.transaction():
            await db.execute(
                "DELETE FROM savings_transactions "
                "WHERE user_id=$1 AND (id=$2 OR source_id=$2)",
                user["id"], pair_id)
        return {"status": "deleted", "pair_deleted": True}
    await db.execute("DELETE FROM savings_transactions WHERE id=$1 AND user_id=$2", tid, user["id"])
    return {"status": "deleted"}

# Export-Helfer leben in ``helpers.py`` (ausgelagert v1.15.1)


@app.get("/api/savings-transactions/export")
async def export_st(db=Depends(get_db), user=Depends(get_current_user)):
    # Bugfix v1.15.0: Der Export enthaelt jetzt vorab einen Metadaten-
    # Block mit allen Sparzielen, Achievements, Wochen-/Monatszielen,
    # Wunsch-Anschaffungen, Zukunftsideen und Trophaeen. Danach folgt
    # das eigentliche Protokoll wie bisher. Jede Sektion beginnt mit
    # einer Kommentarzeile ``# SEKTION: ...`` und ihrem eigenen Header.
    # Protokoll-Aufbau ausgelagert nach ``helpers._sparziel_protocol_lines``
    # (v1.23.0), damit der kombinierte Gesamt-Export dieselbe Logik nutzt.
    lines: list[str] = _build_export_header(user)
    lines.extend(await _build_export_metadata(db, user["id"]))
    lines.append("# SEKTION: Protokoll")
    lines.append("Datum;Typ;Titel;Beschreibung;Periode;Betrag;Notiz")
    lines.extend(await _sparziel_protocol_lines(db, user["id"]))
    csv = "\n".join(lines) + "\n"
    # UTF-8 mit BOM, damit Excel Umlaute (ä/ö/ü/ß) korrekt darstellt
    content = ("\ufeff" + csv).encode("utf-8")
    return Response(content=content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="vexbob-log.csv"',
                             "Cache-Control": "no-store"})

# ---------- Activity Log ----------
@app.get("/api/activity-log")
async def activity_log(limit: int = 500, db=Depends(get_db), user=Depends(get_current_user)):
    events = []
    ci_rows = await db.fetch(
        """SELECT pl.id, pl.progress_goal_id, pl.log_date, pl.week_key, pl.month_key, pl.created_at, pl.note,
                  pg.title, pg.reward_amount, pg.rhythm_type, pg.target_count
           FROM progress_logs pl JOIN progress_goals pg ON pg.id = pl.progress_goal_id
           WHERE pl.user_id=$1
           ORDER BY pl.created_at DESC LIMIT $2""",
        user["id"], limit)
    for r in ci_rows:
        rhythm = r["rhythm_type"] or "weekly"
        pk = r["month_key"] if rhythm == "monthly" else r["week_key"]
        col = "month_key" if rhythm == "monthly" else "week_key"
        count_at_or_before = int(await db.fetchval(
            f"SELECT COUNT(*) FROM progress_logs WHERE progress_goal_id=$1 AND user_id=$2 AND {col}=$3 AND id <= $4",
            r["progress_goal_id"], user["id"], pk, r["id"]))
        target = int(r["target_count"])
        just_fulfilled = count_at_or_before == target
        amt = float(r["reward_amount"]) if just_fulfilled else 0.0
        events.append({"type": "checkin", "date": r["created_at"].isoformat(),
            "log_date": r["log_date"].isoformat(),
            "title": r["title"], "description": f"{count_at_or_before}/{target} · {pk}",
            "amount": amt, "log_id": r["id"], "source_id": r["progress_goal_id"],
            "fulfilled": just_fulfilled, "note": r["note"] or "", "deletable": True})

    ml_rows = await db.fetch(
        """SELECT al.id, al.achievement_id, al.achieved_value, al.reward_amount, al.date_achieved, al.note,
                  a.title, a.unit
           FROM achievement_logs al JOIN achievements a ON a.id = al.achievement_id
           WHERE al.user_id=$1
           ORDER BY al.date_achieved DESC LIMIT $2""",
        user["id"], limit)
    for r in ml_rows:
        unit = r["unit"] or ""
        val = float(r["achieved_value"])
        events.append({
            "type": "milestone",
            "date": r["date_achieved"].isoformat(),
            "title": r["title"],
            "description": f"Erreicht bei {fmt_de_num(val)} {unit}".strip(),
            "achieved_value": val, "unit": unit,
            "amount": float(r["reward_amount"]),
            "log_id": r["id"], "source_id": r["achievement_id"],
            "note": r["note"] or "", "deletable": True
        })

    # v1.41.0: Wertaenderungen an Meilenstein-Zielen, die (noch) keinen
    # Meilenstein ausgeloest haben. Sie tragen keinen Betrag — das Geld haengt
    # weiterhin am Meilenstein-Eintrag. Loeschbar ist nur die jeweils letzte
    # Aenderung eines Ziels, weil nur die sich sauber zurueckrechnen laesst.
    pr_rows = await db.fetch(
        """SELECT pr.id, pr.achievement_id, pr.old_value, pr.new_value, pr.delta,
                  pr.hit_milestone, pr.note, pr.created_at, a.title, a.unit,
                  (pr.id = (SELECT MAX(p2.id) FROM achievement_progress_logs p2
                             WHERE p2.achievement_id = pr.achievement_id
                               AND p2.user_id = pr.user_id)) AS is_latest
             FROM achievement_progress_logs pr
             JOIN achievements a ON a.id = pr.achievement_id
            WHERE pr.user_id=$1
            ORDER BY pr.created_at DESC LIMIT $2""",
        user["id"], limit)
    for r in pr_rows:
        unit = r["unit"] or ""
        delta = float(r["delta"])
        desc = f"{fmt_de_num(float(r['old_value']))} → {fmt_de_num(float(r['new_value']))} {unit}".strip()
        events.append({
            "type": "progress",
            "date": r["created_at"].isoformat(),
            "title": r["title"],
            "description": desc,
            "amount": 0.0,
            "delta": delta, "unit": unit,
            "hit_milestone": bool(r["hit_milestone"]),
            "log_id": r["id"], "source_id": r["achievement_id"],
            "note": r["note"] or "",
            "deletable": bool(r["is_latest"]) and not r["hit_milestone"],
        })

    for r in await db.fetch(
        "SELECT * FROM savings_transactions WHERE user_id=$1 AND source_type='initial' ORDER BY created_at DESC LIMIT $2",
        user["id"], limit):
        events.append({"type": "initial", "date": r["created_at"].isoformat(), "title": "Anfangsbestand",
            "description": r["description"] or "", "amount": float(r["amount"]),
            "log_id": r["id"], "note": r["note"] or "", "deletable": True})

    # v1.26.0: Ueberweisungen Puffer → Sparziel als eigener Event-Typ.
    # Wir zeigen nur die POSITIVE (Ziel-)Seite; die passende negative
    # Puffer-Seite wird beim Loeschen automatisch mit entfernt (siehe
    # DELETE-Endpoint).
    tr_rows = await db.fetch(
        """SELECT st.id, st.amount, st.description, st.created_at, st.source_id,
                  st.note, st.savings_goal_id, sg.name AS goal_name
             FROM savings_transactions st
             JOIN savings_goals sg ON sg.id = st.savings_goal_id
            WHERE st.user_id=$1 AND st.source_type='transfer' AND st.amount > 0
            ORDER BY st.created_at DESC LIMIT $2""",
        user["id"], limit)
    for r in tr_rows:
        events.append({
            "type": "transfer",
            "date": r["created_at"].isoformat(),
            "title": r["description"] or "Übertrag",
            "description": f"Auf „{r['goal_name']}\"",
            "amount": float(r["amount"]),
            "log_id": r["id"], "source_id": r["source_id"],
            "note": r["note"] or "", "deletable": True,
        })

    sb_rows = await db.fetch(
        """SELECT st.id, st.amount, st.description, st.created_at, st.source_id, st.period_key, st.note, pg.title
           FROM savings_transactions st LEFT JOIN progress_goals pg ON pg.id = st.source_id
           WHERE st.user_id=$1 AND st.source_type='progress' AND st.period_key LIKE '%%-streak-%%'
           ORDER BY st.created_at DESC LIMIT $2""",
        user["id"], limit)
    for r in sb_rows:
        events.append({"type": "streak_bonus", "date": r["created_at"].isoformat(),
            "title": r["title"] or "?", "description": r["description"] or "",
            "amount": float(r["amount"]), "log_id": r["id"], "source_id": r["source_id"],
            "note": r["note"] or "", "deletable": True})

    events.sort(key=lambda x: x["date"], reverse=True)
    return events[:limit]

# ---------- Stats ----------
@app.get("/api/stats/savings-progress")
async def st_sp(db=Depends(get_db), user=Depends(get_current_user)):
    """Kumulierter Saldo des AKTIVEN Sparziels über die Zeit."""
    sg_id = await _active_goal_id(db, user["id"])
    if sg_id is None:
        return []
    rows = await db.fetch(
        "SELECT created_at, amount FROM savings_transactions "
        "WHERE user_id=$1 AND savings_goal_id=$2 ORDER BY created_at",
        user["id"], sg_id)
    c = 0; out = []
    for r in rows:
        c += float(r["amount"])
        out.append({"date": r["created_at"].isoformat() if r["created_at"] else None, "cumulative": c})
    return out

# ---------- Activity Heatmap ----------
@app.get("/api/stats/heatmap")
async def stats_heatmap(days: int = 365, db=Depends(get_db), user=Depends(get_current_user)):
    """Liefert pro Tag: Anzahl Check-ins, Anzahl Meilensteine, ausgezahlter Betrag."""
    if days < 1 or days > 730:
        raise HTTPException(400, "days muss 1..730 sein")
    since = date.today() - timedelta(days=days-1)

    ci = await db.fetch(
        """SELECT log_date::date AS d, COUNT(*) AS c
           FROM progress_logs WHERE user_id=$1 AND log_date >= $2
           GROUP BY log_date::date""",
        user["id"], since)

    ml = await db.fetch(
        """SELECT date_achieved::date AS d, COUNT(*) AS c
           FROM achievement_logs WHERE user_id=$1 AND date_achieved >= $2
           GROUP BY date_achieved::date""",
        user["id"], since)

    tx = await db.fetch(
        """SELECT created_at::date AS d, COALESCE(SUM(amount),0) AS s
           FROM savings_transactions
           WHERE user_id=$1 AND created_at >= $2 AND source_type <> 'initial'
           GROUP BY created_at::date""",
        user["id"], since)

    by_day = {}
    for r in ci: by_day.setdefault(r["d"].isoformat(), {"checkins":0,"milestones":0,"amount":0.0})["checkins"] = int(r["c"])
    for r in ml: by_day.setdefault(r["d"].isoformat(), {"checkins":0,"milestones":0,"amount":0.0})["milestones"] = int(r["c"])
    for r in tx: by_day.setdefault(r["d"].isoformat(), {"checkins":0,"milestones":0,"amount":0.0})["amount"] = float(r["s"])

    out = []
    cur = since
    end = date.today()
    while cur <= end:
        key = cur.isoformat()
        data = by_day.get(key, {"checkins":0,"milestones":0,"amount":0.0})
        total = data["checkins"] + data["milestones"]
        if total == 0: level = 0
        elif total <= 1: level = 1
        elif total <= 3: level = 2
        elif total <= 6: level = 3
        else: level = 4
        out.append({
            "date": key,
            "checkins": data["checkins"],
            "milestones": data["milestones"],
            "amount": round(data["amount"], 2),
            "total": total,
            "level": level,
        })
        cur += timedelta(days=1)
    return out

# ---------- Trophies / Completed Goals ----------
@app.get("/api/trophies")
async def list_trophies(db=Depends(get_db), user=Depends(get_current_user)):
    rows = await db.fetch(
        "SELECT * FROM completed_goals WHERE user_id=$1 ORDER BY completed_at DESC",
        user["id"])
    return [ser(r) for r in rows]

@app.post("/api/trophies")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def create_trophy(request: Request, b: TrophyCreate, db=Depends(get_db), user=Depends(get_current_user)):
    started = None
    duration_days = None
    if b.started_at:
        try:
            started = datetime.fromisoformat(b.started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            duration_days = (datetime.now(timezone.utc) - started).days
        except ValueError:
            raise HTTPException(400, "started_at ungültig")
    row = await db.fetchrow(
        """INSERT INTO completed_goals
           (user_id, name, target_amount, final_amount, started_at, icon, color, note, photo_url, duration_days)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *""",
        user["id"], b.name, b.target_amount, b.final_amount, started,
        b.icon or "🏆", b.color or "gold", b.note, b.photo_url, duration_days)
    return ser(row)

@app.post("/api/savings-goal/{gid}/complete")
@limiter.limit(LIMIT_WRITE_RARE)
async def complete_savings_goal(request: Request, gid: int, b: TrophyCreate, db=Depends(get_db), user=Depends(get_current_user)):
    """Aktives Sparziel als abgeschlossen markieren, archivieren, neues leeres anlegen."""
    goal = await db.fetchrow(
        "SELECT * FROM savings_goals WHERE id=$1 AND user_id=$2 AND is_active=TRUE",
        gid, user["id"])
    if not goal:
        raise HTTPException(404, "Aktives Sparziel nicht gefunden")

    total = float(await db.fetchval(
        "SELECT COALESCE(SUM(amount),0) FROM savings_transactions "
        "WHERE user_id=$1 AND savings_goal_id=$2", user["id"], gid))
    duration_days = None
    if goal["created_at"]:
        duration_days = (datetime.now(timezone.utc) - goal["created_at"]).days

    async with db.transaction():
        trophy = await db.fetchrow(
            """INSERT INTO completed_goals
               (user_id, name, target_amount, final_amount, started_at, icon, color, note, photo_url, duration_days)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *""",
            user["id"], b.name or goal["name"], float(goal["target_amount"]), total,
            goal["created_at"], b.icon or "🏆", b.color or "gold", b.note, b.photo_url, duration_days)
        await db.execute(
            "UPDATE savings_goals SET is_active=FALSE WHERE id=$1 AND user_id=$2",
            gid, user["id"])
        await db.execute(
            "DELETE FROM savings_transactions WHERE user_id=$1 AND savings_goal_id=$2",
            user["id"], gid)
        await db.execute(
            "INSERT INTO savings_goals (user_id, name, target_amount, is_active) VALUES ($1, 'Neues Sparziel', 100, TRUE)",
            user["id"])
    logger.info(f"User {user['id']} completed goal {gid}, saved trophy {trophy['id']}")
    return ser(trophy)

@app.delete("/api/trophies/{tid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def del_trophy(request: Request, tid: int, db=Depends(get_db), user=Depends(get_current_user)):
    r = await db.execute(
        "DELETE FROM completed_goals WHERE id=$1 AND user_id=$2", tid, user["id"])
    if r == "DELETE 0":
        raise HTTPException(404, "Nicht gefunden")
    return {"status": "deleted"}


# ---------- Backup / Restore / Snapshots ----------
@app.get("/api/backup")
async def backup(db=Depends(get_db), user=Depends(get_current_user)):
    return await create_snapshot(db, trigger_type="manual", user_id=user["id"])

@app.post("/api/backup/restore")
@limiter.limit(LIMIT_WRITE_RARE)
async def restore(request: Request, b: RestoreBody, db=Depends(get_db), user=Depends(get_current_user)):
    try:
        stats = await restore_snapshot(db, b.payload, user_id=user["id"], wipe=b.wipe)
        logger.info(f"Restore complete for user {user['id']}: {stats}")
        return {"status": "ok", "stats": stats}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Restore failed")
        raise HTTPException(500, f"Restore fehlgeschlagen: {e}")

@app.get("/api/backup/snapshots")
async def list_snapshots(db=Depends(get_db), user=Depends(get_current_user)):
    rows = await db.fetch(
        "SELECT id, created_at, trigger_type, size_bytes FROM backup_snapshots "
        "WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50", user["id"])
    return [ser(r) for r in rows]

@app.get("/api/backup/snapshots/{sid}")
async def get_snapshot(sid: int, db=Depends(get_db), user=Depends(get_current_user)):
    row = await db.fetchrow(
        "SELECT payload FROM backup_snapshots WHERE id=$1 AND user_id=$2", sid, user["id"])
    if not row:
        raise HTTPException(404, "Snapshot nicht gefunden")
    import json
    return json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]

@app.delete("/api/backup/snapshots/{sid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def del_snapshot(request: Request, sid: int, db=Depends(get_db), user=Depends(get_current_user)):
    await db.execute("DELETE FROM backup_snapshots WHERE id=$1 AND user_id=$2", sid, user["id"])
    return {"status": "deleted"}
# ==========================================================================
# Ausgaben-Modul (Paket 9) — ausgelagert in routers/expenses_router.py
# ==========================================================================
from routers.expenses_router import router as expenses_router
app.include_router(expenses_router)

# ==========================================================================
# Marken-Modul (v1.16.0) — ausgelagert in routers/brands_router.py
# ------------------------------------------------------------------
from routers.brands_router import router as brands_router
app.include_router(brands_router)


# ------------------------------------------------------------------
# Notizen-Modul (Paket 14) — ausgelagert in routers/notes_router.py
# ==========================================================================
from routers.notes_router import router as notes_router
app.include_router(notes_router)

# ==========================================================================
# Blog-Modul (v1.18.0) — öffentliches Blog, Admin-Editor
# --------------------------------------------------------------------------
from routers.blog_router import router as blog_router
app.include_router(blog_router)

# ==========================================================================
# Health-Modul (v1.22.0) — Sync via Auto Health Export (iPhone REST API)
# --------------------------------------------------------------------------
from routers.health_router import router as health_router
app.include_router(health_router)

# ==========================================================================
# Gesamt-Export (v1.23.0) — Sparziel + Ausgaben + Gesundheit in einer CSV
# --------------------------------------------------------------------------
from routers.export_router import router as export_router
app.include_router(export_router)
