"""Ernaehrungs-Tracker — Lebensmittel, Gerichte, Mengen, Naehrwerte.

Endpoints:
  GET    /api/food/barcode/{code}     — Strichcode: Bestand, Katalog, dann OFF
  GET    /api/food/search             — Textsuche in Katalog bzw. OFF
  GET    /api/food/catalog            — Stand des eigenen Katalogs
  POST   /api/food/catalog            — Katalog einspielen (nur Admin)
  GET    /api/food/items              — eigener Bestand samt eigenen Groessen
  POST   /api/food/items              — aufnehmen oder aendern
  DELETE /api/food/items/{id}         — aus dem Bestand entfernen
  GET    /api/food/dishes             — eigene Gerichte samt Portionswerten
  POST   /api/food/dishes             — Gericht anlegen oder aendern
  DELETE /api/food/dishes/{id}        — Gericht loeschen
  GET    /api/food/track/day          — ein Tag mit Summen je Naehrwert
  POST   /api/food/track/log          — eintragen (Menge, keine Stufe)
  PATCH  /api/food/track/log/{id}     — Mahlzeit oder Notiz richtigstellen
  DELETE /api/food/track/log/{id}     — Eintrag entfernen
  GET    /api/food/track/targets      — eigene Tagesziele
  PUT    /api/food/track/targets      — Tagesziele setzen
  GET    /api/food/track/history      — Zeitraum, Tag fuer Tag
  GET    /api/food/track/frequent     — was oft eingetragen wird
  POST   /api/food/dishes/{id}/photo  — Foto eines Gerichts (ersetzt)
  GET    /api/food/dishes/{id}/photo  — das Foto
  GET    /api/food/dishes/{id}/thumb  — das Foto, klein
  DELETE /api/food/dishes/{id}/photo  — Foto entfernen
  GET    /api/food/track/bridge       — haeufige Tagebuch-Namen ohne Bestand
  POST   /api/food/track/bridge/dismiss — einen davon nicht mehr vorschlagen

Seit v1.98.0 ist das ein Modul von zweien. Das Essenstagebuch (/essen/,
routers/tagebuch_router.py) fragt nach Name und Stufe und schreibt nach
``food_diary``; hier geht es um Menge und Naehrwerte, und geschrieben wird
nach ``food_log``. Die Trennung steht in den Spaltenlisten, nicht in einer
Pruefung: ``food_diary`` hat keine Menge, ``food_log`` keine Stufe.

Drei Entscheidungen tragen diesen Teil:

1. **Es wird gerechnet, nicht geschaetzt.** Ein Lebensmittel wird in einer
   Menge eingetragen, ein Gericht in Portionen -- beides ergibt eine Zahl.
   Frueher trug ein Gericht eine Grobstufe, und aus "normal" wurde eine
   Spanne; das ist jetzt Sache des Tagebuchs, das gar keine Zahlen behauptet.

2. **Umgerechnet wird beim Speichern.** ``grams`` steht an der Zeile, nicht
   in der Anzeige -- sonst aendert eine korrigierte Scheibengroesse einen
   vergangenen Tag.

3. **Eine Luecke ist keine Null.** Fehlt einer Zutat die Ballaststoffangabe,
   ist die Tagessumme unvollstaendig und nicht niedriger. Die Antwort sagt
   das je Naehrwert (``incomplete``), und der Ring zeigt es als gestrichelte
   Spur.
"""
import asyncio
import gzip
import io
from typing import Optional

from fastapi import (APIRouter, Depends, File, HTTPException, Query, Request,
                     Response, UploadFile)
from pydantic import BaseModel

from auth import get_current_user, require_admin
from database import get_db
from deps import (limiter, LIMIT_WRITE_FREQUENT, LIMIT_WRITE_RARE,
                  LIMIT_WRITE_STANDARD)
from services import expenses as bilder   # process_image_strict — eine Fassung
from services import food_calc as calc
from services import food_catalog as katalog
from services import food_mahlzeit as mz
from services import openfoodfacts as off

router = APIRouter(tags=["food"])

SPALTEN = ("kcal", "protein_g", "carbs_g", "sugar_g", "fat_g", "sat_fat_g",
           "fiber_g", "salt_g", "portion_g", "package_g")


class Groesse(BaseModel):
    """Eine eigene Einheit eines Lebensmittels: Scheibe, Becher, Riegel …"""
    label: str
    grams: Optional[float] = None


class Zutat(BaseModel):
    item_id: int
    # Wie es eingegeben wurde. ``grams`` rechnet der Server daraus aus --
    # das Frontend soll keine Umrechnung kennen muessen.
    amount: float
    unit: str = "g"


class GerichtEingabe(BaseModel):
    id: Optional[int] = None
    name: str
    note: Optional[str] = None
    items: list[Zutat] = []


class LogEingabe(BaseModel):
    """Genau eine Herkunft und eine MENGE.

    Es gibt hier kein ``level`` und kein ``label`` -- beides gehoert ins
    Essenstagebuch und liegt dort in einer eigenen Tabelle. Die Felder fehlen
    absichtlich: was das Modell nicht kennt, kann kein Frontend versehentlich
    hierher schicken, und dieselbe Abwesenheit steht in der Spaltenliste von
    ``food_log``.
    """
    dish_id: Optional[int] = None
    item_id: Optional[int] = None
    # Ein Gericht wird in PORTIONEN eingetragen (unit = "Portion"), ein
    # Lebensmittel in einer eigenen Groesse oder in g/ml. Ohne Angabe gilt
    # die Standardgroesse.
    amount: Optional[float] = None
    unit: Optional[str] = None
    meal: Optional[str] = None
    note: Optional[str] = None
    day: Optional[str] = None
    # Ortszeit des Browsers, "HH:MM": der Server laeuft in UTC und darf aus
    # seiner eigenen Uhr keine Mahlzeit ableiten.
    at: Optional[str] = None


class EintragAendern(BaseModel):
    """Was sich an einer Zeile nachtraeglich richtigstellen laesst."""
    meal: Optional[str] = None
    note: Optional[str] = None


class ZieleEingabe(BaseModel):
    """Die eigenen Tagesziele, nach Naehrwert benannt (``kcal``,
    ``protein_g`` …). ``None`` darin heisst ausdruecklich "kein eigenes Ziel"
    und stellt den allgemeinen Richtwert wieder her."""
    targets: Optional[dict] = None


class LebensmittelEingabe(BaseModel):
    name: str
    brand: Optional[str] = None
    barcode: Optional[str] = None
    source: str = "eigen"
    kcal: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    sugar_g: Optional[float] = None
    fat_g: Optional[float] = None
    sat_fat_g: Optional[float] = None
    fiber_g: Optional[float] = None
    salt_g: Optional[float] = None
    portion_g: Optional[float] = None
    package_g: Optional[float] = None
    # Worauf sich die Naehrwerte beziehen: je 100 g oder je 100 ml.
    base_unit: str = "g"
    # Wie die eigene Einheit heisst: Stueck, Scheibe, Becher, Glas …
    portion_label: Optional[str] = None
    # Die eigenen Groessen. ``None`` heisst "nicht angefasst" -- eine
    # Uebernahme aus Open Food Facts schickt keine Liste mit und soll die
    # selbst gepflegten Groessen nicht loeschen. Eine leere Liste heisst
    # dagegen ausdruecklich "keine".
    sizes: Optional[list[Groesse]] = None
    # Von Hand nachgebessert: ein erneuter Abruf laesst die Zeile dann in Ruhe.
    user_edited: bool = False
    # Gesetzt beim Bearbeiten eines vorhandenen Eintrags.
    id: Optional[int] = None


