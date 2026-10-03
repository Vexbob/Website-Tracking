"""Sparziel aufgeben (v2.35.0): das Geld bleibt und zieht in den Puffer.

Loeschen nimmt das Angesparte mit, Abschliessen macht eine Trophaee daraus.
Fuer „doch keine Lust mehr auf das Ding“ gibt es seitdem einen dritten Weg.
Geprueft wird, was in der Datenbank passiert -- ohne Postgres, mit einer
Attrappe, die die Abfragen mitschreibt und den Kontostand nachrechnet.
"""
import asyncio
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

import main                                    # noqa: E402
from schemas import SavGoalGiveUp              # noqa: E402

NUTZER = {"id": 1}
PUFFER, ZIEL = 10, 20
AUFGEBEN = main.give_up_sg.__wrapped__


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeDB:
    """Haelt Buchungen und Ziele im Speicher und fuehrt die Abfragen aus,
    die das Aufgeben schickt."""

    def __init__(self, buchungen, ziel_general=False):
        self.ziele = {PUFFER: {"id": PUFFER, "name": "Allgemein", "is_general": True},
                      ZIEL: {"id": ZIEL, "name": "Rennrad", "is_general": ziel_general}}
        self.buchungen = [dict(b) for b in buchungen]

    def transaction(self):
        return _Tx()

    def summe(self, ziel):
        return round(sum(b["amount"] for b in self.buchungen if b["goal"] == ziel), 2)

    async def fetchrow(self, sql, *args):
        if "FROM savings_goals WHERE id=$1" in sql:
            return self.ziele.get(args[0])
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        if "is_general=TRUE" in sql:
            return PUFFER
        if "SUM(amount)" in sql:
            return self.summe(args[1])
        raise AssertionError(sql)

    async def fetch(self, sql, *args):
        if "source_type='transfer'" in sql and "SELECT source_id" in sql:
            return [{"source_id": b["source_id"]} for b in self.buchungen
                    if b["goal"] == args[1] and b["type"] == "transfer" and b["source_id"]]
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if sql.startswith("DELETE FROM savings_transactions"):
            paare = set(args[1])
            self.buchungen = [b for b in self.buchungen
                              if not (b["type"] == "transfer" and b["source_id"] in paare)]
        elif sql.startswith("UPDATE savings_transactions SET savings_goal_id"):
            for b in self.buchungen:
                if b["goal"] == args[2]:
                    b["goal"] = args[0]
        elif sql.startswith("INSERT INTO savings_transactions"):
            self.buchungen.append({"id": 999, "amount": 0, "type": "aufgegeben",
                                   "source_id": None, "goal": args[3],
                                   "desc": args[1], "note": args[2]})
        elif sql.startswith("DELETE FROM savings_goals"):
            self.ziele.pop(args[0], None)
        else:
            raise AssertionError(sql)
        return "OK"


def _b(id_, betrag, ziel, art="achievement", source_id=None):
    return {"id": id_, "amount": betrag, "goal": ziel, "type": art, "source_id": source_id}


def _bestand():
    """Puffer 200 €, davon 100 € aufs Rennrad uebertragen; dazu 1.365,50 €
    eigene Belohnungen auf dem Rennrad. Rennrad gesamt: 1.465,50 €."""
    return [
        _b(1, 200.0, PUFFER, "initial"),
        _b(2, -100.0, PUFFER, "transfer", source_id=2),
        _b(3, 100.0, ZIEL, "transfer", source_id=2),
        _b(4, 1000.0, ZIEL),
        _b(5, 365.5, ZIEL, "progress"),
    ]


def test_das_geld_landet_im_puffer_und_das_ziel_ist_weg():
    db = FakeDB(_bestand())
    puffer_vorher = db.summe(PUFFER)
    antwort = _run(AUFGEBEN(None, ZIEL, SavGoalGiveUp(note="  doch lieber Gravel  "),
                            db=db, user=NUTZER))
    assert antwort["moved"] == pytest.approx(1465.5)
    assert db.summe(PUFFER) == pytest.approx(puffer_vorher + 1465.5)
    assert ZIEL not in db.ziele
    assert not [b for b in db.buchungen if b["goal"] == ZIEL]


def test_der_uebertrag_aus_dem_puffer_hebt_sich_auf():
    """Beide Seiten des Paares fallen weg -- sie wuerden sich im Puffer nur
    gegenseitig aufheben und im Verlauf wie zwei Bewegungen aussehen."""
    db = FakeDB(_bestand())
    _run(AUFGEBEN(None, ZIEL, SavGoalGiveUp(), db=db, user=NUTZER))
    assert not [b for b in db.buchungen if b["type"] == "transfer"]
    # Die eigenen Buchungen bleiben -- umgezogen, nicht ersetzt.
    assert {b["id"] for b in db.buchungen} >= {1, 4, 5}


def test_der_vermerk_traegt_grund_und_betrag_aber_kein_geld():
    db = FakeDB(_bestand())
    _run(AUFGEBEN(None, ZIEL, SavGoalGiveUp(note="  doch lieber Gravel  "),
                  db=db, user=NUTZER))
    vermerk = next(b for b in db.buchungen if b["type"] == "aufgegeben")
    assert vermerk["amount"] == 0
    assert vermerk["note"] == "doch lieber Gravel"
    assert "1.465,50 €" in vermerk["desc"] and "Rennrad" in vermerk["desc"]
    assert vermerk["goal"] == PUFFER


def test_ohne_grund_bleibt_die_notiz_leer():
    db = FakeDB(_bestand())
    _run(AUFGEBEN(None, ZIEL, SavGoalGiveUp(note="   "), db=db, user=NUTZER))
    assert next(b for b in db.buchungen if b["type"] == "aufgegeben")["note"] is None


def test_den_puffer_selbst_kann_man_nicht_aufgeben():
    db = FakeDB(_bestand(), ziel_general=True)
    with pytest.raises(HTTPException) as fehler:
        _run(AUFGEBEN(None, ZIEL, SavGoalGiveUp(), db=db, user=NUTZER))
    assert fehler.value.status_code == 400


def test_ein_fremdes_ziel_gibt_es_nicht():
    db = FakeDB(_bestand())
    with pytest.raises(HTTPException) as fehler:
        _run(AUFGEBEN(None, 4711, SavGoalGiveUp(), db=db, user=NUTZER))
    assert fehler.value.status_code == 404
