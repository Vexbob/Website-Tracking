"""Depot: den Trade-Republic-Kontoauszug lesen (v2.38.0).

Geprueft wird ohne echtes PDF: ``kontoauszug_lesen`` arbeitet auf Woertern mit
ihrer Lage, und genau die baut ``_seite`` hier nach -- in den Spalten, in
denen sie im Auszug stehen. Der wichtigste Test ist ein negativer: ein Saldo,
der nicht aufgeht, darf nicht gespeichert werden.
"""
import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from services import depot_import as leser                    # noqa: E402
from routers import depot_router                               # noqa: E402
from services import depot_rechnung as rechnung                # noqa: E402

# Spalten wie im echten Auszug (x-Lage in pt).
X = {"datum": 74, "typ": 101, "besch": 145, "ein": 373, "aus": 427, "saldo": 494}


def _kopf(oben=343):
    return [(oben, 74, 97, "DATUM"), (oben, 101, 111, "TYP"), (oben, 145, 186, "BESCHREIBUNG"),
            (oben, 373, 432, "ZAHLUNGSEINGANG"), (oben, 433, 482, "ZAHLUNGSAUSGANG"),
            (oben, 501, 519, "SALDO")]


def _buchung(oben, tag, typ, besch, ein=None, aus=None, saldo="0,00\xa0€"):
    w = [(oben, 74, 97, tag.rsplit(" ", 1)[0]), (oben + 8, 74, 92, tag.rsplit(" ", 1)[1]),
         (oben + 4, 101, 140, typ)]
    for i, zeile in enumerate(besch):
        w.append((oben + i * 8, 145, 360, zeile))
    if ein:
        w.append((oben + 4, 373, 400, ein))
    if aus:
        w.append((oben + 4, 427, 452, aus))
    w.append((oben + 4, 494, 519, saldo))
    return w


def _seite(buchungen, uebersicht=("0,00\xa0€", "180,00\xa0€", "72,60\xa0€", "107,40\xa0€")):
    w = [(105, 74, 171, "TRADE REPUBLIC BANK GMBH"), (140, 431, 520, "01 Juli 2021 - 04 Okt. 2026"),
         (204, 74, 171, "KONTOÜBERSICHT"), (257, 74, 110, "Cashkonto")]
    w += [(257, x, x + 40, t) for x, t in zip((148, 239, 348, 500), uebersicht)]
    w += [(314, 74, 176, "UMSATZÜBERSICHT")] + _kopf()
    oben = 358
    for b in buchungen:
        w += _buchung(oben, *b)
        oben += 32
    return w


ZWEI = [
    ("28 Juli 2021", "Überweisung", ["Einzahlung akzeptiert: DE89370400440532013000 auf"],
     "180,00\xa0€", None, "180,00\xa0€"),
    ("28 Juli 2021", "Handel", ["Ausführung Handel Direktkauf Kauf IE00TEST0011 BSPIII-CORE",
                                 "MSCI WLD DLA 1111222220210728"], None, "72,60\xa0€", "107,40\xa0€"),
]


def test_ein_auszug_wird_gelesen_und_geprueft():
    a = leser.kontoauszug_lesen([_seite(ZWEI)])
    assert a["von"] == date(2021, 7, 1) and a["bis"] == date(2026, 10, 4)
    assert [b["art"] for b in a["buchungen"]] == ["einzahlung", "kauf"]
    kauf = a["buchungen"][1]
    assert kauf["betrag"] == Decimal("-72.60") and kauf["isin"] == "IE00TEST0011"
    assert kauf["name"] == "BSPIII-CORE MSCI WLD DLA"
    assert a["endsaldo"] == Decimal("107.40")


def test_ein_saldo_der_nicht_aufgeht_wird_nicht_gespeichert():
    """Ein falsch gelesener Betrag saehe aus wie ein richtiger -- deshalb
    wird abgelehnt statt gespeichert."""
    kaputt = [ZWEI[0], ZWEI[1][:5] + ("100,00\xa0€",)]
    with pytest.raises(leser.LeseFehler) as fehler:
        leser.kontoauszug_lesen([_seite(kaputt)])
    assert "nichts gespeichert" in str(fehler.value)


