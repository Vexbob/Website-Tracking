"""Ernaehrungs-Router — Lebensmittel nachschlagen und aufbewahren.

Endpoints:
  GET    /api/food/barcode/{code}  — Strichcode bei Open Food Facts nachschlagen
  GET    /api/food/search          — Textsuche bei Open Food Facts
  GET    /api/food/items           — eigener Lebensmittel-Bestand
  POST   /api/food/items           — Lebensmittel aufnehmen oder aendern
  DELETE /api/food/items/{id}      — Lebensmittel entfernen

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
from deps import limiter, LIMIT_WRITE_RARE, LIMIT_WRITE_STANDARD
from services import openfoodfacts as off

router = APIRouter(tags=["food"])

SPALTEN = ("kcal", "protein_g", "carbs_g", "sugar_g", "fat_g", "sat_fat_g",
           "fiber_g", "salt_g", "portion_g")


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
