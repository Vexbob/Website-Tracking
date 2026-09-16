"""Tests fuer den Ernaehrungs-Tracker (v1.98.0).

Die Gegenprobe zu ``test_tagebuch.py``: dort darf keine Menge durchkommen,
hier keine Stufe. Beides ist keine Prüfung mehr, sondern Abwesenheit -- weder
das Eingabemodell noch die Tabelle kennen das jeweils andere Feld. Diese Tests
halten fest, dass das so bleibt.

Dazu die Rechnung, die sich mit v1.98.0 geaendert hat: ein Gericht wird in
PORTIONEN eingetragen statt in Grobstufen, und damit hat jede Zeile eine Zahl
statt einer Spanne.
"""
import asyncio
import os
import re
import sys
from datetime import date, datetime, time, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from fastapi import HTTPException              # noqa: E402

from routers import food_router as fr          # noqa: E402
from services import food_calc as calc         # noqa: E402

NUTZER = {"id": 1}
HEUTE = date.today()

EINTRAGEN = fr.eintragen.__wrapped__
AENDERN = fr.eintrag_aendern.__wrapped__


def _zeile(**felder):
    """Eine Tageszeile, wie sie aus dem JOIN kommt."""
    basis = {
        "id": 1, "meal": "mittag", "note": None, "day": HEUTE,
        "created_at": datetime(2026, 9, 18, 12, tzinfo=timezone.utc),
        "logged_time": time(12, 30), "meal_auto": False,
        "dish_id": None, "item_id": None, "amount": None, "unit": None,
        "grams": None, "dish_name": None, "item_name": None, "item_brand": None,
        "portion_g": None, "base_unit": "g", "kcal": None, "protein_g": None,
        "fiber_g": None, "carbs_g": None, "fat_g": None,
    }
    basis.update(felder)
    return basis


# Ein Gericht mit 600 kcal je Portion (300 g), ein Brot mit 250 kcal/100 g.
GERICHT = _zeile(id=1, dish_id=7, dish_name="Wraps", amount=1.5,
                 unit="Portion", grams=450)
BROT = _zeile(id=2, item_id=3, item_name="Brot", item_brand="Bäcker",
              amount=2, unit="Scheibe", grams=90, meal="fruehstueck",
              kcal=250, protein_g=8, fiber_g=5, carbs_g=45, fat_g=2)

PORTION = {"grams": 300, "kcal": 600, "protein_g": 30, "fiber_g": None,
           "carbs_g": 60, "fat_g": 20, "incomplete": ["fiber_g"]}


class AttrappeDB:
    """Antwortet wie die Datenbank und prueft die Parameterzahl mit."""

    def __init__(self, zeilen=(), einstellung=None, treffer=None):
        self.zeilen = list(zeilen)
        self.einstellung = einstellung
        self.treffer = treffer
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
            return [{"dish_id": 7, "link_id": 1, "grams": 300, "position": 0,
                     "amount": 300, "unit": "g", "item_id": 3, "name": "Wrap",
                     "brand": None, "base_unit": "g", "portion_g": None,
                     "package_g": None, "portion_label": None,
                     "kcal": 200, "protein_g": 10, "fiber_g": None,
                     "carbs_g": 20, "fat_g": 6.67}]
        if "food_item_sizes" in sql:
            return [{"item_id": 3, "label": "Scheibe", "grams": 45, "position": 0}]
        return []

    async def fetchrow(self, sql, *args):
        self._pruefe(sql, args)
        if "FROM food_settings" in sql:
            return self.einstellung
        if "FROM food_items WHERE id=" in sql:
            return {"id": 3, "base_unit": "g", "portion_g": 45,
                    "portion_label": "Scheibe", "package_g": None}
        return self.treffer

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
# Die Trennung — die Gegenprobe zum Tagebuch
# ==========================================================================
def test_eine_stufe_kommt_gar_nicht_erst_ins_eingabemodell():
    daten = fr.LogEingabe(item_id=3, amount=2, unit="Scheibe",
                          level="normal", label="Pizza")
    for feld in ("level", "label"):
        assert not hasattr(daten, feld), f"{feld} darf es im Tracker nicht geben"


def test_geschrieben_wird_keine_stufe():
    db = AttrappeDB()
    asyncio.run(EINTRAGEN(request=None,
                          daten=fr.LogEingabe(item_id=3, amount=2, unit="Scheibe"),
                          db=db, user=NUTZER))
    sql, _ = db.geschrieben[0]
    assert "INSERT INTO food_log" in sql
    for verboten in ("level", "label"):
        assert verboten not in sql


def test_ohne_herkunft_oder_mit_zweien_geht_nichts():
    for daten in (fr.LogEingabe(), fr.LogEingabe(dish_id=7, item_id=3)):
        with pytest.raises(HTTPException) as fehler:
            asyncio.run(EINTRAGEN(request=None, daten=daten,
                                  db=AttrappeDB(), user=NUTZER))
        assert fehler.value.status_code == 400


# ==========================================================================
# Gericht in Portionen
# ==========================================================================
def test_ein_gericht_wird_in_portionen_gerechnet():
    db = AttrappeDB()
    asyncio.run(EINTRAGEN(request=None,
                          daten=fr.LogEingabe(dish_id=7, amount=1.5),
                          db=db, user=NUTZER))
    _, args = db.geschrieben[0]
    assert fr.PORTION_EINHEIT in args
    assert 1.5 in args
    # 300 g je Portion, anderthalb davon. Gerechnet wird beim SPEICHERN --
    # sonst aendert eine spaeter geaenderte Zutat einen vergangenen Tag.
    assert 450.0 in args


