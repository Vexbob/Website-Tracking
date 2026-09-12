"""Tests fuer die Spannen-Rechnung des Ernaehrungs-Moduls (v1.87.0).

Der springende Punkt: aus einer Grobstufe darf nie eine einzelne Zahl
werden, und eine fehlende Angabe darf nie als 0 in einer Summe landen.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services import food_calc as calc  # noqa: E402


# Je 100 g. Der Wrap ohne Ballaststoff-Angabe ist der Fall, der weh tut.
TORTILLA = {"kcal": 300, "protein_g": 8, "fiber_g": None, "carbs_g": 50, "fat_g": 7}
HAEHNCHEN = {"kcal": 110, "protein_g": 23, "fiber_g": 0, "carbs_g": 0, "fat_g": 2}


def test_gericht_rechnet_zutaten_auf_die_portion():
    summe = calc.zutaten_summe([(60, TORTILLA), (100, HAEHNCHEN)])
    # 60 g Tortilla = 180 kcal, 100 g Haehnchen = 110 kcal
    assert summe["kcal"] == 290
    assert summe["protein_g"] == round(8 * 0.6 + 23, 1)
    assert summe["grams"] == 160
    # Eine fehlende Angabe macht die Summe unvollstaendig -- nicht kleiner.
    assert summe["fiber_g"] is None
    assert summe["incomplete"] == ["fiber_g"]


def test_stufe_wird_zur_spanne():
    basis = {"kcal": 500, "protein_g": 30, "fiber_g": None,
             "carbs_g": 50, "fat_g": 20}
    normal = calc.eintrag_spanne(basis, "normal")
    viel = calc.eintrag_spanne(basis, "viel")

    assert normal["kcal"] == (425.0, 575.0)        # 0,85 bis 1,15
    assert viel["kcal"] == (700.0, 1000.0)         # 1,4 bis 2,0
    # "Uebermaessig" ist unschaerfer als "normal" -- die Spanne ist breiter.
    assert (viel["kcal"][1] - viel["kcal"][0]) > (normal["kcal"][1] - normal["kcal"][0])
    # Fehlend bleibt fehlend, auch nach der Stufe.
    assert normal["fiber_g"] is None


def test_tag_summiert_spannen_und_merkt_sich_luecken():
    wraps = calc.zutaten_summe([(60, TORTILLA), (100, HAEHNCHEN)])
    tag = calc.tages_summe([
        calc.eintrag_spanne(wraps, "viel"),
        calc.eintrag_spanne(wraps, "normal"),
    ])

    kcal = tag["kcal"]
    # 290 kcal je Portion: einmal 1,4-2,0 und einmal 0,85-1,15
    assert kcal["min"] == round(290 * 1.4 + 290 * 0.85)
    assert kcal["max"] == round(290 * 2.0 + 290 * 1.15)
    assert kcal["min"] < kcal["max"]
    assert kcal["incomplete"] is False
    # Ballaststoffe fehlten in einer Zutat -- der ganze Tag ist dort unvollstaendig.
    assert tag["fiber_g"]["incomplete"] is True
    assert tag["fiber_g"]["label"] == "Ballaststoffe"


def test_anteil_am_richtwert_ist_gedeckelt():
    riesig = {"kcal": 9000, "protein_g": 0, "fiber_g": 0, "carbs_g": 0, "fat_g": 0}
    tag = calc.tages_summe([calc.eintrag_spanne(riesig, "viel")])
    # Der Balken laeuft nicht weiter als 150 % -- darueber sagt er nichts mehr.
    assert tag["kcal"]["share_max"] == 1.5
    assert tag["kcal"]["max"] == 18000
    assert tag["kcal"]["reference"] == calc.RICHTWERT["kcal"]


def test_leerer_tag_ist_null_und_nicht_unvollstaendig():
    tag = calc.tages_summe([])
    assert tag["kcal"]["min"] == 0 and tag["kcal"]["max"] == 0
    assert tag["kcal"]["incomplete"] is False
