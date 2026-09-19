"""Waechter fuer die Meilenstein-Quellen (v2.9.0).

Die Automatik holt den Stand einer Kachel aus einem anderen Modul. Gebucht
wird dabei nichts -- gebucht wird erst, wenn jemand bestaetigt. Die Tests hier
sichern die drei Zusagen, die das tragen:

1. Der Katalog beschreibt sich selbst vollstaendig genug, dass der Dialog sich
   daraus bauen kann. Eine Quelle, die ein Feld ohne Beschriftung oder eine
   Bedingung auf ein Feld mitbringt, das es nicht gibt, faellt hier auf und
   nicht erst im Browser, wo sie einfach als leeres Auswahlfeld dasteht.
2. Eine unbekannte Quelle liefert keinen Wert, statt zu knallen. Die
   Sparziel-Seite haengt an einer Antwort; eine Quelle, die eine alte
   Einstellung mitschleppt, darf die anderen Kacheln nicht mitnehmen.
3. Und der eigentliche Punkt: ``_milestones_at`` zusammen mit
   ``credited_milestones`` zahlt eine Schwelle nur EINMAL -- auch wenn der
   Wert aus einer Quelle kommt, die hoch und runter geht. Das ist der Fall,
   den der Nutzer beschrieben hat: von 143 auf 146 kg und wieder zurueck.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from helpers import _milestones_at                      # noqa: E402
from services import achievement_sources as quellen     # noqa: E402


def test_jede_quelle_ist_vollstaendig_beschrieben():
    """Der Dialog zeichnet nur, was im Register steht -- also muss es stehen."""
    assert quellen.QUELLEN, "Ohne Quellen gibt es nichts zu automatisieren."
    for key, q in quellen.QUELLEN.items():
        assert q.get("label"), f"{key} hat keine Beschriftung"
        assert q.get("modul"), f"{key} sagt nicht, zu welchem Modul es gehoert"
        assert callable(q.get("lesen")), f"{key} hat keine Lesefunktion"
        schluessel = {p["key"] for p in q["params"]}
        for p in q["params"]:
            assert p.get("label"), f"{key}.{p['key']} hat keine Beschriftung"
            assert p.get("typ") == "auswahl", f"{key}.{p['key']}: nur Auswahlfelder"
            # Ein Pflichtfeld ohne Optionen waere ein Dialog, in dem man nichts
            # waehlen kann; die Optionen duerfen aber aus dem Bestand kommen
            # (leere Liste im Register, gefuellt von ``katalog``).
            assert "optionen" in p, f"{key}.{p['key']} hat keine Optionsliste"
            for bedingung in (p.get("wenn") or {}):
                assert bedingung in schluessel, (
                    f"{key}.{p['key']} haengt an '{bedingung}', das es nicht gibt")


def test_unbekannte_quelle_liefert_nichts_statt_zu_knallen():
    async def lauf():
        assert await quellen.wert_lesen(None, 1, None, {}) is None
        assert await quellen.wert_lesen(None, 1, "", {}) is None
        assert await quellen.wert_lesen(None, 1, "gibt.es.nicht", {}) is None
    asyncio.run(lauf())


def test_params_lesen_vertraegt_muell():
    assert quellen.params_lesen(None) == {}
    assert quellen.params_lesen("") == {}
    assert quellen.params_lesen("kein json") == {}
    assert quellen.params_lesen("[1,2]") == {}
    assert quellen.params_lesen('{"metrik":"weight"}') == {"metrik": "weight"}
    assert quellen.params_lesen({"metrik": "weight"}) == {"metrik": "weight"}


def test_zuruecknehmen_zahlt_nicht_zweimal():
    """Der Fall aus der Anfrage: 145 -> 139 -> 146 -> 139.

    ``credited_milestones`` geht nie zurueck, also ist die Zahl der faelligen
    Meilensteine nach dem Wiederabstieg null. Genau darauf rechnet
    ``auto-status``, und genau danach bucht ``_wert_setzen``.
    """
    start, schwelle = 145.0, 5.0
    gebucht = 0

    # Erster Abstieg unter 140: ein Meilenstein.
    erreicht = _milestones_at(start, 139.0, schwelle, "decrease")
    assert erreicht - gebucht == 1
    gebucht = max(gebucht, erreicht)

    # Wieder rauf auf 146 -- nichts faellig, und nichts wird zurueckgenommen.
    erreicht = _milestones_at(start, 146.0, schwelle, "decrease")
    assert max(0, erreicht - gebucht) == 0
    assert gebucht == 1

    # Und wieder runter auf 139: dieselbe Schwelle, kein zweites Geld.
    erreicht = _milestones_at(start, 139.0, schwelle, "decrease")
    assert max(0, erreicht - gebucht) == 0

    # Erst die naechste Schwelle (unter 135) zahlt wieder.
    erreicht = _milestones_at(start, 134.5, schwelle, "decrease")
    assert erreicht - gebucht == 1


def test_mehrere_schwellen_auf_einmal_werden_alle_gezaehlt():
    """Wer laenger nicht bestaetigt hat, bekommt nicht weniger.

    Die Quelle laeuft weiter, auch wenn niemand hinsieht. Faellt das Gewicht
    von 145 auf 134, sind das zwei Meilensteine (unter 140, unter 135) -- und
    ``auto-status`` muss beide ankuendigen, sonst verspricht die Kachel
    weniger, als beim Bestaetigen fliesst.
    """
    assert _milestones_at(145.0, 134.0, 5.0, "decrease") == 2
    assert _milestones_at(1500.0, 1624.0, 50.0, "increase") == 2
