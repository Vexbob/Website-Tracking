"""CS2-Modul — was sich ohne Datenbank pruefen laesst.

Drei Gruppen, nach dem Muster von ``test_chess.py``:

1. **Die reine Rechnung** -- direkt aufgerufen, ohne alles.
2. **Die Abfragen des Routers gegen eine Attrappe.** Ob eine Abfrage RICHTIG
   rechnet, sieht man ohne Postgres nicht; ob sie ueberhaupt losgeschickt
   werden kann, sehr wohl.
3. **Zwei Waechter ueber der Migration.** Sie halten den teuersten Fehler
   fest, den dieses Modul hatte -- siehe ``test_die_signatur_faengt_auch_leere_abnutzung``.
"""
import asyncio
import os
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

import pytest                                              # noqa: E402
from services import cs2_rechnung as r                     # noqa: E402

BACKEND = pathlib.Path(__file__).resolve().parent.parent
# =========================================================================
# 1. Die Rechnung
# =========================================================================

def test_brutto_ist_menge_mal_preis():
    assert r.brutto(33, Decimal("4.14")) == Decimal("136.62")


def test_fehlende_angabe_ist_nicht_null():
    """Eine angefangene Zeile ist keine Zeile ueber null Euro."""
    assert r.brutto(None, Decimal("4.14")) is None
    assert r.brutto(33, None) is None


def test_netto_zieht_die_gebuehr_ab():
    assert r.netto(Decimal("136.62")) == Decimal("116.13")


def test_summe_zaehlt_unvollstaendige_getrennt():
    summe = r.summiere([
        {"quantity": 2, "price_eur": Decimal("10.00"), "playskin": False},
        {"quantity": None, "price_eur": Decimal("5.00"), "playskin": False},
        {"quantity": 1, "price_eur": None, "playskin": False},
    ])
    assert summe["brutto"] == Decimal("20.00")
    assert summe["positionen"] == 1
    assert summe["unvollstaendig"] == 2


def test_netto_summiert_sich_aus_den_zeilen():
    """Die Kopfzahl muss sich aus der Liste darunter aufaddieren.

    Bei 0,07 EUR je Position sind Einzelrundung und Endrundung verschieden:
    3 x 0,06 = 0,18 gegen 0,85 x 0,21 = 0,18 -- hier gleich. Bei 0,03:
    3 x 0,03 = 0,09 gegen 0,85 x 0,09 = 0,08. Genau dieser Fall wird geprueft.
    """
    zeilen = [{"quantity": 1, "price_eur": Decimal("0.03"), "playskin": False}] * 3
    summe = r.summiere(zeilen)
    einzeln = sum(r.netto(r.brutto(z["quantity"], z["price_eur"])) for z in zeilen)
    assert summe["netto"] == einzeln


def test_playskin_zaehlt_im_gesamtwert_mit():
    summe = r.summiere([
        {"quantity": 1, "price_eur": Decimal("100.00"), "playskin": True},
        {"quantity": 1, "price_eur": Decimal("50.00"), "playskin": False},
    ])
    assert summe["brutto"] == Decimal("150.00")
    assert summe["playskin_brutto"] == Decimal("100.00")
    assert summe["invest_brutto"] == Decimal("50.00")
    assert summe["playskin_brutto"] + summe["invest_brutto"] == summe["brutto"]


@pytest.mark.parametrize("eingabe,erwartet", [
    ("1.234,56", "1234.56"), ("1234.56", "1234.56"), ("12,34 €", "12.34"),
    ("16,10", "16.10"), ("4.14", "4.14"), ("0", "0.00"),
])
def test_preis_lesen(eingabe, erwartet):
    assert r.preis_lesen(eingabe) == Decimal(erwartet)


@pytest.mark.parametrize("murks", ["", "   ", "abc", "€"])
def test_preis_lesen_sagt_auf_deutsch_was_fehlt(murks):
    with pytest.raises(ValueError) as fehler:
        r.preis_lesen(murks)
    # Der Satz landet unveraendert im Toast -- er muss einer sein.
    assert str(fehler.value).endswith((".", "!"))


