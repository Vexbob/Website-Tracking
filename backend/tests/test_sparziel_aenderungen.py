"""Jede Aenderung am Sparziel kommt in den Verlauf (v2.36.0), Ideen tragen
eine fertige Vorlage, und die Zahl der Wochenziele laesst sich deckeln.

Geprueft wird ohne Datenbank: die Beschreibung einer Aenderung ist eine
reine Funktion ueber zwei Zeilen, die Vorlage eine Pruefung ueber ein dict.
"""
import asyncio
import json
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

import main                                         # noqa: E402
from services import sparziel_aenderungen as ae     # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ------------------------------------------------------- Was hat sich geaendert

def _wochenziel(**felder):
    basis = {"title": "Sport", "reward_amount": 5, "rhythm_type": "weekly",
             "target_count": 3, "streak_bonus_amount": 0, "streak_bonus_threshold": 0,
             "partial_count": 0, "partial_percent": 0, "reward_goal_id": None}
    basis.update(felder)
    return basis


def test_nur_was_sich_geaendert_hat_steht_da():
    was = ae.unterschiede("wochenziel", _wochenziel(),
                          _wochenziel(reward_amount=8, target_count=4))
    assert was == "Belohnung 5,00 € → 8,00 €; Ziel 3 → 4"


def test_speichern_ohne_aenderung_ergibt_nichts():
    """Sonst stuende nach jedem Oeffnen und Speichern eine leere Zeile im Verlauf."""
    assert ae.unterschiede("wochenziel", _wochenziel(), _wochenziel(reward_amount=5.0)) == ""


def test_rhythmus_und_link_werden_lesbar():
    assert ae.unterschiede("wochenziel", _wochenziel(), _wochenziel(rhythm_type="monthly")) \
        == "Rhythmus pro Woche → pro Monat"
    alt = {"name": "Rad", "target_amount": 900, "link": None}
    assert ae.unterschiede("sparziel", alt, dict(alt, link="https://x.de/rad")) == "Link gesetzt"
    assert ae.unterschiede("sparziel", dict(alt, link="https://x.de"), alt) == "Link entfernt"


def test_betraege_stehen_deutsch():
    assert ae.eur(1465.5) == "1.465,50 €"
    assert ae.zahl(2.5) == "2,5" and ae.zahl(3.0) == "3"


def test_eine_erfundene_aenderung_faellt_sofort_auf():
    class DB:
        async def execute(self, *a):
            raise AssertionError("darf nicht schreiben")
    with pytest.raises(ValueError):
        _run(ae.vermerken(DB(), 1, "verzaubert", "wochenziel", 1, "Sport"))


def test_das_ereignis_nennt_objekt_aktion_und_namen():
    from datetime import datetime
    e = ae.ereignis({"id": 1, "created_at": datetime(2026, 10, 5, 9, 0), "aktion": "geloescht",
                     "objekt": "achievement", "titel": "100 km", "details": "25,00 € entfernt"})
    assert e["title"] == "Achievement gelöscht"
    assert e["description"] == "„100 km“ · 25,00 € entfernt"
    assert e["amount"] == 0.0 and e["deletable"] is False


# ------------------------------------------------------------ Ideen als Vorlage

def test_eine_wochenziel_vorlage_wird_geprueft_und_gespeichert():
    roh = main._idee_vorlage("Lesen", "progress",
                             {"reward_amount": 3, "rhythm_type": "weekly", "target_count": 4})
    gespeichert = json.loads(roh)
    assert gespeichert["reward_amount"] == 3 and gespeichert["target_count"] == 4
    # Der Titel steht an der Idee, nicht doppelt in der Vorlage.
    assert "title" not in gespeichert


def test_eine_unvollstaendige_vorlage_wird_abgewiesen():
    """Eine Idee, die beim Aktivieren an einem Pflichtfeld scheitert, waere
    keine fertige Idee."""
    with pytest.raises(HTTPException):
        main._idee_vorlage("Lesen", "progress", {"rhythm_type": "weekly"})
    with pytest.raises(HTTPException):
        main._idee_vorlage("Lesen", "progress",
                           {"reward_amount": 3, "rhythm_type": "taeglich", "target_count": 4})
    with pytest.raises(HTTPException):
        main._idee_vorlage("100 km", "milestone",
                           {"reward_amount": 5, "unit": "km", "threshold_increment": 0})


def test_ohne_art_gibt_es_keine_vorlage():
    assert main._idee_vorlage("Sprachkurs", None, None) is None
    with pytest.raises(HTTPException):
        main._idee_vorlage("Sprachkurs", None, {"reward_amount": 3})


# ------------------------------------------------------------ Hoechstzahl

class _PrefDB:
    def __init__(self, grenze, anzahl):
        self.grenze, self.anzahl = grenze, anzahl

    async def fetchval(self, sql, *args):
        if "user_prefs" in sql:
            return None if self.grenze is None else json.dumps(self.grenze)
        if "COUNT(*) FROM progress_goals" in sql:
            return self.anzahl
        raise AssertionError(sql)


def test_ohne_einstellung_gibt_es_keine_grenze():
    _run(main._wochenziel_platz_pruefen(_PrefDB(None, 40), 1))
    _run(main._wochenziel_platz_pruefen(_PrefDB(0, 40), 1))


def test_die_grenze_greift_beim_naechsten_wochenziel():
    _run(main._wochenziel_platz_pruefen(_PrefDB(5, 4), 1))
    with pytest.raises(HTTPException) as fehler:
        _run(main._wochenziel_platz_pruefen(_PrefDB(5, 5), 1))
    assert "höchstens 5" in fehler.value.detail


# ------------------------------------------------------------ Links

def test_ein_link_bekommt_https_und_nur_http_ist_erlaubt():
    assert main._link_sauber("amazon.de/rad") == "https://amazon.de/rad"
    assert main._link_sauber("  ") is None
    with pytest.raises(HTTPException):
        main._link_sauber("javascript:alert(1)")
