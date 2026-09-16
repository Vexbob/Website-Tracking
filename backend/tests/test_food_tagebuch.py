"""Tests fuer das Ernaehrungs-Tagebuch mit seinen zwei Modi (v1.94.0).

Ohne Postgres laesst sich nicht pruefen, ob eine Abfrage richtig RECHNET --
wohl aber, ob sie ueberhaupt losgeschickt werden kann und ob aus den Zeilen
das Richtige wird. Die Attrappe unten antwortet wie die Datenbank und prueft
dabei mit, dass die Parameterzahl je Abfrage stimmt.

Worum es inhaltlich geht:

  * Ein **freier Eintrag** ("Pizza beim Italiener") hat keine Naehrwerte. Er
    muss im Tag stehen, gezaehlt werden und in der Summe FEHLEN -- erfundene
    Kalorien waeren schlimmer als eine ausgewiesene Luecke.
  * Ein **eigenes Tagesziel** ersetzt den allgemeinen Richtwert, aber nur da,
    wo eines gesetzt ist.
  * Der **Verlauf** fuellt Tage ohne Eintrag auf: eine Luecke, die man nicht
    sieht, wird zu einem Tag, den es nie gab.
"""
import asyncio
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from fastapi import HTTPException          # noqa: E402

from routers import food_router as fr      # noqa: E402
from services import food_calc as calc     # noqa: E402

NUTZER = {"id": 1}
HEUTE = date.today()


def _zeile(**felder):
    """Eine Tagebuchzeile, wie sie aus dem JOIN kommt."""
    basis = {
        "id": 1, "level": None, "meal": None, "note": None, "label": None,
        "created_at": datetime(2026, 9, 16, 12, tzinfo=timezone.utc), "day": HEUTE,
        "dish_id": None, "item_id": None, "amount": None, "unit": None,
        "grams": None, "dish_name": None, "item_name": None, "item_brand": None,
        "portion_g": None, "base_unit": "g", "kcal": None, "protein_g": None,
        "fiber_g": None, "carbs_g": None, "fat_g": None,
    }
    basis.update(felder)
    return basis


# Ein Gericht mit 600 kcal je Portion, ein Lebensmittel mit 250 kcal/100 g.
GERICHT = _zeile(id=1, dish_id=7, dish_name="Wraps", level="normal", meal="mittag")
LEBENSMITTEL = _zeile(id=2, item_id=3, item_name="Brot", item_brand="Bäcker",
                      grams=90, amount=2, unit="Scheibe", meal="fruehstueck",
                      kcal=250, protein_g=8, fiber_g=5, carbs_g=45, fat_g=2)
FREI = _zeile(id=3, label="Pizza beim Italiener", level="viel", meal="abend")


class AttrappeDB:
    """Antwortet wie die Datenbank und prueft die Parameterzahl mit."""

    def __init__(self, zeilen=(), einstellung=None):
        self.zeilen = list(zeilen)
        self.einstellung = einstellung
        self.geschrieben = []

    def _pruefe(self, sql, args):
        hoechste = max([int(n) for n in re.findall(r"[$](\d+)", sql)] or [0])
        assert hoechste == len(args), (
            f"SQL erwartet ${hoechste} Parameter, uebergeben wurden {len(args)}\n{sql}")

    async def fetch(self, sql, *args):
        self._pruefe(sql, args)
        if "FROM food_log l" in sql:
            return self.zeilen
        if "FROM food_dishes d" in sql:
            return [{"id": 7, "name": "Wraps", "note": None, "created_at": None}]
        if "FROM food_dish_items" in sql:
            return [{"dish_id": 7, "link_id": 1, "grams": 200, "position": 0,
                     "amount": 200, "unit": "g", "item_id": 3, "name": "Wrap",
                     "brand": None, "base_unit": "g", "portion_g": None,
                     "package_g": None, "portion_label": None,
                     "kcal": 300, "protein_g": 10, "fiber_g": 4,
                     "carbs_g": 40, "fat_g": 8}]
        if "food_item_sizes" in sql:
            return []
        return []

    async def fetchrow(self, sql, *args):
        self._pruefe(sql, args)
        if "FROM food_settings" in sql:
            return self.einstellung
        if "FROM food_log WHERE id=" in sql:
            return {"id": 5, "day": HEUTE, "grams": args and None}
        if "FROM food_items WHERE id=" in sql:
            return {"id": 3, "base_unit": "g", "portion_g": 45,
                    "portion_label": "Scheibe", "package_g": None}
        return None

    async def fetchval(self, sql, *args):
        self._pruefe(sql, args)
        return 1

    async def execute(self, sql, *args):
        self._pruefe(sql, args)
        self.geschrieben.append((sql, args))
        return "OK"


