"""Ernaehrungs-Router — Lebensmittel nachschlagen und aufbewahren.

Endpoints:
  GET    /api/food/barcode/{code}  — Strichcode nachschlagen
  GET    /api/food/search          — Textsuche
  GET    /api/food/catalog         — Stand des eigenen Katalogs
  GET    /api/food/items           — eigener Lebensmittel-Bestand
  POST   /api/food/items           — Lebensmittel aufnehmen oder aendern
  DELETE /api/food/items/{id}      — Lebensmittel entfernen
  GET    /api/food/dishes          — Gerichte samt Zutaten und Naehrwerten
  POST   /api/food/dishes          — Gericht anlegen oder aendern
  DELETE /api/food/dishes/{id}     — Gericht loeschen
  GET    /api/food/day             — ein Tag: Eintraege und Tagesspanne
  POST   /api/food/log            — Eintrag hinzufuegen (Gericht + Stufe,
                                     Lebensmittel + Menge)
  DELETE /api/food/log/{id}        — Eintrag entfernen

Der Bestand ist bewusst eine eigene Tabelle und kein Durchreichen zur
fremden Datenbank: nach ein paar Wochen deckt das, was man selbst einmal
aufgenommen hat, den Alltag ab -- und es bleibt lesbar, wenn Open Food Facts
einen Eintrag aendert oder loescht.

Nachgeschlagen wird nur auf Zuruf. Ein Abruf beim Anzeigen der Liste waere
eine Abfrage je Zeile bei einer fremden, ehrenamtlich betriebenen Datenbank.

Nachgeschlagen wird in dieser Reihenfolge:

    1. der eigene Bestand   -- eigene Korrekturen gehen allem vor
    2. der eigene Katalog   -- der Abzug von Open Food Facts, lokal
    3. Open Food Facts live -- fuer alles, was seit dem Abzug dazukam

Der Katalog vor der Leitung, weil er in Millisekunden antwortet und immer da
ist; die Leitung dahinter, weil ein Abzug altert. Woher eine Zahl kam, steht
in der Antwort (``origin``) -- das gehoert auf den Bildschirm, nicht in eine
stille Annahme.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from auth import get_current_user
from database import get_db
from deps import (limiter, LIMIT_WRITE_FREQUENT, LIMIT_WRITE_RARE,
                  LIMIT_WRITE_STANDARD)
from services import food_calc as calc
from services import food_catalog as katalog
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
    dish_id: Optional[int] = None
    item_id: Optional[int] = None
    # Ein GERICHT wird in Stufen gegessen (normal / uebermaessig), ein
    # einzelnes LEBENSMITTEL in Mengen. Deshalb sind beide Felder freiwillig
    # und die Pruefung haengt daran, was eingetragen wird.
    level: Optional[str] = None
    amount: Optional[float] = None
    unit: Optional[str] = None
    meal: Optional[str] = None
    note: Optional[str] = None
    day: Optional[str] = None


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
    return await katalog.stand(db)


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
        })
    return raus


@router.get("/api/food/dishes")
async def gerichte(db=Depends(get_db), user=Depends(get_current_user)):
    return {"dishes": await _gerichte(db, user["id"]),
            "levels": [{"key": k, "label": v} for k, v in calc.STUFEN_LABEL.items()]}


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

    return {"ok": True, "dishes": await _gerichte(db, user["id"])}


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
# Tagebuch
# ---------------------------------------------------------------------------
def _menge_text(zeile) -> str:
    """Wie die Menge dasteht: „180 g“, „2 × Scheibe (50 g)“.

    Die Grammzahl steht dabei, sobald in einer eigenen Einheit eingetragen
    wurde -- sonst haengt der Naehrwert an einer Zahl, die man nicht sieht.
    """
    def zahl(v):
        return f"{float(v):g}".replace(".", ",")

    basis = zeile["base_unit"] or "g"
    menge = zeile["amount"] if zeile["amount"] is not None else zeile["grams"]
    einheit = zeile["unit"] or basis
    if einheit in calc.RESERVIERT:
        return f"{zahl(menge)} {einheit}"
    return f"{zahl(menge)} × {einheit} ({zahl(zeile['grams'])} {basis})"


async def _tag(db, user_id: int, tag) -> dict:
    """Ein Tag: was eingetragen wurde und was daraus folgt."""
    zeilen = await db.fetch(
        "SELECT l.id, l.level, l.meal, l.note, l.created_at, l.dish_id, l.item_id, "
        "       l.amount, l.unit, l.grams, "
        "       d.name AS dish_name, i.name AS item_name, i.brand AS item_brand, "
        "       i.portion_g, i.base_unit, "
        "       i.kcal, i.protein_g, i.fiber_g, i.carbs_g, i.fat_g "
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

    eintraege, spannen = [], []
    for z in zeilen:
        geschaetzt, menge_text = False, None
        if z["dish_id"]:
            basis = portionen.get(z["dish_id"]) or {}
            name, zusatz = z["dish_name"], "Gericht"
            spanne = calc.eintrag_spanne(basis, z["level"] or "normal")
        elif z["grams"] is not None:
            # Eine gewogene oder abgezaehlte Menge: kein Schaetzen noetig.
            name = z["item_name"]
            zusatz = z["item_brand"] or "Lebensmittel"
            spanne = calc.exakte_spanne(calc.je_menge(dict(z), z["grams"]))
            menge_text = _menge_text(z)
        else:
            # Eintrag von vor v1.90.0: damals gab es auch fuer Lebensmittel
            # nur die Stufe. Er wird weiter so gerechnet, wie er gemeint war
            # -- nachtraeglich eine Grammzahl zu erfinden waere schlimmer.
            portion = float(z["portion_g"]) if z["portion_g"] else calc.PORTION_FALLBACK
            basis = calc.je_menge(dict(z), portion)
            name = z["item_name"]
            zusatz = z["item_brand"] or "Lebensmittel"
            geschaetzt = not z["portion_g"]
            spanne = calc.eintrag_spanne(basis, z["level"] or "normal")
        spannen.append(spanne)
        eintraege.append({
            "id": z["id"], "name": name, "sub": zusatz,
            "kind": "dish" if z["dish_id"] else "item",
            "level": z["level"],
            "level_label": (calc.STUFEN_LABEL.get(z["level"]) if z["level"]
                            and z["grams"] is None else None),
            "amount_label": menge_text,
            "meal": z["meal"], "note": z["note"],
            "assumed_portion": geschaetzt,
            "kcal_min": None if spanne["kcal"] is None else round(spanne["kcal"][0]),
            "kcal_max": None if spanne["kcal"] is None else round(spanne["kcal"][1]),
        })

    return {
        "day": str(tag),
        "entries": eintraege,
        "totals": calc.tages_summe(spannen),
        "macros": list(calc.MAKROS),
        "reference_note": calc.RICHTWERT_QUELLE,
    }


@router.get("/api/food/day")
async def tag(date: Optional[str] = None, db=Depends(get_db),
              user=Depends(get_current_user)):
    from datetime import date as Datum
    if date:
        try:
            tag = Datum.fromisoformat(date)
        except ValueError:
            raise HTTPException(400, "Das ist kein Datum (erwartet: JJJJ-MM-TT).")
    else:
        tag = Datum.today()
    return await _tag(db, user["id"], tag)


@router.post("/api/food/log")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def eintragen(request: Request, daten: LogEingabe, db=Depends(get_db),
                    user=Depends(get_current_user)):
    """Traegt ein Gericht oder ein Lebensmittel fuer einen Tag ein."""
    from datetime import date as Datum
    if bool(daten.dish_id) == bool(daten.item_id):
        raise HTTPException(400, "Entweder ein Gericht oder ein Lebensmittel.")
    if daten.dish_id and daten.level not in calc.STUFEN:
        raise HTTPException(400, "Es gibt nur zwei Stufen: normal oder übermäßig.")
    try:
        tag = Datum.fromisoformat(daten.day) if daten.day else Datum.today()
    except ValueError:
        raise HTTPException(400, "Das ist kein Datum (erwartet: JJJJ-MM-TT).")

    menge, einheit, gramm = None, None, None
    if daten.dish_id:
        gehoert = await db.fetchval(
            "SELECT 1 FROM food_dishes WHERE id=$1 AND user_id=$2",
            daten.dish_id, user["id"])
        if not gehoert:
            raise HTTPException(404, "Das gibt es in deinem Bestand nicht.")
    else:
        # Bei einem einzelnen Lebensmittel wird eine echte Menge eingetragen.
        # Ohne Angabe ist es die Standardgroesse -- die erste eigene Groesse,
        # sonst 100 g bzw. 100 ml, der Bezug der Naehrwerte.
        lebensmittel = await db.fetchrow(
            "SELECT id, base_unit, portion_g, portion_label, package_g "
            "  FROM food_items WHERE id=$1 AND user_id=$2",
            daten.item_id, user["id"])
        if not lebensmittel:
            raise HTTPException(404, "Das gibt es in deinem Bestand nicht.")
        eigene = await _groessen_eines(db, daten.item_id)
        basis = lebensmittel["base_unit"] or "g"
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
        "INSERT INTO food_log (user_id, day, dish_id, item_id, level, meal, note, "
        "   amount, unit, grams) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
        user["id"], tag, daten.dish_id, daten.item_id,
        daten.level if daten.dish_id else None,
        daten.meal, daten.note, menge, einheit, gramm)
    return await _tag(db, user["id"], tag)


@router.delete("/api/food/log/{log_id}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def eintrag_entfernen(request: Request, log_id: int, db=Depends(get_db),
                            user=Depends(get_current_user)):
    zeile = await db.fetchrow(
        "DELETE FROM food_log WHERE id=$1 AND user_id=$2 RETURNING day",
        log_id, user["id"])
    if not zeile:
        raise HTTPException(404, "Diesen Eintrag gibt es nicht.")
    return await _tag(db, user["id"], zeile["day"])
