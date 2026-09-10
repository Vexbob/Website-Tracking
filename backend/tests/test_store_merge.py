"""Tests fuer Laden-Dubletten und die nachtraegliche Einordnung (v1.81.0).

Geprueft wird, was ohne Datenbank und ohne Modell-Aufruf pruefbar ist: wann
zwei Laeden als Dublette gelten, und wie die Antwort des Modells gedeutet
wird. Das Zusammenfuehren selbst und der Schreibvorgang haengen an asyncpg
und gehoeren in einen Integrationstest.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from routers import expenses_router as er
from services import expense_classifier as ec


# ====================================================== Laden-Dubletten
# Zusammenfuehren laesst sich nicht rueckgaengig machen. Ein Vorschlag zu
# wenig ist deshalb besser als einer zu viel.

def test_schreibweisen_desselben_ladens_sind_dublette():
    assert er._store_variant_of("Lidl", "LIDL PLUS")
    assert er._store_variant_of("Rewe", "REWE Markt GmbH")
    assert er._store_variant_of("Amazon", "AMAZON.DE")


def test_praefix_gilt_als_dublette():
    """"Rewe" und "Rewe City" sind dasselbe Geschaeft in zwei Schreibweisen."""
    assert er._store_variant_of("Rewe", "Rewe City")


def test_verschiedene_laeden_sind_keine_dublette():
    assert not er._store_variant_of("Rewe", "Edeka")
    assert not er._store_variant_of("Total", "Aral")
    assert not er._store_variant_of("Apple", "Apfelhof Meier")


def test_kurze_namen_werden_nicht_ueber_praefix_verbunden():
    """Ein zwei Zeichen langer Anfang wuerde die halbe Liste verbinden --
    deshalb greift die Praefix-Regel erst ab vier Zeichen."""
    assert not er._store_variant_of("dm", "dm-drogerie markt XY")
    assert not er._store_variant_of("Aldi", "Al")


def test_leerer_name_ergibt_keine_dublette():
    assert not er._store_variant_of("", "Lidl")
    assert not er._store_variant_of("Lidl", "")


def test_gleicher_name_ist_kein_vorschlag_gegen_sich_selbst():
    """Identische Schluessel sind eine Dublette -- aber die Gruppierung im
    Endpunkt vergleicht nie eine Zeile mit sich selbst."""
    assert er._store_variant_of("Lidl", "lidl")


# ============================================ Antwort des Modells deuten

def test_antwort_wird_auf_nummern_abgebildet():
    txt = '{"zuordnung": [{"nr": 2, "typ": "subscription", "kategorie": "Strom"}, ' \
          '{"nr": 1, "typ": "receipt", "kategorie": "Lebensmittel"}]}'
    out = ec._parse_antwort(txt, 2)
    assert out[1]["typ"] == "receipt"
    assert out[2]["kategorie"] == "Strom"


def test_antwort_in_code_zaeunen():
    """Das Modell packt JSON gern in ```json ... ```."""
    txt = '```json\n{"zuordnung": [{"nr": 1, "typ": "other", "kategorie": "X"}]}\n```'
    assert ec._parse_antwort(txt, 1)[1]["typ"] == "other"


def test_blanke_liste_statt_objekt():
    txt = '[{"nr": 1, "typ": "restaurant", "kategorie": "Essen"}]'
    assert ec._parse_antwort(txt, 1)[1]["typ"] == "restaurant"


def test_unbekannter_typ_wird_zu_sonstiges():
    """Ein erfundener Schluessel darf nicht in die Datenbank."""
    txt = '{"zuordnung": [{"nr": 1, "typ": "bahnfahrt", "kategorie": "Reise"}]}'
    assert ec._parse_antwort(txt, 1)[1]["typ"] == "other"


def test_fehlende_nummer_faellt_auf_die_reihenfolge_zurueck():
    txt = '{"zuordnung": [{"typ": "receipt", "kategorie": "A"}, ' \
          '{"typ": "other", "kategorie": "B"}]}'
    out = ec._parse_antwort(txt, 2)
    assert out[1]["kategorie"] == "A" and out[2]["kategorie"] == "B"


def test_nummern_ausserhalb_des_bereichs_fliegen_raus():
    txt = '{"zuordnung": [{"nr": 99, "typ": "receipt", "kategorie": "A"}]}'
    assert ec._parse_antwort(txt, 2) == {}


def test_doppelte_nummer_gewinnt_die_erste():
    txt = '{"zuordnung": [{"nr": 1, "typ": "receipt", "kategorie": "A"}, ' \
          '{"nr": 1, "typ": "other", "kategorie": "B"}]}'
    assert ec._parse_antwort(txt, 1)[1]["kategorie"] == "A"


def test_kaputte_antwort_wird_als_fehler_gemeldet():
    with pytest.raises(ec.ClassifyError):
        ec._parse_antwort("kein json", 1)
    with pytest.raises(ec.ClassifyError):
        ec._parse_antwort("", 1)


def test_leere_kategorie_wird_none():
    txt = '{"zuordnung": [{"nr": 1, "typ": "receipt", "kategorie": "   "}]}'
    assert ec._parse_antwort(txt, 1)[1]["kategorie"] is None


# ==================================================== Zusammenfassung

def _v(payee, typ, kat, n, beantwortet=True):
    return {"payee": payee, "bank_kat": "", "bank_unterkat": "",
            "buchungen": n, "summe": 0.0, "typ": typ, "kategorie": kat,
            "beantwortet": beantwortet}


def test_zusammenfassung_zaehlt_buchungen_nicht_kombinationen():
    """An einer Entscheidung koennen hundert Buchungen haengen -- das ist die
    Zahl, die zaehlt."""
    z = ec.zusammenfassung([_v("Lidl", "receipt", "Lebensmittel", 104),
                            _v("AOK", "subscription", "Versicherung", 22)],
                           ["Lebensmittel"])
    assert z["buchungen"] == 126
    assert z["kombinationen"] == 2
    assert z["je_typ"]["receipt"] == 104


def test_zusammenfassung_nennt_nur_wirklich_neue_kategorien():
    z = ec.zusammenfassung([_v("Lidl", "receipt", "Lebensmittel", 10),
                            _v("Steam", "online_order", "Spiele", 5)],
                           ["Lebensmittel", "Drogerie"])
    namen = [n for n, _ in z["neue_kategorien"]]
    assert namen == ["Spiele"]


def test_vorhandene_kategorie_trifft_unabhaengig_von_gross_klein():
    z = ec.zusammenfassung([_v("Lidl", "receipt", "lebensmittel", 10)],
                           ["Lebensmittel"])
    assert z["neue_kategorien"] == []


def test_unbeantwortete_zeilen_werden_getrennt_gezaehlt():
    """Eine geratene Einordnung waere schlechter als keine -- sie muss
    sichtbar bleiben."""
    z = ec.zusammenfassung([_v("Lidl", "receipt", "Lebensmittel", 10),
                            _v("Rätsel", "other", None, 7, beantwortet=False)],
                           ["Lebensmittel"])
    assert z["buchungen"] == 10
    assert z["ohne_antwort"] == 7


# ======================================================== Beleg-Typen

def test_alle_typen_sind_die_der_datenbank():
    """TYP_KEYS muss zu normalize_expense_type passen, sonst schreibt der
    Lauf Werte, die der Rest der App nicht kennt."""
    from services.ai_receipt_parser import _BUILTIN_EXPENSE_TYPES
    assert ec.TYP_KEYS == _BUILTIN_EXPENSE_TYPES


def test_jeder_typ_hat_eine_erklaerung_fuer_das_modell():
    for key, text in ec.TYP_LISTE:
        assert key in ec.TYP_KEYS
        assert len(text) > 20