def test_kein_preis_ist_kein_alter_preis():
    """Vier Stufen, und ``ohne`` ist eine eigene."""
    jetzt = datetime(2026, 9, 22, tzinfo=timezone.utc)
    assert r.frische(None, jetzt) == "ohne"
    assert r.frische(jetzt - timedelta(days=1), jetzt) == "frisch"
    assert r.frische(jetzt - timedelta(days=30), jetzt) == "alt"
    assert r.frische(jetzt - timedelta(days=60), jetzt) == "sehr_alt"


def test_alter_kommt_auch_mit_einer_zeichenkette_zurecht():
    jetzt = datetime(2026, 9, 22, tzinfo=timezone.utc)
    assert r.alter_in_tagen("2026-09-12T00:00:00+00:00", jetzt) == 10


@pytest.mark.parametrize("roh,erwartet", [
    ("ak-47 | frontside misty", "AK-47 | Frontside Misty"),
    ("m4a1-s|printstream", "M4A1-S | Printstream"),
    ("  chroma   3  ", "Chroma 3"),
    ("five-seven | case hardened", "Five-SeveN | Case Hardened"),
    ("sawad-off | the kraken", "Sawed-Off | The Kraken"),
])
def test_schreibweise_wird_vereinheitlicht(roh, erwartet):
    """Zwei Schreibweisen desselben Skins waeren zwei Gegenstaende."""
    assert r.item_name(roh) == erwartet


def test_markt_name_setzt_die_teile_zusammen():
    assert r.markt_name("AK-47 | Frontside Misty", "FT", True) \
        == "StatTrak™ AK-47 | Frontside Misty (Field-Tested)"
    assert r.markt_name("Chroma 3", None, False) == "Chroma 3"


# =========================================================================
# 3. Die Abfragen gegen eine Attrappe
# =========================================================================

class AttrappeDB:
    """Antwortet auf die Abfragen des Routers mit plausiblen Zeilen.

    Sie prueft dabei zwei Dinge, die ohne Postgres sichtbar sind: ob die Zahl
    der Platzhalter zur Zahl der Werte passt, und ob ein ``$n`` uebersprungen
    wurde. Beides sind Fehler, die erst zur Laufzeit auffallen -- und dann an
    einer Seite, die leer bleibt.
    """

    def __init__(self):
        self.abfragen = []

    def _pruefe(self, sql, args):
        nummern = sorted({int(n) for n in re.findall(r"\$(\d+)", sql)})
        assert not nummern or nummern == list(range(1, len(nummern) + 1)), \
            f"Platzhalter mit Luecke: {nummern}\n{sql}"
        assert len(nummern) == len(args), \
            f"SQL erwartet {len(nummern)} Werte, uebergeben wurden {len(args)}\n{sql}"
        self.abfragen.append(sql)

    async def fetch(self, sql, *args):
        self._pruefe(sql, args)
        if "FROM cs2_categories" in sql:
            return [{"id": 1, "name": "Skin", "supports_wear": True,
                     "supports_stattrak": True, "supports_playskin": True,
                     "sort_order": 0}]
        if "FROM cs2_items" in sql:
            return [{"id": 3, "category_id": 1, "name": "AK-47 | Frontside Misty",
                     "positionen": 1}]
        if "FROM cs2_snapshots" in sql:
            return []
        return [{"id": 11, "item_id": 3, "wear": "FT",
                 "stattrak": False, "playskin": False, "quantity": 2,
                 "price_eur": Decimal("16.10"),
                 "priced_at": datetime.now(timezone.utc), "created_at": None,
                 "item_name": "AK-47 | Frontside Misty", "category_id": 1,
                 "category_name": "Skin", "brutto": Decimal("32.20")}]

    async def fetchrow(self, sql, *args):
        zeilen = await self.fetch(sql, *args)
        return zeilen[0] if zeilen else None

    async def fetchval(self, sql, *args):
        self._pruefe(sql, args)
        return 1


def _router():
    from routers import cs2_router
    return cs2_router


