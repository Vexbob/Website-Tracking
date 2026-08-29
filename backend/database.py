import os
import asyncio
import asyncpg
from datetime import date
from migrations.runner import apply_migrations

DATABASE_URL = os.getenv("DATABASE_URL")
_pool = None
# v1.33.0: Lock verhindert die Race Condition beim Kalt-Start. Vorher konnten
# parallel eintreffende Requests jeweils "pool is None" sehen und alle einen
# eigenen Pool erzeugen -- alle bis auf einen wurden geleakt (Connections
# blieben offen bis der Prozess starb). Auf Railway mit einem einzelnen
# Worker-Prozess reproduzierbar, sobald direkt nach dem Deploy mehrere Clients
# gleichzeitig requesteten.
_pool_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    """Zentrale Pool-Fabrik. Idempotent, race-safe.

    Alle anderen Module (auth, routers, backup-loop, ...) MUESSEN diese Funktion
    nutzen statt selbst ``asyncpg.create_pool`` aufzurufen -- sonst kommt der
    Race-Bug zurueck. Das ``if _pool is None`` innerhalb des Locks ist der
    klassische Double-Checked-Locking-Idiom fuer asyncio.
    """
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            _pool = await asyncpg.create_pool(
                DATABASE_URL, ssl="require", min_size=1, max_size=10)
    return _pool


async def close_pool() -> None:
    """Sauberes Herunterfahren beim Lifespan-Shutdown."""
    global _pool
    if _pool is not None:
        try:
            await _pool.close()
        finally:
            _pool = None


async def get_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def _seed_empty_user(conn, user_id: int):
    """Neue Accounts starten mit leerem Sparziel + Basis-Kategorien fuer Ausgaben +
    Marken-Seed (v1.16.0). Alle Operationen sind idempotent — wird auch bei
    bestehenden Accounts sicher wieder ausgefuehrt (z.B. um Marken nachzuziehen)."""
    has_any = await conn.fetchval(
        "SELECT 1 FROM savings_goals WHERE user_id=$1 LIMIT 1", user_id)
    if not has_any:
        await conn.execute(
            "INSERT INTO savings_goals (user_id,name,target_amount,is_active) VALUES ($1,'Mein Sparziel',100,TRUE)",
            user_id)
    # v1.18.2: Allgemein-Konto sicherstellen (Puffer fuer Meilenstein-Belohnungen)
    has_general = await conn.fetchval(
        "SELECT 1 FROM savings_goals WHERE user_id=$1 AND is_general=TRUE LIMIT 1", user_id)
    if not has_general:
        try:
            await conn.execute(
                "INSERT INTO savings_goals (user_id,name,target_amount,is_active,is_general) "
                "VALUES ($1,'Allgemein',0,FALSE,TRUE)",
                user_id)
        except Exception:
            pass  # Migration hat's evtl. schon erledigt
    # Default-Kategorien fuer Ausgaben (idempotent per uniq-Index)
    has_cats = await conn.fetchval(
        "SELECT 1 FROM expense_categories WHERE user_id=$1 LIMIT 1", user_id)
    if not has_cats:
        defaults = [
            ("Lebensmittel", "#22c55e", "🍎", 10),
            ("Drogerie",     "#ec4899", "🧴", 20),
            ("Restaurant",   "#f59e0b", "🍽️", 30),
            ("Technik",      "#3b82f6", "💻", 40),
            ("Kleidung",     "#8b5cf6", "👕", 50),
            ("Transport",    "#14b8a6", "🚗", 60),
            ("Wohnen",       "#ef4444", "🏠", 70),
            ("Freizeit",     "#eab308", "🎉", 80),
            ("Sonstiges",    "#6b7280", "📦", 999),
        ]
        for name, color, icon, order in defaults:
            await conn.execute(
                "INSERT INTO expense_categories (user_id,name,color,icon,sort_order) "
                "VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING",
                user_id, name, color, icon, order)
    # Marken-Seed (v1.16.0). Idempotent per uniq_brands_user_name.
    # ``store_id`` nur setzen wenn User bereits einen Laden mit passendem Namen hat.
    await _seed_brands_for_user(conn, user_id)


async def _seed_brands_for_user(conn, user_id: int):
    """Legt vordefinierte Marken fuer den User an (falls noch keine existieren).

    Eigenmarken werden auf einen bereits vorhandenen User-Store (case-insensitive
    Name-Match) verlinkt; findet sich kein Store, bleibt ``store_id=NULL``.
    Hersteller-Marken haben nie eine ``store_id``.

    Der Seeder rennt nur einmal pro User durch (Guard: ``seed_source='system'``
    schon vorhanden). Neue User-Marken (``seed_source=NULL``) bleiben unberuehrt.
    """
    already_seeded = await conn.fetchval(
        "SELECT 1 FROM brands WHERE user_id=$1 AND seed_source='system' LIMIT 1",
        user_id)
    if already_seeded:
        return
    try:
        from brand_seed_data import PRIVATE_LABELS, BRANDS
    except ImportError:
        return  # Seed-Daten fehlen -> ueberspringen

    # Store-Lookup (case-insensitive) fuer Eigenmarken-Verknuepfung
    store_rows = await conn.fetch(
        "SELECT id, LOWER(name) AS lname FROM stores WHERE user_id=$1", user_id)
    store_by_name = {r["lname"]: r["id"] for r in store_rows}

    def _find_store_id(hint: str):
        if not hint:
            return None
        h = hint.lower().strip()
        # Direkte Uebereinstimmung
        if h in store_by_name:
            return store_by_name[h]
        # Fuzzy: Store-Name enthaelt Hint oder umgekehrt
        for lname, sid in store_by_name.items():
            if h in lname or lname in h:
                return sid
        return None

    # Eigenmarken
    for name, store_hint in PRIVATE_LABELS:
        sid = _find_store_id(store_hint)
        await conn.execute(
            "INSERT INTO brands (user_id, name, is_private_label, store_id, seed_source) "
            "VALUES ($1, $2, TRUE, $3, 'system') "
            "ON CONFLICT (user_id, LOWER(name)) DO NOTHING",
            user_id, name, sid)

    # Hersteller-Marken
    for name, parent in BRANDS:
        await conn.execute(
            "INSERT INTO brands (user_id, name, is_private_label, parent_company, seed_source) "
            "VALUES ($1, $2, FALSE, $3, 'system') "
            "ON CONFLICT (user_id, LOWER(name)) DO NOTHING",
            user_id, name, parent)


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