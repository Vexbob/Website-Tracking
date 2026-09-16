"""Tests fuer das Essenstagebuch (v1.97.0).

Der wichtigste Test hier ist ein negativer: **eine Menge kommt nicht durch.**
Bis v1.96.0 lagen Tagebuch und Tracker in derselben Tabelle, und der
Schreibweg hat den eingestellten Modus kein einziges Mal gelesen -- wer im
Tracker „100 g Haferflocken" eintrug, fand denselben Eintrag anschliessend im
Tagebuch. Jetzt gibt es im Eingabemodell gar kein Feld dafuer, und in der
Antwort kein Feld, in dem eine Zahl stehen koennte. Beides wird hier geprueft:
die Abwesenheit IST die Zusicherung.

Ohne Postgres laesst sich nicht pruefen, ob eine Abfrage richtig rechnet --
wohl aber, ob sie losgeschickt werden kann und was aus den Zeilen wird. Die
Attrappe antwortet wie die Datenbank und prueft dabei mit, dass die
Parameterzahl je Abfrage stimmt (dieses Muster hat im Schach-Modul einen
echten Fehler gefangen).
"""
import asyncio
import os
import re
import sys
from datetime import date, datetime, time, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from fastapi import HTTPException              # noqa: E402
from pydantic import ValidationError           # noqa: E402

from routers import tagebuch_router as tb      # noqa: E402
from services import food_mahlzeit as mz       # noqa: E402

NUTZER = {"id": 1}
HEUTE = date.today()

# Der Begrenzer (slowapi) will ein echtes Request-Objekt sehen. Geprueft wird
# die Wirkung der Endpunkte, nicht ihr Limit -- also die Funktion darunter.
EINTRAGEN = tb.eintragen.__wrapped__
AENDERN = tb.aendern.__wrapped__
ENTFERNEN = tb.entfernen.__wrapped__


def _zeile(**felder):
    basis = {
        "id": 1, "day": HEUTE, "label": "Müsli", "level": "normal",
        "meal": "fruehstueck", "note": None, "logged_time": time(8, 12),
        "meal_auto": False,
        "created_at": datetime(2026, 9, 17, 8, 12, tzinfo=timezone.utc),
    }
    basis.update(felder)
    return basis


class AttrappeDB:
    """Antwortet wie die Datenbank und prueft die Parameterzahl mit."""

    def __init__(self, zeilen=(), schnell=(), treffer=None):
        self.zeilen = list(zeilen)
        self.schnell = list(schnell)
        self.treffer = treffer
        self.geschrieben = []
        self.gelesen = []

    def _pruefe(self, sql, args):
        hoechste = max([int(n) for n in re.findall(r"[$](\d+)", sql)] or [0])
        assert hoechste == len(args), (
            f"SQL erwartet ${hoechste} Parameter, uebergeben wurden {len(args)}\n{sql}")

    async def fetch(self, sql, *args):
        self._pruefe(sql, args)
        self.gelesen.append(sql)
        if "GROUP BY lower(label)" in sql:
            return self.schnell
        return self.zeilen

    async def fetchrow(self, sql, *args):
        self._pruefe(sql, args)
        return self.treffer

    async def execute(self, sql, *args):
        self._pruefe(sql, args)
        self.geschrieben.append((sql, args))
        return "OK"


def _tag(zeilen=(), schnell=()):
    db = AttrappeDB(zeilen, schnell)
    return db, asyncio.run(tb._tag(db, NUTZER["id"], HEUTE))


# ==========================================================================
# Die Trennung — der gemeldete Fehler
# ==========================================================================
def test_eine_menge_kommt_gar_nicht_erst_ins_eingabemodell():
    """Gramm, Menge, Einheit, Lebensmittel: nichts davon gibt es hier.

    Pydantic laesst unbekannte Felder standardmaessig fallen -- das genuegt
    hier, weil der Router ausschliesslich aus dem Modell liest. Was zaehlt,
    ist dass keines dieser Felder je in der Zeile landet.
    """
    daten = tb.EintragEingabe(label="Haferflocken", level="normal",
                              grams=100, amount=2, unit="Scheibe", item_id=3)
    for feld in ("grams", "amount", "unit", "item_id", "dish_id"):
        assert not hasattr(daten, feld), f"{feld} darf es im Tagebuch nicht geben"


