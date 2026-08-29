from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, HTTPException, Header, status
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from typing import Optional
import hashlib
import hmac
import os
import time
import secrets as _secrets
import asyncpg

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable must be set")

ALGORITHM = "HS256"
# v1.33.0: konfigurierbar via ENV. Default bleibt 24h damit bestehende Deploys
# keinen ueberraschten Re-Login-Zwang bekommen.
try:
    TOKEN_EXPIRE_HOURS = max(1, int(os.getenv("JWT_EXPIRE_HOURS", "24")))
except ValueError:
    TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# v1.33.0: Timing-Attack-Schutz im Login.
# Wenn der User NICHT existiert, wollen wir trotzdem einmal bcrypt.verify()
# aufrufen, damit ein Angreifer aus der Response-Zeit nicht ableiten kann, ob
# ein Username existiert oder nicht. Der Hash unten ist ein fester Bcrypt-Hash
# fuer einen zufaelligen String, der zur Laufzeit einmal erzeugt wird -- er
# wird NIE gegen einen echten User passen.
_DUMMY_PASSWORD_HASH = pwd_context.hash(_secrets.token_urlsafe(32))


def verify_password_ct(password: str, password_hash: Optional[str]) -> bool:
    """Constant-time password check: verifiziert immer gegen einen Hash --
    entweder den echten, oder gegen einen Dummy-Hash. So ist die Laufzeit
    des Login-Endpunkts bei "User existiert nicht" ~ gleich wie bei
    "User existiert aber Passwort falsch"."""
    target = password_hash if password_hash else _DUMMY_PASSWORD_HASH
    try:
        ok = pwd_context.verify(password, target)
    except Exception:
        ok = False
    # Wenn kein Passwort-Hash da war (User existiert nicht bzw. noch nicht
    # aktiviert), muss das Ergebnis IMMER False sein -- auch wenn der Dummy
    # zufaellig matcht (statistisch ausgeschlossen, aber sauber ist sauber).
    return ok and bool(password_hash)


# v1.33.0: 60s In-Memory-Cache fuer get_current_user, damit nicht jeder
# authentifizierte Request eine extra DB-Query fuer User-Lookup ausloest.
# Ein Dashboard-Aufruf feuert typischerweise 15-25 Requests -- die alle
# denselben User treffen. Bewusst simpel gehalten: dict + Timestamp, kein
# externes LRU-Package.
_USER_CACHE_TTL_S = 60
_user_cache: dict[str, tuple[float, dict]] = {}

# ---------------------------------------------------------------------------
# Health-Sync API-Keys (v1.22.0)
# ---------------------------------------------------------------------------
# Personal-Access-Token-artiger Mechanismus fuer die Auto-Health-Export-App:
# die App kann keinen JWT-Login-Flow durchfuehren, sondern schickt bei jedem
# automatisierten Sync nur einen statischen Header mit. Klartext-Format:
#   hae_<user_id>_<32-byte-urlsafe-random>
# Der User-Praefix erlaubt einen gezielten DB-Lookup ohne Full-Table-Scan.
# Gespeichert wird nur ein HMAC-SHA256-Hash (SECRET_KEY als Pepper) — kein
# bcrypt notwendig, da der Klartext-Key selbst schon hochentropisch ist und
# der Endpoint ggf. mehrmals taeglich automatisiert aufgerufen wird.
HEALTH_KEY_PREFIX = "hae"


def _hash_health_key(raw_key: str) -> str:
    return hmac.new(SECRET_KEY.encode(), raw_key.encode(), hashlib.sha256).hexdigest()


def generate_health_api_key(user_id: int) -> tuple[str, str]:
    """Erzeugt einen neuen Health-API-Key. Gibt (klartext_key, hash) zurueck.
    Der Klartext wird NUR hier zurueckgegeben und muss dem User einmalig
    angezeigt werden — er wird nicht persistiert."""
    token = _secrets.token_urlsafe(32)
    raw_key = f"{HEALTH_KEY_PREFIX}_{user_id}_{token}"
    return raw_key, _hash_health_key(raw_key)


def parse_health_key_user_id(raw_key: str) -> Optional[int]:
    """Extrahiert die user_id aus dem Key-Praefix, ohne DB-Zugriff."""
    parts = raw_key.split("_")
    if len(parts) < 3 or parts[0] != HEALTH_KEY_PREFIX:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


async def get_user_from_health_api_key(
    authorization: Optional[str] = Header(None),
) -> dict:
    """Auth-Dependency fuer den Health-Import-Endpoint. Erwartet
    ``Authorization: Bearer hae_<user_id>_<random>``. Komplett getrennt vom
    JWT-Login-Flow, damit externe Automations (Auto Health Export) sich mit
    einem langlebigen, aber jederzeit widerrufbaren Key authentifizieren
    koennen."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Fehlender oder ungueltiger Authorization-Header")
    raw_key = authorization.split(" ", 1)[1].strip()
    user_id = parse_health_key_user_id(raw_key)
    if user_id is None:
        raise HTTPException(401, "Ungueltiges API-Key-Format")

    from database import get_pool
    pool = await get_pool()

    key_hash = _hash_health_key(raw_key)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, user_id FROM health_api_keys "
            "WHERE user_id=$1 AND key_hash=$2 AND revoked_at IS NULL",
            user_id, key_hash)
        if not row:
            raise HTTPException(401, "API-Key ungueltig oder widerrufen")
        await conn.execute(
            "UPDATE health_api_keys SET last_used_at=NOW() WHERE id=$1", row["id"])
    return {"id": user_id}

# Deferred import um circular dependency zu vermeiden
def _get_db_dep():
    from database import get_db
    return get_db

async def authenticate(username: str, password: str, conn: asyncpg.Connection):
    """v1.33.0: haerter gegen User-Enumeration.

    Der Bcrypt-Verify laeuft IMMER (auch wenn der User nicht existiert oder
    noch keinen Passwort-Hash hat) und gibt konstant "Falsche Credentials"
    zurueck -- keine unterscheidbare Antwort zwischen "User nicht da",
    "User noch nicht aktiviert" und "Passwort falsch".
    """
    row = await conn.fetchrow("SELECT * FROM users WHERE username = $1", username)
    pw_hash = row["password_hash"] if row else None
    if not verify_password_ct(password, pw_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falsche Credentials")
    return username

def create_token(username: str) -> str:
    payload = {"sub": username, "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def _invalidate_user_cache(username: Optional[str] = None) -> None:
    """Wird von Admin-Actions (Passwort-Reset, Delete, Rechte-Aenderung)
    aufgerufen, damit der 60s-Cache nicht "verzoegert" alte Rechte liefert."""
    if username is None:
        _user_cache.clear()
    else:
        _user_cache.pop(username, None)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Dekodiert Token und laedt User-Datensatz (id, username, is_admin).

    v1.33.0: nutzt ``database.get_pool()`` (race-safe) und einen 60s-Cache,
    damit ein Dashboard-Aufruf nicht 20x dieselbe User-Row aus der DB holt.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid token")

    now = time.monotonic()
    cached = _user_cache.get(username)
    if cached and (now - cached[0]) < _USER_CACHE_TTL_S:
        return cached[1]

    from database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, is_admin FROM users WHERE username=$1", username)
    if not row:
        # Aus dem Cache raus (falls der User geloescht wurde und der alte
        # Cache-Eintrag noch drin haengt) und stumpf 401.
        _user_cache.pop(username, None)
        raise HTTPException(401, "User not found")
    user = {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}
    _user_cache[username] = (now, user)
    return user

async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(403, "Nur Admin darf das")
    return user