async def _groessen(db, user_id: int) -> dict:
    """Alle eigenen Groessen eines Kontos, nach Lebensmittel gebuendelt.

    Eine Abfrage fuer den ganzen Bestand statt einer je Zeile: die Liste hat
    ein paar hundert Eintraege, die Groessen sind ein paar hundert mehr.
    """
    rows = await db.fetch(
        "SELECT s.item_id, s.label, s.grams FROM food_item_sizes s "
        "  JOIN food_items i ON i.id = s.item_id "
        " WHERE i.user_id=$1 ORDER BY s.item_id, s.position, s.id", user_id)
    raus = {}
    for r in rows:
        raus.setdefault(r["item_id"], []).append(
            {"label": r["label"], "grams": float(r["grams"])})
    return raus


async def _groessen_eines(db, item_id: int) -> list:
    rows = await db.fetch(
        "SELECT label, grams FROM food_item_sizes WHERE item_id=$1 "
        " ORDER BY position, id", item_id)
    return [{"label": r["label"], "grams": float(r["grams"])} for r in rows]


async def _groessen_schreiben(db, item_id: int, liste) -> None:
    """Ersetzt die Groessen eines Lebensmittels — und zieht die Standardgroesse nach.

    Ersetzen statt einzeln nachfuehren, wie bei den Zutaten eines Gerichts:
    die Liste ist ein Ganzes, und ein halb uebernommener Stand waere
    schlimmer als ein kurzer Moment ohne Zeile.
    """
    await db.execute("DELETE FROM food_item_sizes WHERE item_id=$1", item_id)
    for g in liste:
        await db.execute(
            "INSERT INTO food_item_sizes (item_id, label, grams, position) "
            "VALUES ($1,$2,$3,$4)", item_id, g["label"], g["grams"], g["position"])
    # ``portion_g``/``portion_label`` sind abgeleitet: sie tragen die ERSTE
    # Groesse und sind damit die, die beim Eintragen vorgeschlagen wird.
    erste = liste[0] if liste else None
    await db.execute(
        "UPDATE food_items SET portion_g=$2, portion_label=$3 WHERE id=$1",
        item_id, erste["grams"] if erste else None,
        erste["label"] if erste else None)


def _ser(row, groessen=()) -> dict:
    d = dict(row)
    d["sizes"] = [dict(g) for g in groessen]
    d["units"] = calc.einheiten_fuer(d, groessen)
    # NUMERIC kommt als Decimal zurueck -- als JSON waere das eine
    # Zeichenkette, und im Frontend stuende "6.30" statt 6,3.
    for spalte in SPALTEN:
        if d.get(spalte) is not None:
            d[spalte] = float(d[spalte])
    return d


# ---------------------------------------------------------------------------
# Nachschlagen
# ---------------------------------------------------------------------------
@router.get("/api/food/barcode/{code}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def barcode(request: Request, code: str, db=Depends(get_db),
                  user=Depends(get_current_user)):
    """Schlaegt den Strichcode nach — und sagt, ob er schon im Bestand ist.

    Der eigene Bestand geht vor: wer denselben Artikel zum zweiten Mal
    scannt, will seine eigenen, vielleicht korrigierten Werte sehen und
    nicht wieder die fremden.
    """
    ziffern = "".join(z for z in code if z.isdigit())
    vorhanden = await db.fetchrow(
        "SELECT * FROM food_items WHERE user_id=$1 AND barcode=$2",
        user["id"], ziffern)
    bekannt = (_ser(vorhanden, await _groessen_eines(db, vorhanden["id"]))
               if vorhanden else None)

    # Zuerst der eigene Katalog: er antwortet aus derselben Datenbank, in der
    # diese Abfrage ohnehin schon steht.
    produkt = await katalog.nach_code(db, ziffern)
    if produkt:
        return {"found": True, "product": produkt, "known": bekannt,
                "origin": "katalog"}
    try:
        produkt = await asyncio.to_thread(off.hole_produkt, ziffern)
    except off.QuellenFehler as e:
        if bekannt:
            # Im Bestand ist er ja -- dass die fremde Datenbank ihn nicht
            # (mehr) kennt, ist dann eine Randnotiz und kein Fehler.
            return {"found": False, "known": bekannt, "note": str(e)}
        raise HTTPException(404, str(e))
    return {"found": True, "product": produkt, "known": bekannt,
            "origin": "off"}


@router.get("/api/food/search")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def suche(request: Request, q: str = Query(..., min_length=2),
                db=Depends(get_db), user=Depends(get_current_user)):
    """Textsuche — fuer alles ohne Strichcode.

    Der eigene Katalog zuerst. Nur wenn der nichts hat, geht die Frage
    hinaus: so bleibt die Suche schnell, funktioniert auch dann, wenn der
    fremde Dienst gerade ueberlastet ist (der 503, der das ausgeloest hat),
    und belastet ihn nur dort, wo er wirklich gebraucht wird.
    """
    treffer = await katalog.suche(db, q)
    if treffer:
        return {"results": treffer, "origin": "katalog"}
    try:
        return {"results": await asyncio.to_thread(off.suche, q), "origin": "off"}
    except off.QuellenFehler as e:
        stand = await katalog.stand(db)
        if not stand["count"]:
            # Ohne Katalog war die Leitung der einzige Weg -- dann ist ihr
            # Ausfall der ganze Fehler und muss auch so dastehen.
            raise HTTPException(502, str(e))
        raise HTTPException(
            502, str(e) + " Im eigenen Katalog steht dazu nichts — "
                          "von Hand anlegen geht trotzdem.")


@router.get("/api/food/catalog")
async def katalog_stand(db=Depends(get_db), user=Depends(get_current_user)):
    """Wie viel im Katalog steht und wie alt er ist."""
    stand = await katalog.stand(db)
    # Nur wer den Katalog ersetzen darf, bekommt die Ablegeflaeche zu sehen.
    stand["may_import"] = bool(user.get("is_admin"))
    return stand


# Der fertige Katalog sind heute knapp 10 MB. Die Grenze liegt darueber,
# damit ein spaeter etwas groesserer Schnitt nicht am Limit scheitert -- und
# tief genug, dass eine versehentlich abgelegte Urlaubsvideodatei nicht erst
# durch die Leitung muss.
# Ein Gerichtsfoto darf so gross sein wie ein Bon -- dieselbe Grenze, und
# nach der Verarbeitung ist es ohnehin ein JPEG von 1600 px.
FOTO_MAX_BYTES = 8 * 1024 * 1024
KATALOG_MAX_BYTES = 32 * 1024 * 1024
KATALOG_SPALTEN = 14


def _katalog_strom(rohdaten: bytes):
    """Die hochgeladene Datei als Datenstrom — gepackt oder nicht.

    Erkannt wird am Inhalt, nicht am Dateinamen: wer die Datei einmal
    ausgepackt hat, soll sie trotzdem ablegen koennen.
    """
    if rohdaten[:2] == b"\x1f\x8b":
        return gzip.GzipFile(fileobj=io.BytesIO(rohdaten))
    return io.BytesIO(rohdaten)


