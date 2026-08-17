import os
import math
import logging
import asyncio
from datetime import date, timedelta, datetime, timezone
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request, status, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import asyncpg
import secrets
from datetime import date as _date_type
from fastapi.security import OAuth2PasswordRequestForm

import database as db_module
from database import (
    get_db, init_db, week_key_for, month_key_for, period_key, prev_period,
    _seed_empty_user,
)
from auth import authenticate, create_token, get_current_user, require_admin, pwd_context
from services.backup import create_snapshot, restore_snapshot, prune_snapshots

# Zentrale Utilities & Konstanten (auch von routers/* genutzt)
from deps import (
    logger, limiter,
    LIMIT_LOGIN, LIMIT_WRITE_FREQUENT, LIMIT_WRITE_STANDARD, LIMIT_WRITE_RARE,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS-Origins via ENV konfigurierbar (Komma-getrennt).
# Default deckt lokale Entwicklung ab.
_cors_env = os.getenv("CORS_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500")
CORS_ORIGINS = [o.strip() for o in _cors_env.split(",") if o.strip()]

app.add_middleware(CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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
            if db_module._pool is None:
                db_module._pool = await asyncpg.create_pool(
                    db_module.DATABASE_URL, ssl="require", min_size=1, max_size=10)
            async with db_module._pool.acquire() as conn:
                # Global-Snapshot (user_id NULL) — nur Admin kann drauf zugreifen
                await create_snapshot(conn, trigger_type="auto_daily", user_id=None)
                if datetime.now(timezone.utc).weekday() == 6:
                    await create_snapshot(conn, trigger_type="auto_weekly", user_id=None)
                await prune_snapshots(conn)
        except Exception as e:
            logger.exception(f"Auto-backup failed: {e}")
            await asyncio.sleep(3600)

@app.on_event("startup")
async def startup():
    logger.info("Startup: initializing DB")
    await init_db()
    logger.info(f"Startup complete. CORS origins: {CORS_ORIGINS}")
    asyncio.create_task(_auto_backup_loop())

def ser(row):
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
    return d

def fmt_de_num(v):
    f = float(v)
    if f == int(f):
        return str(int(f))
    return f"{f:.2f}".rstrip("0").rstrip(".").replace(".", ",")

# ---------- Models ----------
class SavGoalUpd(BaseModel):
    name: Optional[str] = None
    target_amount: Optional[float] = None

class AchCreate(BaseModel):
    title: str; reward_amount: float; unit: str
    start_value: float = 0; threshold_increment: float
    step_amount: Optional[float] = None  # Klick-Schrittweite; default = threshold_increment
    target_value: Optional[float] = None; direction: str = "increase"

class AchUpd(BaseModel):
    current_value: float
    achieved_at: Optional[str] = None
    note: Optional[str] = None  # optionale Notiz für neu erzeugte Meilenstein-Einträge

class AchEdit(BaseModel):
    title: Optional[str] = None; reward_amount: Optional[float] = None
    unit: Optional[str] = None; start_value: Optional[float] = None
    threshold_increment: Optional[float] = None
    step_amount: Optional[float] = None
    target_value: Optional[float] = None
    direction: Optional[str] = None

class PGCreate(BaseModel):
    title: str; reward_amount: float; rhythm_type: str = "weekly"; target_count: int
    streak_bonus_amount: float = 0; streak_bonus_threshold: int = 0

class PGUpd(BaseModel):
    title: Optional[str] = None; reward_amount: Optional[float] = None
    target_count: Optional[int] = None; rhythm_type: Optional[str] = None
    streak_bonus_amount: Optional[float] = None; streak_bonus_threshold: Optional[int] = None

class CheckinBody(BaseModel):
    log_date: Optional[str] = None
    note: Optional[str] = None

class NoteBody(BaseModel):
    note: Optional[str] = None

class HMCreate(BaseModel):
    metric_type: str; value: float

class PotCreate(BaseModel):
    name: str; estimated_price: Optional[float] = None

class FICreate(BaseModel):
    title: str; category: Optional[str] = None

class ReorderBody(BaseModel):
    order: list[int]

class RestoreBody(BaseModel):
    payload: dict
    wipe: bool = False

class UserCreate(BaseModel):
    username: str
    password: str

class UserPasswordReset(BaseModel):
    password: str

class UserCreateInvite(BaseModel):
    username: str

class ActivateBody(BaseModel):
    token: str
    password: str

class TrophyCreate(BaseModel):
    name: str
    target_amount: float
    final_amount: float
    started_at: Optional[str] = None
    icon: Optional[str] = "🏆"
    color: Optional[str] = "gold"
    note: Optional[str] = None
    photo_url: Optional[str] = None

# ---------- Auth ----------
@app.post("/token")
@limiter.limit(LIMIT_LOGIN)
async def login(request: Request,
                form: OAuth2PasswordRequestForm = Depends(),
                conn: asyncpg.Connection = Depends(get_db)):
    row = await conn.fetchrow("SELECT * FROM users WHERE username = $1", form.username)
    if not row or row["password_hash"] is None or not pwd_context.verify(form.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falsche Credentials")
    return {"access_token": create_token(row["username"]), "token_type": "bearer"}

@app.get("/api/me")
async def me(user=Depends(get_current_user)):
    return {"username": user["username"], "is_admin": user["is_admin"], "id": user["id"]}

BACKEND_VERSION = "1.15.0"


@app.get("/api/health")
async def health():
    """Health-Check + Info welches Backend läuft (nützlich nach Deploy-Rollouts)."""
    return {
        "status": "ok",
        "backend_version": BACKEND_VERSION,
        "routes": sum(1 for r in app.routes if hasattr(r, "endpoint")),
        "expenses_router": True,
        "notes_router": True,
    }

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
    if not b.password or len(b.password) < 6:
        raise HTTPException(400, "Passwort mindestens 6 Zeichen")
    target = await db.fetchrow("SELECT id, username FROM users WHERE id=$1", uid)
    if not target:
        raise HTTPException(404, "User nicht gefunden")
    hash_ = pwd_context.hash(b.password)
    await db.execute("UPDATE users SET password_hash=$1 WHERE id=$2", hash_, uid)
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
    if not b.password or len(b.password) < 6:
        raise HTTPException(400, "Passwort mindestens 6 Zeichen")
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
async def _active_goal_id(db, user_id: int) -> Optional[int]:
    """Gibt die ID des aktiven Sparziels zurück (oder None)."""
    return await db.fetchval(
        "SELECT id FROM savings_goals WHERE user_id=$1 AND is_active=TRUE ORDER BY id DESC LIMIT 1",
        user_id)

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

class SavGoalCreate(BaseModel):
    name: str
    target_amount: float
    activate: bool = True

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
    owned = await db.fetchval(
        "SELECT 1 FROM savings_goals WHERE id=$1 AND user_id=$2", gid, user["id"])
    if not owned:
        raise HTTPException(404, "Sparziel nicht gefunden")
    async with db.transaction():
        await db.execute(
            "UPDATE savings_goals SET is_active=FALSE WHERE user_id=$1", user["id"])
        await db.execute(
            "UPDATE savings_goals SET is_active=TRUE WHERE id=$1 AND user_id=$2",
            gid, user["id"])
    logger.info(f"User {user['id']} activated savings_goal {gid}")
    return ser(await db.fetchrow("SELECT * FROM savings_goals WHERE id=$1", gid))

@app.delete("/api/savings-goals/{gid}")
@limiter.limit(LIMIT_WRITE_RARE)
async def del_sg(request: Request, gid: int, db=Depends(get_db), user=Depends(get_current_user)):
    row = await db.fetchrow("SELECT * FROM savings_goals WHERE id=$1 AND user_id=$2", gid, user["id"])
    if not row:
        raise HTTPException(404, "Sparziel nicht gefunden")
    other = await db.fetchval(
        "SELECT COUNT(*) FROM savings_goals WHERE user_id=$1 AND id<>$2", user["id"], gid)
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
def _milestones_at(sv, cv, inc, direction):
    """Zaehlt, wieviele Meilenstein-Schwellen bei ``cv`` bereits erreicht sind.

    Bugfix v1.15.0: Fliesskomma-Toleranz. Ohne Epsilon wuerde z.B.
    ``(9.999999999 // 1.0) == 9`` liefern, obwohl der User in Wahrheit
    per +0.1-Klicks den 10ten Meilenstein erreicht hat — die Belohnung
    wuerde ausbleiben, bis der naechste Klick kommt.
    """
    if inc <= 0:
        return 0
    inc = float(inc)
    # relative Toleranz von 1e-6 · inc — deckt akkumulierte Float-Fehler
    # ueber viele +x-Klicks ab, verfaelscht aber keine echten Zwischenwerte.
    eps = inc * 1e-6
    if direction == "increase":
        raw = (float(cv) - float(sv) + eps) / inc
    else:
        raw = (float(sv) - float(cv) + eps) / inc
    return max(0, int(math.floor(raw)))

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
    return ser(await db.fetchrow(
        "INSERT INTO achievements "
        "(user_id,title,reward_amount,unit,current_value,start_value,threshold_increment,step_amount,target_value,direction) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *",
        user["id"], b.title, b.reward_amount, b.unit, b.start_value, b.start_value,
        b.threshold_increment, step, b.target_value, b.direction))

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
    sg_id = await _active_goal_id(db, user["id"])
    tm = _milestones_at(sv, nv, inc, dirn)
    if tm > cred:
        # Notiz nur an den zuletzt erreichten Meilenstein hängen
        # (falls mehrere in einem Rutsch erreicht werden)
        last_step = tm
        for step in range(cred + 1, tm + 1):
            milestone_value = sv + step * inc if dirn == "increase" else sv - step * inc
            desc = f"Meilenstein: {a['title']} ({fmt_de_num(milestone_value)} {a['unit']})"
            step_note = note_val if step == last_step else None
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
    for field in ["title","reward_amount","unit","start_value","threshold_increment","step_amount","target_value","direction"]:
        if field not in provided:
            continue
        val = getattr(b, field)
        # Nur target_value darf via null geleert werden, alle anderen
        # Felder bleiben Pflichtwerte (also weiter "None ignorieren").
        if val is None and field != "target_value":
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
async def _streak(db, gid: int, user_id: int, rhythm: str, target: int) -> int:
    col = "month_key" if rhythm == "monthly" else "week_key"
    rows = await db.fetch(
        f"SELECT {col} AS k, COUNT(*) AS c FROM progress_logs WHERE progress_goal_id=$1 AND user_id=$2 GROUP BY {col}",
        gid, user_id)
    fulfilled = {r["k"] for r in rows if r["c"] >= target}
    streak = 0
    cursor = date.today()
    if period_key(rhythm, cursor) not in fulfilled:
        cursor = prev_period(rhythm, cursor)
    for _ in range(520):
        if period_key(rhythm, cursor) in fulfilled:
            streak += 1
            cursor = prev_period(rhythm, cursor)
        else:
            break
    return streak

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
    return ser(await db.fetchrow(
        "INSERT INTO progress_goals (user_id,title,reward_amount,rhythm_type,target_count,streak_bonus_amount,streak_bonus_threshold) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *",
        user["id"], b.title, b.reward_amount, b.rhythm_type, b.target_count,
        b.streak_bonus_amount, b.streak_bonus_threshold))

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
        sg_id = await _active_goal_id(db, user["id"])
        ex = await db.fetchval(
            "SELECT COUNT(*) FROM savings_transactions WHERE user_id=$1 AND source_type='progress' AND source_id=$2 AND period_key=$3",
            user["id"], gid, pk)
        if ex == 0 and float(pg["reward_amount"]) > 0:
            await db.execute(
                "INSERT INTO savings_transactions "
                "(user_id,amount,source_type,source_id,description,period_key,savings_goal_id) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                user["id"], float(pg["reward_amount"]), "progress", gid, f"{pg['title']} ({pk})", pk, sg_id)
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
                    await db.execute(
                        "INSERT INTO savings_transactions "
                        "(user_id,amount,source_type,source_id,description,period_key,savings_goal_id) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                        user["id"], bonus_amount, "progress", gid,
                        f"Streak-Bonus {streak}×: {pg['title']}", bonus_pk, sg_id)
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
async def pg_history(gid: int, limit: int = 8, db=Depends(get_db), user=Depends(get_current_user)):
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
        cnt = int(await db.fetchval(
            f"SELECT COUNT(*) FROM progress_logs WHERE progress_goal_id=$1 AND user_id=$2 AND {col}=$3",
            gid, user["id"], pk))
        paid = int(await db.fetchval(
            "SELECT COUNT(*) FROM savings_transactions WHERE user_id=$1 AND source_type='progress' AND source_id=$2 AND period_key=$3",
            user["id"], gid, pk))
        periods.append({"period_key": pk, "start": start.isoformat(), "end": end.isoformat(),
            "current_count": cnt, "target_count": target, "fulfilled": cnt >= target,
            "paid_out": paid > 0, "is_current": pk == period_key(rhythm, today)})
        cur = prev_period(rhythm, cur)
    return periods

# ---------- Health Metrics ----------
@app.get("/api/health-metrics")
async def list_hm(type: Optional[str] = None, db=Depends(get_db), user=Depends(get_current_user)):
    if type:
        return [ser(r) for r in await db.fetch(
            "SELECT * FROM health_metrics WHERE user_id=$1 AND metric_type=$2 ORDER BY recorded_at",
            user["id"], type)]
    grouped = {}
    for r in await db.fetch(
        "SELECT * FROM health_metrics WHERE user_id=$1 ORDER BY recorded_at", user["id"]):
        d = ser(r); grouped.setdefault(d["metric_type"], []).append(d)
    return grouped

@app.post("/api/health-metrics")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def create_hm(request: Request, b: HMCreate, db=Depends(get_db), user=Depends(get_current_user)):
    return ser(await db.fetchrow(
        "INSERT INTO health_metrics (user_id,metric_type,value) VALUES ($1,$2,$3) RETURNING *",
        user["id"], b.metric_type, b.value))

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
    await db.execute("DELETE FROM savings_transactions WHERE id=$1 AND user_id=$2", tid, user["id"])
    return {"status": "deleted"}

# ---------------------------------------------------------------
# Helfer fuer Export-Metadaten (Bugfix v1.15.0)
# ---------------------------------------------------------------
def _export_csv_field(s: str) -> str:
    s = (s or "").replace('"', '""').replace(';', ',').replace('\n', ' ').replace('\r', ' ')
    return f'"{s}"'


def _export_amt(v) -> str:
    try:
        return f"{float(v):.2f}"
    except Exception:
        return ""


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


@app.get("/api/savings-transactions/export")
async def export_st(db=Depends(get_db), user=Depends(get_current_user)):
    # ---------- CSV-Helfer ----------
    def _csv_field(s: str) -> str:
        s = (s or "").replace('"', '""').replace(';', ',').replace('\n', ' ').replace('\r', ' ')
        return f'"{s}"'

    def _amt(v) -> str:
        try:
            return f"{float(v):.2f}"
        except Exception:
            return ""

    # Bugfix v1.15.0: Der Export enthaelt jetzt vorab einen Metadaten-
    # Block mit allen Sparzielen, Achievements, Wochen-/Monatszielen,
    # Wunsch-Anschaffungen, Zukunftsideen und Trophaeen. Danach folgt
    # das eigentliche Protokoll wie bisher. Jede Sektion beginnt mit
    # einer Kommentarzeile ``# SEKTION: ...`` und ihrem eigenen Header.
    lines: list[str] = _build_export_header(user)
    lines.extend(await _build_export_metadata(db, user["id"]))
    lines.append("# SEKTION: Protokoll")
    log_header = "Datum;Typ;Titel;Beschreibung;Periode;Betrag;Notiz"
    lines.append(log_header)
    log_body: list[str] = []

    ci_rows = await db.fetch(
        """SELECT pl.log_date, pl.week_key, pl.month_key, pl.created_at, pl.note,
                  pg.title, pg.reward_amount, pg.rhythm_type, pg.target_count, pl.progress_goal_id, pl.id
           FROM progress_logs pl JOIN progress_goals pg ON pg.id = pl.progress_goal_id
           WHERE pl.user_id=$1
           ORDER BY pl.created_at""",
        user["id"])
    for r in ci_rows:
        rhythm = r["rhythm_type"] or "weekly"
        pk = r["month_key"] if rhythm == "monthly" else r["week_key"]
        col = "month_key" if rhythm == "monthly" else "week_key"
        cnt_upto = int(await db.fetchval(
            f"SELECT COUNT(*) FROM progress_logs WHERE progress_goal_id=$1 AND user_id=$2 AND {col}=$3 AND id <= $4",
            r["progress_goal_id"], user["id"], pk, r["id"]))
        target = int(r["target_count"])
        just_fulfilled = cnt_upto == target
        amt = float(r["reward_amount"]) if just_fulfilled else 0.0
        d = r["created_at"].isoformat() if r["created_at"] else ""
        desc = f"{cnt_upto}/{target}"
        log_body.append(f'{d};checkin;{_csv_field(r["title"])};{_csv_field(desc)};{pk or ""};{amt:.2f};{_csv_field(r["note"] or "")}')

    ml_rows = await db.fetch(
        """SELECT al.achieved_value, al.reward_amount, al.date_achieved, al.note, a.title, a.unit
           FROM achievement_logs al JOIN achievements a ON a.id = al.achievement_id
           WHERE al.user_id=$1
           ORDER BY al.date_achieved""",
        user["id"])
    for r in ml_rows:
        d = r["date_achieved"].isoformat() if r["date_achieved"] else ""
        unit = r["unit"] or ""
        desc = f"Bei {fmt_de_num(r['achieved_value'])} {unit}".strip()
        log_body.append(f'{d};milestone;{_csv_field(r["title"])};{_csv_field(desc)};;{float(r["reward_amount"]):.2f};{_csv_field(r["note"] or "")}')

    tx_rows = await db.fetch(
        """SELECT created_at, amount, source_type, source_id, description, period_key, note
           FROM savings_transactions WHERE user_id=$1 ORDER BY created_at""",
        user["id"])
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
        log_body.append(f'{d};{row_type};{_csv_field(title)};{_csv_field(desc)};{pk};{float(r["amount"]):.2f};{_csv_field(r["note"] or "")}')

    lines.extend(sorted(log_body))
    csv = "\n".join(lines) + "\n"
    return Response(content=csv, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=vexbob-log.csv"})

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

    for r in await db.fetch(
        "SELECT * FROM savings_transactions WHERE user_id=$1 AND source_type='initial' ORDER BY created_at DESC LIMIT $2",
        user["id"], limit):
        events.append({"type": "initial", "date": r["created_at"].isoformat(), "title": "Anfangsbestand",
            "description": r["description"] or "", "amount": float(r["amount"]),
            "log_id": r["id"], "note": r["note"] or "", "deletable": True})

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
# Notizen-Modul (Paket 14) — ausgelagert in routers/notes_router.py
# ==========================================================================
from routers.notes_router import router as notes_router
app.include_router(notes_router)
