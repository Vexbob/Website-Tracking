"""Hoerdiagramm in Stunden (v2.44.0): der Verlauf nennt je Art die Hoerzeit
und wie viel der Wiedergaben ueberhaupt eine Zeit hat."""
import asyncio
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from routers import music_router as mr                          # noqa: E402

FILTER = {"date_from": None, "date_to": None, "q": None, "artist": None, "kind": None,
          "grain": None, "group_by": None, "min_plays": None}


class _DB:
    def __init__(self, punkte, je_art):
        self.punkte, self.je_art = punkte, je_art

    async def fetch(self, sql, *a):
        return self.je_art if "kind, SUM(plays)" in sql else self.punkte

    async def fetchrow(self, sql, *a):
        return {"von": date(2026, 9, 1), "bis": date(2026, 9, 30)}

    async def fetchval(self, sql, *a):
        return 30


def _verlauf(punkte, je_art):
    return asyncio.new_event_loop().run_until_complete(
        mr.series(step="woche", split="kind", f=FILTER, db=_DB(punkte, je_art), user={"id": 1}))


def _p(periode, plays, ms, ohne):
    return {"period": periode, "start": date(2026, 9, 7), "plays": plays, "ms": ms, "titles": 1,
            "artists": 1, "coarse": 0, "ohne_zeit": ohne}


def test_hoerzeit_je_art_und_abdeckung():
    out = _verlauf([_p("2026-KW37", 101, 23_400_000, 0)],
                   [{"period": "2026-KW37", "kind": "Musik", "plays": 100, "ms": 18_000_000},
                    {"period": "2026-KW37", "kind": "Podcast", "plays": 1, "ms": 5_400_000}])
    assert out["zeit_abdeckung"] == 1.0
    je = {s["kind"]: s for s in out["series"]}
    # Eine Folge von 1,5 h wiegt in Stunden, nicht als eine Wiedergabe.
    assert je["Podcast"]["ms_values"] == [5_400_000] and je["Podcast"]["values"] == [1]
    assert je["Musik"]["ms"] == 18_000_000


def test_ohne_minuten_bleibt_es_bei_wiedergaben():
    out = _verlauf([_p("2026-KW37", 200, None, 200)],
                   [{"period": "2026-KW37", "kind": "Musik", "plays": 200, "ms": None}])
    assert out["zeit_abdeckung"] == 0.0
