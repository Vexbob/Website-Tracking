"""Ernaehrungs-Router — Lebensmittel nachschlagen und aufbewahren.

Endpoints:
  GET    /api/food/barcode/{code}  — Strichcode bei Open Food Facts nachschlagen
  GET    /api/food/search          — Textsuche bei Open Food Facts
  GET    /api/food/items           — eigener Lebensmittel-Bestand
  POST   /api/food/items           — Lebensmittel aufnehmen oder aendern
  DELETE /api/food/items/{id}      — Lebensmittel entfernen
  GET    /api/food/dishes          — Gerichte samt Zutaten und Naehrwerten
  POST   /api/food/dishes          — Gericht anlegen oder aendern
  DELETE /api/food/dishes/{id}     — Gericht loeschen
  GET    /api/food/day             — ein Tag: Eintraege und Tagesspanne
  POST   /api/food/log             — Eintrag hinzufuegen (Gericht/Lebensmittel + Stufe)
  DELETE /api/food/log/{id}        — Eintrag entfernen

Der Bestand ist bewusst eine eigene Tabelle und kein Durchreichen zur
fremden Datenbank: nach ein paar Wochen deckt das, was man selbst einmal
aufgenommen hat, den Alltag ab -- und es bleibt lesbar, wenn Open Food Facts
einen Eintrag aendert oder loescht.

Nachgeschlagen wird nur auf Zuruf. Ein Abruf beim Anzeigen der Liste waere
eine Abfrage je Zeile bei einer fremden, ehrenamtlich betriebenen Datenbank.
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
from services import openfoodfacts as off

router = APIRouter(tags=["food"])

SPALTEN = ("kcal", "protein_g", "carbs_g", "sugar_g", "fat_g", "sat_fat_g",
           "fiber_g", "salt_g", "portion_g")


class Zutat(BaseModel):
    item_id: int
    grams: float


class GerichtEingabe(BaseModel):
    id: Optional[int] = None
    name: str
    note: Optional[str] = None
    items: list[Zutat] = []


class LogEingabe(BaseModel):
    dish_id: Optional[int] = None
    item_id: Optional[int] = None
    level: str = "normal"
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
    # Von Hand nachgebessert: ein erneuter Abruf laesst die Zeile dann in Ruhe.
    user_edited: bool = False


def _ser(row) -> dict:
    d = dict(row)
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
    try:
        produkt = await asyncio.to_thread(off.hole_produkt, ziffern)
    except off.QuellenFehler as e:
        if vorhanden:
            # Im Bestand ist er ja -- dass die fremde Datenbank ihn nicht
            # (mehr) kennt, ist dann eine Randnotiz und kein Fehler.
            return {"found": False, "known": _ser(vorhanden), "note": str(e)}
        raise HTTPException(404, str(e))
    return {"found": True, "product": produkt,
            "known": _ser(vorhanden) if vorhanden else None}


@router.get("/api/food/search")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def suche(request: Request, q: str = Query(..., min_length=2),
                user=Depends(get_current_user)):
    """Textsuche — fuer alles ohne Strichcode."""
    try:
        treffer = await asyncio.to_thread(off.suche, q)
    except off.QuellenFehler as e:
        raise HTTPException(502, str(e))
    return {"results": treffer}


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
    return {"items": [_ser(r) for r in rows]}


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
    ziffern = "".join(z for z in (daten.barcode or "") if z.isdigit()) or None

    werte = [user["id"], daten.source, ziffern, name, daten.brand,
             daten.kcal, daten.protein_g, daten.carbs_g, daten.sugar_g,
             daten.fat_g, daten.sat_fat_g, daten.fiber_g, daten.salt_g,
             daten.portion_g, daten.user_edited]
    zeile = await db.fetchrow(
        "INSERT INTO food_items (user_id, source, barcode, name, brand, kcal, "
        "   protein_g, carbs_g, sugar_g, fat_g, sat_fat_g, fiber_g, salt_g, "
        "   portion_g, user_edited) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15) "
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
        "   user_edited = food_items.user_edited OR EXCLUDED.user_edited, "
        "   updated_at = now() "
        "RETURNING *", *werte)
    return {"ok": True, "item": _ser(zeile)}


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
    zutaten = await db.fetch(
        "SELECT z.dish_id, z.id AS link_id, z.grams, z.position, "
        "       i.id AS item_id, i.name, i.brand, "
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
                       "brand": z["brand"]} for z in eigene],
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
            if zutat.grams <= 0:
                raise HTTPException(400, "Eine Zutat ohne Menge ergibt keine Portion.")
            # Das Lebensmittel muss dem Konto gehoeren -- sonst liesse sich
            # ueber eine fremde ID ein fremder Bestand auslesen.
            gehoert = await db.fetchval(
                "SELECT 1 FROM food_items WHERE id=$1 AND user_id=$2",
                zutat.item_id, user["id"])
            if not gehoert:
                raise HTTPException(400, "Unbekanntes Lebensmittel in der Zutatenliste.")
            await db.execute(
                "INSERT INTO food_dish_items (dish_id, item_id, grams, position) "
                "VALUES ($1,$2,$3,$4)", zeile["id"], zutat.item_id, zutat.grams, platz)

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
async def _tag(db, user_id: int, tag) -> dict:
    """Ein Tag: was eingetragen wurde und was daraus folgt."""
    zeilen = await db.fetch(
        "SELECT l.id, l.level, l.meal, l.note, l.created_at, l.dish_id, l.item_id, "
        "       d.name AS dish_name, i.name AS item_name, i.brand AS item_brand, "
        "       i.portion_g, i.kcal, i.protein_g, i.fiber_g, i.carbs_g, i.fat_g "
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
        if z["dish_id"]:
            basis = portionen.get(z["dish_id"]) or {}
            name, zusatz, geschaetzt = z["dish_name"], "Gericht", False
        else:
            portion = float(z["portion_g"]) if z["portion_g"] else calc.PORTION_FALLBACK
            anteil = portion / 100.0
            basis = {m: (None if z[m] is None else float(z[m]) * anteil)
                     for m in calc.MAKROS}
            name = z["item_name"]
            zusatz = z["item_brand"] or "Lebensmittel"
            geschaetzt = not z["portion_g"]
        spanne = calc.eintrag_spanne(basis, z["level"])
        spannen.append(spanne)
        eintraege.append({
            "id": z["id"], "name": name, "sub": zusatz,
            "kind": "dish" if z["dish_id"] else "item",
            "level": z["level"],
            "level_label": calc.STUFEN_LABEL.get(z["level"], z["level"]),
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
    if daten.level not in calc.STUFEN:
        raise HTTPException(400, "Es gibt nur zwei Stufen: normal oder übermäßig.")
    try:
        tag = Datum.fromisoformat(daten.day) if daten.day else Datum.today()
    except ValueError:
        raise HTTPException(400, "Das ist kein Datum (erwartet: JJJJ-MM-TT).")

    tabelle = "food_dishes" if daten.dish_id else "food_items"
    fremd = daten.dish_id or daten.item_id
    gehoert = await db.fetchval(
        f"SELECT 1 FROM {tabelle} WHERE id=$1 AND user_id=$2", fremd, user["id"])
    if not gehoert:
        raise HTTPException(404, "Das gibt es in deinem Bestand nicht.")

    await db.execute(
        "INSERT INTO food_log (user_id, day, dish_id, item_id, level, meal, note) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7)",
        user["id"], tag, daten.dish_id, daten.item_id, daten.level,
        daten.meal, daten.note)
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
