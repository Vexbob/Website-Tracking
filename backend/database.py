import os
import asyncpg
from datetime import date
from migrations.runner import apply_migrations

DATABASE_URL = os.getenv("DATABASE_URL")
_pool = None

async def get_db():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, ssl="require", min_size=1, max_size=10)
    async with _pool.acquire() as conn:
        yield conn


async def _seed_empty_user(conn, user_id: int):
    """Neue Accounts starten mit leerem Sparziel als Grundstruktur."""
    has_any = await conn.fetchval(
        "SELECT 1 FROM savings_goals WHERE user_id=$1 LIMIT 1", user_id)
    if has_any:
        return
    await conn.execute(
        "INSERT INTO savings_goals (user_id,name,target_amount,is_active) VALUES ($1,'Mein Sparziel',100,TRUE)",
        user_id)


async def init_db():
    """Initialisiert die Datenbank: Migrations anwenden.
    Admin-Account wird NICHT automatisch angelegt — das erfolgt manuell per SQL
    oder über einen zukünftigen CLI-Befehl. Siehe docs/development.md."""
    conn = await asyncpg.connect(DATABASE_URL, ssl="require")
    try:
        await apply_migrations(conn)
    finally:
        await conn.close()


# ---------- Zeit-Helper ----------
def week_key_for(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"

def month_key_for(d: date) -> str:
    return d.strftime("%Y-%m")

def period_key(rhythm: str, d: date) -> str:
    return month_key_for(d) if rhythm == "monthly" else week_key_for(d)

def prev_period(rhythm: str, d: date) -> date:
    from datetime import timedelta
    if rhythm == "monthly":
        if d.month == 1:
            return date(d.year-1, 12, 1)
        return date(d.year, d.month-1, 1)
    return d - timedelta(days=7)

def current_week_key() -> str:
    return week_key_for(date.today())

def current_month_key() -> str:
    return month_key_for(date.today())