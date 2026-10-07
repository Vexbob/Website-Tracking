"""Depot rechnen: Stueck, Einstand, Wert und Ergebnis (v2.39.0).

Alles mit erfundenen Buchungen und Kursen. Die Faelle folgen dem Auszug:
Zeilen vor Juni 2024 nennen keine Stueckzahl, danach jede.
"""
import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services import depot_kurse as kurse_quelle               # noqa: E402
from services import depot_rechnung as r                       # noqa: E402

A, B = "IE00TEST0001", "IE00TEST0002"


def _b(tag, art, betrag, isin=A, stueck=None, saldo=None):
    return {"datum": tag, "art": art, "betrag": Decimal(betrag), "isin": isin,
            "stueck": None if stueck is None else Decimal(stueck), "name": "Test",
            "saldo": None if saldo is None else Decimal(saldo)}


# ------------------------------------------------------------ Bestand

def test_nennt_jede_zeile_die_stueckzahl_beginnt_der_bestand_bei_null():
    p = r.positionen([_b(date(2025, 1, 2), "kauf", "-100", stueck="2")])[A]
    assert p["quelle"] == "auszug" and p["start"] == 0 and p["ab"] is None


def test_die_stueckzahl_aus_der_app_rechnet_zurueck():
    rows = [_b(date(2024, 3, 1), "sparplan", "-50"),                    # ohne Stueck
            _b(date(2024, 7, 1), "sparplan", "-50", stueck="0.5"),
            _b(date(2024, 9, 1), "verkauf", "40", stueck="0.2")]
    p = r.positionen(rows, {A: (Decimal("1.3"), date(2024, 10, 1))})[A]
    # 1,3 heute = Stand an der Grenze + 0,5 − 0,2  ->  1,0 an der Grenze
    assert p["quelle"] == "app" and p["start"] == Decimal("1.0") and p["ab"] == date(2024, 3, 1)


def test_eine_verkaufte_position_endet_bei_null():
    rows = [_b(date(2024, 3, 1), "kauf", "-100"),
            _b(date(2024, 7, 1), "verkauf", "60", stueck="3")]
    p = r.positionen(rows)[A]
    assert p["quelle"] == "verkauft" and p["start"] == Decimal(3)


def test_ohne_stueckzahl_wird_nicht_geschaetzt():
    p = r.positionen([_b(date(2024, 3, 1), "sparplan", "-50")])[A]
    assert p["start"] is None and p["quelle"] is None


def test_fehlt_die_stueckzahl_rechnen_die_kurse_sie_aus():
    rows = [_b(date(2024, 3, 1), "sparplan", "-50"),                    # ohne Stueck
            _b(date(2024, 7, 1), "sparplan", "-50", stueck="0.5")]
    # Freitag 100 €: der Sparplan am Montag nimmt den letzten Schlusskurs davor.
    kurse = {A: [(date(2024, 2, 29), Decimal(100)), (date(2024, 7, 1), Decimal(100))]}
    p = r.positionen(rows, kurse=kurse)[A]
    assert p["quelle"] == "kurse" and p["start"] == Decimal("0.5") and p["geschaetzt"] == 1
    # Die Zahl aus der App geht vor.
    assert r.positionen(rows, {A: (Decimal(2), date(2024, 8, 1))}, kurse)[A]["quelle"] == "app"
    # Ein zu alter Kurs rechnet nichts um.
    alt = {A: [(date(2024, 1, 2), Decimal(100))]}
    assert r.positionen(rows, kurse=alt)[A]["start"] is None


def test_kurse_fuer_die_rechnung_ab_der_ersten_alten_zeile():
    rows = [_b(date(2023, 11, 2), "kauf", "-20"), _b(date(2024, 6, 10), "sparplan", "-5", stueck="0.01")]
    assert r.kursbedarf(rows) == {A: date(2023, 11, 2) - r.VORLAUF}


def test_eine_stueckzahl_die_nicht_passt_wird_gemeldet():
    rows = [_b(date(2024, 3, 1), "kauf", "-50"),
            _b(date(2024, 9, 1), "verkauf", "40", stueck="2")]
    p = r.positionen(rows, {A: (Decimal("0.5"), date(2024, 8, 1))})[A]
    assert p["start"] is None and "passt nicht" in p["fehler"]


