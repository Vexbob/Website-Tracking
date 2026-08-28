"""Backup-Service: Snapshots erstellen, wiederherstellen, aufräumen."""
import json
import logging
from datetime import datetime, timezone
import asyncpg

logger = logging.getLogger("vexbob.backup")

# Reihenfolge wichtig wegen Foreign Keys:
# Parents zuerst (users, savings_goals, achievements, progress_goals),
# dann Children (logs, transactions, completed_goals).
TABLES_ORDERED = [
    "users",
    "savings_goals",
    "achievements",
    "achievement_logs",
    "progress_goals",
    "progress_logs",
    "savings_transactions",
    "potential_goals",
    "future_ideas",
    "completed_goals",
]

def _ser_value(v):
    """Konvertiert Python-Objekte in JSON-safe Werte."""
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    # asyncpg gibt NUMERIC als Decimal zurück → in float konvertieren
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

async def create_snapshot(conn: asyncpg.Connection, trigger_type: str = "manual") -> dict:
    """Erstellt einen Snapshot aller Nutzdaten und speichert ihn in backup_snapshots."""
    data = {}
    for t in TABLES_ORDERED:
        if not await _table_exists(conn, t):
            data[t] = []
            continue
        try:
            rows = await conn.fetch(f"SELECT * FROM {t}")
            data[t] = [_ser_row(r) for r in rows]
        except Exception as e:
            logger.warning(f"Snapshot: konnte Tabelle {t} nicht lesen: {e}")
            data[t] = []
    payload = {
        "backup_date": datetime.now(timezone.utc).isoformat(),
        "version": "1.2.0",
        "trigger": trigger_type,
        "data": data,
    }
    payload_json = json.dumps(payload, ensure_ascii=False)
    size = len(payload_json.encode("utf-8"))

    # Nur speichern, wenn Zieltabelle existiert (falls Migration 004 noch nicht durch ist)
    if await _table_exists(conn, "backup_snapshots"):
        await conn.execute(
            "INSERT INTO backup_snapshots (trigger_type, payload, size_bytes) VALUES ($1, $2::jsonb, $3)",
            trigger_type, payload_json, size)
        logger.info(f"Snapshot created ({trigger_type}, {size} bytes)")
    else:
        logger.warning("backup_snapshots-Tabelle fehlt, Snapshot wird nicht persistiert")
    return payload

async def prune_snapshots(conn: asyncpg.Connection, keep_daily: int = 7, keep_weekly: int = 4):
    """Behält die letzten N Daily- und Weekly-Snapshots. Manuelle bleiben unberührt."""
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

async def restore_snapshot(conn: asyncpg.Connection, payload: dict, wipe: bool = False) -> dict:
    """Stellt einen Snapshot wieder her.
    wipe=True: leert alle Tabellen zuerst (DESTRUKTIV).
    wipe=False: fügt nur fehlende IDs hinzu (dedupliziert per Primary Key).
    """
    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError("Ungültiges Backup-Format: 'data' fehlt")
    data = payload["data"]
    if not isinstance(data, dict):
        raise ValueError("Ungültiges Backup-Format: 'data' muss ein Objekt sein")

    stats = {"restored": {}, "skipped": {}, "wiped": wipe}

    async with conn.transaction():
        if wipe:
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

            existing_ids = set()
            if not wipe:
                existing = await conn.fetch(f"SELECT id FROM {t}")
                existing_ids = {r["id"] for r in existing}

            restored = 0
            skipped = 0
            for row in rows:
                if not isinstance(row, dict):
                    skipped += 1
                    continue
                if not wipe and row.get("id") in existing_ids:
                    skipped += 1
                    continue
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

            # Sequence auf max(id) setzen, damit neue Inserts nicht kollidieren
            if rows and any(isinstance(r, dict) and "id" in r for r in rows):
                try:
                    await conn.execute(
                        f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {t}), 1))")
                except Exception as e:
                    logger.warning(f"Sequence-Reset {t} fehlgeschlagen: {e}")
    return stats