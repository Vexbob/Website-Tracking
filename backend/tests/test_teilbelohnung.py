"""Tests fuer die Teilbelohnung der Wochenziele (v2.16.0).

„Ab 5 von 7 Check-ins gibt es am Ende der Woche 50 % der Belohnung.“ Vier
Dinge muessen dabei halten:

- abgerechnet wird erst, wenn die Periode vorbei ist -- am Mittwoch bei 5/7
  ist noch offen, ob es 7/7 werden;
- wer das Ziel erreicht, bekommt die volle Belohnung und KEINE Teilbelohnung
  dazu -- auch wenn der fehlende Check-in erst nachgetragen wird;
- faellt der Stand unter die Schwelle, geht die Buchung wieder weg;
- das Einschalten zahlt keine alten Wochen nach.
"""
import asyncio
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from fastapi import HTTPException  # noqa: E402

import main  # noqa: E402
from database import period_key  # noqa: E402

HEUTE = date.today()
DIESE_WOCHE = period_key("weekly", HEUTE)
LETZTE_WOCHE = period_key("weekly", HEUTE - timedelta(days=7))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _ziel(**felder):
    basis = {"id": 4, "title": "Sport", "reward_amount": 10, "target_count": 7,
             "rhythm_type": "weekly", "reward_goal_id": None,
             "partial_count": 5, "partial_percent": 50,
             "partial_since": HEUTE - timedelta(days=30)}
    basis.update(felder)
    return basis


class Buchungen:
    """Haelt die Teilbelohnungs-Buchungen wie ``savings_transactions``."""

    def __init__(self):
        self.zeilen = {}          # period_key -> Betrag

    async def fetchval(self, sql, *args):
        if "savings_goals" in sql or "general" in sql.lower():
            return 1
        return 1 if args[-1] in self.zeilen else 0

    async def fetchrow(self, sql, *args):
        return {"id": 1}

    async def execute(self, sql, *args):
        if sql.startswith("DELETE"):
            self.zeilen.pop(args[-1], None)
        elif sql.startswith("INSERT"):
            self.zeilen[args[5]] = args[1]


@pytest.fixture(autouse=True)
def _kein_zielrouting(monkeypatch):
    async def ziel(*a, **k):
        return 1
    monkeypatch.setattr(main, "_reward_goal_for", ziel)


def test_die_regel_rechnet_den_anteil_der_belohnung():
    n, betrag, _ = main._teil_regel(_ziel())
    assert (n, betrag) == (5, 5.0)


@pytest.mark.parametrize("felder", [
    {"partial_count": 0}, {"partial_percent": 0}, {"partial_count": 7},
    {"partial_since": None}, {"reward_amount": 0},
])
def test_ohne_vollstaendige_regel_gibt_es_keine(felder):
    assert main._teil_regel(_ziel(**felder)) is None


def test_die_schwelle_muss_vor_dem_ziel_liegen():
    with pytest.raises(HTTPException):
        main._teil_pruefen(7, 50, 7)
    with pytest.raises(HTTPException):
        main._teil_pruefen(3, 120, 7)
    main._teil_pruefen(0, 0, 7)          # aus ist erlaubt
    main._teil_pruefen(5, 50, 7)


def test_eine_vergangene_woche_ueber_der_schwelle_wird_bezahlt():
    db = Buchungen()
    _run(main._teil_abrechnen(db, 1, _ziel(), LETZTE_WOCHE, 5))
    assert db.zeilen == {LETZTE_WOCHE + "-teil": 5.0}


def test_die_laufende_woche_wird_noch_nicht_abgerechnet():
    db = Buchungen()
    _run(main._teil_abrechnen(db, 1, _ziel(), DIESE_WOCHE, 6))
    assert db.zeilen == {}


def test_wer_das_ziel_erreicht_bekommt_keine_teilbelohnung_dazu():
    """Ein nachgetragener Check-in macht die Woche voll: die Teilbelohnung
    weicht, die volle Belohnung haengt an ihrem eigenen Schluessel."""
    db = Buchungen()
    _run(main._teil_abrechnen(db, 1, _ziel(), LETZTE_WOCHE, 6))
    assert db.zeilen
    _run(main._teil_abrechnen(db, 1, _ziel(), LETZTE_WOCHE, 7))
    assert db.zeilen == {}


def test_unter_der_schwelle_geht_die_buchung_wieder_weg():
    db = Buchungen()
    _run(main._teil_abrechnen(db, 1, _ziel(), LETZTE_WOCHE, 5))
    _run(main._teil_abrechnen(db, 1, _ziel(), LETZTE_WOCHE, 4))
    assert db.zeilen == {}


def test_zweimal_abrechnen_bucht_einmal():
    db = Buchungen()
    _run(main._teil_abrechnen(db, 1, _ziel(), LETZTE_WOCHE, 5))
    _run(main._teil_abrechnen(db, 1, _ziel(), LETZTE_WOCHE, 6))
    assert len(db.zeilen) == 1


def test_das_einschalten_zahlt_keine_alten_wochen_nach():
    db = Buchungen()
    _run(main._teil_abrechnen(db, 1, _ziel(partial_since=HEUTE), LETZTE_WOCHE, 6))
    assert db.zeilen == {}


def test_die_teilbelohnung_steht_im_log_und_nicht_als_streak_im_export():
    import inspect
    import helpers
    assert "-teil" in inspect.getsource(main._aktivitaets_ereignisse)
    assert '"teilbelohnung"' in inspect.getsource(helpers._sparziel_protocol_lines)
