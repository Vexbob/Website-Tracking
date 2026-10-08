"""Erinnerungen auf der Startseite: was als Einstellung gilt (v2.42.0).

Wann eine faellig ist, rechnet js/erinnerungen.js; hier steht die Pruefung
des Servers -- eine kaputte Liste darf gar nicht erst gespeichert werden."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from routers import ui_router as ui                             # noqa: E402

GUT = {"id": "depot", "text": "Depot: Kontoauszug importieren", "href": "/depot/",
       "rhythmus": "quartal", "tag": 14, "monat": 3, "erledigt": "2026-09-14"}


def test_eine_gueltige_liste():
    assert ui._check_erinnerungen([GUT]) == [GUT]
    # Ohne Modul geht es auch; der Monat faellt dann auf 1.
    ohne = ui._check_erinnerungen([{"id": "a", "text": "Etwas", "rhythmus": "monat", "tag": 1}])
    assert ohne[0]["href"] == "" and ohne[0]["monat"] == 1 and ohne[0]["erledigt"] is None


@pytest.mark.parametrize("aenderung", [
    {"tag": 31}, {"tag": 0}, {"rhythmus": "woche"}, {"monat": 4},          # Quartal hat drei Monate
    {"href": "/gibtsnicht/"}, {"text": ""}, {"text": "x" * 81}, {"id": "Gross"},
    {"erledigt": "gestern"}])
def test_was_abgelehnt_wird(aenderung):
    with pytest.raises(ValueError):
        ui._check_erinnerungen([dict(GUT, **aenderung)])


def test_jede_kennung_nur_einmal_und_hoechstens_zwoelf():
    with pytest.raises(ValueError):
        ui._check_erinnerungen([GUT, GUT])
    with pytest.raises(ValueError):
        ui._check_erinnerungen([dict(GUT, id=f"e{i}") for i in range(13)])
    assert ui.ERINNERUNGEN_PREF in ui.UI_PREFS
