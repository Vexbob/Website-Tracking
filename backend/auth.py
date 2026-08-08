from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, HTTPException, status
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
import os
import asyncpg

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable must be set")

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# Deferred import um circular dependency zu vermeiden
def _get_db_dep():
    from database import get_db
    return get_db

async def authenticate(username: str, password: str, conn: asyncpg.Connection):
    row = await conn.fetchrow("SELECT * FROM users WHERE username = $1", username)
    if not row or not pwd_context.verify(password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falsche Credentials")
    return username

def create_token(username: str) -> str:
    payload = {"sub": username, "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """Dekodiert Token und lädt User-Datensatz (id, username, is_admin) aus DB."""
    from database import _pool, DATABASE_URL
    import database as db_module
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid token")

    # Lazy pool init falls nötig
    if db_module._pool is None:
        db_module._pool = await asyncpg.create_pool(
            db_module.DATABASE_URL, ssl="require", min_size=1, max_size=10)
    async with db_module._pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, is_admin FROM users WHERE username=$1", username)
    if not row:
        raise HTTPException(401, "User not found")
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}

async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(403, "Nur Admin darf das")
    return user