"""Gesundheitswerte von Hand (v2.37.0): wohin ein Wert geht und was
abgewiesen wird."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from routers import health_manuell_router as hand             # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ------------------------------------------------------------- Handwerte

def test_eigene_schluessel():
    assert hand.eigen_id("eigen_12") == 12
    assert hand.eigen_id("weight") is None
    assert hand.eigen_id("eigen_x") is None


def test_ein_wert_aus_der_zukunft_wird_abgewiesen():
    morgen = datetime.now(timezone.utc) + timedelta(days=1)
    with pytest.raises(HTTPException):
        hand._zeit(morgen.isoformat(), morgen.date().isoformat())
    jetzt = datetime.now(timezone.utc) - timedelta(minutes=1)
    zp, tag = hand._zeit(jetzt.isoformat(), jetzt.date().isoformat())
    assert zp.tzinfo is not None


class _DB:
    def __init__(self, eigen_da=True):
        self.eigen_da = eigen_da
        self.geschrieben = []

    async def fetchval(self, sql, *a):
        return 1 if self.eigen_da else None

    async def execute(self, sql, *a):
        self.geschrieben.append((sql, a))
        return "INSERT 0 1"


def _eintragen(db, **felder):
    zp = datetime.now(timezone.utc) - timedelta(hours=1)
    b = hand.WertEingabe(zeitpunkt=zp.isoformat(), datum=zp.date().isoformat(), **felder)
    return _run(hand.wert_eintragen.__wrapped__(None, b, db=db, user={"id": 1}))


def test_jeder_wert_landet_in_seiner_tabelle_und_als_handwert():
    for felder, tabelle in [
        ({"metrik": "weight", "wert": 141.4}, "health_metric_samples"),
        ({"metrik": "blood_glucose", "wert": 96}, "health_blood_glucose"),
        ({"metrik": "blood_pressure", "systolisch": 128, "diastolisch": 82}, "health_blood_pressure"),
        ({"metrik": "eigen_3", "wert": 4}, "health_eigene_werte"),
    ]:
        db = _DB()
        _eintragen(db, **felder)
        sql = db.geschrieben[0][0]
        assert tabelle in sql
        if tabelle != "health_eigene_werte":
            # Ein Handwert ist als solcher erkennbar -- und nur er laesst
            # sich von Hand wieder loeschen.
            assert "'manual'" in sql


def test_unsinniger_blutdruck_und_unbekannte_groessen():
    with pytest.raises(HTTPException):
        _eintragen(_DB(), metrik="blood_pressure", systolisch=80, diastolisch=120)
    with pytest.raises(HTTPException):
        _eintragen(_DB(), metrik="bluthochdruck", wert=1)
    with pytest.raises(HTTPException):
        _eintragen(_DB(eigen_da=False), metrik="eigen_9", wert=1)
    with pytest.raises(HTTPException):
        _eintragen(_DB(), metrik="weight")              # Wert fehlt
