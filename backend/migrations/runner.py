"""Einfaches Migrations-System.
Migrations sind SQL-Dateien in migrations/sql/, benannt NNN_beschreibung.sql (aufsteigend).
Angewandte Migrations werden in Tabelle schema_migrations getrackt.
"""
import os
import logging
import asyncpg

logger = logging.getLogger("vexbob.migrations")
MIG_DIR = os.path.join(os.path.dirname(__file__), "sql")

async def apply_migrations(conn: asyncpg.Connection):
    await conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ DEFAULT NOW())""")
    applied = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
    if not os.path.isdir(MIG_DIR):
        logger.warning(f"Migration dir missing: {MIG_DIR}")
        return
    files = sorted(f for f in os.listdir(MIG_DIR) if f.endswith(".sql"))
    for fname in files:
        version = fname.rsplit(".", 1)[0]  # "001_add_sort_order"
        if version in applied:
            continue
        path = os.path.join(MIG_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            sql = f.read()
        logger.info(f"Applying migration {version}")
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)
        logger.info(f"Migration {version} applied ✓")