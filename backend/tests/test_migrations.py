"""Tests fuer den Migration-Runner (v1.35.0).

Kein echter Postgres notwendig -- wir mocken die asyncpg-Connection minimal
mit einem AsyncMock. Der Fokus liegt auf:
- SHA256-Berechnung ist stabil und Datei-inhalt-abhaengig
- Checksum-Drift erzeugt einen RuntimeError statt still zu passieren
- MIGRATIONS_DRY_RUN unterdrueckt Schreibzugriffe
"""
import asyncio
import os
import sys
import tempfile
import types

os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# asyncpg wird vom Runner nur fuer Type-Hints referenziert (``asyncpg.Connection``).
# Fuer die Unit-Tests ohne echte DB stubben wir das Modul, damit die Tests
# auch in einer Entwickler-Umgebung ohne asyncpg-Installation laufen.
if "asyncpg" not in sys.modules:
    stub = types.ModuleType("asyncpg")
    class _Conn:  # pragma: no cover - Type-only stub
        pass
    stub.Connection = _Conn
    sys.modules["asyncpg"] = stub

import migrations.runner as runner  # noqa: E402


def test_sha256_is_content_dependent():
    a = runner._sha256("SELECT 1;")
    b = runner._sha256("SELECT 2;")
    assert a != b
    # Whitespace-Aenderungen fliessen ein -- explizit gewollt.
    assert runner._sha256("SELECT 1;") != runner._sha256("SELECT 1; ")


class _FakeConn:
    """Minimaler asyncpg-Connection-Mock. Sammelt SQL-Executes und liefert
    vordefinierte Fetch-Ergebnisse."""

    def __init__(self, applied_rows):
        self._applied = applied_rows
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"

    async def fetch(self, sql, *args):
        if "schema_migrations" in sql:
            return self._applied
        return []

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False

        return _Tx()


def _write_migration(dirpath: str, name: str, sql: str) -> str:
    path = os.path.join(dirpath, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(sql)
    return path


def test_drift_raises_runtime_error(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        _write_migration(d, "001_x.sql", "SELECT 1;")
        # In der DB gespeicherter Checksum passt NICHT zum aktuellen Datei-Inhalt
        applied = [{"version": "001_x", "checksum": "deadbeef" * 8}]
        monkeypatch.setattr(runner, "MIG_DIR", d)
        conn = _FakeConn(applied)

        try:
            asyncio.run(runner.apply_migrations(conn))
        except RuntimeError as e:
            assert "Checksum-Drift" in str(e)
            assert "001_x" in str(e)
        else:
            raise AssertionError("Erwartete RuntimeError bei Checksum-Drift")


def test_dry_run_does_not_write(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        _write_migration(d, "001_x.sql", "SELECT 1;")
        monkeypatch.setattr(runner, "MIG_DIR", d)
        monkeypatch.setenv("MIGRATIONS_DRY_RUN", "1")
        conn = _FakeConn([])  # noch nichts angewendet
        asyncio.run(runner.apply_migrations(conn))

        # Nur die CREATE TABLE + ALTER TABLE / SELECT-Vorbereitung -- kein
        # INSERT in schema_migrations.
        inserts = [s for (s, _) in conn.executed if "INSERT INTO schema_migrations" in s]
        assert inserts == [], f"DRY_RUN sollte NICHTS inserten, war: {inserts}"


def test_legacy_row_without_checksum_gets_backfilled(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        _write_migration(d, "001_x.sql", "SELECT 1;")
        monkeypatch.setattr(runner, "MIG_DIR", d)
        monkeypatch.delenv("MIGRATIONS_DRY_RUN", raising=False)
        # Existierender Eintrag ohne Checksum (Alt-Zeile)
        applied = [{"version": "001_x", "checksum": None}]
        conn = _FakeConn(applied)
        asyncio.run(runner.apply_migrations(conn))

        # UPDATE ... SET checksum=... sollte aufgetaucht sein
        updates = [s for (s, _) in conn.executed
                   if "UPDATE schema_migrations" in s and "checksum" in s]
        assert len(updates) == 1, (
            f"Alt-Zeile ohne checksum sollte einmal nachgezogen werden, "
            f"war: {updates}"
        )