# ------------------------------------------------------------ Einstand

def test_einstand_nach_durchschnitt_und_realisiert_beim_verkauf():
    rows = [_b(date(2025, 1, 2), "kauf", "-200", stueck="2"),
            _b(date(2025, 2, 3), "kauf", "-300", stueck="2"),
            _b(date(2025, 3, 3), "verkauf", "400", stueck="2")]
    g = r.gehen(r.positionen(rows)[A])
    # Durchschnitt 125 je Stueck: 400 − 250 = 150 realisiert, 250 bleiben.
    assert g["realisiert"] == [(date(2025, 3, 3), Decimal(150))]
    assert g["einstand"] == Decimal(250) and g["menge"] == Decimal(2)


def test_eine_alte_ganz_verkaufte_position_realisiert_erloes_minus_kauf():
    rows = [_b(date(2022, 1, 3), "kauf", "-100"), _b(date(2022, 6, 1), "verkauf", "130")]
    g = r.gehen(r.positionen(rows)[A])
    assert g["realisiert"] == [(date(2022, 6, 1), Decimal(30))] and g["menge"] == 0


def test_ein_ueberschuss_vor_der_grenze_ist_dort_realisiert():
    rows = [_b(date(2024, 1, 2), "kauf", "-100"), _b(date(2024, 3, 1), "verkauf", "150"),
            _b(date(2024, 7, 1), "kauf", "-50", stueck="1")]
    g = r.gehen(r.positionen(rows, {A: (Decimal(2), date(2024, 8, 1))})[A])
    assert g["realisiert"] == [(date(2024, 3, 1), Decimal(50))]
    assert g["einstand"] == Decimal(50) and g["menge"] == Decimal(2)


# ------------------------------------------------------------ Auswertung

def test_depotwert_und_ergebnis():
    rows = [_b(date(2025, 1, 2), "einzahlung", "1000", isin=None, saldo="1000"),
            _b(date(2025, 1, 2), "kauf", "-200", stueck="2", saldo="800"),
            _b(date(2025, 1, 3), "kauf", "-90", isin=B, stueck="1", saldo="710")]
    kurse = {A: [(date(2025, 1, 2), Decimal(100)), (date(2025, 1, 6), Decimal(120))]}
    aw = r.auswerten(rows, kurse, heute=date(2025, 1, 7))
    j = aw["jetzt"]
    # A: 2 × 120 = 240; B hat keinen Kurs und zaehlt zum Einstand (90).
    assert j["wert"] == 330.0 and j["einstand"] == 290.0 and j["cash"] == 710.0
    # Ergebnis = Wert + Cash − netto eingezahlt = 330 + 710 − 1000
    assert j["ergebnis"] == 40.0 and j["unrealisiert"] == 40.0
    assert aw["positionen"][B]["wert"] is None and aw["positionen"][A]["kaufkurs"] == 100.0
    assert [p["datum"] for p in aw["verlauf"]] == ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]


def test_unbekannte_stueckzahl_steht_zum_einstand_im_wert():
    rows = [_b(date(2024, 3, 1), "sparplan", "-50", saldo="0"),
            _b(date(2024, 7, 1), "sparplan", "-50", stueck="0.5", saldo="0")]
    aw = r.auswerten(rows, {A: [(date(2024, 7, 1), Decimal(200))]}, heute=date(2024, 7, 2))
    pos = aw["positionen"][A]
    assert pos["stueck"] is None and pos["im_bestand"] and aw["jetzt"]["wert"] == 100.0
    # Mit der Stueckzahl aus der App: 1,5 × 200.
    aw = r.auswerten(rows, {A: [(date(2024, 7, 1), Decimal(200))]},
                     {A: (Decimal("1.5"), date(2024, 7, 2))}, heute=date(2024, 7, 2))
    assert aw["jetzt"]["wert"] == 300.0 and aw["positionen"][A]["stueck_quelle"] == "app"


def test_kursbedarf_ab_dem_beginn_des_verlaufs():
    rows = [_b(date(2022, 1, 3), "kauf", "-100", isin=B), _b(date(2022, 6, 1), "verkauf", "130", isin=B),
            _b(date(2024, 3, 1), "kauf", "-100"), _b(date(2024, 7, 1), "verkauf", "60", stueck="3")]
    # B war vor dem Beginn (01.03.2024) schon verkauft und braucht keinen Kurs.
    assert r.kursbedarf(rows) == {A: date(2024, 3, 1) - r.VORLAUF}


