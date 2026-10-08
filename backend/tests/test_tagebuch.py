"""Tests fuer das Essenstagebuch (v1.97.0).

Der wichtigste Test hier ist ein negativer: **eine Menge kommt nicht durch.**
Bis v1.96.0 lagen Tagebuch und Tracker in derselben Tabelle, und der
Schreibweg hat den eingestellten Modus kein einziges Mal gelesen -- wer im
Tracker „100 g Haferflocken“ eintrug, fand denselben Eintrag anschliessend im
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
        # Die Schnellwahl liest Rohzeilen ueber zwei Monate (v2.33.0).
        if "ORDER BY day DESC" in sql:
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
    assert time(8, 12) in args


def test_an_einem_vergangenen_tag_wird_nicht_geraten():
    """„Es ist jetzt Abend“ sagt nichts darueber, was letzten Dienstag war."""
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
    assert time(19, 30) not in args and "19:30" not in args, (
        "Die Browser-Uhr sagt, wie spaet es JETZT ist. An einem vergangenen "
        "Tag ist das die Tippzeit und keine Essenszeit -- sie darf nicht als "
        "Uhrzeit an der Zeile stehen.")


def test_heute_behaelt_die_uhrzeit():
    """Die Gegenprobe: am selben Tag ist die Uhr genau das, was sie sagt."""
    db = AttrappeDB()
    asyncio.run(EINTRAGEN(
        request=None,
        daten=tb.EintragEingabe(label="Pasta", level="normal", at="19:30"),
        db=db, user=NUTZER))
    _, args = db.geschrieben[0]
    assert time(19, 30) in args


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


def test_die_uhrzeit_laesst_sich_richtigstellen():
    """v2.42.0: war die Mahlzeit nur aus der Uhrzeit geraten, raet die neue
    Uhrzeit sie neu; eine von Hand gesetzte bleibt."""
    db = AttrappeDB(treffer={"id": 5, "day": HEUTE, "meal_auto": True})
    asyncio.run(AENDERN(request=None, eintrag_id=5, daten=tb.EintragAendern(time="19:30"),
                        db=db, user=NUTZER))
    sql, args = db.geschrieben[0]
    assert "logged_time=$3" in sql and args[2] == time(19, 30)
    assert "meal=$4" in sql and args[3] == mz.mahlzeit_fuer_uhrzeit(19)

    db = AttrappeDB(treffer={"id": 5, "day": HEUTE, "meal_auto": False})
    asyncio.run(AENDERN(request=None, eintrag_id=5, daten=tb.EintragAendern(time="07:05"),
                        db=db, user=NUTZER))
    sql, args = db.geschrieben[0]
    assert "logged_time=$3" in sql and "meal=" not in sql


def test_die_uhrzeit_laesst_sich_wegnehmen_aber_nicht_verstuemmeln():
    db = AttrappeDB(treffer={"id": 5, "day": HEUTE, "meal_auto": True})
    asyncio.run(AENDERN(request=None, eintrag_id=5, daten=tb.EintragAendern(time=""),
                        db=db, user=NUTZER))
    sql, args = db.geschrieben[0]
    assert "logged_time=$3" in sql and args[2] is None and "meal=" not in sql
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(AENDERN(request=None, eintrag_id=5, daten=tb.EintragAendern(time="halb acht"),
                            db=AttrappeDB(treffer={"id": 5, "day": HEUTE, "meal_auto": False}), user=NUTZER))
    assert fehler.value.status_code == 400


def test_herausgenommene_lebensmittel_fehlen_in_der_schnellwahl():
    db = AttrappeDB()
    asyncio.run(tb._schnellwahl(db, 1, 60, 6))
    assert "food_diary_ausgeblendet" in db.gelesen[0]


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


def _roh(label, tage_her=0, meal="mittag", uhr=None):
    """Eine Rohzeile, wie die Schnellwahl sie liest."""
    return {"label": label, "day": HEUTE - timedelta(days=tage_her),
            "meal": meal, "logged_time": uhr}


def test_die_schnellwahl_fasst_schreibweisen_zusammen():
    """Sonst stuenden „Müsli“ und „müsli“ als zwei Knoepfe nebeneinander.
    Herausgegeben wird die juengste Schreibweise."""
    zeilen = [_roh("Müsli", 0), _roh("müsli", 1), _roh("Müsli", 2)]
    assert tb.schnellwahl_rang(zeilen, 6) == [
        {"label": "Müsli", "count": 3, "last": HEUTE}]


def test_die_schnellwahl_liest_rohzeilen_neueste_zuerst():
    db = AttrappeDB(schnell=[_roh("Kaffee", 0), _roh("Kaffee", 1), _roh("Apfel", 3)])
    tag = asyncio.run(tb._tag(db, NUTZER["id"], HEUTE))
    assert [q["label"] for q in tag["quick"]] == ["Kaffee", "Apfel"]
    sql = next(s for s in db.gelesen if "ORDER BY day DESC" in s)
    assert "FROM food_diary" in sql and "user_id=$1" in sql


def _gewohnheit():
    """Zwanzig Tage: Kaffee jeden Morgen, Pasta jeden Mittag (seltener)."""
    zeilen = []
    for t in range(20):
        zeilen.append(_roh("Kaffee", t, "fruehstueck", time(8, 10)))
        zeilen.append(_roh("Kaffee", t, "fruehstueck", time(8, 40)))
        zeilen.append(_roh("Pasta", t, "mittag", time(12, 30)))
    return zeilen


def test_mittags_kommt_zuerst_was_man_mittags_isst():
    rang = tb.schnellwahl_rang(_gewohnheit(), 6, jetzt=(12, 45))
    assert [q["label"] for q in rang] == ["Pasta", "Kaffee"]
    # Morgens ist es umgekehrt -- und ohne Uhr zaehlt nur die Haeufigkeit.
    assert [q["label"] for q in tb.schnellwahl_rang(_gewohnheit(), 6, jetzt=(8, 0))] == [
        "Kaffee", "Pasta"]
    assert [q["label"] for q in tb.schnellwahl_rang(_gewohnheit(), 6)] == [
        "Kaffee", "Pasta"]


def test_ab_der_fuenften_nennung_um_diese_zeit_rueckt_es_vor():
    """Vier Mittage sind keine Gewohnheit, der fuenfte macht eine: bis dahin
    bleibt es bei der Rangfolge nach Haeufigkeit."""
    def mittag(n):
        return ([_roh("Pasta", t, "mittag", time(12, 30)) for t in range(n)]
                + [_roh("Kaffee", t, "fruehstueck", time(8, 10)) for t in range(40)])
    assert tb.ZEIT_AB == 5
    assert tb.schnellwahl_rang(mittag(4), 6, jetzt=(12, 45))[0]["label"] == "Kaffee"
    assert tb.schnellwahl_rang(mittag(5), 6, jetzt=(12, 45))[0]["label"] == "Pasta"


def test_gewohntes_steht_nach_der_zahl_um_diese_zeit_geordnet():
    zeilen = ([_roh("Salat", t, "mittag", time(12, 0)) for t in range(6)]
              + [_roh("Pasta", t, "mittag", time(13, 0)) for t in range(9)]
              + [_roh("Kaffee", t, "fruehstueck", time(8, 0)) for t in range(40)]
              + [_roh("Apfel", t, "snack", time(16, 0)) for t in range(12)])
    assert [q["label"] for q in tb.schnellwahl_rang(zeilen, 6, jetzt=(12, 30))] == [
        "Pasta", "Salat", "Kaffee", "Apfel"]


def test_das_zeitfenster_reicht_ueber_mitternacht():
    zeilen = [_roh("Tee", t, "snack", time(23, 40)) for t in range(25)]
    zeilen += [_roh("Kaffee", t, "fruehstueck", time(8, 0)) for t in range(30)]
    assert tb.schnellwahl_rang(zeilen, 6, jetzt=(0, 30))[0]["label"] == "Tee"


def test_ohne_uhrzeit_zaehlt_die_mahlzeit():
    """Nachgetragene Tage haben keine Uhrzeit -- dort entscheidet die Mahlzeit."""
    zeilen = [_roh("Suppe", t, "abend") for t in range(25)]
    zeilen += [_roh("Kaffee", t, "fruehstueck") for t in range(40)]
    assert tb.schnellwahl_rang(zeilen, 6, jetzt=(19, 0))[0]["label"] == "Suppe"


def test_was_in_dieser_mahlzeit_schon_steht_macht_platz():
    """Ein angetippter Vorschlag verschwindet, der naechste rueckt nach --
    aber nur fuer die Mahlzeit von jetzt: der Morgenkaffee kommt am
    Nachmittag wieder."""
    db = AttrappeDB(
        zeilen=[_zeile(id=1, label="Pasta", meal="mittag", logged_time=time(12, 30)),
                _zeile(id=2, label="Kaffee", meal="fruehstueck")],
        schnell=_gewohnheit() + [_roh("Apfel", 1, "snack", time(16, 0))])
    tag = asyncio.run(tb._tag(db, NUTZER["id"], HEUTE, (12, 45)))
    namen = [q["label"] for q in tag["quick"]]
    assert "Pasta" not in namen
    assert "Kaffee" in namen and "Apfel" in namen


def test_an_einem_vergangenen_tag_zaehlt_die_uhr_nicht():
    gestern = HEUTE - timedelta(days=1)
    db = AttrappeDB(zeilen=[_zeile(id=1, day=gestern, label="Kaffee")],
                    schnell=_gewohnheit())
    tag = asyncio.run(tb._tag(db, NUTZER["id"], gestern, (12, 45)))
    # Kein Uhrzeit-Rang (sonst stuende Pasta vorn), und was an dem Tag
    # schon steht, faellt weg.
    assert [q["label"] for q in tag["quick"]] == ["Pasta"]


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