def test_der_tag_enthaelt_keine_einzige_zahl_ueber_das_essen():
    _, tag = _tag([_zeile()])
    for feld in ("totals", "targets", "macros", "macro_labels", "kcal"):
        assert feld not in tag, (
            f"'{feld}' steht in der Antwort -- das Tagebuch rechnet nicht")
    eintrag = tag["entries"][0]
    for feld in ("kcal_min", "kcal_max", "has_nutrition", "amount_label", "grams"):
        assert feld not in eintrag


def test_geschrieben_wird_nur_was_es_hier_gibt():
    db = AttrappeDB()
    asyncio.run(EINTRAGEN(
        request=None, daten=tb.EintragEingabe(label=" Müsli ", level="normal"),
        db=db, user=NUTZER))
    sql, args = db.geschrieben[0]
    assert "INSERT INTO food_diary" in sql
    for verboten in ("grams", "amount", "unit", "item_id", "dish_id"):
        assert verboten not in sql
    # Der Name wird getrimmt gespeichert.
    assert " Müsli " not in args and "Müsli" in args


# ==========================================================================
# Eintragen
# ==========================================================================
def test_ohne_namen_geht_es_nicht():
    for name in ("", "   "):
        with pytest.raises(HTTPException) as fehler:
            asyncio.run(EINTRAGEN(
                request=None, daten=tb.EintragEingabe(label=name, level="normal"),
                db=AttrappeDB(), user=NUTZER))
        assert fehler.value.status_code == 400


def test_zu_langer_name_wird_abgewiesen():
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(EINTRAGEN(
            request=None,
            daten=tb.EintragEingabe(label="x" * (tb.LABEL_MAX + 1), level="normal"),
            db=AttrappeDB(), user=NUTZER))
    assert fehler.value.status_code == 400
    assert "Notiz" in fehler.value.detail


def test_erfundene_stufe_faellt_auf():
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(EINTRAGEN(
            request=None, daten=tb.EintragEingabe(label="Pizza", level="sehr viel"),
            db=AttrappeDB(), user=NUTZER))
    assert fehler.value.status_code == 400
    assert "übermäßig" in fehler.value.detail


def test_erfundene_mahlzeit_faellt_auf():
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(EINTRAGEN(
            request=None,
            daten=tb.EintragEingabe(label="Brunch", level="normal", meal="brunch"),
            db=AttrappeDB(), user=NUTZER))
    assert fehler.value.status_code == 400
    assert "Frühstück" in fehler.value.detail


# ==========================================================================
# Die Mahlzeiten-Automatik
# ==========================================================================
def test_uhrzeit_faellt_auf_die_richtige_mahlzeit():
    for stunde, erwartet in ((0, "fruehstueck"), (10, "fruehstueck"),
                             (11, "mittag"), (14, "mittag"),
                             (15, "abend"), (20, "abend"),
                             (21, "snack"), (23, "snack")):
        assert mz.mahlzeit_fuer_uhrzeit(stunde) == erwartet, stunde


def test_kaputte_uhrzeit_ist_kein_fehler_sondern_keine_vermutung():
    for wert in (None, "", "abc", "25:00", "12", "12:99"):
        assert mz.uhrzeit_sauber(wert) is None
    assert mz.uhrzeit_sauber("08:05") == (8, 5)


def test_heute_wird_geraten_und_als_vermutung_markiert():
    db = AttrappeDB()
    asyncio.run(EINTRAGEN(
        request=None,
        daten=tb.EintragEingabe(label="Müsli", level="normal", at="08:12"),
        db=db, user=NUTZER))
    _, args = db.geschrieben[0]
    assert "fruehstueck" in args
    assert args[-1] is True, "meal_auto muss die Vermutung kenntlich machen"
    assert "08:12" in args


def test_an_einem_vergangenen_tag_wird_nicht_geraten():
    """„Es ist jetzt Abend" sagt nichts darueber, was letzten Dienstag war."""
    db = AttrappeDB()
    gestern = str(HEUTE - timedelta(days=1))
    asyncio.run(EINTRAGEN(
        request=None,
        daten=tb.EintragEingabe(label="Pasta", level="normal", at="19:30",
                                day=gestern),
        db=db, user=NUTZER))
    _, args = db.geschrieben[0]
    assert None in args, "ohne Zuordnung statt geraten"
    assert args[-1] is False