def test_filter_und_liste_bauen_dieselbe_klausel():
    """Die eine Regel dieses Moduls: EINE Grundgesamtheit.

    Liste und Kopfzahlen rufen beide ``_bestand_filter``. Waechst dort
    eine zweite Fassung heran, faellt es hier auf und nicht an einer Zahl.
    """
    cr = _router()
    wo_a, werte_a = cr._bestand_filter(1, "ak", "2,3", True)
    wo_b, werte_b = cr._bestand_filter(1, "ak", "2,3", True)
    assert wo_a == wo_b and werte_a == werte_b
    # Jeder Platzhalter muss einen Wert haben.
    nummern = sorted({int(n) for n in re.findall(r"\$(\d+)", wo_a)})
    assert nummern == list(range(1, len(werte_a) + 1))


def test_filter_laesst_sich_versetzt_einhaengen():
    """``ab_index`` erlaubt vorangestellte Parameter, ohne die Klausel zu kopieren."""
    cr = _router()
    wo, werte = cr._bestand_filter(1, "ak", None, False, ab_index=3)
    nummern = sorted({int(n) for n in re.findall(r"\$(\d+)", wo)})
    assert nummern[0] == 3
    assert len(nummern) == len(werte)


def test_id_liste_verwirft_unlesbares_still():
    cr = _router()
    assert cr._id_liste("3, 7 ,9") == [3, 7, 9]
    assert cr._id_liste("3,abc,9") == [3, 9]
    assert cr._id_liste(None) == []


def test_ueberblick_laeuft_durch():
    cr = _router()
    db = AttrappeDB()
    antwort = asyncio.run(cr.ueberblick(db=db, user={"id": 1}))
    assert antwort["bestand"]["brutto"] == 32.20
    assert antwort["bestand"]["netto"] == 27.37
    assert antwort["je_kategorie"][0]["name"] == "Skin"
    assert "je_lager" not in antwort, "Die Lageraufteilung ist mit 052 weggefallen"


def test_liste_sagt_wenn_sie_kuerzt():
    cr = _router()
    db = AttrappeDB()
    antwort = asyncio.run(cr.positionen(db=db, user={"id": 1}))
    assert antwort["gezeigt"] == len(antwort["positionen"])
    assert "gekuerzt" in antwort


def test_sortierung_faellt_auf_wert_zurueck():
    """Eine erfundene Sortierung darf keine SQL-Zeichenkette ins Feld lassen."""
    cr = _router()
    for spalte in ("name", "preis", "wert", "menge", "typ", "alter"):
        assert spalte in cr.SORTIERSPALTEN, f"Spalte {spalte} fehlt der Tabelle"
    boese = "; DROP TABLE cs2_positions --"
    assert boese not in cr._ordnung(boese, boese)
    assert cr._ordnung(boese, boese) == cr._ordnung(cr.STANDARD_SORTIERUNG, "ab")
    # Leere Werte sind immer die kleinsten: Postgres sortiert NULL sonst als
    # groessten, und eine Position ohne Preisstand ist die aelteste, nicht die
    # juengste.
    assert "NULLS FIRST" in cr._ordnung("alter", "auf")
    assert "NULLS LAST" in cr._ordnung("wert", "ab")
    for spalte in cr.SORTIERSPALTEN:
        assert cr._ordnung(spalte, "ab").endswith("i.name ASC")


def test_regeln_raeumen_statt_abzulehnen():
    """Ein Case hat keine Abnutzung -- die Angabe faellt weg, die Position entsteht."""
    cr = _router()
    ohne = {"supports_wear": False, "supports_stattrak": False, "supports_playskin": False}
    assert cr._regeln_anwenden(ohne, "FT", True, True) == (None, False, False)
    mit = {"supports_wear": True, "supports_stattrak": True, "supports_playskin": True}
    assert cr._regeln_anwenden(mit, "FT", True, False) == ("FT", True, False)


SQL_051 = BACKEND / "migrations" / "sql" / "051_cs2.sql"
SQL_052 = BACKEND / "migrations" / "sql" / "052_cs2_ohne_lager.sql"


