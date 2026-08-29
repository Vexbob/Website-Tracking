"""Einfaches Migrations-System.

Migrations sind SQL-Dateien in ``migrations/sql/``, benannt
``NNN_beschreibung.sql`` (aufsteigend). Angewandte Migrations werden in Tabelle
``schema_migrations`` getrackt.

v1.35.0: Jede angewandte Migration wird zusaetzlich mit einem SHA256-Checksum
ihres damaligen Inhalts persistiert. Beim naechsten Startup vergleicht der
Runner den aktuellen Datei-Checksum mit dem gespeicherten -- wurde eine
bereits deployte Migration nachtraeglich veraendert (klassischer Fussschuss,
wenn man "nur schnell was fixt"), knallt es hart, statt still ein
inkonsistentes Schema zu tolerieren. Alt-Reihen ohne Checksum werden beim
naechsten Start OPPORTUNISTISCH mit dem aktuellen Wert nachgezogen, damit
bestehende Deploys nicht kaputt gehen.

Optionaler Dry-Run per ENV ``MIGRATIONS_DRY_RUN=1`` -- Runner listet nur was
angewendet WUERDE, macht aber keinerlei Schreibzugriffe. Praktisch fuer
Deploy-Preview.
"""
import hashlib
import logging
import os

import asyncpg

logger = logging.getLogger("vexbob.migrations")
MIG_DIR = os.path.join(os.path.dirname(__file__), "sql")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def apply_migrations(conn: asyncpg.Connection):
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ DEFAULT NOW()
        )"""
    )
    # v1.35.0: Checksum-Spalte idempotent nachziehen.
    try:
        await conn.execute(
            "ALTER TABLE schema_migrations "
            "ADD COLUMN IF NOT EXISTS checksum TEXT"
        )
    except Exception as e:
        logger.warning(f"Kann checksum-Spalte nicht anlegen: {e}")

    applied_rows = await conn.fetch(
        "SELECT version, checksum FROM schema_migrations"
    )
    applied = {r["version"]: r["checksum"] for r in applied_rows}

    if not os.path.isdir(MIG_DIR):
        logger.warning(f"Migration dir missing: {MIG_DIR}")
        return

    files = sorted(f for f in os.listdir(MIG_DIR) if f.endswith(".sql"))
    dry_run = os.getenv("MIGRATIONS_DRY_RUN", "").strip() in ("1", "true", "yes")

    drift_errors: list[str] = []

    for fname in files:
        version = fname.rsplit(".", 1)[0]  # "001_add_sort_order"
        path = os.path.join(MIG_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            sql = f.read()
        cur_hash = _sha256(sql)

        if version in applied:
            stored = applied[version]
            if stored is None:
                # Alt-Eintrag: einmalig nachtragen, damit beim naechsten
                # Startup echter Drift-Check greift.
                if not dry_run:
                    await conn.execute(
                        "UPDATE schema_migrations SET checksum=$1 WHERE version=$2",
                        cur_hash, version,
                    )
                    logger.info(
                        f"Migration {version}: checksum nachtraeglich "
                        "gespeichert (Alt-Eintrag ohne Hash)"
                    )
            elif stored != cur_hash:
                # Harter Fehler -- Datei wurde nachtraeglich veraendert.
                drift_errors.append(
                    f"Migration {version} wurde nachtraeglich modifiziert "
                    f"(erwartet {stored[:12]}..., aktuell {cur_hash[:12]}...). "
                    "Erzeuge eine neue Migration statt bestehende zu editieren."
                )
            continue

        # Neue Migration
        if dry_run:
            logger.info(f"[DRY-RUN] Would apply migration {version}")
            continue

        logger.info(f"Applying migration {version}")
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)",
                version, cur_hash,
            )
        logger.info(f"Migration {version} applied ✓")

    if drift_errors:
        for msg in drift_errors:
            logger.error(msg)
        raise RuntimeError(
            "Migration-Checksum-Drift erkannt: " + " | ".join(drift_errors)
        )