def test_ergebnis_je_monat_und_im_zeitraum():
    verlauf = [{"datum": "2025-01-15", "ergebnis": 10.0}, {"datum": "2025-01-31", "ergebnis": 25.0},
               {"datum": "2025-02-20", "ergebnis": 5.0}, {"datum": "2025-03-31", "ergebnis": 30.0}]
    m = r.ergebnis_monate(verlauf, ["2024-12", "2025-01", "2025-02", "2025-03"])
    assert [x["ergebnis"] for x in m] == [None, 15.0, -20.0, 25.0]
    assert r.ergebnis_zeitraum(verlauf, date(2025, 2, 1), date(2025, 3, 31)) == (5.0, "2025-01-31")
    assert r.ergebnis_zeitraum(verlauf, date(2024, 1, 1), date(2024, 6, 1)) == (None, None)


def test_realisiert_je_jahr_lueckenlos():
    real = [(date(2022, 5, 1), A, Decimal(30)), (date(2024, 2, 1), A, Decimal(-5)), (date(2024, 9, 1), B, Decimal(10))]
    assert r.realisiert_jahre(real, 2021, 2024) == [
        {"jahr": 2021, "realisiert": 0.0}, {"jahr": 2022, "realisiert": 30.0},
        {"jahr": 2023, "realisiert": 0.0}, {"jahr": 2024, "realisiert": 5.0}]


# ------------------------------------------------------------ Kursquelle

def test_die_suche_nimmt_nur_genau_diese_isin():
    antwort = {"list": [{"isin": "IE00TEST0009", "entityType": "FUND", "entityValue": "1"},
                        {"isin": A, "entityType": "FUND", "entityValue": "2", "name": "Test"}]}
    assert kurse_quelle.instrument_waehlen(antwort, A) == ("FUND", "2", "Test")
    assert kurse_quelle.instrument_waehlen({"list": []}, A) is None


def test_der_handelsplatz_von_trade_republic_zuerst_und_nur_euro():
    uebersicht = {"quoteList": {"list": [
        {"isoCurrency": "USD", "market": {"name": "LS Exchange", "idNotation": 1}},
        {"isoCurrency": "EUR", "market": {"name": "Xetra", "idNotation": 2}},
        {"isoCurrency": "EUR", "market": {"name": "LS Exchange", "idNotation": 3}}]}}
    assert kurse_quelle.markt_waehlen(uebersicht) == ("3", "LS Exchange")
    assert kurse_quelle.markt_waehlen({"quoteList": {"list": []}}) is None


def test_schlusskurse_lesen():
    antwort = {"isoCurrency": "EUR", "datetimeLast": [1789992000, 1790078400, 1790164800],
               "last": [100.25, None, 101.5]}
    assert kurse_quelle.schlusskurse(antwort) == [(date(2026, 9, 21), Decimal("100.25")),
                                                  (date(2026, 9, 23), Decimal("101.5"))]
    with pytest.raises(kurse_quelle.KursFehler):
        kurse_quelle.schlusskurse({"isoCurrency": "USD", "datetimeLast": [1], "last": [1]})


def test_der_verlauf_kommt_in_stuecken_bis_heute(monkeypatch):
    """Eine Abfrage reicht fuenf Jahre: ein Auszug ab 2019 braucht zwei."""
    gefragt = []
    def holen(pfad, **p):
        gefragt.append(p["startDate"])
        if p["startDate"] == "2019-01-02":
            return {"isoCurrency": "EUR", "datetimeLast": [1546430400, 1704196800], "last": [10, 20]}   # 02.01.2019, 02.01.2024
        return {"isoCurrency": "EUR", "datetimeLast": [1735819200], "last": [30]}                       # 02.01.2025
    monkeypatch.setattr(kurse_quelle, "_holen", holen)
    q = {"typ": "FUND", "instrument": "1", "notierung": "2"}
    k = kurse_quelle.verlauf_holen(q, date(2019, 1, 2), bis=date(2025, 1, 5))
    assert gefragt == ["2019-01-02", "2024-01-03"] and [t.year for t, _ in k] == [2019, 2024, 2025]
