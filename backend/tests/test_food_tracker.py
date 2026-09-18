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
from datetime import date, datetime, time, timedelta, timezone

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


def test_an_einem_vergangenen_tag_zaehlt_die_browser_uhr_nicht():
    """Die Uhr sagt, wie spaet es JETZT ist -- nicht, wann gegessen wurde.

    Weder die Mahlzeit noch die Uhrzeit darf daraus entstehen: sonst steht an
    einer abends nachgetragenen Zeile "21:47" als Essenszeit, und dieselbe
    Zahl landet im Export in der Spalte "Uhrzeit".
    """
    db = AttrappeDB()
    gestern = str(HEUTE - timedelta(days=1))
    asyncio.run(EINTRAGEN(
        request=None,
        daten=fr.LogEingabe(item_id=3, amount=2, unit="Scheibe",
                            at="19:30", day=gestern),
        db=db, user=NUTZER))
    _, args = db.geschrieben[0]
    assert "19:30" not in args
    assert "abend" not in args
    assert args[-1] is False


def test_heute_behaelt_die_uhrzeit():
    """Die Gegenprobe: am selben Tag ist die Uhr genau das, was sie sagt."""
    db = AttrappeDB()
    asyncio.run(EINTRAGEN(
        request=None,
        daten=fr.LogEingabe(item_id=3, amount=2, unit="Scheibe", at="19:30"),
        db=db, user=NUTZER))
    _, args = db.geschrieben[0]
    assert "19:30" in args


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


# ==========================================================================
# Fotos fuer Gerichte (v1.99.0)
# ==========================================================================
class AttrappeDatei:
    """Ein hochgeladenes Bild, so weit der Router es anfasst."""

    def __init__(self, daten=b"nicht-wirklich-ein-bild"):
        self.daten = daten

    async def read(self):
        return self.daten


class AttrappeFoto:
    def __init__(self, gehoert=True):
        self.gehoert = gehoert
        self.geschrieben = []

    def _pruefe(self, sql, args):
        hoechste = max([int(n) for n in re.findall(r"[$](\d+)", sql)] or [0])
        assert hoechste == len(args)

    async def fetchval(self, sql, *args):
        self._pruefe(sql, args)
        return 1 if self.gehoert else None

    async def fetchrow(self, sql, *args):
        self._pruefe(sql, args)
        return None

    async def execute(self, sql, *args):
        self._pruefe(sql, args)
        self.geschrieben.append((sql, args))
        return "OK"

    async def fetch(self, sql, *args):
        self._pruefe(sql, args)
        return []


HOCHLADEN = fr.foto_hochladen.__wrapped__


def test_ein_fremdes_gericht_bekommt_kein_foto():
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(HOCHLADEN(request=None, dish_id=99, file=AttrappeDatei(),
                              db=AttrappeFoto(gehoert=False), user=NUTZER))
    assert fehler.value.status_code == 404


def test_ein_zu_grosses_bild_wird_abgewiesen():
    gross = AttrappeDatei(b"x" * (fr.FOTO_MAX_BYTES + 1))
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(HOCHLADEN(request=None, dish_id=1, file=gross,
                              db=AttrappeFoto(), user=NUTZER))
    assert fehler.value.status_code == 413


def test_was_kein_bild_ist_faellt_auf_statt_still_zu_landen(monkeypatch):
    """Der Fehler von v1.66.0: die weiche Fassung speichert einen Byte-Haufen
    als ``application/octet-stream``, liefert HTTP 200 -- und das Bild
    erscheint nie. Hier muss es 400 sein."""
    def wirft(roh):
        raise ValueError("Das Format konnte nicht gelesen werden.")
    monkeypatch.setattr(fr.bilder, "process_image_strict", wirft)
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(HOCHLADEN(request=None, dish_id=1, file=AttrappeDatei(),
                              db=AttrappeFoto(), user=NUTZER))
    assert fehler.value.status_code == 400


