"""Tests fuer den Ausgaben-CSV-Import (Backlog aus der Banking-App).

Geprueft wird das, was ohne Datenbank pruefbar ist: das Deuten der Datei
(Datum, Betrag, Kopfzeile), das Zusammenfassen der Zahlungsempfaenger zu
Laeden und die Regeln, nach denen Zeilen wegfallen. Das Schreiben selbst --
Zeitraum ersetzen, Laeden anlegen -- haengt an asyncpg und gehoert in einen
Integrationstest gegen eine echte Postgres-Instanz.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from services import expense_import as ei
from services import full_export as fx


# ------------------------------------------------------------------- Datum

def test_datum_deutsch_und_iso():
    assert ei.parse_date("01.08.2026") == date(2026, 8, 1)
    assert ei.parse_date("2026-08-01") == date(2026, 8, 1)


def test_datum_mit_uhrzeit():
    """Manche Ausleitungen haengen eine Uhrzeit an; der Tag zaehlt."""
    assert ei.parse_date("28.07.2026 14:32") == date(2026, 7, 28)


def test_datum_leer_und_unsinn():
    assert ei.parse_date("") is None
    assert ei.parse_date("keine Ahnung") is None


# ------------------------------------------------------------------ Betrag

def test_betrag_deutsch_mit_waehrung():
    assert ei.parse_amount("-9,99 €") == -9.99
    assert ei.parse_amount("-148,64 €") == -148.64


def test_betrag_positiv_bleibt_positiv():
    """Das Vorzeichen entscheidet spaeter ueber Ausgabe oder Gutschrift --
    es darf hier nicht verloren gehen."""
    assert ei.parse_amount("1.250,00 €") == 1250.0


def test_betrag_tausenderpunkt_und_englisch():
    assert ei.parse_amount("1.234,56") == 1234.56
    assert ei.parse_amount("1,234.56") == 1234.56


def test_betrag_nachgestelltes_minus():
    """"9,99-" kommt in Bank-Ausleitungen wirklich vor."""
    assert ei.parse_amount("9,99-") == -9.99


def test_betrag_ohne_dezimalstellen():
    assert ei.parse_amount("-30 €") == -30.0


def test_betrag_leer_ist_none():
    assert ei.parse_amount("") is None
    assert ei.parse_amount("k.A.") is None


# ------------------------------------------------- Empfaenger vergleichbar
# Das ist die Stelle, an der sich entscheidet, ob aus einem Jahr Kontoauszug
# 20 oder 200 Laeden werden.

def test_schreibweisen_desselben_ladens_treffen_sich():
    assert ei.norm_payee("Amazon") == ei.norm_payee("AMAZON.DE")
    assert ei.norm_payee("Amazon") == ei.norm_payee("Amazon EU S.a.r.l.")


def test_dienstleister_praefix_faellt_weg():
    """Vor dem Stern steht der Zahlungsdienstleister, dahinter der Haendler."""
    assert ei.norm_payee("Mol*PassaSports.de") == "passasports"
    assert ei.norm_payee("PayPal *STEAM GAMES") == ei.norm_payee("Steam Games")


def test_rechtsform_und_initialen_fallen_weg():
    assert ei.norm_payee("S. Payment Solutions GmbH") == "paymentsolutions"
    assert ei.norm_payee("REWE Markt GmbH") == ei.norm_payee("Rewe")


def test_filialnummer_faellt_weg():
    assert ei.norm_payee("LIDL SAGT DANKE FIL 1234") == ei.norm_payee("Lidl")


def test_verschiedene_laeden_bleiben_verschieden():
    """Die Normalisierung darf nicht so grob werden, dass sie zusammenwirft."""
    assert ei.norm_payee("Total") != ei.norm_payee("Aral")
    assert ei.norm_payee("Rewe") != ei.norm_payee("Edeka")
    assert ei.norm_payee("Apple") != ei.norm_payee("Apfelhof Meier")


def test_leerer_empfaenger_ergibt_leeren_schluessel():
    assert ei.norm_payee("") == ""
    assert ei.norm_payee("   ") == ""


# ------------------------------------------------------- Anzeigename

def test_anzeigename_ist_lesbar():
    assert ei.pretty_payee("Mol*PassaSports.de") == "PassaSports"


def test_anzeigename_macht_aus_terminal_grossschrift_normale():
    assert ei.pretty_payee("AMAZON MARKETPLACE") == "Amazon Marketplace"


def test_kurzes_kuerzel_bleibt_gross():
    """dm und ARAL schreiben sich so; nur lange Versalienketten sind
    Terminal-Schreibweise."""
    assert ei.pretty_payee("ARAL") == "ARAL"


# --------------------------------------------------------------- Kopfzeile

HEAD = "Buchungsdatum;Betrag;Zahlungsempfänger;Kategorie;Unterkategorie\n"
BEISPIEL = HEAD + (
    "01.08.2026;-9,99 €;Amazon;Shopping;Online-Shopping\n"
    "31.07.2026;-30,00 €;Total;Mobilität;Tanken\n"
    "31.07.2026;-35,50 €;Amazon;Shopping;Online-Shopping\n"
    "29.07.2026;-129,95 €;Mol*PassaSports.de;Weitere Ausgaben;Weitere Ausgaben\n"
    "28.07.2026;-38,11 €;S. Payment Solutions GmbH;Lebensmittel;Supermarkt\n"
)


def test_beispieldatei_wird_gelesen():
    header, rows = ei.read_table(BEISPIEL.encode("utf-8"))
    assert len(rows) == 5
    assert rows[0]["payee"] == "Amazon"
    assert rows[0]["subcategory"] == "Online-Shopping"


def test_kopfzeile_ohne_datum_wird_abgelehnt():
    with pytest.raises(ei.ExpenseImportError) as e:
        ei.read_table(b"Foo;Bar\n1;2\n")
    assert "Datumsspalte" in str(e.value)


def test_kopfzeile_ohne_betrag_wird_abgelehnt():
    with pytest.raises(ei.ExpenseImportError) as e:
        ei.read_table("Buchungsdatum;Empfänger\n01.08.2026;Amazon\n".encode("utf-8"))
    assert "Betragsspalte" in str(e.value)


def test_kommentarzeilen_eines_vexbob_exports_fliegen_raus():
    raw = ("# Vexbob Gesamt-Export\n" + BEISPIEL).encode("utf-8")
    _h, rows = ei.read_table(raw)
    assert len(rows) == 5


def test_bom_und_tabulator():
    raw = ("﻿" + HEAD.replace(";", "\t") +
           "01.08.2026\t-9,99 €\tAmazon\tShopping\tOnline-Shopping\n").encode("utf-8")
    _h, rows = ei.read_table(raw)
    assert rows[0]["payee"] == "Amazon"


# ------------------------------------------------------------ Zeilen deuten

def test_betraege_werden_positiv_gespeichert():
    """Im Bestand ist eine Ausgabe eine positive Zahl -- das Vorzeichen der
    Bank ist eine Konto-Sicht, keine Ausgaben-Sicht."""
    _h, rows = ei.read_table(BEISPIEL.encode("utf-8"))
    built = ei.build_rows(rows)
    assert all(e["amount"] > 0 for e in built["entries"])
    assert built["entries"][0]["amount"] == 9.99


def test_gutschrift_wird_uebersprungen_und_gezaehlt():
    raw = (HEAD + "01.08.2026;1.500,00 €;Arbeitgeber;Einkommen;Gehalt\n"
                  "02.08.2026;-9,99 €;Amazon;Shopping;Online-Shopping\n")
    _h, rows = ei.read_table(raw.encode("utf-8"))
    built = ei.build_rows(rows)
    assert len(built["entries"]) == 1
    assert built["skipped"]["gutschrift"] == 1
    assert built["examples"]["gutschrift"]


def test_nullbetrag_faellt_weg():
    raw = HEAD + "01.08.2026;0,00 €;Irgendwer;Sonstiges;Sonstiges\n"
    _h, rows = ei.read_table(raw.encode("utf-8"))
    built = ei.build_rows(rows)
    assert built["entries"] == []
    assert built["skipped"]["null"] == 1


def test_zeile_ohne_datum_faellt_weg():
    raw = HEAD + ";-9,99 €;Amazon;Shopping;Online-Shopping\n"
    _h, rows = ei.read_table(raw.encode("utf-8"))
    built = ei.build_rows(rows)
    assert built["skipped"]["ohne_datum"] == 1


def test_bank_kategorien_bleiben_roh_erhalten():
    """Sie sind die Vorgabe der App, nicht die dieser Website -- und die
    Grundlage fuer die spaetere Zuordnung."""
    _h, rows = ei.read_table(BEISPIEL.encode("utf-8"))
    e = ei.build_rows(rows)["entries"][3]
    assert e["category"] == "Weitere Ausgaben"
    assert e["subcategory"] == "Weitere Ausgaben"


# ------------------------------------------------------------ Laden-Planung

def test_vorhandener_laden_wird_getroffen_nicht_neu_angelegt():
    _h, rows = ei.read_table(BEISPIEL.encode("utf-8"))
    entries = ei.build_rows(rows)["entries"]
    plan = ei.plan_stores(entries, [{"id": 7, "name": "Amazon"}])
    assert [m["store_id"] for m in plan["matched"]] == [7]
    assert all(n["name"] != "Amazon" for n in plan["new"])


def test_zwei_schreibweisen_ergeben_einen_neuen_laden():
    raw = (HEAD + "01.08.2026;-9,99 €;AMAZON.DE;Shopping;Online-Shopping\n"
                  "02.08.2026;-5,00 €;Amazon;Shopping;Online-Shopping\n")
    _h, rows = ei.read_table(raw.encode("utf-8"))
    plan = ei.plan_stores(ei.build_rows(rows)["entries"], [])
    assert len(plan["new"]) == 1
    assert plan["new"][0]["rows"] == 2


def test_neue_laeden_stehen_nach_haeufigkeit():
    _h, rows = ei.read_table(BEISPIEL.encode("utf-8"))
    plan = ei.plan_stores(ei.build_rows(rows)["entries"], [])
    counts = [n["rows"] for n in plan["new"]]
    assert counts == sorted(counts, reverse=True)
    assert plan["new"][0]["rows"] == 2      # Amazon zweimal


def test_buchung_ohne_empfaenger_bekommt_keinen_laden():
    raw = HEAD + "01.08.2026;-9,99 €;;Shopping;Online-Shopping\n"
    _h, rows = ei.read_table(raw.encode("utf-8"))
    plan = ei.plan_stores(ei.build_rows(rows)["entries"], [])
    assert plan["without"]["rows"] == 1
    assert plan["new"] == []


def test_summen_je_laden_stimmen():
    _h, rows = ei.read_table(BEISPIEL.encode("utf-8"))
    plan = ei.plan_stores(ei.build_rows(rows)["entries"], [])
    amazon = next(n for n in plan["new"] if n["rows"] == 2)
    assert amazon["amount"] == pytest.approx(45.49)


# --------------------------------------------------------- Sammelposten

def test_sammelposten_heisst_nach_der_unterkategorie():
    _h, rows = ei.read_table(BEISPIEL.encode("utf-8"))
    e = ei.build_rows(rows)["entries"][0]
    assert ei.item_description(e) == "Online-Shopping"
    assert ei.item_original_text(e) == "C24: Shopping / Online-Shopping"


def test_sammelposten_ohne_kategorie_bekommt_ersatznamen():
    raw = "Buchungsdatum;Betrag;Zahlungsempfänger\n01.08.2026;-9,99 €;Amazon\n"
    _h, rows = ei.read_table(raw.encode("utf-8"))
    e = ei.build_rows(rows)["entries"][0]
    assert ei.item_description(e) == "Sammelbuchung"
    assert ei.item_original_text(e) is None


# -------------------------------------------------------------- Export

def test_export_kennt_die_protokoll_sektion():
    keys = [s["key"] for s in fx.EXPORT_SECTIONS]
    assert "expense_imports" in keys
    sec = next(s for s in fx.EXPORT_SECTIONS if s["key"] == "expense_imports")
    assert sec["group"] == "ausgaben"
    assert sec["aggregatable"] is False


def test_herkunft_steht_als_klartext_in_der_datei():
    """'import' waere in fuenf Jahren Ratearbeit."""
    assert fx.HERKUNFT["import"].startswith("CSV-Import")
    assert fx.HERKUNFT["receipt"] == "Bon gescannt"


def test_protokoll_sektion_ist_ueber_sections_waehlbar():
    picked = fx.clean_sections(["expense_imports"])
    assert picked == ["expense_imports"]


# ------------------------------------------------- Erklaerung im Vorspann
# Der Nutzer hat den Hinweis ausdruecklich verlangt: ohne ihn sieht der
# Rueckblick ein Jahr spaeter aus wie schlecht erfasste Bons.

def _header(backlog=None):
    from datetime import date as _d
    return fx._export_header({"username": "Test"}, fx.ALL_SECTION_KEYS,
                             None, None, {"ausgaben": "none"}, backlog)


BACKLOG = None


def _mit_backlog():
    from datetime import date as _d
    return _header({"n": 774, "von": _d(2025, 1, 2), "bis": _d(2025, 12, 30),
                    "summe": 9840.55, "eigen": 96})


def test_vorspann_nennt_den_backlog_mit_zeitraum():
    txt = "\n".join(_mit_backlog())
    assert "NACHTRAG (Backlog)" in txt
    assert "774" in txt
    assert "2025-01-02" in txt and "2025-12-30" in txt


def test_vorspann_erklaert_die_fehlenden_positionen():
    """Die Zahl allein wuerde die Frage aufwerfen, die sie beantworten soll."""
    txt = "\n".join(_mit_backlog())
    assert "KEINE Einzelpositionen" in txt
    assert "kein Erfassungsfehler" in txt


def test_vorspann_trennt_bank_kategorien_von_eigenen():
    txt = "\n".join(_mit_backlog())
    assert "NICHT die Kategorien dieser Website" in txt


def test_vorspann_nennt_auch_die_selbst_erfassten():
    txt = "\n".join(_mit_backlog())
    assert "Selbst erfasst" in txt and "96" in txt


def test_ohne_import_kein_hinweis():
    """Eine Erklaerung fuer etwas, das es nicht gibt, ist Rauschen."""
    txt = "\n".join(_header(None))
    assert "NACHTRAG" not in txt
    assert "Backlog" not in txt


def test_sektionsnamen_sind_unterscheidbar():
    """Musik und Ausgaben haben beide ein Upload-Protokoll."""
    labels = [x["label"] for x in fx.EXPORT_SECTIONS]
    assert len(labels) == len(set(labels))
