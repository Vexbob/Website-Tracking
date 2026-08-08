"""Backup-Service: Snapshots erstellen, wiederherstellen, aufräumen.
User-scoped: create_snapshot/restore_snapshot filtern per user_id.
user_id=None bedeutet globaler Snapshot (nur Admin/Autobackup)."""
import json
import logging
from datetime import datetime, timezone
from typing import Optional
import asyncpg

logger = logging.getLogger("vexbob.backup")

TABLES_ORDERED = [
    "users",
    "savings_goals",
    "achievements",
    "achievement_logs",
    "progress_goals",
    "progress_logs",
    "health_metrics",
    "savings_transactions",
    "potential_goals",
    "future_ideas",
    "completed_goals",
]

# Tabellen, die eine user_id haben (users selber nicht)
USER_SCOPED_TABLES = {t for t in TABLES_ORDERED if t != "users"}

def _ser_value(v):
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    try:
        from decimal import Decimal
        if isinstance(v, Decimal):
            return float(v)
    except ImportError:
        pass
    return v

def _ser_row(row):
    return {k: _ser_value(v) for k, v in dict(row).items()}

async def _table_exists(conn: asyncpg.Connection, table: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=$1",
        table))

async def _column_exists(conn: asyncpg.Connection, table: str, column: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=$1 AND column_name=$2",
        table, column))

async def create_snapshot(conn: asyncpg.Connection, trigger_type: str = "manual",
                          user_id: Optional[int] = None) -> dict:
    """Erstellt einen Snapshot.
    user_id=None: globaler Snapshot (alle Daten aller User) — nur für Admin/Autobackup.
    user_id=X:    nur Daten von User X."""
    data = {}
    for t in TABLES_ORDERED:
        if not await _table_exists(conn, t):
            data[t] = []
            continue
        try:
            if user_id is not None and t in USER_SCOPED_TABLES and await _column_exists(conn, t, "user_id"):
                rows = await conn.fetch(f"SELECT * FROM {t} WHERE user_id=$1", user_id)
            elif user_id is not None and t == "users":
                # Beim User-Backup: nur eigenen User-Datensatz mitnehmen
                rows = await conn.fetch("SELECT * FROM users WHERE id=$1", user_id)
            else:
                rows = await conn.fetch(f"SELECT * FROM {t}")
            data[t] = [_ser_row(r) for r in rows]
        except Exception as e:
            logger.warning(f"Snapshot: konnte Tabelle {t} nicht lesen: {e}")
            data[t] = []
    payload = {
        "backup_date": datetime.now(timezone.utc).isoformat(),
        "version": "1.3.0",
        "trigger": trigger_type,
        "user_id": user_id,
        "data": data,
    }
    payload_json = json.dumps(payload, ensure_ascii=False)
    size = len(payload_json.encode("utf-8"))

    if await _table_exists(conn, "backup_snapshots"):
        await conn.execute(
            "INSERT INTO backup_snapshots (trigger_type, payload, size_bytes, user_id) "
            "VALUES ($1, $2::jsonb, $3, $4)",
            trigger_type, payload_json, size, user_id)
        logger.info(f"Snapshot created ({trigger_type}, {size} bytes, user_id={user_id})")
    else:
        logger.warning("backup_snapshots-Tabelle fehlt, Snapshot wird nicht persistiert")
    return payload

async def prune_snapshots(conn: asyncpg.Connection, keep_daily: int = 7, keep_weekly: int = 4):
    if not await _table_exists(conn, "backup_snapshots"):
        return
    for trig, keep in [("auto_daily", keep_daily), ("auto_weekly", keep_weekly)]:
        rows = await conn.fetch(
            "SELECT id FROM backup_snapshots WHERE trigger_type=$1 ORDER BY created_at DESC OFFSET $2",
            trig, keep)
        if rows:
            ids = [r["id"] for r in rows]
            await conn.execute("DELETE FROM backup_snapshots WHERE id = ANY($1::int[])", ids)
            logger.info(f"Pruned {len(ids)} old {trig} snapshots")