def test_der_ort_schlaegt_die_uhr():
    """Wer ueber das Plus einer Mahlzeit eintraegt, wird nicht gefragt."""
    db = AttrappeDB()
    asyncio.run(EINTRAGEN(
        request=None,
        daten=tb.EintragEingabe(label="Apfel", level="normal",
                                meal="snack", at="08:12"),
        db=db, user=NUTZER))
    _, args = db.geschrieben[0]
    assert "snack" in args and "fruehstueck" not in args
    assert args[-1] is False


# ==========================================================================
# Richtigstellen
# ==========================================================================
def test_stufe_laesst_sich_umschalten():
    db = AttrappeDB(treffer={"id": 5, "day": HEUTE})
    asyncio.run(AENDERN(request=None, eintrag_id=5,
                        daten=tb.EintragAendern(level="viel"),
                        db=db, user=NUTZER))
    sql, args = db.geschrieben[0]
    assert "UPDATE food_diary SET level=$3" in sql
    assert args == (5, 1, "viel")


def test_eine_gesetzte_mahlzeit_ist_keine_vermutung_mehr():
    db = AttrappeDB(treffer={"id": 5, "day": HEUTE})
    asyncio.run(AENDERN(request=None, eintrag_id=5,
                        daten=tb.EintragAendern(meal="abend"),
                        db=db, user=NUTZER))
    sql, _ = db.geschrieben[0]
    assert "meal_auto=FALSE" in sql


def test_fremder_eintrag_wird_nicht_gefunden():
    for aufruf in (
            lambda: AENDERN(request=None, eintrag_id=99,
                            daten=tb.EintragAendern(level="viel"),
                            db=AttrappeDB(treffer=None), user=NUTZER),
            lambda: ENTFERNEN(request=None, eintrag_id=99,
                              db=AttrappeDB(treffer=None), user=NUTZER)):
        with pytest.raises(HTTPException) as fehler:
            asyncio.run(aufruf())
        assert fehler.value.status_code == 404


# ==========================================================================
# Der Tag und die Schnellwahl
# ==========================================================================
def test_der_tag_zaehlt_nach_stufen_und_kennt_die_mahlzeiten():
    _, tag = _tag([_zeile(id=1, level="normal"),
                   _zeile(id=2, level="viel", meal=None),
                   _zeile(id=3, level="normal", meal="abend")])
    assert tag["counts"] == {"entries": 3, "normal": 2, "viel": 1}
    # Eine Zeile ohne Mahlzeit faellt in den eigenen Topf, nicht still unter
    # "Zwischendurch".
    assert tag["entries"][1]["meal"] == "ohne"
    assert [m["key"] for m in tag["meals"]][-1] == "ohne"
    # Die Grenzen gehen mit raus, damit das Frontend denselben Vorschlag
    # anzeigt, den der Server spaeter trifft.
    assert tag["meal_hours"] == {"fruehstueck": 11, "mittag": 15, "abend": 21}


def test_die_schnellwahl_fasst_schreibweisen_zusammen():
    db, tag = _tag([], schnell=[{"label": "Müsli", "anzahl": 43,
                                 "zuletzt": HEUTE}])
    assert tag["quick"] == [{"label": "Müsli", "count": 43, "last": HEUTE}]


def test_die_schnellwahl_gruppiert_kleingeschrieben():
    """Sonst stuenden „Müsli" und „müsli" als zwei Knoepfe nebeneinander.

    Ohne echte Datenbank ist die Abfrage selbst die pruefbare Zusicherung:
    gruppiert wird kleingeschrieben, herausgegeben die juengste Schreibweise.
    """
    db = AttrappeDB()
    asyncio.run(tb._schnellwahl(db, 1, 60, 6))
    sql = db.gelesen[0]
    assert "GROUP BY lower(label)" in sql
    assert "ARRAY_AGG(label ORDER BY day DESC)" in sql
    assert "FROM food_diary" in sql


def test_migration_046_wirft_kein_schema_weg():
    """Sie legt an und leert — sie baut nicht um.

    Der Umbau von ``food_log`` gehoert zur Etappe, in der auch die Oberflaeche
    des Trackers neu entsteht. Bis dahin muss die alte Seite weiterlaufen.
    """
    import pathlib
    datei = (pathlib.Path(__file__).resolve().parents[2]
             / "backend" / "migrations" / "sql" / "046_food_tagebuch.sql")
    text = datei.read_text(encoding="utf-8").upper()
    for verboten in ("DROP TABLE", "TRUNCATE", "DROP COLUMN"):
        assert verboten not in text, f"046 enthaelt {verboten}"
    assert "CREATE TABLE IF NOT EXISTS FOOD_DIARY" in text