def _tag(zeilen=(), einstellung=None):
    db = AttrappeDB(zeilen, einstellung)
    return db, asyncio.run(fr._tag(db, NUTZER["id"], HEUTE))


# ==========================================================================
# Der Tag
# ==========================================================================
def test_freier_eintrag_steht_im_tag_und_fehlt_in_der_summe():
    _, tag = _tag([GERICHT, FREI])
    namen = [e["name"] for e in tag["entries"]]
    assert namen == ["Wraps", "Pizza beim Italiener"]

    pizza = tag["entries"][1]
    assert pizza["kind"] == "free"
    assert pizza["has_nutrition"] is False
    assert pizza["kcal_min"] is None          # keine erfundene Zahl
    assert pizza["level_label"] == "übermäßig"

    # Die Summe kennt nur das Gericht -- und sagt, dass sie unvollstaendig ist.
    assert tag["totals"]["kcal"]["incomplete"] is True
    assert tag["totals"]["kcal"]["min"] > 0
    assert tag["counts"] == {"entries": 2, "normal": 1, "viel": 1,
                             "exact": 0, "unknown": 1}


def test_mahlzeiten_stehen_als_liste_und_jede_zeile_traegt_ihre():
    _, tag = _tag([LEBENSMITTEL, GERICHT, FREI])
    assert [m["key"] for m in tag["meals"]] == [
        "fruehstueck", "mittag", "abend", "snack", "ohne"]
    assert [e["meal"] for e in tag["entries"]] == ["fruehstueck", "mittag", "abend"]

    # Ohne Zuordnung faellt in einen eigenen Topf, nicht still unter "Snack".
    _, ohne = _tag([_zeile(id=9, label="Kaffee", level="normal")])
    assert ohne["entries"][0]["meal"] == "ohne"


def test_gewogene_menge_zaehlt_als_genau_und_traegt_ihren_text():
    _, tag = _tag([LEBENSMITTEL])
    eintrag = tag["entries"][0]
    assert eintrag["amount_label"] == "2 × Scheibe (90 g)"
    assert eintrag["level_label"] is None      # eine Menge hat keine Stufe
    assert eintrag["kcal_min"] == eintrag["kcal_max"] == 225   # 90 g à 250/100
    assert tag["counts"]["exact"] == 1
    assert tag["totals"]["kcal"]["incomplete"] is False


def test_eigenes_ziel_ersetzt_den_richtwert_nur_wo_eines_steht():
    einstellung = {"mode": "ausfuehrlich", "kcal_target": 2000,
                   "protein_target": None, "fiber_target": None,
                   "carbs_target": None, "fat_target": None, "updated_at": None}
    _, tag = _tag([LEBENSMITTEL], einstellung)

    assert tag["mode"] == "ausfuehrlich"
    assert tag["totals"]["kcal"]["reference"] == 2000
    assert tag["totals"]["kcal"]["own_target"] is True
    # Wo kein eigenes Ziel steht, gilt weiter der allgemeine Richtwert.
    assert tag["totals"]["protein_g"]["reference"] == calc.RICHTWERT["protein_g"]
    assert tag["totals"]["protein_g"]["own_target"] is False
    # Was noch fehlt, ist bei einer Spanne selbst eine Spanne.
    assert tag["totals"]["kcal"]["remaining_min"] == 2000 - 225
    assert tag["totals"]["kcal"]["remaining_max"] == 2000 - 225