def test_summen_muessen_zur_kontouebersicht_passen():
    with pytest.raises(leser.LeseFehler):
        leser.kontoauszug_lesen([_seite(ZWEI, uebersicht=("0,00\xa0€", "999,00\xa0€",
                                                            "72,60\xa0€", "107,40\xa0€"))])


def test_was_nach_der_umsatztabelle_kommt_ist_keine_buchung():
    seite = _seite(ZWEI) + [(500, 74, 180, "BARMITTELÜBERSICHT"),
                            (530, 74, 97, "04 Okt."), (538, 74, 92, "2026"),
                            (534, 494, 519, "107,40\xa0€")]
    assert len(leser.kontoauszug_lesen([seite])["buchungen"]) == 2


def test_kein_pdf_und_kein_trade_republic():
    with pytest.raises(leser.LeseFehler):
        leser.woerter_aus_pdf(b"Datum;Betrag\n")
    with pytest.raises(leser.LeseFehler):
        leser.kontoauszug_lesen([[(100, 74, 200, "Irgendeine Bank")]])


@pytest.mark.parametrize("text, wert", [
    ("12.345,67\xa0€", Decimal("12345.67")), ("0,59\xa0€", Decimal("0.59")), ("", Decimal(0))])
def test_betraege(text, wert):
    assert leser.betrag(text) == wert


@pytest.mark.parametrize("text, tag", [
    ("27 Juli 2021", date(2021, 7, 27)), ("24 Aug. 2021", date(2021, 8, 24)),
    ("04 Sept. 2021", date(2021, 9, 4)), ("03 März 2024", date(2024, 3, 3))])
def test_daten(text, tag):
    assert leser.datum(text) == tag


@pytest.mark.parametrize("typ, besch, ein, art, isin, name, stueck", [
    ("Handel", "Savings plan execution IE00TEST0022 Beispiel VII plc - Beispiel Core Index 500 UCITS ETF USD (Acc), quantity: 0.012345",
     False, "sparplan", "IE00TEST0022", "Beispiel Core Index 500 UCITS ETF USD (Acc)", Decimal("0.012345")),
    ("Handel", "Sell trade IE00TEST0033 Beispiel ETFs Europe I plc - Beispiel Welt UCITS ETF USD Unhedged, quantity: 6",
     True, "verkauf", "IE00TEST0033", "Beispiel Welt UCITS ETF USD Unhedged", Decimal("6")),
    ("Handel", "Savings plan execution FR00TEST0044 Beispiel ETF Leveraged USA Daily UCITS ETF - EUR, quantity: 0.250000",
     False, "sparplan", "FR00TEST0044", "Beispiel ETF Leveraged USA Daily UCITS ETF", Decimal("0.250000")),
    ("Handel", "Ausführung Direktkauf XF000BTC0017 C1234567890", False, "kauf", "XF000BTC0017", "Bitcoin", None),
    ("Handel", "Ausführung Handel Direktverkauf Verkauf LU00TEST0055 BSP.EUROPA INDEX 1C 3333444420230605 KW",
     True, "verkauf", "LU00TEST0055", "BSP.EUROPA INDEX 1C", None),
    ("Überweisung", "Einzahlung akzeptiert: DE89370400440532013000 auf DE02120300000000202051",
     True, "einzahlung", None, None, None),
    ("Überweisung", "PayOut to transit", False, "auszahlung", None, None, None),
    ("Ertrag", "Cash Dividend for ISIN US00TEST0066", True, "ertrag", "US00TEST0066", "US00TEST0066", None),
    ("Zinsen", "Your interest payment", True, "zinsen", None, None, None),
])
def test_buchungen_deuten(typ, besch, ein, art, isin, name, stueck):
    d = leser.buchung_deuten(typ, besch, Decimal(1) if ein else Decimal(0), Decimal(0) if ein else Decimal(1))
    assert (d["art"], d["isin"], d["name"], d["stueck"]) == (art, isin, name, stueck)


