"""Der eigene Katalog — Nachschlagen ohne fremden Dienst.

Dieselbe Form wie ``openfoodfacts.py``, damit der Router nur eine kennt:
ein Treffer ist ein dict mit Name, Marke, Naehrwerten je 100 und der Liste
der fehlenden Angaben. Nur ``source`` unterscheidet sich -- ``katalog``
statt ``off`` --, damit im Frontend dransteht, woher die Zahl kommt.

Gefuellt wird die Tabelle aus dem taeglichen Abzug von Open Food Facts
(``scripts/off_katalog.py``). Sie ist damit ein **Stand**, keine Leitung:
schnell und immer da, aber ein paar Wochen alt. Deshalb bleibt Open Food
Facts als Rueckfall bestehen -- ein Produkt, das es dort seit gestern gibt,
steht hier noch nicht.
"""

NAEHRWERTE = ("kcal", "protein_g", "carbs_g", "sugar_g", "fat_g",
              "sat_fat_g", "fiber_g", "salt_g")

# Mehr Woerter helfen der Suche nicht mehr, kosten aber je eines einen
# weiteren Durchgang durch den Index.
WOERTER_MAX = 4


def _umbauen(row) -> dict:
    daten = {
        "barcode": row["code"],
        "name": row["name"],
        "brand": row["brand"] or None,
        "base_unit": row["base_unit"] or "g",
        "portion_g": float(row["portion_g"]) if row["portion_g"] is not None else None,
        "quantity": None,
        "source": "katalog",
        "updated_at": row["updated_at"],
    }
    for spalte in NAEHRWERTE:
        wert = row[spalte]
        daten[spalte] = float(wert) if wert is not None else None
    daten["missing"] = [s for s in NAEHRWERTE if daten[s] is None]
    daten["usable"] = bool(daten["name"]) and daten["kcal"] is not None
    return daten


async def nach_code(db, code: str):
    """Ein Produkt zum Strichcode — oder None."""
    ziffern = "".join(z for z in str(code or "") if z.isdigit())
    if not ziffern:
        return None
    zeile = await db.fetchrow("SELECT * FROM food_catalog WHERE code=$1", ziffern)
    return _umbauen(zeile) if zeile else None


async def suche(db, text: str, hoechstens: int = 12) -> list:
    """Textsuche im Katalog.

    Alle Woerter muessen vorkommen, in beliebiger Reihenfolge -- "milka
    alpenmilch" findet auch "Alpenmilch Schokolade, Milka". Gesucht wird
    ueber Name und Marke zusammen, weil genau dieser Ausdruck den Index
    traegt.
    """
    woerter = [w for w in str(text or "").split() if len(w) >= 2][:WOERTER_MAX]
    if not woerter:
        return []

    feld = "(name || ' ' || COALESCE(brand, ''))"
    bedingungen = " AND ".join(
        f"{feld} ILIKE ${i + 1}" for i in range(len(woerter)))
    werte = [f"%{w}%" for w in woerter]
    # Der erste Begriff steuert zusaetzlich die Reihenfolge: was damit
    # anfaengt, ist fast immer das Gesuchte ("Apfel" vor "Bratapfel-Joghurt").
    werte.append(woerter[0] + "%")
    anfang = f"${len(werte)}"

    zeilen = await db.fetch(
        f"SELECT * FROM food_catalog WHERE {bedingungen} "
        f" ORDER BY (name ILIKE {anfang}) DESC, length(name), lower(name) "
        f" LIMIT {int(hoechstens)}", *werte)
    return [_umbauen(z) for z in zeilen]


async def stand(db) -> dict:
    """Wie viel im Katalog steht und wie alt er ist.

    Beides gehoert auf die Seite: ein Nachschlagewerk, dessen Alter man
    nicht sieht, wird irgendwann geglaubt, obwohl es nicht mehr stimmt.
    """
    zeile = await db.fetchrow(
        "SELECT count(*) AS anzahl, max(updated_at) AS neuestes FROM food_catalog")
    return {"count": zeile["anzahl"] or 0, "newest": zeile["neuestes"]}