def test_ohne_einstellung_gilt_der_lockere_modus():
    _, tag = _tag([])
    assert tag["mode"] == "locker"
    assert tag["targets"] == {m: None for m in calc.MAKROS}
    assert tag["counts"]["entries"] == 0


# ==========================================================================
# Eintragen
# ==========================================================================
def _eintragen(**felder):
    db = AttrappeDB()
    daten = fr.LogEingabe(**felder)
    return db, asyncio.run(fr.eintragen.__wrapped__(
        request=None, daten=daten, db=db, user=NUTZER))


def test_genau_eine_herkunft_je_zeile():
    # Nichts angegeben.
    with pytest.raises(HTTPException) as fehler:
        _eintragen(level="normal")
    assert "Genau eines" in fehler.value.detail
    # Zwei auf einmal.
    with pytest.raises(HTTPException):
        _eintragen(dish_id=7, label="Pizza", level="normal")


def test_freier_eintrag_braucht_eine_stufe():
    with pytest.raises(HTTPException) as fehler:
        _eintragen(label="Pizza")
    assert "zwei Stufen" in fehler.value.detail

    db, _ = _eintragen(label="  Pizza beim Italiener  ", level="viel", meal="abend")
    sql, args = db.geschrieben[-1]
    assert "INSERT INTO food_log" in sql
    # Getrimmt gespeichert, mit Stufe und Mahlzeit, ohne Menge.
    assert args[4] == "Pizza beim Italiener"
    assert args[5] == "viel" and args[6] == "abend"
    assert args[8] is None and args[10] is None


def test_erfundene_mahlzeit_faellt_auf():
    with pytest.raises(HTTPException) as fehler:
        _eintragen(label="Pizza", level="normal", meal="brunch")
    assert "Frühstück" in fehler.value.detail


def test_zu_langer_freitext_wird_abgewiesen():
    with pytest.raises(HTTPException):
        _eintragen(label="x" * 121, level="normal")


# ==========================================================================
# Richtigstellen
# ==========================================================================
def test_stufe_laesst_sich_nachtraeglich_richtigstellen():
    db = AttrappeDB()
    asyncio.run(fr.eintrag_aendern.__wrapped__(
        request=None, log_id=5, daten=fr.EintragAendern(level="viel", meal="abend"),
        db=db, user=NUTZER))
    sql, args = db.geschrieben[0]
    assert sql.startswith("UPDATE food_log SET level=$3, meal=$4")
    assert args == (5, 1, "viel", "abend")


def test_eine_menge_traegt_keine_stufe():
    # Der Eintrag steht in Gramm -- ihm eine Stufe zu geben hiesse, die
    # gewogene Menge durch eine Schaetzung zu ersetzen.
    db = AttrappeDB()

    async def zeile_mit_menge(sql, *args):
        db._pruefe(sql, args)
        return {"id": 5, "day": HEUTE, "grams": 90}
    db.fetchrow = zeile_mit_menge

    with pytest.raises(HTTPException) as fehler:
        asyncio.run(fr.eintrag_aendern.__wrapped__(
            request=None, log_id=5, daten=fr.EintragAendern(level="viel"),
            db=db, user=NUTZER))
    assert "Menge" in fehler.value.detail


# ==========================================================================
# Verlauf
# ==========================================================================
def test_verlauf_fuellt_tage_ohne_eintrag_auf():
    db = AttrappeDB([GERICHT, FREI])
    von = str(HEUTE - timedelta(days=4))
    antwort = asyncio.run(fr.verlauf(von=von, bis=str(HEUTE), db=db, user=NUTZER))

    assert len(antwort["days"]) == 5
    assert [t["day"] for t in antwort["days"]][-1] == str(HEUTE)
    # Vier leere Tage stehen mit Nullen da, statt zu fehlen.
    assert [t["entries"] for t in antwort["days"]] == [0, 0, 0, 0, 2]
    assert antwort["summary"]["days_logged"] == 1
    assert antwort["summary"]["entries"] == 2