def _ohne_kommentare(pfad) -> str:
    """Nur der Code. Die Koepfe dieser Dateien nennen die Gegenbeispiele
    ausdruecklich -- danach darf ein Waechter nicht suchen."""
    return "\n".join(z for z in pfad.read_text(encoding="utf-8").splitlines()
                     if not z.lstrip().startswith("--"))


def test_die_signatur_traegt_kein_lager_mehr():
    """Nach 052 ist die Signatur (Nutzer, Gegenstand, Wear, StatTrak, Playskin).

    Bleibt irgendwo ein ``storage_id`` stehen, findet das ``ON CONFLICT`` den
    Index nicht mehr -- und der Import legt dann Dubletten an, statt
    zusammenzufuehren.
    """
    sql = _ohne_kommentare(SQL_052)
    assert "DROP COLUMN IF EXISTS storage_id" in sql
    assert "DROP TABLE IF EXISTS cs2_storages" in sql
    assert "COALESCE(wear, \'\'::text), stattrak, playskin)" in sql
    for datei in (BACKEND / "routers" / "cs2_router.py",
                  BACKEND / "services" / "cs2_transfer.py",
                  BACKEND / "services" / "cs2_export.py"):
        code = "\n".join(z for z in datei.read_text(encoding="utf-8").splitlines()
                         if not z.lstrip().startswith("#"))
        assert "storage_id" not in code, f"{datei.name} kennt noch storage_id"
        assert "cs2_storages" not in code, f"{datei.name} kennt noch cs2_storages"


def test_die_signatur_faengt_auch_leere_abnutzung():
    """Der teuerste Fehler dieses Moduls, als Waechter.

    Postgres haelt zwei NULL fuer verschieden. Ein ``UNIQUE (…, wear, …)`` an
    der Tabelle laesst deshalb beliebig viele gleiche Zeilen zu, sobald ``wear``
    leer ist -- und leer ist es bei jeder Kategorie ausser Skin. Beim zweiten
    Lauf der Uebernahme waren dadurch 57 von 116 Zeilen gedoppelt, und
    ``ON CONFLICT`` fuehrte dort nie zusammen. Sichtbar war davon nur eine zu
    hohe Gesamtsumme.
    """
    sql = _ohne_kommentare(SQL_051) + "\n" + _ohne_kommentare(SQL_052)
    # Mit ``::text``: genau so legt Postgres den Ausdruck im Index ab, und nur
    # so findet ein ``ON CONFLICT`` ihn wieder.
    assert "COALESCE(wear, \'\'::text)" in sql, \
        "Die Signatur muss COALESCE(wear, \'\'::text) tragen -- ohne das zaehlt " \
        "NULL als eigener Wert, mit fehlendem ::text findet ON CONFLICT den Index nicht"
    # Ein blankes UNIQUE ueber dieselben Spalten waere der Rueckfall.
    assert "UNIQUE (user_id, item_id, wear" not in sql


def test_jedes_on_conflict_auf_positionen_nennt_denselben_ausdruck():
    """Ein ``ON CONFLICT``, das den Ausdruck nicht nennt, findet den Index nicht."""
    import re as _re
    for datei in (BACKEND / "routers" / "cs2_router.py",
                  BACKEND / "services" / "cs2_export.py"):
        text = datei.read_text(encoding="utf-8")
        # Bis zum Zeilenende lesen, nicht bis zur ersten Klammer -- die
        # gehoert inzwischen zu COALESCE.
        for treffer in _re.findall(r"ON CONFLICT \(.*item_id.*", text):
            assert "COALESCE(wear, \'\'::text)" in treffer, f"{datei.name}: {treffer}"


def test_unbekannte_abnutzung_wird_abgelehnt():
    cr = _router()
    from fastapi import HTTPException
    mit = {"supports_wear": True, "supports_stattrak": False, "supports_playskin": False}
    with pytest.raises(HTTPException) as fehler:
        cr._regeln_anwenden(mit, "XX", False, False)
    assert fehler.value.status_code == 400


# =========================================================================
# 4. Die Uebernahme aus einer Datei
# =========================================================================

from services import cs2_transfer as t                      # noqa: E402


