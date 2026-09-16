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


def test_tag_summiert_und_merkt_sich_luecken():
    """Seit v1.98.0 eine Zahl statt einer Spanne — die Stufen sind Sache des
    Tagebuchs, und ein Gericht wird in Portionen eingetragen."""
    wraps = calc.zutaten_summe([(60, TORTILLA), (100, HAEHNCHEN)])
    eine = {m: wraps[m] for m in calc.MAKROS}
    halbe = {m: (None if wraps[m] is None else wraps[m] * 0.5) for m in calc.MAKROS}
    tag = calc.tages_summe_genau([eine, halbe])

    # 290 kcal je Portion, einmal ganz und einmal halb.
    assert tag["kcal"]["value"] == round(290 * 1.5)
    assert tag["kcal"]["incomplete"] is False
    # Ballaststoffe fehlten in einer Zutat -- der ganze Tag ist dort
    # unvollstaendig. NICHT niedriger: der Unterschied zwischen "wenig
    # gegessen" und "wir wissen es nicht" ist der Kern des Moduls.
    assert tag["fiber_g"]["incomplete"] is True
    assert tag["fiber_g"]["label"] == "Ballaststoffe"


def test_anteil_ist_ungedeckelt_und_der_ueberschuss_steht_daneben():
    """Gedeckelt wird im Ring, nicht in der Rechnung. Wer hier deckelt, kann
    spaeter nicht mehr sagen, wie weit darueber es war."""
    tag = calc.tages_summe_genau([{"kcal": 3600}])
    assert tag["kcal"]["value"] == 3600
    assert tag["kcal"]["share"] == 1.5            # 3600 von 2400
    assert tag["kcal"]["reference"] == calc.RICHTWERT["kcal"]
    # Ueberschritten heisst 0 und nicht negativ; wie weit darueber, sagt over.
    assert tag["kcal"]["remaining"] == 0
    assert tag["kcal"]["over"] == 1200


def test_eigenes_ziel_ersetzt_den_richtwert_nur_wo_eines_steht():
    tag = calc.tages_summe_genau([{"kcal": 1000, "protein_g": 30}],
                                 {"kcal_target": 2000})
    assert tag["kcal"]["reference"] == 2000
    assert tag["kcal"]["own_target"] is True
    assert tag["kcal"]["remaining"] == 1000
    # Wo kein eigenes Ziel steht, gilt weiter der allgemeine Richtwert.
    assert tag["protein_g"]["reference"] == calc.RICHTWERT["protein_g"]
    assert tag["protein_g"]["own_target"] is False


def test_leerer_tag_ist_null_und_nicht_unvollstaendig():
    tag = calc.tages_summe_genau([])
    assert tag["kcal"]["value"] == 0
    assert tag["kcal"]["incomplete"] is False
    assert tag["kcal"]["over"] == 0


# --------------------------------------------------------------------------
# Einheiten (v1.90.0: beliebig viele eigene Groessen je Lebensmittel)
# --------------------------------------------------------------------------
BROT = {"base_unit": "g"}
BROT_GROESSEN = [
    {"label": "Scheibe", "grams": 45},
    {"label": "Laib", "grams": 750},
    {"label": "Packung", "grams": 500},
]
SAFT = {"base_unit": "ml"}
SAFT_GROESSEN = [{"label": "Glas", "grams": 200}]
LOSES = {"base_unit": "g"}


def test_alle_eigenen_groessen_stehen_zur_wahl():
    keys = [e["key"] for e in calc.einheiten_fuer(BROT, BROT_GROESSEN)]
    # Die Basis zuerst, danach die eigenen in ihrer Reihenfolge -- und zwar
    # ALLE: ein Brot hat eine Scheibe UND einen Laib.
    assert keys == ["g", "Scheibe", "Laib", "Packung"]
    # Ein Getraenk rechnet in Millilitern.
    assert calc.einheiten_fuer(SAFT, SAFT_GROESSEN)[0]["key"] == "ml"
    # Ohne hinterlegte Groessen wird nichts angeboten, was geraten waere.
    assert [e["key"] for e in calc.einheiten_fuer(LOSES)] == ["g"]


def test_umrechnung_in_die_basis():
    assert calc.in_basis(2, "Scheibe", BROT, BROT_GROESSEN) == (90.0, None)
    assert calc.in_basis(1, "Packung", BROT, BROT_GROESSEN) == (500.0, None)
    assert calc.in_basis(150, "g", BROT, BROT_GROESSEN) == (150.0, None)
    assert calc.in_basis(1, "Glas", SAFT, SAFT_GROESSEN) == (200.0, None)


def test_fehlende_groesse_wird_gesagt_nicht_verschwiegen():
    # Die Groesse wurde geloescht, der alte Eintrag nennt sie noch.
    wert, hinweis = calc.in_basis(1, "Scheibe", LOSES, [])
    assert wert == calc.PORTION_FALLBACK
    assert hinweis and "Scheibe" in hinweis


def test_alte_schluessel_werden_noch_verstanden():
    # Bis v1.89.0 hiessen die Einheiten 'portion' und 'packung'; ein alter
    # Tab im Browser darf keinen falschen Wert schreiben.
    alt = {"base_unit": "g", "portion_g": 62, "package_g": 370}
    assert calc.in_basis(2, "portion", alt, []) == (124.0, None)
    assert calc.in_basis(1, "packung", alt, []) == (370.0, None)