def test_verlauf_rechnet_anteile_nur_ueber_das_was_sie_kennen():
    db = AttrappeDB([GERICHT, FREI, LEBENSMITTEL])
    antwort = asyncio.run(fr.verlauf(von=str(HEUTE), bis=str(HEUTE),
                                     db=db, user=NUTZER))
    zusammen = antwort["summary"]
    # Die gewogene Menge traegt keine Stufe und zaehlt deshalb im Anteil
    # nicht mit: eins von zwei Eintraegen mit Stufe war uebermaessig.
    assert zusammen["leveled"] == 2
    assert zusammen["viel_share"] == 0.5
    # Der Tag enthaelt einen freien Eintrag und zaehlt deshalb nicht im
    # Kalorienschnitt -- er waere sonst ein sehr sparsamer Tag, der er nie war.
    assert zusammen["complete_days"] == 0
    assert zusammen["kcal_avg_min"] is None


def test_verlauf_deckelt_sehr_lange_zeitraeume():
    db = AttrappeDB()
    antwort = asyncio.run(fr.verlauf(von="2000-01-01", bis=str(HEUTE),
                                     db=db, user=NUTZER))
    assert antwort["truncated"] is True
    assert len(antwort["days"]) == 401


# ==========================================================================
# Derselbe Bestand, zwei Modi
# ==========================================================================
def test_lebensmittel_mit_stufe_wird_geschaetzt_statt_abgewogen():
    """Der lockere Weg fuer ein Lebensmittel: „Brot, normal".

    Waere hier still die Standardgroesse eingetragen worden, haetten die
    beiden Knoepfe „normal" und „uebermaessig" dasselbe getan -- und nur so
    ausgesehen, als taeten sie etwas.
    """
    db, _ = _eintragen(item_id=3, level="viel", meal="fruehstueck")
    sql, args = db.geschrieben[-1]
    assert "INSERT INTO food_log" in sql
    assert args[3] == 3            # item_id
    assert args[5] == "viel"       # level steht da
    assert args[8] is None         # keine Menge
    assert args[10] is None        # und keine Gramm


def test_lebensmittel_mit_menge_bleibt_abgewogen():
    db, _ = _eintragen(item_id=3, amount=2, unit="g")
    sql, args = db.geschrieben[-1]
    assert args[5] is None         # keine Stufe
    assert args[8] == 2.0 and args[9] == "g"
    assert args[10] == 2.0         # in der Basis gerechnet


def test_stufe_und_menge_ergeben_zusammen_denselben_tag():
    # Eine Zeile mit Stufe und eine mit Menge stehen nebeneinander im
    # selben Tag -- der Modus wechselt die Frage, nicht die Ablage.
    mit_stufe = _zeile(id=4, item_id=3, item_name="Brot", level="normal",
                       portion_g=45, kcal=250, protein_g=8, fiber_g=5,
                       carbs_g=45, fat_g=2)
    _, tag = _tag([mit_stufe, LEBENSMITTEL])
    assert [e["kind"] for e in tag["entries"]] == ["item", "item"]
    assert tag["entries"][0]["level_label"] == "normal"
    assert tag["entries"][1]["amount_label"] == "2 × Scheibe (90 g)"
    # Die geschaetzte Zeile ist eine Spanne, die abgewogene ein Punkt.
    assert tag["entries"][0]["kcal_min"] < tag["entries"][0]["kcal_max"]
    assert tag["entries"][1]["kcal_min"] == tag["entries"][1]["kcal_max"]
    assert tag["counts"] == {"entries": 2, "normal": 1, "viel": 0,
                             "exact": 1, "unknown": 0}