def test_ein_zweiter_upload_ersetzt_statt_anzuhaeufen(monkeypatch):
    monkeypatch.setattr(fr.bilder, "process_image_strict",
                        lambda roh: (b"gross", b"klein", "image/jpeg", 5))
    db = AttrappeFoto()
    asyncio.run(HOCHLADEN(request=None, dish_id=1, file=AttrappeDatei(),
                          db=db, user=NUTZER))
    sql, _ = db.geschrieben[0]
    assert "ON CONFLICT (dish_id) DO UPDATE" in sql


def test_das_foto_haengt_im_backup_am_gericht():
    """Ohne PARENT_SCOPE faellt eine Tabelle ohne user_id in den
    'alles lesen'-Zweig -- das Leck von v1.65.0."""
    from services import backup
    assert backup.PARENT_SCOPE["food_dish_images"] == ("dish_id", "food_dishes")
    assert "food_dish_images" in backup.BYTEA_COLUMNS
    assert "food_dish_images" in backup.TABLES_ORDERED


# ==========================================================================
# Die Bruecke ins Essenstagebuch
# ==========================================================================
class AttrappeBruecke:
    def __init__(self, zeilen=()):
        self.zeilen = list(zeilen)
        self.sql = None
        self.geschrieben = []

    def _pruefe(self, sql, args):
        hoechste = max([int(n) for n in re.findall(r"[$](\d+)", sql)] or [0])
        assert hoechste == len(args), sql

    async def fetch(self, sql, *args):
        self._pruefe(sql, args)
        self.sql = sql
        return self.zeilen

    async def fetchval(self, sql, *args):
        self._pruefe(sql, args)
        return 61

    async def execute(self, sql, *args):
        self._pruefe(sql, args)
        self.geschrieben.append((sql, args))
        return "OK"


def test_die_bruecke_laesst_weg_was_es_schon_gibt():
    db = AttrappeBruecke([{"name": "Müsli", "anzahl": 43, "zuletzt": HEUTE}])
    antwort = asyncio.run(fr.bruecke(db=db, user=NUTZER))
    assert antwort["suggestions"][0]["count"] == 43
    assert antwort["diary_days"] == 61
    # Drei Ausschluesse tragen die Abfrage: was schon Lebensmittel ist, was
    # schon Gericht ist, und was einmal abgelehnt wurde.
    assert "FROM food_items" in db.sql
    assert "FROM food_dishes" in db.sql
    assert "food_bridge_dismissed" in db.sql
    # Gruppiert wird kleingeschrieben -- sonst waeren "Müsli" und "müsli" zwei.
    assert "GROUP BY lower(d.label)" in db.sql
    # Was zweimal dastand, ist kein Muster, sondern Zufall.
    assert "HAVING COUNT(*) >= $3" in db.sql


def test_die_bruecke_liest_nur():
    """Ein Tagebuch-Eintrag von damals bleibt einer -- aus einer Stufe
    nachtraeglich eine Grammzahl zu erfinden, waere die falsche
    Genauigkeit (dieselbe Regel wie in Migration 042)."""
    db = AttrappeBruecke()
    asyncio.run(fr.bruecke(db=db, user=NUTZER))
    for wort in ("UPDATE", "INSERT", "DELETE"):
        assert wort not in db.sql.upper()


def test_abgelehnt_wird_kleingeschrieben_gemerkt():
    db = AttrappeBruecke()
    asyncio.run(fr.bruecke_ablehnen.__wrapped__(
        request=None, daten=fr.BrueckeAblehnen(label="Müsli"),
        db=db, user=NUTZER))
    sql, args = db.geschrieben[0]
    assert "INSERT INTO food_bridge_dismissed" in sql
    assert "müsli" in args


def test_ein_leerer_name_wird_nicht_abgelehnt():
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(fr.bruecke_ablehnen.__wrapped__(
            request=None, daten=fr.BrueckeAblehnen(label="   "),
            db=AttrappeBruecke(), user=NUTZER))
    assert fehler.value.status_code == 400