def _dok(**mehr) -> dict:
    d = {"modul": "cs2", "fassung": t.FASSUNG, "positionen": []}
    d.update(mehr)
    return d


def test_fremde_datei_wird_mit_einem_satz_abgelehnt():
    """Die Meldung landet im Toast -- sie muss ein Satz sein, kein Code."""
    for murks, stueck in [
        ({"modul": "musik", "fassung": 1, "positionen": []}, "Modul"),
        (_dok(fassung=99), "Fassung"),
        ({"modul": "cs2", "fassung": t.FASSUNG}, "positionen"),
        ("kein Objekt", "Übertragungsdokument"),
    ]:
        with pytest.raises(t.TransferFehler) as fehler:
            t.pruefen(murks)
        assert stueck in str(fehler.value)
        assert str(fehler.value).endswith((".", "!"))


def test_eine_position_ohne_namen_bricht_den_ganzen_lauf():
    """Halb gelesen waere schlimmer als abgelehnt: man saehe nicht, was fehlt."""
    with pytest.raises(t.TransferFehler) as fehler:
        t.pruefen(_dok(positionen=[
            {"kategorie": "Skin", "gegenstand": "AK-47 | X", "menge": 1},
            {"kategorie": "Skin", "gegenstand": "  ", "menge": 1},
        ]))
    assert "Position 2" in str(fehler.value)


@pytest.mark.parametrize("feld,wert,stueck", [
    ("wear", "XX", "Abnutzung"),
    ("menge", "viele", "Stückzahl"),
    ("menge", -3, "unter null"),
    ("preis", "abc", "Betrag"),
    ("preis", "-5", "unter null"),
    ("preis_am", "irgendwann", "Zeitpunkt"),
])
def test_jede_unlesbare_angabe_nennt_ihre_position(feld, wert, stueck):
    p = {"kategorie": "Case", "gegenstand": "Chroma 3", "menge": 1}
    p[feld] = wert
    with pytest.raises(t.TransferFehler) as fehler:
        t.pruefen(_dok(positionen=[p]))
    assert stueck in str(fehler.value) and "Position 1" in str(fehler.value)


def test_gelesene_angaben_haben_die_richtigen_typen():
    daten = t.pruefen(_dok(positionen=[{
        "kategorie": "Skin", "gegenstand": "AK-47 | Frontside Misty", "wear": "FT",
        "stattrak": False, "playskin": True,
        "menge": "3", "preis": "16.10", "preis_am": "2026-09-22T10:13:16+00:00",
    }]))
    p = daten["positionen"][0]
    assert p["menge"] == 3 and isinstance(p["menge"], int)
    assert p["preis"] == Decimal("16.10")
    assert p["preis_am"].tzinfo is not None
    assert p["playskin"] is True


def test_ein_zeitpunkt_ohne_zone_gilt_als_utc():
    """Sonst verschiebt sich das Preisalter um die Zeitzone des Rechners."""
    daten = t.pruefen(_dok(positionen=[{
        "kategorie": "Case", "gegenstand": "Chroma 3", "menge": 1,
        "preis": "1.00", "preis_am": "2026-09-22T10:00:00"}]))
    assert daten["positionen"][0]["preis_am"].tzinfo is not None


# =========================================================================
# 4b. Was mit dem Wegfall der Lager dazukam
# =========================================================================

def test_fassung_eins_bleibt_lesbar():
    """Eine Datei von vor dem Wegfall der Lager darf nicht wertlos werden.

    Das ``lager`` an der Position gehoert nicht mehr zur Signatur. Es
    abzulehnen waere haerter als noetig -- ein Feld zu viel macht eine Datei
    nicht unlesbar.
    """
    daten = t.pruefen({
        "modul": "cs2", "fassung": 1,
        "positionen": [{"kategorie": "Case", "gegenstand": "Chroma 3",
                        "lager": "Cases_1", "menge": 3, "preis": "4.14"}],
    })
    assert len(daten["positionen"]) == 1
    assert "lager" not in daten["positionen"][0]
    assert daten["positionen"][0]["menge"] == 3


