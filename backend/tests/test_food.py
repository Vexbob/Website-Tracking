"""Tests fuer die Umrechnung von Open Food Facts (v1.85.0).

Ohne Netz. Der Fokus liegt auf dem, was bei dieser Quelle wirklich weh tut:
fehlende Angaben. Sie sind haeufig -- und eine 0 statt "keine Angabe" waere
eine Zahl, die in jeder Tagessumme mitlaeuft, ohne zu stimmen.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services import openfoodfacts as off  # noqa: E402


NUTELLA = {
    "status": 1,
    "product": {
        "code": "3017620422003",
        "product_name": "Nutella",
        "brands": "Nutella, Ferrero",
        "quantity": "400 g e",
        "nutriments": {
            "energy-kcal_100g": 539, "proteins_100g": 6.3,
            "carbohydrates_100g": 57.5, "sugars_100g": 56.3,
            "fat_100g": 30.9, "saturated-fat_100g": 10.6,
            "fiber_100g": 0, "salt_100g": 0.107,
        },
    },
}

OHNE_BALLASTSTOFFE = {
    "status": 1,
    "product": {
        "code": "4311501668436",
        "product_name": "Haferbar",
        "product_name_de": "Haferriegel Schoko",
        "brands": "Edeka",
        "serving_size": "60 g",
        "nutriments": {
            "energy-kcal_100g": "442", "proteins_100g": 10,
            "carbohydrates_100g": 49, "fat_100g": 21,
            "fiber_100g": None, "salt_100g": "",
        },
    },
}


def test_naehrwerte_werden_uebernommen(monkeypatch):
    monkeypatch.setattr(off, "_hole", lambda url: NUTELLA)
    p = off.hole_produkt("3017620422003")

    assert p["name"] == "Nutella"
    assert p["brand"] == "Nutella"          # nur die erste Marke
    assert p["kcal"] == 539 and p["protein_g"] == 6.3
    # Eine echte 0 bleibt 0 und wird nicht zu "fehlt".
    assert p["fiber_g"] == 0
    assert "fiber_g" not in p["missing"]
    assert p["usable"] is True
    assert p["source"] == "off"


def test_fehlende_angaben_bleiben_none(monkeypatch):
    monkeypatch.setattr(off, "_hole", lambda url: OHNE_BALLASTSTOFFE)
    p = off.hole_produkt("4311501668436")

    # Der deutsche Name hat Vorrang.
    assert p["name"] == "Haferriegel Schoko"
    # Zahl als Zeichenkette ist trotzdem eine Zahl.
    assert p["kcal"] == 442
    # Fehlend heisst None und steht in ``missing`` -- nicht 0.
    assert p["fiber_g"] is None and "fiber_g" in p["missing"]
    assert p["salt_g"] is None and "salt_g" in p["missing"]
    assert p["sugar_g"] is None
    # Die Portion wird aus "60 g" gezogen.
    assert p["portion_g"] == 60


def test_unbekannter_code_sagt_was_zu_tun_ist(monkeypatch):
    monkeypatch.setattr(off, "_hole", lambda url: {"status": 0})
    try:
        off.hole_produkt("0000000000000")
    except off.QuellenFehler as e:
        assert "von Hand anlegen" in str(e)
    else:
        raise AssertionError("hätte auffallen müssen")


def test_kein_strichcode_faellt_sofort_auf():
    try:
        off.hole_produkt("keine-ziffern")
    except off.QuellenFehler as e:
        assert "Strichcode" in str(e)
    else:
        raise AssertionError("hätte auffallen müssen")


def test_suche_laesst_unbrauchbare_treffer_weg(monkeypatch):
    monkeypatch.setattr(off, "_hole", lambda url: {"products": [
        NUTELLA["product"],
        {"code": "1", "product_name": "", "nutriments": {}},          # kein Name
        {"code": "2", "product_name": "Irgendwas", "nutriments": {}},  # keine kcal
    ]})
    treffer = off.suche("nutella")
    assert len(treffer) == 1 and treffer[0]["name"] == "Nutella"


def test_zu_kurze_suche_fragt_gar_nicht_erst(monkeypatch):
    def _nie(url):
        raise AssertionError("es haette gar nicht gefragt werden duerfen")
    monkeypatch.setattr(off, "_hole", _nie)
    assert off.suche("a") == []