# ==========================================================================
# Die Menge laesst sich korrigieren (v2.1.0)
# ==========================================================================
# Bis dahin nahm PATCH nur Mahlzeit und Notiz. Wer 200 g eintrug und 100 g
# meinte, musste loeschen und von vorn suchen -- im Tagebuch liess sich
# dagegen alles aendern. Ausgerechnet das genaue Modul war das, in dem die
# Zahl nicht zu berichtigen war.
def test_die_menge_laesst_sich_nachtraeglich_berichtigen():
    db = AttrappeDB(treffer={"id": 5, "day": HEUTE, "dish_id": None,
                             "item_id": 3, "amount": 2, "unit": "Scheibe"})
    asyncio.run(AENDERN(request=None, log_id=5,
                        daten=fr.EintragAendern(amount=1),
                        db=db, user=NUTZER))
    sql, args = db.geschrieben[0]
    assert "amount=" in sql and "unit=" in sql and "grams=" in sql
    assert 1.0 in args


def test_eine_berichtigte_menge_rechnet_die_gramm_mit():
    """Sonst stuende an der Zeile eine neue Menge mit dem alten Gewicht --
    und die Tagessumme haette mit der Zeile nichts mehr zu tun."""
    db = AttrappeDB(treffer={"id": 5, "day": HEUTE, "dish_id": None,
                             "item_id": 3, "amount": 2, "unit": "Scheibe"})
    asyncio.run(AENDERN(request=None, log_id=5,
                        daten=fr.EintragAendern(amount=3),
                        db=db, user=NUTZER))
    _, args = db.geschrieben[0]
    # Eine Scheibe wiegt in der Attrappe 45 g -- drei sind 135 g.
    assert 135.0 in args or 135 in args


def test_eine_menge_von_null_wird_auch_beim_berichtigen_abgewiesen():
    db = AttrappeDB(treffer={"id": 5, "day": HEUTE, "dish_id": None,
                             "item_id": 3, "amount": 2, "unit": "Scheibe"})
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(AENDERN(request=None, log_id=5,
                            daten=fr.EintragAendern(amount=0),
                            db=db, user=NUTZER))
    assert fehler.value.status_code == 400


def test_eine_nicht_hinterlegte_groesse_faellt_auch_beim_berichtigen_auf():
    """Beide Wege muessen dieselbe Regel anwenden. Taeten sie es nicht,
    entstuende ueber die Korrektur eine Zeile, die es ueber das Eintragen nie
    gegeben haette -- und niemand saehe es ihr an."""
    db = AttrappeDB(treffer={"id": 5, "day": HEUTE, "dish_id": None,
                             "item_id": 3, "amount": 2, "unit": "Scheibe"})
    with pytest.raises(HTTPException) as fehler:
        asyncio.run(AENDERN(request=None, log_id=5,
                            daten=fr.EintragAendern(amount=1, unit="Fuhre"),
                            db=db, user=NUTZER))
    assert fehler.value.status_code == 400


def test_die_quelle_laesst_sich_nicht_umschreiben():
    """Aus einem Gericht ein Lebensmittel zu machen waere kein
    Richtigstellen, sondern ein anderer Eintrag."""
    daten = fr.EintragAendern(amount=1)
    for feld in ("dish_id", "item_id", "day", "label", "level"):
        assert not hasattr(daten, feld)


def test_nur_notiz_geaendert_laesst_die_menge_in_ruhe():
    """Wer die Notiz anfasst, soll nicht nebenbei die Gramm neu gerechnet
    bekommen."""
    db = AttrappeDB(treffer={"id": 5, "day": HEUTE, "dish_id": None,
                             "item_id": 3, "amount": 2, "unit": "Scheibe"})
    asyncio.run(AENDERN(request=None, log_id=5,
                        daten=fr.EintragAendern(note="mit Butter"),
                        db=db, user=NUTZER))
    sql, _ = db.geschrieben[0]
    assert "note=" in sql
    assert "grams=" not in sql and "amount=" not in sql