@router.post("/api/food/catalog")
@limiter.limit(LIMIT_WRITE_RARE)
async def katalog_einspielen(request: Request, file: UploadFile = File(...),
                             db=Depends(get_db), user=Depends(require_admin)):
    """Ersetzt den Katalog durch die hochgeladene Datei.

    Ersetzen, nicht ergaenzen: ein neuer Abzug ist ein neuer Stand, und zwei
    Staende nebeneinander waeren spaeter nicht zu trennen. Alles laeuft in
    einer Transaktion -- schlaegt es fehl, steht der alte Katalog unberuehrt
    da, statt halb ueberschrieben.

    Gebaut wird die Datei mit ``scripts/off_katalog.py``. Den ganzen Abzug
    hier hochzuladen waere keine Erleichterung: 1,2 GB durch eine
    HTTP-Anfrage, damit der Server dieselbe Arbeit macht, die auf einem
    Rechner mit der Datei in vier Minuten erledigt ist.
    """
    rohdaten = await file.read()
    if not rohdaten:
        raise HTTPException(400, "Die Datei ist leer.")
    if len(rohdaten) > KATALOG_MAX_BYTES:
        raise HTTPException(
            413, "Die Datei ist größer als %d MB. Der gefilterte Katalog ist "
                 "rund 10 MB — sicher, dass das nicht der ganze Abzug ist?"
                 % (KATALOG_MAX_BYTES // 1024 // 1024))

    # Erst hineinsehen, dann die Tabelle leeren. Andersherum stuende der
    # Katalog leer da, weil jemand die falsche Datei erwischt hat.
    try:
        probe = _katalog_strom(rohdaten).read(64 * 1024)
    except (OSError, EOFError) as e:
        raise HTTPException(400, "Die Datei ließ sich nicht lesen (%s)." % e)
    erste = probe.split(b"\n", 1)[0].decode("utf-8", "replace")
    felder = erste.split("\t")
    if len(felder) != KATALOG_SPALTEN or not felder[0].strip().isdigit():
        raise HTTPException(
            400, "Das sieht nicht nach einem Katalog aus: erwartet werden %d "
                 "durch Tabulator getrennte Spalten, die erste ein Strichcode "
                 "— gefunden %d. Gebaut wird die Datei mit "
                 "scripts/off_katalog.py."
                 % (KATALOG_SPALTEN, len(felder)))

    vorher = await katalog.stand(db)
    try:
        async with db.transaction():
            await db.execute("TRUNCATE food_catalog")
            await db.copy_to_table(
                "food_catalog", source=_katalog_strom(rohdaten),
                columns=list(katalog.SPALTEN), format="csv", delimiter="\t",
                null="")
    except Exception as e:
        # Der haeufigste Fall ist eine Datei mit anderen Spalten -- die
        # Meldung von Postgres nennt Zeile und Wert, das hilft mehr als ein
        # eigener Satz darueber.
        raise HTTPException(400, "Einspielen fehlgeschlagen: %s" % e)

    nachher = await katalog.stand(db)
    nachher["may_import"] = True
    nachher["replaced"] = vorher["count"]
    return nachher


# ---------------------------------------------------------------------------
# Eigener Bestand
# ---------------------------------------------------------------------------
@router.get("/api/food/items")
async def bestand(q: Optional[str] = None, limit: int = Query(200, le=500),
                  db=Depends(get_db), user=Depends(get_current_user)):
    werte = [user["id"]]
    wo = "user_id=$1"
    if q and q.strip():
        werte.append(f"%{q.strip()}%")
        wo += " AND (name ILIKE $2 OR brand ILIKE $2)"
    rows = await db.fetch(
        f"SELECT * FROM food_items WHERE {wo} "
        f" ORDER BY lower(name) LIMIT {int(limit)}", *werte)
    groessen = await _groessen(db, user["id"])
    return {"items": [_ser(r, groessen.get(r["id"], [])) for r in rows],
            # Vorschlaege fuer das Eingabefeld -- keine Vorschrift, aber es
            # erspart das Tippen der immer gleichen zehn Woerter.
            "size_suggestions": list(calc.GAENGIGE_GROESSEN)}


@router.post("/api/food/items")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def aufnehmen(request: Request, daten: LebensmittelEingabe,
                    db=Depends(get_db), user=Depends(get_current_user)):
    """Nimmt ein Lebensmittel auf — oder aktualisiert es beim selben Strichcode.

    Eine von Hand nachgebesserte Zeile wird dabei nicht ueberschrieben: wer
    einen Wert von der Packung korrigiert hat, will ihn beim naechsten Scan
    nicht wieder durch den fremden ersetzt sehen.
    """
    name = (daten.name or "").strip()
    if not name:
        raise HTTPException(400, "Ohne Namen geht es nicht.")
    if daten.source not in ("off", "eigen"):
        raise HTTPException(400, "Unbekannte Herkunft.")
    if daten.base_unit not in ("g", "ml"):
        raise HTTPException(400, "Nährwerte beziehen sich auf 100 g oder 100 ml.")
    groessen, fehler = calc.groessen_sauber(
        [g.model_dump() for g in daten.sizes] if daten.sizes is not None else None)
    if fehler:
        raise HTTPException(400, fehler)
    ziffern = "".join(z for z in (daten.barcode or "") if z.isdigit()) or None

    # Bearbeiten: ein vorhandener Eintrag wird geradeheraus ueberschrieben.
    # Der Weg darunter (ON CONFLICT ueber den Strichcode) trifft nur zu, wenn
    # es einen Strichcode gibt -- von Hand angelegte Lebensmittel haben keinen.
    if daten.id:
        # ``portion_g`` und ``portion_label`` stehen hier bewusst NICHT: sie
        # sind seit v1.90.0 abgeleitet und werden allein aus der
        # Groessenliste geschrieben. Wuerden sie hier mitgesetzt, machte eine
        # Aenderung ohne Groessenliste die Standardgroesse still kaputt.
        zeile = await db.fetchrow(
            "UPDATE food_items SET name=$3, brand=$4, barcode=$5, kcal=$6, "
            "   protein_g=$7, carbs_g=$8, sugar_g=$9, fat_g=$10, sat_fat_g=$11, "
            "   fiber_g=$12, salt_g=$13, base_unit=$14, user_edited=TRUE, "
            "   updated_at=now() "
            " WHERE id=$1 AND user_id=$2 RETURNING *",
            daten.id, user["id"], name, daten.brand, ziffern, daten.kcal,
            daten.protein_g, daten.carbs_g, daten.sugar_g, daten.fat_g,
            daten.sat_fat_g, daten.fiber_g, daten.salt_g, daten.base_unit)
        if not zeile:
            raise HTTPException(404, "Dieses Lebensmittel gibt es nicht.")
        if daten.sizes is not None:
            await _groessen_schreiben(db, zeile["id"], groessen)
            zeile = await db.fetchrow("SELECT * FROM food_items WHERE id=$1",
                                      zeile["id"])
        return {"ok": True,
                "item": _ser(zeile, await _groessen_eines(db, zeile["id"]))}

    werte = [user["id"], daten.source, ziffern, name, daten.brand,
             daten.kcal, daten.protein_g, daten.carbs_g, daten.sugar_g,
             daten.fat_g, daten.sat_fat_g, daten.fiber_g, daten.salt_g,
             daten.portion_g, daten.user_edited, daten.package_g,
             daten.base_unit, (daten.portion_label or "").strip() or None]
    zeile = await db.fetchrow(
        "INSERT INTO food_items (user_id, source, barcode, name, brand, kcal, "
        "   protein_g, carbs_g, sugar_g, fat_g, sat_fat_g, fiber_g, salt_g, "
        "   portion_g, user_edited, package_g, base_unit, portion_label) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18) "
        "ON CONFLICT (user_id, barcode) DO UPDATE SET "
        "   name = CASE WHEN food_items.user_edited THEN food_items.name "
        "               ELSE EXCLUDED.name END, "
        "   brand = CASE WHEN food_items.user_edited THEN food_items.brand "
        "                ELSE EXCLUDED.brand END, "
        "   kcal = CASE WHEN food_items.user_edited THEN food_items.kcal "
        "               ELSE EXCLUDED.kcal END, "
        "   protein_g = CASE WHEN food_items.user_edited THEN food_items.protein_g "
        "                    ELSE EXCLUDED.protein_g END, "
        "   carbs_g = CASE WHEN food_items.user_edited THEN food_items.carbs_g "
        "                  ELSE EXCLUDED.carbs_g END, "
        "   sugar_g = CASE WHEN food_items.user_edited THEN food_items.sugar_g "
        "                  ELSE EXCLUDED.sugar_g END, "
        "   fat_g = CASE WHEN food_items.user_edited THEN food_items.fat_g "
        "                ELSE EXCLUDED.fat_g END, "
        "   sat_fat_g = CASE WHEN food_items.user_edited THEN food_items.sat_fat_g "
        "                    ELSE EXCLUDED.sat_fat_g END, "
        "   fiber_g = CASE WHEN food_items.user_edited THEN food_items.fiber_g "
        "                  ELSE EXCLUDED.fiber_g END, "
        "   salt_g = CASE WHEN food_items.user_edited THEN food_items.salt_g "
        "                 ELSE EXCLUDED.salt_g END, "
        "   portion_g = COALESCE(EXCLUDED.portion_g, food_items.portion_g), "
        "   package_g = COALESCE(EXCLUDED.package_g, food_items.package_g), "
        "   portion_label = COALESCE(food_items.portion_label, EXCLUDED.portion_label), "
        "   user_edited = food_items.user_edited OR EXCLUDED.user_edited, "
        "   updated_at = now() "
        "RETURNING *", *werte)

    if daten.sizes is not None:
        await _groessen_schreiben(db, zeile["id"], groessen)
    elif daten.portion_g and not await _groessen_eines(db, zeile["id"]):
        # Uebernahme aus Open Food Facts: die dortige Portionsangabe wird zur
        # ersten eigenen Groesse, damit sie im Auswahlfeld auftaucht. Nur,
        # wenn noch keine eigene da ist -- eine selbst gepflegte Liste faehrt
        # ein erneuter Scan nicht ueber den Haufen.
        await _groessen_schreiben(db, zeile["id"], [
            {"label": (daten.portion_label or "Portion"),
             "grams": float(daten.portion_g), "position": 0}])
    zeile = await db.fetchrow("SELECT * FROM food_items WHERE id=$1", zeile["id"])
    return {"ok": True, "item": _ser(zeile, await _groessen_eines(db, zeile["id"]))}


@router.delete("/api/food/items/{item_id}")
@limiter.limit(LIMIT_WRITE_RARE)
async def entfernen(request: Request, item_id: int, db=Depends(get_db),
                    user=Depends(get_current_user)):
    treffer = await db.fetchrow(
        "DELETE FROM food_items WHERE id=$1 AND user_id=$2 RETURNING id",
        item_id, user["id"])
    if not treffer:
        raise HTTPException(404, "Dieses Lebensmittel gibt es nicht.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Gerichte
# ---------------------------------------------------------------------------
async def _gerichte(db, user_id: int, dish_id: Optional[int] = None) -> list:
    """Gerichte samt Zutaten und den Naehrwerten EINER normalen Portion."""
    werte = [user_id]
    wo = "d.user_id=$1"
    if dish_id:
        werte.append(dish_id)
        wo += " AND d.id=$2"
    gerichte = await db.fetch(
        f"SELECT d.id, d.name, d.note, d.created_at FROM food_dishes d "
        f" WHERE {wo} ORDER BY lower(d.name)", *werte)
    if not gerichte:
        return []
    # Spalten einzeln benennen: ``i.*`` wuerde z.id ueberschreiben (beide
    # Tabellen haben eine Spalte "id"), und die Zutat haette dann die ID des
    # Lebensmittels getragen.
    groessen = await _groessen(db, user_id)
    mit_foto = {z["dish_id"] for z in await db.fetch(
        "SELECT b.dish_id FROM food_dish_images b "
        "  JOIN food_dishes d ON d.id = b.dish_id WHERE d.user_id=$1", user_id)}
    zutaten = await db.fetch(
        "SELECT z.dish_id, z.id AS link_id, z.grams, z.position, "
        "       z.amount, z.unit, "
        "       i.id AS item_id, i.name, i.brand, i.base_unit, "
        "       i.portion_g, i.package_g, i.portion_label, "
        "       i.kcal, i.protein_g, i.fiber_g, i.carbs_g, i.fat_g "
        "  FROM food_dish_items z JOIN food_items i ON i.id = z.item_id "
        "  JOIN food_dishes d ON d.id = z.dish_id "
        " WHERE d.user_id=$1 ORDER BY z.position, z.id", user_id)

    raus = []
    for g in gerichte:
        eigene = [z for z in zutaten if z["dish_id"] == g["id"]]
        summe = calc.zutaten_summe(
            [(z["grams"], {m: z[m] for m in calc.MAKROS}) for z in eigene])
        raus.append({
            "id": g["id"], "name": g["name"], "note": g["note"],
            "created_at": g["created_at"],
            "items": [{"id": z["link_id"], "item_id": z["item_id"],
                       "grams": float(z["grams"]), "name": z["name"],
                       "brand": z["brand"],
                       "amount": float(z["amount"]) if z["amount"] else float(z["grams"]),
                       "unit": z["unit"] or (z["base_unit"] or "g"),
                       "units": calc.einheiten_fuer(
                           dict(z), groessen.get(z["item_id"], []))}
                      for z in eigene],
            "portion": summe,
            # Nur ob es eines gibt -- die Bytes selbst haetten in einer Liste
            # nichts zu suchen (siehe Migration 048).
            "has_photo": g["id"] in mit_foto,
        })
    return raus


@router.get("/api/food/dishes")
async def gerichte(db=Depends(get_db), user=Depends(get_current_user)):
    # Portionen statt Stufen: ein halbes, ein ganzes, anderthalb Gerichte.
    # Die Liste steht hier, damit die Seite keine eigene erfindet.
    return {"dishes": await _gerichte(db, user["id"]),
            "portions": [0.5, 1, 1.5, 2]}


@router.post("/api/food/dishes")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def gericht_speichern(request: Request, daten: GerichtEingabe,
                            db=Depends(get_db), user=Depends(get_current_user)):
    """Legt ein Gericht an oder schreibt es neu.

    Die Zutaten werden dabei ersetzt statt einzeln nachgefuehrt: ein Rezept
    ist ein Ganzes, und ein halb uebernommener Stand waere schlimmer als ein
    kurzer Moment ohne Zeile.
    """
    name = (daten.name or "").strip()
    if not name:
        raise HTTPException(400, "Ohne Namen geht es nicht.")
    if not daten.items:
        raise HTTPException(400, "Ein Gericht braucht mindestens eine Zutat.")

    async with db.transaction():
        if daten.id:
            zeile = await db.fetchrow(
                "UPDATE food_dishes SET name=$3, note=$4, updated_at=now() "
                " WHERE id=$1 AND user_id=$2 RETURNING id", daten.id, user["id"],
                name, daten.note)
            if not zeile:
                raise HTTPException(404, "Dieses Gericht gibt es nicht.")
            await db.execute("DELETE FROM food_dish_items WHERE dish_id=$1", daten.id)
        else:
            zeile = await db.fetchrow(
                "INSERT INTO food_dishes (user_id, name, note) VALUES ($1,$2,$3) "
                "RETURNING id", user["id"], name, daten.note)

        for platz, zutat in enumerate(daten.items):
            if zutat.amount <= 0:
                raise HTTPException(400, "Eine Zutat ohne Menge ergibt keine Portion.")
            # Das Lebensmittel muss dem Konto gehoeren -- sonst liesse sich
            # ueber eine fremde ID ein fremder Bestand auslesen.
            lebensmittel = await db.fetchrow(
                "SELECT id, base_unit, portion_g, package_g FROM food_items "
                " WHERE id=$1 AND user_id=$2", zutat.item_id, user["id"])
            if not lebensmittel:
                raise HTTPException(400, "Unbekanntes Lebensmittel in der Zutatenliste.")
            eigene = await _groessen_eines(db, zutat.item_id)
            erlaubt = [e["key"] for e in calc.einheiten_fuer(dict(lebensmittel), eigene)]
            if zutat.unit not in erlaubt:
                raise HTTPException(
                    400, f"„{zutat.unit}“ ist für dieses Lebensmittel keine "
                         "hinterlegte Größe.")
            # Einmal beim Speichern umrechnen, nicht bei jeder Anzeige: sonst
            # aendert sich ein altes Rezept, sobald jemand eine
            # Portionsgroesse korrigiert.
            gramm, _hinweis = calc.in_basis(zutat.amount, zutat.unit,
                                            dict(lebensmittel), eigene)
            await db.execute(
                "INSERT INTO food_dish_items (dish_id, item_id, grams, position, "
                "   amount, unit) VALUES ($1,$2,$3,$4,$5,$6)",
                zeile["id"], zutat.item_id, round(gramm, 2), platz,
                zutat.amount, zutat.unit)

    # Die ID kommt mit heraus: wer gerade ein Gericht angelegt hat, will
    # danach womoeglich sein Foto dazulegen -- und muesste es sonst in der
    # zurueckgegebenen Liste am Namen wiedersuchen.
    return {"ok": True, "dish_id": zeile["id"],
            "dishes": await _gerichte(db, user["id"])}


@router.delete("/api/food/dishes/{dish_id}")
@limiter.limit(LIMIT_WRITE_RARE)
async def gericht_loeschen(request: Request, dish_id: int, db=Depends(get_db),
                           user=Depends(get_current_user)):
    treffer = await db.fetchrow(
        "DELETE FROM food_dishes WHERE id=$1 AND user_id=$2 RETURNING id",
        dish_id, user["id"])
    if not treffer:
        raise HTTPException(404, "Dieses Gericht gibt es nicht.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Der Tag
# ---------------------------------------------------------------------------
# Seit v1.98.0 zaehlt hier ausschliesslich die MENGE. Ein Lebensmittel wird in
# Gramm oder einer eigenen Groesse eingetragen, ein Gericht in Portionen --
# beides ergibt eine Zahl, keine Spanne. Die Grobstufen ("normal" /
# "uebermaessig") sind Sache des Essenstagebuchs (/api/food/diary/*), und sie
# liegen dort in einer eigenen Tabelle: ``food_diary`` hat keine Mengenspalte,
# ``food_log`` keine Stufe. Beides ist damit nicht verboten, sondern unmoeglich.

# Ein Gericht wird in Portionen eingetragen. Die Einheit traegt ihren Namen,
# damit die Zeile lesbar bleibt ("1,5 x Portion") -- und weil derselbe Text
# auch in einem alten Eintrag noch stimmt.
PORTION_EINHEIT = "Portion"
PORTIONEN_STANDARD = 1.0


def _menge_text(zeile) -> str:
    """Wie die Menge dasteht: 180 g, 2 x Scheibe (50 g), 1,5 x Portion.

    Die Grammzahl steht dabei, sobald in einer eigenen Einheit eingetragen
    wurde -- sonst haengt der Naehrwert an einer Zahl, die man nicht sieht.
    """
    def zahl(v):
        return f"{float(v):g}".replace(".", ",")

    menge = zeile["amount"]
    einheit = zeile["unit"]
    if zeile["dish_id"]:
        return f"{zahl(menge)} × {einheit}"
    basis = zeile["base_unit"] or "g"
    if einheit in calc.RESERVIERT:
        return f"{zahl(menge)} {einheit}"
    return f"{zahl(menge)} × {einheit} ({zahl(zeile['grams'])} {basis})"


async def _einstellungen(db, user_id: int) -> dict:
    """Die eigenen Tagesziele. Kein Eintrag heisst: der Richtwert gilt."""
    row = await db.fetchrow(
        "SELECT kcal_target, protein_target, fiber_target, carbs_target, "
        "       fat_target, updated_at FROM food_settings WHERE user_id=$1", user_id)
    if not row:
        return {"kcal_target": None, "protein_target": None, "fiber_target": None,
                "carbs_target": None, "fat_target": None, "updated_at": None}
    return dict(row)


def _ziele_raus(einst: dict) -> dict:
    """Die Ziele nach Naehrwert benannt — so, wie die Seite sie braucht."""
    return {makro: (None if einst.get(spalte) is None else float(einst[spalte]))
            for makro, spalte in calc.ZIEL_SPALTEN.items()}


SPALTEN_TAG = (
    "l.id, l.meal, l.note, l.created_at, l.day, l.logged_time, l.meal_auto, "
    "l.dish_id, l.item_id, l.amount, l.unit, l.grams, "
    "d.name AS dish_name, i.name AS item_name, i.brand AS item_brand, "
    "i.portion_g, i.base_unit, i.kcal, i.protein_g, i.fiber_g, i.carbs_g, i.fat_g")


def _zeile_rechnen(z, portionen: dict):
    """Aus einer Zeile werden Anzeige und Naehrwerte.

    Zwei Faelle, und beide sind genau: ein Gericht in Portionen, ein
    Lebensmittel in einer Menge. Die dritte und vierte Form von frueher --
    Stufe statt Menge, freier Name ohne Naehrwerte -- gibt es hier nicht mehr;
    sie sind das Tagebuch.
    """
    gramm = float(z["grams"])
    if z["dish_id"]:
        # Die Naehrwerte EINER Portion stehen schon in ``zutaten_summe``;
        # ``amount`` ist die Zahl der Portionen.
        basis = portionen.get(z["dish_id"]) or {}
        anteil = float(z["amount"])
        werte = {m: (None if basis.get(m) is None else float(basis[m]) * anteil)
                 for m in calc.MAKROS}
        name, zusatz, art = z["dish_name"], "Gericht", "dish"
    else:
        werte = calc.je_menge(dict(z), gramm)
        name, art = z["item_name"], "item"
        zusatz = z["item_brand"] or "Lebensmittel"

    eintrag = {
        "id": z["id"],
        "name": name,
        "sub": zusatz,
        "kind": art,
        "amount_label": _menge_text(z),
        "grams": round(gramm, 1),
        "meal": z["meal"] or mz.OHNE_MAHLZEIT,
        "meal_auto": bool(z["meal_auto"]),
        "note": z["note"],
        "logged_time": (z["logged_time"].strftime("%H:%M")
                        if z["logged_time"] else None),
        "has_nutrition": werte.get("kcal") is not None,
        "kcal": None if werte.get("kcal") is None else round(werte["kcal"]),
    }
    return eintrag, werte


def _mahlzeit_summen(eintraege, werte_liste) -> dict:
    """Kalorien je Mahlzeit. Ohne sie steht am Block eine Ueberschrift und
    sonst nichts -- und genau dort will man die Zahl sehen."""
    raus = {}
    for eintrag, werte in zip(eintraege, werte_liste):
        topf = raus.setdefault(eintrag["meal"], {"kcal": 0, "incomplete": False})
        if werte.get("kcal") is None:
            topf["incomplete"] = True
        else:
            topf["kcal"] += werte["kcal"]
    for topf in raus.values():
        topf["kcal"] = round(topf["kcal"])
    return raus


async def _tag(db, user_id: int, tag) -> dict:
    """Ein Tag: was eingetragen wurde und was daraus folgt."""
    zeilen = await db.fetch(
        f"SELECT {SPALTEN_TAG} "
        "  FROM food_log l "
        "  LEFT JOIN food_dishes d ON d.id = l.dish_id "
        "  LEFT JOIN food_items  i ON i.id = l.item_id "
        " WHERE l.user_id=$1 AND l.day=$2 ORDER BY l.created_at", user_id, tag)

    # Die Portionswerte der beteiligten Gerichte einmal holen.
    dish_ids = {z["dish_id"] for z in zeilen if z["dish_id"]}
    portionen = {}
    if dish_ids:
        for g in await _gerichte(db, user_id):
            if g["id"] in dish_ids:
                portionen[g["id"]] = g["portion"]

    einst = await _einstellungen(db, user_id)
    eintraege, werte_liste = [], []
    for z in zeilen:
        eintrag, werte = _zeile_rechnen(z, portionen)
        eintraege.append(eintrag)
        werte_liste.append(werte)

    return {
        "day": str(tag),
        "entries": eintraege,
        "counts": {"entries": len(eintraege),
                   "unknown": sum(1 for e in eintraege if not e["has_nutrition"])},
        "meals": mz.liste_raus(),
        "meal_hours": mz.grenzen_raus(),
        "meal_totals": _mahlzeit_summen(eintraege, werte_liste),
        "totals": calc.tages_summe_genau(werte_liste, einst),
        "targets": _ziele_raus(einst),
        "macros": list(calc.MAKROS),
        "macro_labels": dict(calc.MAKRO_LABEL),
        "reference_note": calc.RICHTWERT_QUELLE,
        "target_note": calc.ZIEL_QUELLE,
    }


def _als_tag(wert):
    from datetime import date as Datum
    if not wert:
        return Datum.today()
    try:
        return Datum.fromisoformat(wert)
    except ValueError:
        raise HTTPException(400, "Das ist kein Datum (erwartet: JJJJ-MM-TT).")


@router.get("/api/food/track/day")
async def tag(date: Optional[str] = None, db=Depends(get_db),
              user=Depends(get_current_user)):
    return await _tag(db, user["id"], _als_tag(date))


@router.post("/api/food/track/log")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def eintragen(request: Request, daten: LogEingabe, db=Depends(get_db),
                    user=Depends(get_current_user)):
    """Traegt ein Gericht (in Portionen) oder ein Lebensmittel (in einer
    Menge) ein. Eine Stufe gibt es hier nicht -- die gehoert ins Tagebuch."""
    quellen = sum(1 for x in (daten.dish_id, daten.item_id) if x)
    if quellen != 1:
        raise HTTPException(400, "Genau eines: ein Gericht oder ein Lebensmittel.")
    try:
        mahlzeit = mz.mahlzeit_sauber(daten.meal)
    except ValueError as e:
        raise HTTPException(400, str(e))
    tag = _als_tag(daten.day)

    from datetime import date as Datum
    zeit = mz.uhrzeit_sauber(daten.at)
    geraten = False
    # Geraten wird nur fuer heute: "es ist jetzt Abend" ist kein Argument
    # darueber, was letzten Dienstag auf dem Teller lag.
    if mahlzeit is None and zeit and tag == Datum.today():
        mahlzeit = mz.mahlzeit_fuer_uhrzeit(zeit[0])
        geraten = True

    if daten.dish_id:
        gericht = None
        for g in await _gerichte(db, user["id"]):
            if g["id"] == daten.dish_id:
                gericht = g
                break
        if not gericht:
            raise HTTPException(404, "Das gibt es in deinem Bestand nicht.")
        menge = PORTIONEN_STANDARD if daten.amount is None else float(daten.amount)
        if menge <= 0:
            raise HTTPException(400, "Eine Menge von null ist kein Eintrag.")
        einheit = PORTION_EINHEIT
        # Das Gewicht einer Portion kennt das Rezept. Gerechnet wird beim
        # Speichern -- sonst aendert eine spaeter geaenderte Zutat einen
        # vergangenen Tag.
        gramm = round(float(gericht["portion"].get("grams") or 0) * menge, 2)
    else:
        lebensmittel = await db.fetchrow(
            "SELECT id, base_unit, portion_g, portion_label, package_g "
            "  FROM food_items WHERE id=$1 AND user_id=$2",
            daten.item_id, user["id"])
        if not lebensmittel:
            raise HTTPException(404, "Das gibt es in deinem Bestand nicht.")
        eigene = await _groessen_eines(db, daten.item_id)
        basis = lebensmittel["base_unit"] or "g"
        # Ohne Angabe die Standardgroesse: die erste eigene Groesse, sonst
        # 100 g bzw. 100 ml -- der Bezug, in dem die Naehrwerte stehen.
        if daten.amount is None:
            menge = 1.0 if eigene else calc.PORTION_FALLBACK
            einheit = eigene[0]["label"] if eigene else basis
        else:
            menge, einheit = float(daten.amount), (daten.unit or basis)
        if menge <= 0:
            raise HTTPException(400, "Eine Menge von null ist kein Eintrag.")
        erlaubt = [e["key"] for e in calc.einheiten_fuer(dict(lebensmittel), eigene)]
        if einheit not in erlaubt:
            raise HTTPException(
                400, f"„{einheit}“ ist für dieses Lebensmittel keine "
                     "hinterlegte Größe.")
        gramm, _hinweis = calc.in_basis(menge, einheit, dict(lebensmittel), eigene)
        gramm = round(gramm, 2)

    await db.execute(
        "INSERT INTO food_log (user_id, day, dish_id, item_id, meal, note, "
        "   amount, unit, grams, logged_time, meal_auto) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
        user["id"], tag, daten.dish_id, daten.item_id, mahlzeit,
        (daten.note or "").strip() or None, menge, einheit, gramm,
        f"{zeit[0]:02d}:{zeit[1]:02d}" if zeit else None, geraten)
    return await _tag(db, user["id"], tag)


@router.patch("/api/food/track/log/{log_id}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def eintrag_aendern(request: Request, log_id: int, daten: EintragAendern,
                          db=Depends(get_db), user=Depends(get_current_user)):
    """Mahlzeit oder Notiz nachtraeglich richtigstellen.

    Absichtlich nur diese zwei: eine Menge nachtraeglich zu aendern hiesse,
    die Umrechnung von damals zu wiederholen -- dafuer gibt es Loeschen und
    neu eintragen. Eine von Hand gesetzte Mahlzeit ist keine Vermutung mehr,
    deshalb faellt dabei ``meal_auto`` weg.
    """
    zeile = await db.fetchrow(
        "SELECT id, day FROM food_log WHERE id=$1 AND user_id=$2",
        log_id, user["id"])
    if not zeile:
        raise HTTPException(404, "Diesen Eintrag gibt es nicht.")

    felder, werte = [], []
    if daten.meal is not None:
        try:
            werte.append(mz.mahlzeit_sauber(daten.meal))
        except ValueError as e:
            raise HTTPException(400, str(e))
        felder.append(f"meal=${len(werte) + 2}")
        felder.append("meal_auto=FALSE")
    if daten.note is not None:
        werte.append(daten.note.strip() or None)
        felder.append(f"note=${len(werte) + 2}")
    if not felder:
        raise HTTPException(400, "Es wurde nichts zum Ändern übergeben.")

    await db.execute(
        f"UPDATE food_log SET {', '.join(felder)} WHERE id=$1 AND user_id=$2",
        log_id, user["id"], *werte)
    return await _tag(db, user["id"], zeile["day"])


@router.delete("/api/food/track/log/{log_id}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def eintrag_entfernen(request: Request, log_id: int, db=Depends(get_db),
                            user=Depends(get_current_user)):
    zeile = await db.fetchrow(
        "DELETE FROM food_log WHERE id=$1 AND user_id=$2 RETURNING day",
        log_id, user["id"])
    if not zeile:
        raise HTTPException(404, "Diesen Eintrag gibt es nicht.")
    return await _tag(db, user["id"], zeile["day"])


# ---------------------------------------------------------------------------
# Tagesziele
# ---------------------------------------------------------------------------
@router.get("/api/food/track/targets")
async def ziele_lesen(db=Depends(get_db), user=Depends(get_current_user)):
    einst = await _einstellungen(db, user["id"])
    return {
        "targets": _ziele_raus(einst),
        "defaults": {m: float(calc.RICHTWERT[m]) for m in calc.MAKROS},
        "macros": list(calc.MAKROS),
        "macro_labels": dict(calc.MAKRO_LABEL),
        "reference_note": calc.RICHTWERT_QUELLE,
        "target_note": calc.ZIEL_QUELLE,
    }


@router.put("/api/food/track/targets")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def ziele_setzen(request: Request, daten: ZieleEingabe,
                       db=Depends(get_db), user=Depends(get_current_user)):
    """Tagesziele — freiwillig und einzeln.

    Ein Ziel auf ``null`` zu setzen ist kein Fehler, sondern die Rueckkehr
    zum allgemeinen Richtwert: wer nur auf Eiweiss achtet, soll nicht fuenf
    Zahlen erfinden muessen.
    """
    einst = await _einstellungen(db, user["id"])
    ziele = {spalte: einst[spalte] for spalte in calc.ZIEL_SPALTEN.values()}
    for makro, wert in (daten.targets or {}).items():
        spalte = calc.ZIEL_SPALTEN.get(makro)
        if spalte is None:
            raise HTTPException(400, f"Unbekannter Nährwert: {makro}")
        if wert is None or wert == "":
            ziele[spalte] = None
            continue
        try:
            zahl = float(wert)
        except (TypeError, ValueError):
            raise HTTPException(400, f"{calc.MAKRO_LABEL[makro]}: das ist keine Zahl.")
        if zahl <= 0:
            raise HTTPException(
                400, f"{calc.MAKRO_LABEL[makro]}: ein Ziel von null ist keines. "
                     "Leer lassen heißt „kein eigenes Ziel“.")
        if zahl > 100000:
            raise HTTPException(400, f"{calc.MAKRO_LABEL[makro]}: das ist zu viel.")
        ziele[spalte] = round(zahl, 1)

    await db.execute(
        "INSERT INTO food_settings (user_id, kcal_target, protein_target, "
        "   fiber_target, carbs_target, fat_target) "
        "VALUES ($1,$2,$3,$4,$5,$6) "
        "ON CONFLICT (user_id) DO UPDATE SET "
        "   kcal_target=EXCLUDED.kcal_target, protein_target=EXCLUDED.protein_target, "
        "   fiber_target=EXCLUDED.fiber_target, carbs_target=EXCLUDED.carbs_target, "
        "   fat_target=EXCLUDED.fat_target, updated_at=now()",
        user["id"], ziele["kcal_target"], ziele["protein_target"],
        ziele["fiber_target"], ziele["carbs_target"], ziele["fat_target"])
    return await ziele_lesen(db=db, user=user)


# ---------------------------------------------------------------------------
# Verlauf
# ---------------------------------------------------------------------------
@router.get("/api/food/track/history")
async def verlauf(von: Optional[str] = Query(None, alias="from"),
                  bis: Optional[str] = Query(None, alias="to"),
                  db=Depends(get_db), user=Depends(get_current_user)):
    """Ein Zeitraum, Tag fuer Tag — je Naehrwert eine Zahl.

    Tage ohne Eintrag stehen mit Nullen drin und fehlen nicht: eine Luecke,
    die man nicht sieht, wird zu einem Tag, den es nie gab.
    """
    from datetime import timedelta

    ende = _als_tag(bis) if bis else _als_tag(None)
    anfang = _als_tag(von) if von else (ende - timedelta(days=29))
    if anfang > ende:
        anfang = ende
    # Ueber 400 Tage wird die Tagesliste breiter als jede Darstellung --
    # darueber schneidet die Antwort zu und sagt es.
    gekuerzt = (ende - anfang).days > 400
    if gekuerzt:
        anfang = ende - timedelta(days=400)

    zeilen = await db.fetch(
        f"SELECT {SPALTEN_TAG} "
        "  FROM food_log l "
        "  LEFT JOIN food_dishes d ON d.id = l.dish_id "
        "  LEFT JOIN food_items  i ON i.id = l.item_id "
        " WHERE l.user_id=$1 AND l.day >= $2 AND l.day <= $3 "
        " ORDER BY l.day, l.created_at", user["id"], anfang, ende)

    portionen = {g["id"]: g["portion"] for g in await _gerichte(db, user["id"])}
    einst = await _einstellungen(db, user["id"])

    je_tag: dict = {}
    for z in zeilen:
        eintrag, werte = _zeile_rechnen(z, portionen)
        topf = je_tag.setdefault(z["day"], {"eintraege": [], "werte": []})
        topf["eintraege"].append(eintrag)
        topf["werte"].append(werte)

    mass = calc.massstab(einst)
    tage, lauf = [], anfang
    while lauf <= ende:
        topf = je_tag.get(lauf)
        if topf:
            summe = calc.tages_summe_genau(topf["werte"], einst)
            tage.append({
                "day": str(lauf),
                "entries": len(topf["eintraege"]),
                "unknown": sum(1 for e in topf["eintraege"] if not e["has_nutrition"]),
                **{m: {"value": summe[m]["value"], "incomplete": summe[m]["incomplete"]}
                   for m in calc.MAKROS},
            })
        else:
            tage.append({
                "day": str(lauf), "entries": 0, "unknown": 0,
                **{m: {"value": 0, "incomplete": False} for m in calc.MAKROS},
            })
        lauf += timedelta(days=1)

    notiert = [t for t in tage if t["entries"]]
    # Der Schnitt zaehlt nur Tage, an denen JEDER Eintrag Naehrwerte hatte.
    # Ein Tag mit einer Luecke waere sonst ein sehr sparsamer Tag, der es nie war.
    voll = [t for t in notiert if not t["unknown"]]
    im_ziel = [t for t in voll if t["kcal"]["value"] <= mass["kcal"]["wert"]]
    return {
        "from": str(anfang), "to": str(ende),
        "days": tage,
        "truncated": gekuerzt,
        "targets": _ziele_raus(einst),
        "reference": {m: float(calc.RICHTWERT[m]) for m in calc.MAKROS},
        "macros": list(calc.MAKROS),
        "macro_labels": dict(calc.MAKRO_LABEL),
        "summary": {
            "days": len(tage),
            "days_logged": len(notiert),
            "entries": sum(t["entries"] for t in notiert),
            "complete_days": len(voll),
            "target_hit_days": len(im_ziel),
            "kcal_avg": (round(sum(t["kcal"]["value"] for t in voll) / len(voll))
                         if voll else None),
            "protein_avg": (round(sum(t["protein_g"]["value"] for t in voll) / len(voll))
                            if voll else None),
        },
    }


# ---------------------------------------------------------------------------
# Was man oft eintraegt
# ---------------------------------------------------------------------------
@router.get("/api/food/track/frequent")
async def haeufig(limit: int = Query(12, le=40), db=Depends(get_db),
                  user=Depends(get_current_user)):
    """Die Vorschlagsliste des Trackers — aus dem eigenen Bestand.

    Anders als im Tagebuch stehen hier nur Dinge, die es wirklich gibt:
    Gerichte und Lebensmittel. Gezaehlt werden die letzten 120 Tage samt der
    zuletzt eingetragenen Menge, damit ein Vorschlag ein Tipp bleibt und keine
    Rechenaufgabe.
    """
    zeilen = await db.fetch(
        "SELECT CASE WHEN l.dish_id IS NOT NULL THEN 'dish' ELSE 'item' END AS kind, "
        "       l.dish_id, l.item_id, COALESCE(d.name, i.name) AS name, "
        "       COUNT(*)::int AS anzahl, MAX(l.day) AS zuletzt, "
        "       (ARRAY_AGG(l.amount ORDER BY l.day DESC))[1] AS letzte_menge, "
        "       (ARRAY_AGG(l.unit ORDER BY l.day DESC))[1] AS letzte_einheit "
        "  FROM food_log l "
        "  LEFT JOIN food_dishes d ON d.id = l.dish_id "
        "  LEFT JOIN food_items  i ON i.id = l.item_id "
        " WHERE l.user_id=$1 AND l.day >= CURRENT_DATE - 120 "
        "   AND COALESCE(d.name, i.name) IS NOT NULL "
        " GROUP BY 1, 2, 3, 4 "
        " ORDER BY 5 DESC, 6 DESC LIMIT $2", user["id"], int(limit))
    return {"suggestions": [
        {"kind": z["kind"], "dish_id": z["dish_id"], "item_id": z["item_id"],
         "name": z["name"], "count": z["anzahl"], "last": str(z["zuletzt"]),
         "last_amount": float(z["letzte_menge"]) if z["letzte_menge"] else None,
         "last_unit": z["letzte_einheit"]}
        for z in zeilen]}


# ---------------------------------------------------------------------------
# Fotos fuer eigene Gerichte
# ---------------------------------------------------------------------------
# Nur fuer Rezepte, nicht fuer Lebensmittel aus Open Food Facts: ein fremdes
# Produktfoto waere weder mein Essen noch meine Daten. Ein selbst gekochtes
# Gericht erkennt man dagegen am Bild -- und eine Gerichteliste mit Bildern
# ist der sichtbarste Teil davon, dass man die Seite gern benutzt.
#
# Verarbeitet wird mit ``process_image_strict`` aus dem Ausgaben-Modul: EXIF
# gedreht, laengste Kante 1600 px, JPEG q82, Thumbnail 320 px. Bewusst die
# strenge Fassung -- die weiche speichert bei unlesbarem Format
# ``application/octet-stream``, liefert HTTP 200 und ein Bild, das nie
# erscheint (der Fehler von v1.66.0).


async def _gericht_gehoert(db, dish_id: int, user_id: int) -> bool:
    return bool(await db.fetchval(
        "SELECT 1 FROM food_dishes WHERE id=$1 AND user_id=$2", dish_id, user_id))


@router.post("/api/food/dishes/{dish_id}/photo")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def foto_hochladen(request: Request, dish_id: int,
                         file: UploadFile = File(...),
                         db=Depends(get_db), user=Depends(get_current_user)):
    """Ein Foto je Gericht. Ein zweiter Upload ersetzt das erste."""
    if not await _gericht_gehoert(db, dish_id, user["id"]):
        raise HTTPException(404, "Dieses Gericht gibt es nicht.")
    roh = await file.read()
    if len(roh) > FOTO_MAX_BYTES:
        raise HTTPException(
            413, f"Das Bild ist größer als {FOTO_MAX_BYTES // (1024 * 1024)} MB.")
    try:
        gross, klein, mime, groesse = bilder.process_image_strict(roh)
    except ValueError as e:
        raise HTTPException(400, str(e))

    await db.execute(
        "INSERT INTO food_dish_images (dish_id, mime_type, size_bytes, "
        "   image_data, thumbnail_data) VALUES ($1,$2,$3,$4,$5) "
        "ON CONFLICT (dish_id) DO UPDATE SET mime_type=EXCLUDED.mime_type, "
        "   size_bytes=EXCLUDED.size_bytes, image_data=EXCLUDED.image_data, "
        "   thumbnail_data=EXCLUDED.thumbnail_data, uploaded_at=now()",
        dish_id, mime, groesse, gross, klein)
    return {"ok": True, "size": groesse}


@router.get("/api/food/dishes/{dish_id}/photo")
async def foto_lesen(dish_id: int, db=Depends(get_db),
                     user=Depends(get_current_user)):
    zeile = await db.fetchrow(
        "SELECT b.image_data, b.mime_type FROM food_dish_images b "
        "  JOIN food_dishes d ON d.id = b.dish_id "
        " WHERE b.dish_id=$1 AND d.user_id=$2", dish_id, user["id"])
    if not zeile or not zeile["image_data"]:
        raise HTTPException(404, "Zu diesem Gericht gibt es kein Foto.")
    return Response(content=bytes(zeile["image_data"]),
                    media_type=zeile["mime_type"] or "image/jpeg")


@router.get("/api/food/dishes/{dish_id}/thumb")
async def foto_klein(dish_id: int, db=Depends(get_db),
                     user=Depends(get_current_user)):
    zeile = await db.fetchrow(
        "SELECT b.thumbnail_data, b.image_data FROM food_dish_images b "
        "  JOIN food_dishes d ON d.id = b.dish_id "
        " WHERE b.dish_id=$1 AND d.user_id=$2", dish_id, user["id"])
    if not zeile:
        raise HTTPException(404, "Zu diesem Gericht gibt es kein Foto.")
    daten = zeile["thumbnail_data"] or zeile["image_data"]
    if not daten:
        raise HTTPException(404, "Die Bilddaten fehlen.")
    return Response(content=bytes(daten), media_type="image/jpeg")


@router.delete("/api/food/dishes/{dish_id}/photo")
@limiter.limit(LIMIT_WRITE_RARE)
async def foto_entfernen(request: Request, dish_id: int, db=Depends(get_db),
                         user=Depends(get_current_user)):
    if not await _gericht_gehoert(db, dish_id, user["id"]):
        raise HTTPException(404, "Dieses Gericht gibt es nicht.")
    await db.execute("DELETE FROM food_dish_images WHERE dish_id=$1", dish_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Die Bruecke: aus dem Tagebuch wird ein Bestand
# ---------------------------------------------------------------------------
# Wer den Tracker einschaltet, hat oft schon Wochen im Essenstagebuch stehen.
# Diese Namen sind die beste Vorlage fuer einen Bestand, den es noch nicht
# gibt -- und der einzige Punkt, an dem die beiden Module einander kennen.
#
# Sie LIEST nur. Ein Tagebuch-Eintrag von damals bleibt ein Tagebuch-Eintrag
# und wird nicht nachtraeglich zu einer Menge; aus einer Stufe eine Grammzahl
# zu erfinden, waere die falsche Genauigkeit (dieselbe Regel wie in Migration
# 042). Nur der NAECHSTE Eintrag im Tracker profitiert.

# Was zweimal dastand, ist kein Muster, sondern Zufall -- und eine Karte mit
# zwoelf Einmalnennungen waere Arbeit statt Angebot.
BRUECKE_MINDESTENS = 3
BRUECKE_TAGE = 120


class BrueckeAblehnen(BaseModel):
    label: str


@router.get("/api/food/track/bridge")
async def bruecke(db=Depends(get_db), user=Depends(get_current_user)):
    """Haeufige Tagebuch-Namen, die es hier noch nicht gibt."""
    zeilen = await db.fetch(
        "SELECT (ARRAY_AGG(d.label ORDER BY d.day DESC))[1] AS name, "
        "       COUNT(*)::int AS anzahl, MAX(d.day) AS zuletzt "
        "  FROM food_diary d "
        " WHERE d.user_id=$1 AND d.day >= CURRENT_DATE - $2::int "
        "   AND NOT EXISTS (SELECT 1 FROM food_items i "
        "                    WHERE i.user_id=$1 AND lower(i.name)=lower(d.label)) "
        "   AND NOT EXISTS (SELECT 1 FROM food_dishes g "
        "                    WHERE g.user_id=$1 AND lower(g.name)=lower(d.label)) "
        "   AND NOT EXISTS (SELECT 1 FROM food_bridge_dismissed b "
        "                    WHERE b.user_id=$1 AND b.label_lower=lower(d.label)) "
        " GROUP BY lower(d.label) HAVING COUNT(*) >= $3 "
        " ORDER BY 2 DESC, 3 DESC LIMIT 8",
        user["id"], BRUECKE_TAGE, BRUECKE_MINDESTENS)
    tage = await db.fetchval(
        "SELECT COUNT(DISTINCT day)::int FROM food_diary WHERE user_id=$1", user["id"])
    return {"suggestions": [{"name": z["name"], "count": z["anzahl"],
                             "last": str(z["zuletzt"])} for z in zeilen],
            "diary_days": tage or 0}


@router.post("/api/food/track/bridge/dismiss")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def bruecke_ablehnen(request: Request, daten: BrueckeAblehnen,
                           db=Depends(get_db), user=Depends(get_current_user)):
    """Diesen Namen nicht mehr vorschlagen."""
    name = (daten.label or "").strip()
    if not name:
        raise HTTPException(400, "Welcher Name?")
    await db.execute(
        "INSERT INTO food_bridge_dismissed (user_id, label_lower) VALUES ($1,$2) "
        "ON CONFLICT DO NOTHING", user["id"], name.lower())
    return await bruecke(db=db, user=user)
