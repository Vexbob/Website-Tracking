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


def test_groessenliste_wird_geprueft():
    liste, fehler = calc.groessen_sauber([
        {"label": " Scheibe ", "grams": 45},
        {"label": "", "grams": None},          # leere Zeile: einfach weg
        {"label": "Laib", "grams": "750"},
    ])
    assert fehler is None
    assert [g["label"] for g in liste] == ["Scheibe", "Laib"]
    assert [g["position"] for g in liste] == [0, 1]

    # Die Grundeinheit laesst sich nicht ueberschreiben.
    assert calc.groessen_sauber([{"label": "g", "grams": 2}])[1]
    # Eine Bezeichnung ohne Gewicht waere im Auswahlfeld eine Falle.
    assert calc.groessen_sauber([{"label": "Scheibe"}])[1]
    # Zweimal dasselbe Wort waere nicht zu unterscheiden.
    assert calc.groessen_sauber([{"label": "Scheibe", "grams": 45},
                                 {"label": "scheibe", "grams": 50}])[1]


# --------------------------------------------------------------------------
# Genaue Menge neben geschaetzter Stufe (v1.90.0)
# --------------------------------------------------------------------------
def test_gewogene_menge_ist_eine_spanne_der_breite_null():
    spanne = calc.exakte_spanne(calc.je_menge(HAEHNCHEN, 150))
    assert spanne["kcal"] == (165.0, 165.0)
    # Fehlend bleibt fehlend, auch bei einer genauen Menge.
    assert calc.exakte_spanne(calc.je_menge(TORTILLA, 60))["fiber_g"] is None


def test_genauer_eintrag_macht_den_tag_schmaler_nicht_breiter():
    gericht = calc.eintrag_spanne({"kcal": 500, "protein_g": 30, "fiber_g": 5,
                                   "carbs_g": 50, "fat_g": 20}, "normal")
    lebensmittel = calc.exakte_spanne(calc.je_menge(HAEHNCHEN, 200))
    tag = calc.tages_summe([gericht, lebensmittel])
    # 425-575 aus dem Gericht, dazu genau 220 aus dem Haehnchen.
    assert tag["kcal"]["min"] == 645
    assert tag["kcal"]["max"] == 795
    # Die Unsicherheit stammt allein aus dem geschaetzten Teil.
    assert tag["kcal"]["max"] - tag["kcal"]["min"] == 150
