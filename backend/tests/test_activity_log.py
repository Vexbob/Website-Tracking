"""Tests fuer das Aktivitaets-Log und seine Kopfzahlen (v2.11.8).

Das Log zeigt die neuesten Eintraege -- 500 davon. Die Zeile darueber nennt
Anzahl und Summe. Bis v2.11.8 rechnete sie im Browser ueber die geladenen
Zeilen und war damit ab dem 501. Ereignis zu klein, ohne es zu sagen.

Seitdem holen Liste und Auskunft ihre Ereignisse aus derselben Funktion
`_aktivitaets_ereignisse`; nur die Liste schneidet ab. Diese Tests halten
beides fest: dass die Auskunft das Ganze zaehlt, und dass sie es nicht
selbst nachrechnet -- die Regel, wann ein Check-in Geld ausloest, darf nur
an einer Stelle stehen.
"""
import asyncio
import inspect
import os
import sys
from datetime import date, datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

import main


NUTZER = {"id": 1}


def _run(coro):
    """Das Projekt nutzt kein pytest-asyncio -- wie in test_health_workouts."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _zeit(tag):
    return datetime(2026, 3, tag, 12, 0, 0)


class FakeDB:
    """Beantwortet die sechs Abfragen des Logs aus dem Speicher.

    Zugeordnet wird ueber ein Stueck des jeweiligen SQL -- mehr braucht es
    nicht, denn jede der sechs Quellen hat ihre eigene Tabelle.
    """

    def __init__(self, checkins=(), meilensteine=(), start=()):
        self.checkins = list(checkins)
        self.meilensteine = list(meilensteine)
        self.start = list(start)

    async def fetch(self, sql, *args):
        if "progress_logs pl JOIN progress_goals" in sql:
            return self.checkins
        if "achievement_logs al JOIN achievements" in sql:
            return self.meilensteine
        if "achievement_progress_logs pr" in sql:
            return []
        if "source_type='initial'" in sql:
            return self.start
        if "source_type='transfer'" in sql:
            return []
        if "source_type='progress'" in sql:
            return []
        raise AssertionError("unerwartete Abfrage: " + sql[:80])


def _checkin(tag, stand, ziel=3, lohn=10.0):
    return {"id": tag, "progress_goal_id": 1, "log_date": date(2026, 3, tag),
            "week_key": "2026-W11", "month_key": "2026-03",
            "created_at": _zeit(tag), "note": "", "title": "Sport",
            "reward_amount": lohn, "rhythm_type": "weekly",
            "target_count": ziel, "stand": stand}


def _meilenstein(tag, lohn):
    return {"id": 100 + tag, "achievement_id": 5, "achieved_value": 42.0,
            "reward_amount": lohn, "date_achieved": date(2026, 3, tag),
            "note": "", "title": "100 km", "unit": "km"}


# ===================================== Die Auskunft meint das Ganze, die Liste
#                                       nur den Ausschnitt

def test_die_liste_kuerzt_und_die_auskunft_nicht():
    """Der Kern des Fehlers: fuenf Ereignisse, drei davon sichtbar.

    Frueher zeigte die Zeile darueber „3 Eintraege“ und eine Summe, in der
    zwei Betraege fehlten.
    """
    db = FakeDB(checkins=[_checkin(1, 1), _checkin(2, 2), _checkin(3, 3)],
                meilensteine=[_meilenstein(4, 25.0), _meilenstein(5, 15.0)])

    liste = _run(main.activity_log(limit=3, db=db, user=NUTZER))
    assert len(liste) == 3

    auskunft = _run(main.activity_log_summary(db=db, user=NUTZER))
    assert auskunft["all"]["count"] == 5
    # Nur der dritte Check-in erfuellt das Ziel (Stand 3 von 3) -- 10 EUR,
    # dazu die beiden Meilensteine.
    assert auskunft["all"]["amount"] == pytest.approx(50.0)


def test_die_auskunft_trennt_nach_art():
    """Die Chips ueber dem Log filtern nach Art -- jede braucht ihre Zahl."""
    db = FakeDB(checkins=[_checkin(1, 1), _checkin(2, 2), _checkin(3, 3)],
                meilensteine=[_meilenstein(4, 25.0)])
    auskunft = _run(main.activity_log_summary(db=db, user=NUTZER))
    assert auskunft["by_type"]["checkin"]["count"] == 3
    assert auskunft["by_type"]["checkin"]["amount"] == pytest.approx(10.0)
    assert auskunft["by_type"]["milestone"]["count"] == 1
    assert auskunft["by_type"]["milestone"]["amount"] == pytest.approx(25.0)


def test_ein_leeres_log_meldet_null_statt_nichts():
    auskunft = _run(main.activity_log_summary(db=FakeDB(), user=NUTZER))
    assert auskunft["all"] == {"count": 0, "amount": 0}
    assert auskunft["by_type"] == {}


def test_die_summe_je_art_ergibt_die_gesamtsumme():
    db = FakeDB(checkins=[_checkin(1, 3, ziel=3, lohn=7.5)],
                meilensteine=[_meilenstein(2, 12.25)],
                start=[{"id": 1, "created_at": _zeit(1), "description": "",
                        "amount": 100.0, "note": ""}])
    a = _run(main.activity_log_summary(db=db, user=NUTZER))
    einzeln = sum(v["amount"] for v in a["by_type"].values())
    assert einzeln == pytest.approx(a["all"]["amount"])
    assert sum(v["count"] for v in a["by_type"].values()) == a["all"]["count"]


# ============================================== Eine Quelle, eine Auszahlregel

def test_liste_und_auskunft_teilen_ihre_quelle():
    for fn in (main.activity_log, main.activity_log_summary):
        quelle = inspect.getsource(fn)
        assert "_aktivitaets_ereignisse(" in quelle, fn.__name__


def test_die_auskunft_kennt_keine_obergrenze():
    """Sonst zaehlte sie wieder nur einen Ausschnitt."""
    assert "limit" not in inspect.signature(main.activity_log_summary).parameters


def test_der_stand_kommt_aus_einer_abfrage_statt_aus_einer_je_zeile():
    """Ohne Obergrenze waere eine Abfrage je Check-in nicht bezahlbar.

    Der Stand innerhalb der Periode kommt deshalb aus einer Fensterfunktion.
    Faellt jemand auf die Schleife zurueck, laedt das Log bei langer Nutzung
    minutenlang -- das faellt erst spaet auf, deshalb steht es hier.
    """
    quelle = inspect.getsource(main._aktivitaets_ereignisse)
    assert "COUNT(*) OVER" in quelle
    assert "fetchval" not in quelle


def test_die_obergrenze_der_liste_bleibt_gedeckelt():
    """`limit` kommt aus der URL -- eine unbegrenzte Antwort waere von aussen
    ausloesbar."""
    db = FakeDB(checkins=[_checkin(t, 1) for t in range(1, 6)])
    assert len(_run(main.activity_log(limit=99999, db=db, user=NUTZER))) == 5
    assert len(_run(main.activity_log(limit=0, db=db, user=NUTZER))) == 1