def test_eine_iban_ist_keine_isin():
    d = leser.buchung_deuten("Überweisung", "Einzahlung akzeptiert: DE89370400440532013000", Decimal(1), Decimal(0))
    assert d["isin"] is None


def test_der_lesbarste_name_gewinnt():
    assert leser.bester_name(["BSPVII-CORE IDX500 DLACC"] * 15
                             + ["Beispiel Core Index 500 UCITS ETF USD (Acc)"] * 3) \
        == "Beispiel Core Index 500 UCITS ETF USD (Acc)"
    assert leser.bester_name(["US00TEST0066", "BEISPIEL INC. DL-,00001"]) == "BEISPIEL INC. DL-,00001"


def _b(datum_, art, betrag, isin="IE0000000001", stueck=None, name="Welt-ETF", saldo=None):
    return {"datum": datum_, "art": art, "betrag": Decimal(betrag), "isin": isin,
            "stueck": None if stueck is None else Decimal(stueck), "name": name,
            "saldo": None if saldo is None else Decimal(saldo)}


def test_bestand_und_ergebnis():
    rows = [_b(date(2024, 1, 1), "kauf", "-100", stueck="2"),
            _b(date(2024, 2, 1), "verkauf", "130", stueck="2"),
            _b(date(2024, 3, 1), "sparplan", "-50", isin="IE0000000002", stueck="0.5"),
            # Ohne Stueckzahl (alte Zeilen): die letzte Ausfuehrung entscheidet.
            _b(date(2022, 1, 1), "kauf", "-40", isin="DE0000000003"),
            _b(date(2022, 2, 1), "verkauf", "35", isin="DE0000000003")]
    w = {x["isin"]: x for x in depot_router.wertpapiere(rows)}
    assert not w["IE0000000001"]["im_bestand"] and w["IE0000000001"]["ergebnis"] == 30.0
    assert w["IE0000000002"]["im_bestand"] and w["IE0000000002"]["stueck"] == 0.5
    assert not w["DE0000000003"]["im_bestand"] and w["DE0000000003"]["stueck"] is None
    # Der Bestand steht vorn.
    assert depot_router.wertpapiere(rows)[0]["isin"] == "IE0000000002"


def test_ein_wertpapier_heisst_ueberall_gleich():
    rows = [_b(date(2024, 1, 1), "kauf", "-10", name="WELT-ETF"),
            _b(date(2024, 2, 1), "kauf", "-10", name="Welt-ETF Acc"),
            _b(date(2024, 3, 1), "kauf", "-10", name="Welt-ETF Acc")]
    assert depot_router.namen(rows) == {"IE0000000001": "Welt-ETF Acc"}


