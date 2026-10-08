"""Sparziel: Haken „gekauft“ an einer Trophaee (v2.43.0)."""
import asyncio
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from fastapi import HTTPException                               # noqa: E402

import main                                                    # noqa: E402
from schemas import TrophaeGekauft                             # noqa: E402

GEKAUFT = main.trophae_gekauft.__wrapped__


class _DB:
    def __init__(self, gefunden=True):
        self.gefunden, self.update, self.log = gefunden, None, []

    async def fetchrow(self, sql, *a):
        assert "UPDATE completed_goals SET gekauft_am=$3 WHERE id=$1 AND user_id=$2" in sql
        self.update = a
        return {"id": a[0], "name": "Rennrad", "gekauft_am": a[2]} if self.gefunden else None

    async def execute(self, sql, *a):
        self.log.append(a)


def _rufen(db, **b):
    return asyncio.new_event_loop().run_until_complete(
        GEKAUFT(request=None, tid=3, b=TrophaeGekauft(**b), db=db, user={"id": 1}))


def test_gekauft_setzen_und_wegnehmen():
    db = _DB()
    _rufen(db, gekauft=True, datum="2026-10-08")
    assert db.update == (3, 1, date(2026, 10, 8))
    assert "gekauft am 08.10.2026" in db.log[0]
    db = _DB()
    _rufen(db, gekauft=False)
    assert db.update == (3, 1, None) and "zurückgenommen" in db.log[0][-1]


def test_kein_datum_in_der_zukunft_und_keine_fremde_trophaee():
    with pytest.raises(HTTPException):
        _rufen(_DB(), gekauft=True, datum=(date.today() + timedelta(days=5)).isoformat())
    with pytest.raises(HTTPException):
        _rufen(_DB(), gekauft=True, datum="morgen")
    with pytest.raises(HTTPException) as e:
        _rufen(_DB(gefunden=False), gekauft=True)
    assert e.value.status_code == 404
