"""Backup zurueckspielen: Tabellen ohne ``id`` (v2.42.0).

user_prefs, depot_stueck und food_diary_ausgeblendet tragen einen
zusammengesetzten Schluessel. Bis v2.41.0 fragte die Wiederherstellung dort
nach ``id``: ohne Leeren brach sie ab, mit Leeren fiel jede Zeile still durch.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from services import backup                                     # noqa: E402

SPALTEN = {
    "user_prefs": {"user_id", "key", "value", "updated_at"},
    "food_diary_ausgeblendet": {"user_id", "schluessel", "ausgeblendet_at"},
    "notes": {"id", "user_id", "title", "content"},
}


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Conn:
    def __init__(self):
        self.sql = []

    def transaction(self):
        return _Tx()

    async def fetch(self, sql, *a):
        self.sql.append(sql)
        if "SELECT id FROM" in sql and any(t in sql for t in ("user_prefs", "food_diary_ausgeblendet")):
            raise RuntimeError('column "id" does not exist')
        return []

    async def execute(self, sql, *a):
        self.sql.append(sql)
        if "ON CONFLICT (id)" in sql and any(t in sql for t in ("user_prefs", "food_diary_ausgeblendet")):
            raise RuntimeError("there is no unique constraint matching the ON CONFLICT specification")
        return "INSERT 0 1"


def _spielen(monkeypatch, wipe):
    async def tabelle(conn, t):
        return t in SPALTEN

    async def spalte(conn, t, c):
        return c in SPALTEN.get(t, set())

    async def spalten(conn, t):
        return SPALTEN.get(t, set())

    monkeypatch.setattr(backup, "_table_exists", tabelle)
    monkeypatch.setattr(backup, "_column_exists", spalte)
    monkeypatch.setattr(backup, "_table_columns", spalten)
    conn = _Conn()
    daten = {"data": {
        "user_prefs": [{"user_id": 99, "key": "ui_erinnerungen", "value": "[]"}],
        "food_diary_ausgeblendet": [{"user_id": 99, "schluessel": "kaffe"}],
        "notes": [{"id": 5, "user_id": 99, "title": "a", "content": "b"}],
    }}
    stats = asyncio.new_event_loop().run_until_complete(
        backup.restore_snapshot(conn, daten, user_id=1, wipe=wipe))
    return conn, stats


def test_tabellen_ohne_id_kommen_zurueck(monkeypatch):
    for wipe in (False, True):
        conn, stats = _spielen(monkeypatch, wipe)
        assert stats["restored"]["user_prefs"] == 1
        assert stats["restored"]["food_diary_ausgeblendet"] == 1
        assert stats["restored"]["notes"] == 1
        # Mit id die bisherige Regel, ohne id die des eigenen Schluessels.
        assert any("INSERT INTO notes" in s and "ON CONFLICT (id)" in s for s in conn.sql)
        assert any("INSERT INTO user_prefs" in s and "ON CONFLICT DO NOTHING" in s for s in conn.sql)