def test_statistik_rechnet_ueber_einen_zeitraum():
    rows = [_b(date(2023, 6, 1), "kauf", "-100", isin="DE0000000003", name="Alt"),
            _b(date(2024, 1, 3), "einzahlung", "300", isin=None),
            _b(date(2024, 1, 4), "sparplan", "-120"),
            _b(date(2024, 1, 5), "sparplan", "-30", isin="IE0000000002", name="Schwellen"),
            _b(date(2024, 2, 1), "zinsen", "2.5", isin=None),
            _b(date(2024, 3, 4), "sparplan", "-150"),
            _b(date(2024, 3, 10), "verkauf", "130", isin="DE0000000003", name="Alt"),
            _b(date(2024, 3, 11), "ertrag", "1.2"),
            # Ausserhalb des Zeitraums: zaehlt fuer nichts ausser das Ergebnis.
            _b(date(2024, 5, 1), "sparplan", "-999")]
    aw = rechnung.auswerten(rows, {}, {}, heute=date(2024, 5, 1))
    s = depot_router.statistik(rows, date(2024, 1, 1), date(2024, 3, 31), aw)
    assert [m["monat"] for m in s["monate"]] == ["2024-01", "2024-02", "2024-03"]
    assert s["monate"][0]["sparplan"] == 150.0 and s["monate"][1]["zinsen"] == 2.5
    assert s["monate"][2]["verkauf"] == 130.0 and s["monate"][2]["ertraege"] == 1.2
    assert s["sparplan"] == [{"isin": "IE0000000001", "name": "Welt-ETF", "summe": 270.0},
                             {"isin": "IE0000000002", "name": "Schwellen", "summe": 30.0}]
    # Der Kauf von 2023 gehoert zum Ergebnis, obwohl er vor dem Zeitraum liegt.
    assert s["ergebnisse"] == [{"isin": "DE0000000003", "name": "Alt", "ergebnis": 30.0,
                                "letzte": "2024-03-10", "im_bestand": False}]
    k = s["kennzahlen"]
    # Ø nur ueber die zwei Monate mit Sparplan, nicht ueber drei.
    assert k["sparplan_schnitt"] == 150.0 and k["sparplan_monate"] == 2
    assert k["ausfuehrungen"] == 4 and k["ertraege_zinsen"] == 3.7
    assert k["eingezahlt_netto"] == 300.0 and k["realisiert"] == 30.0
    # Der Verlauf beginnt erst, wo jeder rechenbare Bestand bekannt ist.
    assert k["ergebnis_ab"] == "2024-03-10" and s["monate"][0]["ergebnis"] is None


# ------------------------------------------------- Uebernehmen (Router)
import asyncio                                                  # noqa: E402

from fastapi import HTTPException                               # noqa: E402


class _Datei:
    filename = "Kontoauszug.pdf"

    async def read(self, n=None):
        return b"%PDF-1.7 erfunden"


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _DB:
    def __init__(self, schon=False, vorhanden=3):
        self.schon, self.vorhanden, self.geschrieben = schon, vorhanden, []

    def transaction(self):
        return _Tx()

    async def fetchrow(self, sql, *a):
        from datetime import datetime, timezone
        return {"hochgeladen_at": datetime(2026, 10, 1, tzinfo=timezone.utc)} if self.schon else None

    async def fetchval(self, sql, *a):
        if "COUNT(*)" in sql:
            return self.vorhanden
        self.geschrieben.append(sql)
        return 7

    async def execute(self, sql, *a):
        self.geschrieben.append(sql)

    async def executemany(self, sql, zeilen):
        self.geschrieben.append(sql)
        self.zeilen = list(zeilen)


def _auszug(monkeypatch):
    auszug = leser.kontoauszug_lesen([_seite(ZWEI)])
    monkeypatch.setattr(leser, "lesen", lambda roh: auszug)


def _import(db, speichern):
    return asyncio.new_event_loop().run_until_complete(
        depot_router.importieren.__wrapped__(None, speichern=speichern, file=_Datei(),
                                             db=db, user={"id": 1}))


def test_die_vorschau_speichert_nichts_und_nennt_was_ersetzt_wird(monkeypatch):
    _auszug(monkeypatch)
    db = _DB(vorhanden=3)
    v = _import(db, speichern=False)
    assert v["anzahl"] == 2 and v["ersetzt"] == 3 and v["endsaldo"] == 107.40
    assert db.geschrieben == []


def test_uebernehmen_ersetzt_den_zeitraum_und_behaelt_das_pdf(monkeypatch):
    _auszug(monkeypatch)
    db = _DB()
    _import(db, speichern=True)
    assert db.geschrieben[0].startswith("DELETE FROM depot_buchungen")
    assert any("depot_import_dateien" in s for s in db.geschrieben)
    assert len(db.zeilen) == 2
    # Die Reihenfolge innerhalb eines Tages bleibt: beide am 28.07., 1 und 2.
    assert [z[3] for z in db.zeilen] == [1, 2]


def test_derselbe_auszug_kommt_kein_zweites_mal(monkeypatch):
    _auszug(monkeypatch)
    with pytest.raises(HTTPException):
        _import(_DB(schon=True), speichern=True)