async def restore_snapshot(conn: asyncpg.Connection, payload: dict,
                           user_id: Optional[int] = None, wipe: bool = False) -> dict:
    """Restore. Wenn user_id gesetzt: nur Daten dieses Users werden geschrieben,
    fremde user_id in payload wird ÜBERSCHRIEBEN mit dem angegebenen user_id.
    wipe=True: leert VOR dem Restore alle Daten des Users (nicht global!)."""
    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError("Ungültiges Backup-Format: 'data' fehlt")
    data = payload["data"]
    if not isinstance(data, dict):
        raise ValueError("Ungültiges Backup-Format: 'data' muss ein Objekt sein")

    stats = {"restored": {}, "skipped": {}, "wiped": wipe}

    async with conn.transaction():
        if wipe:
            if user_id is not None:
                # Nur eigene Daten löschen
                for t in reversed([x for x in TABLES_ORDERED if x != "users"]):
                    if await _table_exists(conn, t) and await _column_exists(conn, t, "user_id"):
                        try:
                            await conn.execute(f"DELETE FROM {t} WHERE user_id=$1", user_id)
                        except Exception as e:
                            logger.warning(f"DELETE {t} für user {user_id} fehlgeschlagen: {e}")
            else:
                # Globaler Wipe (nur Admin/global-Restore)
                for t in reversed(TABLES_ORDERED):
                    if await _table_exists(conn, t):
                        try:
                            await conn.execute(f"TRUNCATE TABLE {t} RESTART IDENTITY CASCADE")
                        except Exception as e:
                            logger.warning(f"TRUNCATE {t} fehlgeschlagen: {e}")

        for t in TABLES_ORDERED:
            rows = data.get(t, [])
            if not rows:
                continue
            if not await _table_exists(conn, t):
                logger.warning(f"Tabelle {t} existiert nicht, überspringe {len(rows)} Zeilen")
                stats["skipped"][t] = len(rows)
                continue

            # Bei User-Restore die users-Tabelle NICHT anfassen (sonst könnte man
            # sich zum Admin machen). User-Datensatz ist rein informativ.
            if user_id is not None and t == "users":
                stats["skipped"][t] = len(rows)
                continue

            has_user_col = await _column_exists(conn, t, "user_id")

            existing_ids = set()
            if not wipe:
                if user_id is not None and has_user_col:
                    existing = await conn.fetch(f"SELECT id FROM {t} WHERE user_id=$1", user_id)
                else:
                    existing = await conn.fetch(f"SELECT id FROM {t}")
                existing_ids = {r["id"] for r in existing}

            restored = 0; skipped = 0
            for row in rows:
                if not isinstance(row, dict):
                    skipped += 1; continue
                # Bei User-Restore: user_id im Row überschreiben
                if user_id is not None and has_user_col:
                    row = {**row, "user_id": user_id}
                if not wipe and row.get("id") in existing_ids:
                    skipped += 1; continue
                cols = list(row.keys())
                placeholders = [f"${i+1}" for i in range(len(cols))]
                vals = [row[c] for c in cols]
                sql = (
                    f'INSERT INTO {t} ({",".join(cols)}) '
                    f'VALUES ({",".join(placeholders)}) '
                    f'ON CONFLICT (id) DO NOTHING'
                )
                try:
                    await conn.execute(sql, *vals)
                    restored += 1
                except Exception as e:
                    logger.warning(f"Restore skip {t}.{row.get('id')}: {e}")
                    skipped += 1
            stats["restored"][t] = restored
            stats["skipped"][t] = skipped

            if rows and any(isinstance(r, dict) and "id" in r for r in rows):
                try:
                    await conn.execute(
                        f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {t}), 1))")
                except Exception as e:
                    logger.warning(f"Sequence-Reset {t} fehlgeschlagen: {e}")
    return stats