def test_der_tag_rechnet_das_gericht_anteilig():
    _, tag = _tag([GERICHT])
    # 600 kcal je Portion, 1,5 Portionen.
    assert tag["totals"]["kcal"]["value"] == 900
    # Ballaststoffe fehlen an einer Zutat -- unvollstaendig, nicht niedriger.
    assert tag["totals"]["fiber_g"]["incomplete"] is True
    eintrag = tag["entries"][0]
    assert eintrag["amount_label"] == "1,5 × Portion"
    assert eintrag["kind"] == "dish"


def test_eine_menge_von_null_ist_kein_eintrag():
    for daten in (fr.LogEingabe(dish_id=7, amount=0),
                  fr.LogEingabe(item_id=3, amount=0, unit="g")):
        with pytest.raises(HTTPException) as fehler:
            asyncio.run(EINTRAGEN(request=None, daten=daten,
                                  db=AttrappeDB(), user=NUTZER))
        assert fehler.value.status_code == 400


# ==========================================================================
# Lebensmittel in einer Menge
# ==========================================================================
def test_eine_nicht_hinterlegte_groesse_faellt_auf():
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(EINTRAGEN(
            request=None, daten=fr.LogEingabe(item_id=3, amount=1, unit="Laib"),
            db=AttrappeDB(), user=NUTZER))
    assert fehler.value.status_code == 400
    assert "hinterlegte Größe" in fehler.value.detail


def test_die_menge_wird_beim_speichern_umgerechnet():
    db = AttrappeDB()
    asyncio.run(EINTRAGEN(request=None,
                          daten=fr.LogEingabe(item_id=3, amount=2, unit="Scheibe"),
                          db=db, user=NUTZER))
    _, args = db.geschrieben[0]
    assert 90.0 in args          # 2 × 45 g
    assert "Scheibe" in args


def test_der_tag_zeigt_die_menge_samt_gramm():
    _, tag = _tag([BROT])
    eintrag = tag["entries"][0]
    assert eintrag["amount_label"] == "2 × Scheibe (90 g)"
    # 250 kcal je 100 g, 90 g davon.
    assert tag["totals"]["kcal"]["value"] == 225
    assert eintrag["has_nutrition"] is True


def test_kalorien_stehen_je_mahlzeit():
    """Ohne sie steht am Block eine Ueberschrift und sonst nichts."""
    _, tag = _tag([GERICHT, BROT])
    assert tag["meal_totals"]["mittag"]["kcal"] == 900
    assert tag["meal_totals"]["fruehstueck"]["kcal"] == 225


# ==========================================================================
# Ziele
# ==========================================================================
def test_ein_ziel_von_null_ist_keines():
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(fr.ziele_setzen.__wrapped__(
            request=None, daten=fr.ZieleEingabe(targets={"kcal": 0}),
            db=AttrappeDB(einstellung=None), user=NUTZER))
    assert fehler.value.status_code == 400
    assert "kein eigenes Ziel" in fehler.value.detail


def test_ein_unbekannter_naehrwert_faellt_auf():
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(fr.ziele_setzen.__wrapped__(
            request=None, daten=fr.ZieleEingabe(targets={"vitamin_c": 80}),
            db=AttrappeDB(einstellung=None), user=NUTZER))
    assert fehler.value.status_code == 400


def test_der_modus_ist_aus_den_einstellungen_verschwunden():
    """Er war die Frage, die jetzt die Wahl des Moduls beantwortet."""
    db = AttrappeDB(einstellung=None)
    antwort = asyncio.run(fr.ziele_lesen(db=db, user=NUTZER))
    assert "mode" not in antwort and "modes" not in antwort
    assert set(antwort["targets"]) == set(calc.MAKROS)


# ==========================================================================
# Mahlzeiten-Automatik — dieselbe Regel wie im Tagebuch
# ==========================================================================
def test_heute_wird_geraten_und_markiert():
    db = AttrappeDB()
    asyncio.run(EINTRAGEN(
        request=None,
        daten=fr.LogEingabe(item_id=3, amount=2, unit="Scheibe", at="08:12"),
        db=db, user=NUTZER))
    _, args = db.geschrieben[0]
    assert "fruehstueck" in args
    assert args[-1] is True


def test_der_ort_schlaegt_die_uhr():
    db = AttrappeDB()
    asyncio.run(EINTRAGEN(
        request=None,
        daten=fr.LogEingabe(item_id=3, amount=2, unit="Scheibe",
                            meal="snack", at="08:12"),
        db=db, user=NUTZER))
    _, args = db.geschrieben[0]
    assert "snack" in args and "fruehstueck" not in args
    assert args[-1] is False


def test_eine_gesetzte_mahlzeit_ist_keine_vermutung_mehr():
    db = AttrappeDB(treffer={"id": 5, "day": HEUTE})
    asyncio.run(AENDERN(request=None, log_id=5,
                        daten=fr.EintragAendern(meal="abend"),
                        db=db, user=NUTZER))
    sql, _ = db.geschrieben[0]
    assert "meal_auto=FALSE" in sql


def test_migration_047_raeumt_nur_auf_was_leer_ist():
    """Sie verschaerft food_log — und food_log ist seit 046 leer."""
    import pathlib
    datei = (pathlib.Path(__file__).resolve().parents[2]
             / "backend" / "migrations" / "sql" / "047_food_tracker.sql")
    text = datei.read_text(encoding="utf-8").upper()
    assert "DROP TABLE" not in text
    assert "DROP COLUMN IF EXISTS LEVEL" in text
    assert "SET NOT NULL" in text