def test_zeilen_die_sich_nur_im_lager_unterschieden_werden_addiert():
    """Der stille Verlust, den es zu verhindern gilt.

    In Fassung 1 stand derselbe Gegenstand in zwei Lagern als zwei Zeilen.
    Ohne Zusammenfuehren traefen beide beim Import auf dieselbe Signatur, die
    zweite ueberschriebe die erste -- und der Bestand haette hinterher weniger
    Stuecke, ohne dass es irgendwo steht.
    """
    daten = t.pruefen({
        "modul": "cs2", "fassung": 1,
        "positionen": [
            {"kategorie": "Case", "gegenstand": "Chroma 3", "lager": "Cases_1",
             "menge": 3, "preis": "4.14", "preis_am": "2026-09-01T10:00:00+00:00"},
            {"kategorie": "Case", "gegenstand": "Chroma 3", "lager": "Cases_2",
             "menge": 30, "preis": "4.20", "preis_am": "2026-09-20T10:00:00+00:00"},
        ],
    })
    assert len(daten["positionen"]) == 1
    assert daten["zusammengefuehrt"] == 1
    # Mengen addiert, Preis vom juengeren Stand.
    assert daten["positionen"][0]["menge"] == 33
    assert daten["positionen"][0]["preis"] == Decimal("4.20")


def test_zusammenfuehren_kommt_mit_fehlenden_angaben_klar():
    """Eine angefangene Zeile ist ein regulaerer Zustand, auch hier."""
    daten = t.pruefen({
        "modul": "cs2", "fassung": 1,
        "positionen": [
            {"kategorie": "Case", "gegenstand": "Fever", "lager": "A"},
            {"kategorie": "Case", "gegenstand": "Fever", "lager": "B", "menge": 5,
             "preis": "0.77"},
        ],
    })
    p = daten["positionen"][0]
    assert p["menge"] == 5 and p["preis"] == Decimal("0.77")


def test_staende_werden_geprueft_statt_durchgereicht():
    """Sie liefen bis v2.14.0 ungeprueft durch -- die erste Datei hatte keine.

    Ein unlesbares Datum scheiterte dann erst beim Einfuegen, mit einer
    Meldung aus dem Datenbanktreiber statt einem Satz, der die Zeile nennt.
    """
    with pytest.raises(t.TransferFehler) as fehler:
        t.pruefen(_dok(staende=[{"datum": "irgendwann"}]))
    assert "Stand 1" in str(fehler.value) and "Datum" in str(fehler.value)

    with pytest.raises(t.TransferFehler) as fehler:
        t.pruefen(_dok(staende=[{"datum": "2026-09-22", "brutto": "viel"}]))
    assert "Stand 1" in str(fehler.value)


def test_ein_stand_kommt_als_datum_heraus_nicht_als_text():
    """asyncpg leitet aus ``$1::date`` den Typ ab und lehnt Text dann ab."""
    from datetime import date as _date
    daten = t.pruefen(_dok(staende=[{
        "datum": "2026-09-22", "brutto": "3089.81", "netto": "2626.40",
        "positionen": 116, "je_kategorie": {"Case": "2520.21"},
    }]))
    s = daten["staende"][0]
    assert isinstance(s["datum"], _date)
    assert s["brutto"] == Decimal("3089.81")
    assert s["je_kategorie"]["Case"] == Decimal("2520.21")
    assert s["veraltet"] == 0


def test_kopfzahl_und_liste_zaehlen_dieselbe_menge():
    """Ueber einer Liste mit 116 Eintraegen darf nicht die Zahl 113 stehen.

    ``positionen`` sind die, die einen Wert beitragen -- eine andere Frage.
    Die Kopfzahl nennt ``zeilen``, und wie viele davon unvollstaendig sind,
    steht daneben.
    """
    s = r.summiere([
        {"quantity": 2, "price_eur": Decimal("16.10")},
        {"quantity": None, "price_eur": Decimal("1.00")},
        {"quantity": 5, "price_eur": None},
    ])
    assert s["zeilen"] == 3
    assert s["positionen"] == 1
    assert s["unvollstaendig"] == 2
    assert s["zeilen"] == s["positionen"] + s["unvollstaendig"]
