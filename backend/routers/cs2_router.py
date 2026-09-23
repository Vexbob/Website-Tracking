"""CS2-Router — Bestand an Spielgegenstaenden, sein Zeitwert und dessen Pflege.

Endpoints:
  GET    /api/cs2/catalog              — Kategorien, Lager, Items fuer die Formulare
  GET    /api/cs2/overview             — Kopfzahlen, Aufteilungen, Verlauf
  GET    /api/cs2/positions            — der Bestand, gefiltert und sortiert
  POST   /api/cs2/positions            — Position anlegen (fuehrt zusammen)
  PATCH  /api/cs2/positions/{id}       — Position aendern
  DELETE /api/cs2/positions/{id}       — Position entfernen
  PUT    /api/cs2/positions/{id}/preis — nur den Preis bestaetigen
  GET    /api/cs2/pflege               — was einen neuen Preis braucht
  POST   /api/cs2/items                — Item anlegen
  PUT    /api/cs2/items/{id}           — Item umbenennen
  DELETE /api/cs2/items/{id}           — Item loeschen (nur ohne Positionen)
  POST   /api/cs2/storages             — Lager anlegen
  PUT    /api/cs2/storages/{id}        — Lager umbenennen
  DELETE /api/cs2/storages/{id}        — Lager loeschen (Positionen ziehen um)
  GET    /api/cs2/snapshots            — Verlauf
  POST   /api/cs2/snapshots            — Stand von heute festhalten
  POST   /api/cs2/import               — Bestand aus einer Datei uebernehmen

Drei Entscheidungen tragen das Ganze:

1. **Liste und Kopfzahlen bauen ihren Filter aus DERSELBEN Funktion.**
   ``_bestand_filter`` liefert die WHERE-Klausel und ihre Werte; die Liste und
   ``/overview`` rufen beide sie auf. Zwei Fassungen desselben Filters sind
   zwei Grundgesamtheiten auf einem Bildschirm -- die Summenzeile der Ausgaben
   hat genau daran bis v2.11.8 eine zu kleine Zahl genannt, ohne dass man es
   der Zeile ansah. Gerechnet wird ueber den ganzen Bestand im Server, nicht
   im Browser ueber das, was gerade geladen ist.

2. **Der Kopf gilt dem Bestand, die Kurve der Historie.** Das sind zwei
   verschiedene Fragen, und deshalb steht der Zeitraum nur an der Kurve. Ein
   Bestand hat kein "im September" -- er ist jetzt da oder nicht. Die Karte
   sagt das auch dazu, statt es offenzulassen.

3. **Ein Preis wird bestaetigt, nicht bloss gesetzt.** ``PUT .../preis``
   schreibt ``priced_at`` auch dann neu, wenn der Preis gleich bleibt: "ich
   habe nachgesehen, es stimmt noch" ist die haeufigste Auskunft bei
   Handpflege und geht sonst verloren. Wer nur die Menge aendert, ruft PATCH
   -- das laesst den Preisstand in Ruhe.
"""
# KEIN ``from __future__ import annotations`` in dieser Datei. Es macht jede
# Annotation zu einer Zeichenkette, und das Pydantic dieser App (2.5.3) kann
# die Vorwaertsreferenz im Endpunkt nicht mehr aufloesen:
#
#     PydanticUndefinedAnnotation: name 'PositionNeu' is not defined
#
# Der Import von ``main`` bricht dabei ab, also startet die GANZE App nicht --
# nicht nur dieses Modul. Neuere Pydantic-Fassungen verzeihen es, deshalb faellt
# es nur gegen die gepinnten Versionen aus ``requirements.txt`` auf.
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from auth import get_current_user
from database import get_db
from deps import logger, limiter, LIMIT_WRITE_FREQUENT, LIMIT_WRITE_RARE, LIMIT_WRITE_STANDARD
from helpers import ser
from services import cs2_rechnung as rechnung
from services import cs2_transfer as transfer

router = APIRouter(tags=["cs2"])

# Wie viele Zeilen eine Listenabfrage hoechstens herausgibt. Der Bestand liegt
# bei gut hundert Positionen; die Grenze ist ein Riegel, kein Seitenwechsel --
# die Kopfzahlen kommen ohnehin aus einer eigenen Abfrage ueber alles.
HOECHSTENS = 1000

SORTIERUNGEN = {
    "wert":      "brutto DESC NULLS LAST, i.name ASC",
    "name":      "i.name ASC",
    "menge":     "p.quantity DESC NULLS LAST, i.name ASC",
    "preis":     "p.price_eur DESC NULLS LAST, i.name ASC",
    "alter":     "p.priced_at ASC NULLS FIRST, i.name ASC",
    "kategorie": "c.sort_order ASC, c.name ASC, i.name ASC",
}


# =========================================================================
# Eingaben
# =========================================================================

class PositionNeu(BaseModel):
    category_id: int
    item_name: str
    storage_id: Optional[int] = None
    wear: Optional[str] = None
    stattrak: bool = False
    playskin: bool = False
    quantity: Optional[int] = None
    price_eur: Optional[str] = None


class PositionAenderung(BaseModel):
    item_name: Optional[str] = None
    storage_id: Optional[int] = None
    wear: Optional[str] = None
    stattrak: Optional[bool] = None
    playskin: Optional[bool] = None
    quantity: Optional[int] = None
    price_eur: Optional[str] = None


class PreisEingabe(BaseModel):
    price_eur: str


class NameEingabe(BaseModel):
    name: str


class ItemNeu(BaseModel):
    category_id: int
    name: str


class SnapshotEingabe(BaseModel):
    note: Optional[str] = None


# =========================================================================
# Geteilte Bausteine
# =========================================================================

def _bestand_filter(user_id: int, suche: Optional[str], kategorien: Optional[str],
                    lager: Optional[str], nur_faellig: bool,
                    ab_index: int = 1) -> tuple[str, list]:
    """WHERE-Klausel und Werte fuer den Bestand -- die EINE Fassung.

    Wird von der Liste, von den Kopfzahlen und von der Pflegeansicht benutzt.
    Getrennte Fassungen waeren getrennte Grundgesamtheiten, und der Unterschied
    faellt erst auf, wenn eine Zahl schon falsch dastand.

    ``ab_index`` sagt, bei welchem ``$n`` die Werte anfangen -- so laesst sich
    die Klausel in eine Abfrage einhaengen, die vorher schon Parameter hat.
    """
    teile = [f"p.user_id = ${ab_index}"]
    werte: list = [user_id]
    n = ab_index + 1

    if suche:
        teile.append(f"(i.name ILIKE ${n} OR c.name ILIKE ${n} OR s.name ILIKE ${n})")
        werte.append(f"%{suche.strip()}%")
        n += 1
    for spalte, roh in (("p.storage_id", lager), ("i.category_id", kategorien)):
        ids = _id_liste(roh)
        if ids:
            teile.append(f"{spalte} = ANY(${n}::int[])")
            werte.append(ids)
            n += 1
    if nur_faellig:
        # Nie bepreist zaehlt mit: eine Zeile ohne Preis ist die faelligste.
        teile.append(f"(p.priced_at IS NULL OR p.priced_at < now() - ${n}::interval)")
        werte.append(timedelta(days=rechnung.ALT_AB_TAGEN))
        n += 1

    return " AND ".join(teile), werte


def _preis(text) -> Optional[Decimal]:
    """Einen eingetippten Preis lesen -- oder mit 400 sagen, warum nicht.

    ``rechnung.preis_lesen`` wirft ``ValueError`` mit einem fertigen deutschen
    Satz. Ungefangen wird daraus ein 500er, und im Browser steht dann
    "Netzwerkfehler" statt "„abc“ ist kein Preis." -- der Satz war fuer den
    Toast geschrieben und kam dort nie an.
    """
    if text is None or text == "":
        return None
    try:
        return rechnung.preis_lesen(text)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _id_liste(roh: Optional[str]) -> list[int]:
    """``"3,7,9"`` wird ``[3, 7, 9]``. Unlesbares faellt still weg."""
    if not roh:
        return []
    out = []
    for teil in str(roh).split(","):
        teil = teil.strip()
        if teil.isdigit():
            out.append(int(teil))
    return out


_BESTAND_VON = """
      FROM cs2_positions p
      JOIN cs2_items     i ON i.id = p.item_id
      JOIN cs2_categories c ON c.id = i.category_id
      JOIN cs2_storages  s ON s.id = p.storage_id
"""


async def _zeilen(db, user_id: int, wo: str, werte: list, ordnung: str = "wert",
                  grenze: int = HOECHSTENS) -> list:
    """Die Positionen samt allem, was die Oberflaeche zeigt."""
    return await db.fetch(
        f"""SELECT p.id, p.item_id, p.storage_id, p.wear, p.stattrak, p.playskin,
                   p.quantity, p.price_eur, p.priced_at, p.created_at,
                   i.name AS item_name, i.category_id,
                   c.name AS category_name,
                   s.name AS storage_name,
                   (p.quantity * p.price_eur) AS brutto
            {_BESTAND_VON}
             WHERE {wo}
             ORDER BY {SORTIERUNGEN.get(ordnung, SORTIERUNGEN['wert'])}
             LIMIT {int(grenze)}""",
        *werte)


def _position_raus(row) -> dict:
    """Eine Zeile so, wie die Oberflaeche sie braucht.

    Brutto und Netto kommen aus der Rechnung und nicht aus der Datenbank --
    eine gespeicherte Summe waere eine zweite Stelle, die dasselbe behauptet.
    """
    d = ser(row, decimals_as_float=True)
    b = rechnung.brutto(row["quantity"], row["price_eur"])
    d["brutto"] = float(b) if b is not None else None
    n = rechnung.netto(b)
    d["netto"] = float(n) if n is not None else None
    d["frische"] = rechnung.frische(row["priced_at"])
    d["alter_tage"] = rechnung.alter_in_tagen(row["priced_at"])
    d["unvollstaendig"] = row["quantity"] is None or row["price_eur"] is None
    d["markt_name"] = rechnung.markt_name(row["item_name"], row["wear"], row["stattrak"])
    return d


async def _lager_standard(db, user_id: int) -> int:
    """Das Auffanglager. Fehlt es, wird es angelegt -- ohne ist nichts ablegbar."""
    vorhanden = await db.fetchval(
        "SELECT id FROM cs2_storages WHERE user_id=$1 AND is_default LIMIT 1", user_id)
    if vorhanden:
        return vorhanden
    return await db.fetchval(
        "INSERT INTO cs2_storages (user_id, name, is_default, sort_order) "
        "VALUES ($1, 'Unsortiert', TRUE, 0) "
        "ON CONFLICT (user_id, name) DO UPDATE SET is_default=TRUE RETURNING id",
        user_id)


async def _item_finden_oder_anlegen(db, user_id: int, category_id: int, name: str) -> int:
    """Ein Item je Name und Kategorie. Der Name entscheidet, nicht die Eingabe."""
    sauber = rechnung.item_name(name)
    if not sauber:
        raise HTTPException(400, "Der Gegenstand braucht einen Namen.")
    kat = await db.fetchval(
        "SELECT id FROM cs2_categories WHERE id=$1 AND user_id=$2", category_id, user_id)
    if not kat:
        raise HTTPException(404, "Diese Kategorie gibt es nicht.")
    return await db.fetchval(
        "INSERT INTO cs2_items (user_id, category_id, name) VALUES ($1,$2,$3) "
        "ON CONFLICT (user_id, category_id, name) DO UPDATE SET name=EXCLUDED.name "
        "RETURNING id",
        user_id, category_id, sauber)


async def _kategorie_regeln(db, user_id: int, category_id: int) -> dict:
    row = await db.fetchrow(
        "SELECT supports_wear, supports_stattrak, supports_playskin "
        "  FROM cs2_categories WHERE id=$1 AND user_id=$2", category_id, user_id)
    if not row:
        raise HTTPException(404, "Diese Kategorie gibt es nicht.")
    return dict(row)


def _regeln_anwenden(regeln: dict, wear, stattrak, playskin) -> tuple:
    """Was die Kategorie nicht kennt, wird geraeumt statt abgelehnt.

    Ein Case hat keine Abnutzung. Eine Eingabe dafuer ist kein Fehler, sondern
    eine Angabe, die es an dieser Stelle nicht gibt -- sie faellt weg, und die
    Position entsteht trotzdem.
    """
    if not regeln["supports_wear"]:
        wear = None
    elif wear not in (None, "") and wear not in rechnung.WEAR_WERTE:
        raise HTTPException(400, f"„{wear}“ ist keine Abnutzung.")
    return (wear or None,
            bool(stattrak) if regeln["supports_stattrak"] else False,
            bool(playskin) if regeln["supports_playskin"] else False)


# =========================================================================
# Katalog
# =========================================================================

@router.get("/api/cs2/catalog")
async def katalog(db=Depends(get_db), user=Depends(get_current_user)):
    """Kategorien, Lager und Items -- alles, woraus die Formulare waehlen."""
    kategorien = await db.fetch(
        "SELECT id, name, supports_wear, supports_stattrak, supports_playskin, sort_order "
        "  FROM cs2_categories WHERE user_id=$1 ORDER BY sort_order, name", user["id"])
    lager = await db.fetch(
        "SELECT s.id, s.name, s.is_default, s.sort_order, "
        "       (SELECT COUNT(*) FROM cs2_positions p WHERE p.storage_id = s.id) AS positionen "
        "  FROM cs2_storages s WHERE s.user_id=$1 ORDER BY s.is_default DESC, s.sort_order, s.name",
        user["id"])
    items = await db.fetch(
        "SELECT i.id, i.category_id, i.name, "
        "       (SELECT COUNT(*) FROM cs2_positions p WHERE p.item_id = i.id) AS positionen "
        "  FROM cs2_items i WHERE i.user_id=$1 ORDER BY i.name", user["id"])
    return {
        "kategorien": [ser(r) for r in kategorien],
        "lager": [ser(r) for r in lager],
        "items": [ser(r) for r in items],
        "wear": [{"wert": w, "label": rechnung.WEAR_LANG[w]} for w in rechnung.WEAR_WERTE],
        "gebuehr": float(rechnung.GEBUEHR),
        "alt_ab_tagen": rechnung.ALT_AB_TAGEN,
        "sehr_alt_ab_tagen": rechnung.SEHR_ALT_AB_TAGEN,
    }


# =========================================================================
# Bestand
# =========================================================================

@router.get("/api/cs2/positions")
async def positionen(suche: Optional[str] = None, kategorien: Optional[str] = None,
                     lager: Optional[str] = None, nur_faellig: bool = False,
                     sortierung: str = "wert",
                     db=Depends(get_db), user=Depends(get_current_user)):
    """Der Bestand. Die Kopfzahlen dazu stehen in ``/overview`` -- mit
    demselben Filter, damit beide dieselbe Menge meinen."""
    wo, werte = _bestand_filter(user["id"], suche, kategorien, lager, nur_faellig)
    rows = await _zeilen(db, user["id"], wo, werte, sortierung)
    gesamt = await db.fetchval(
        f"SELECT COUNT(*) {_BESTAND_VON} WHERE {wo}", *werte)
    return {
        "positionen": [_position_raus(r) for r in rows],
        "gezeigt": len(rows),
        "gesamt": int(gesamt or 0),
        # Ehrlich sagen, wenn die Liste nur ein Stueck zeigt -- sonst steht
        # eine grosse Zahl ueber wenigen Zeilen.
        "gekuerzt": int(gesamt or 0) > len(rows),
    }


@router.get("/api/cs2/overview")
async def ueberblick(suche: Optional[str] = None, kategorien: Optional[str] = None,
                     lager: Optional[str] = None, nur_faellig: bool = False,
                     tage: int = Query(365, ge=0, le=3650),
                     db=Depends(get_db), user=Depends(get_current_user)):
    """Kopfzahlen ueber den gefilterten Bestand, Verlauf ueber den Zeitraum.

    Der Zeitraum gilt NUR der Kurve. Ein Bestand ist jetzt da oder nicht; ihn
    auf einen Monat einzuschraenken hiesse, eine Frage zu beantworten, die
    niemand gestellt hat.
    """
    wo, werte = _bestand_filter(user["id"], suche, kategorien, lager, nur_faellig)
    rows = await db.fetch(
        f"""SELECT p.quantity, p.price_eur, p.playskin, p.priced_at,
                   i.category_id, p.storage_id
            {_BESTAND_VON} WHERE {wo}""", *werte)
    summe = rechnung.summiere([dict(r) for r in rows])

    namen_kat = {r["id"]: r["name"] for r in await db.fetch(
        "SELECT id, name FROM cs2_categories WHERE user_id=$1", user["id"])}
    namen_lag = {r["id"]: r["name"] for r in await db.fetch(
        "SELECT id, name FROM cs2_storages WHERE user_id=$1", user["id"])}

    def aufteilung(werte_je_id: dict, namen: dict) -> list:
        raus = [{"id": k, "name": namen.get(k, "?"), "brutto": float(v)}
                for k, v in werte_je_id.items()]
        raus.sort(key=lambda z: z["brutto"], reverse=True)
        return raus

    verlauf = await db.fetch(
        "SELECT taken_on, total_gross, total_net, playskin_gross, "
        "       rows_valid, rows_incomplete, stale_rows, note "
        "  FROM cs2_snapshots WHERE user_id=$1 "
        "   AND ($2 = 0 OR taken_on >= CURRENT_DATE - $2::int) "
        " ORDER BY taken_on", user["id"], tage)

    # Der Vergleich gilt dem juengsten Stand VOR heute. Ein Snapshot von heute
    # waere der Bestand selbst -- die Differenz dagegen ist immer null und
    # sieht aus wie "nichts passiert".
    vorher = await db.fetchrow(
        "SELECT taken_on, total_gross FROM cs2_snapshots "
        " WHERE user_id=$1 AND taken_on < CURRENT_DATE "
        " ORDER BY taken_on DESC LIMIT 1", user["id"])
    veraenderung = None
    if vorher and vorher["total_gross"] and vorher["total_gross"] > 0:
        diff = summe["brutto"] - Decimal(str(vorher["total_gross"]))
        veraenderung = {
            "seit": vorher["taken_on"].isoformat(),
            "brutto": float(rechnung.cent(diff)),
            "prozent": float(rechnung.cent(diff / Decimal(str(vorher["total_gross"])) * 100)),
        }

    top = await _zeilen(db, user["id"], wo, werte, "wert", grenze=5)

    return {
        "bestand": {
            "brutto": float(summe["brutto"]),
            "netto": float(summe["netto"]),
            "playskin_brutto": float(summe["playskin_brutto"]),
            "playskin_netto": float(summe["playskin_netto"]),
            "invest_brutto": float(summe["invest_brutto"]),
            "invest_netto": float(summe["invest_netto"]),
            "positionen": summe["positionen"],
            "unvollstaendig": summe["unvollstaendig"],
            "veraltet": summe["veraltet"],
            "stueck": summe["stueck"],
        },
        "je_kategorie": aufteilung(summe["je_kategorie"], namen_kat),
        "je_lager": aufteilung(summe["je_lager"], namen_lag),
        "top": [_position_raus(r) for r in top],
        "verlauf": [ser(r, decimals_as_float=True) for r in verlauf],
        "veraenderung": veraenderung,
        "gefiltert": bool(suche or kategorien or lager or nur_faellig),
    }


@router.post("/api/cs2/positions")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def position_anlegen(request: Request, daten: PositionNeu,
                           db=Depends(get_db), user=Depends(get_current_user)):
    """Position anlegen -- oder die vorhandene erhoehen.

    Dieselbe Signatur zweimal einzutragen ist kein Fehler, sondern ein
    Nachkauf: die Mengen werden addiert. Der Preis der bestehenden Zeile wird
    dabei NUR ueberschrieben, wenn einer mitkam -- die Vorgaengerfassung hat
    ihn immer ersetzt und damit bei jedem Nachkauf den alten Stand verloren.
    """
    regeln = await _kategorie_regeln(db, user["id"], daten.category_id)
    wear, stattrak, playskin = _regeln_anwenden(
        regeln, daten.wear, daten.stattrak, daten.playskin)
    item_id = await _item_finden_oder_anlegen(
        db, user["id"], daten.category_id, daten.item_name)
    storage_id = daten.storage_id or await _lager_standard(db, user["id"])
    if not await db.fetchval(
            "SELECT 1 FROM cs2_storages WHERE id=$1 AND user_id=$2", storage_id, user["id"]):
        raise HTTPException(404, "Dieses Lager gibt es nicht.")

    preis = _preis(daten.price_eur)
    menge = daten.quantity

    row = await db.fetchrow(
        """INSERT INTO cs2_positions
               (user_id, item_id, storage_id, wear, stattrak, playskin,
                quantity, price_eur, priced_at)
           -- ``$8`` traegt seinen Typ ausdruecklich: er steht einmal als Wert
           -- und einmal in einem CASE, und Postgres kann ihn dort sonst nicht
           -- bestimmen (AmbiguousParameterError). Dasselbe gilt fuer $7.
           VALUES ($1,$2,$3,$4,$5,$6,$7::int,$8::numeric,
                   CASE WHEN $8::numeric IS NULL THEN NULL ELSE now() END)
           ON CONFLICT (user_id, item_id, COALESCE(wear, ''::text), stattrak, playskin, storage_id)
           DO UPDATE SET
               quantity  = COALESCE(cs2_positions.quantity, 0) + COALESCE(EXCLUDED.quantity, 0),
               price_eur = COALESCE(EXCLUDED.price_eur, cs2_positions.price_eur),
               priced_at = CASE WHEN EXCLUDED.price_eur IS NULL
                                THEN cs2_positions.priced_at ELSE now() END
           RETURNING id""",
        user["id"], item_id, storage_id, wear, stattrak, playskin, menge, preis)
    return await _eine_position(db, user["id"], row["id"])


@router.patch("/api/cs2/positions/{pid}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def position_aendern(request: Request, pid: int, daten: PositionAenderung,
                           db=Depends(get_db), user=Depends(get_current_user)):
    """Eine Position aendern. Der Preisstand bleibt, solange kein Preis kommt."""
    alt = await db.fetchrow(
        "SELECT p.*, i.category_id FROM cs2_positions p "
        "  JOIN cs2_items i ON i.id = p.item_id "
        " WHERE p.id=$1 AND p.user_id=$2", pid, user["id"])
    if not alt:
        raise HTTPException(404, "Diese Position gibt es nicht.")

    regeln = await _kategorie_regeln(db, user["id"], alt["category_id"])
    wear, stattrak, playskin = _regeln_anwenden(
        regeln,
        alt["wear"] if daten.wear is None else daten.wear,
        alt["stattrak"] if daten.stattrak is None else daten.stattrak,
        alt["playskin"] if daten.playskin is None else daten.playskin)

    item_id = alt["item_id"]
    if daten.item_name:
        item_id = await _item_finden_oder_anlegen(
            db, user["id"], alt["category_id"], daten.item_name)
    storage_id = daten.storage_id or alt["storage_id"]
    if not await db.fetchval(
            "SELECT 1 FROM cs2_storages WHERE id=$1 AND user_id=$2", storage_id, user["id"]):
        raise HTTPException(404, "Dieses Lager gibt es nicht.")

    preis = alt["price_eur"]
    preis_neu = False
    if daten.price_eur is not None:
        preis = _preis(daten.price_eur)
        preis_neu = preis != alt["price_eur"] or preis is not None

    menge = alt["quantity"] if daten.quantity is None else daten.quantity

    try:
        await db.execute(
            """UPDATE cs2_positions
                  SET item_id=$3, storage_id=$4, wear=$5, stattrak=$6, playskin=$7,
                      quantity=$8::int, price_eur=$9::numeric,
                      priced_at = CASE WHEN $10::boolean THEN now() ELSE priced_at END
                WHERE id=$1 AND user_id=$2""",
            pid, user["id"], item_id, storage_id, wear, stattrak, playskin,
            menge, preis, preis_neu)
    except Exception as e:
        if "idx_cs2_positions_signatur" in str(e) or "duplicate key" in str(e).lower():
            raise HTTPException(
                400, "Diese Position gibt es schon — gleicher Gegenstand, "
                     "gleiche Ausführung, gleiches Lager.")
        raise
    return await _eine_position(db, user["id"], pid)


@router.put("/api/cs2/positions/{pid}/preis")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def preis_bestaetigen(request: Request, pid: int, daten: PreisEingabe,
                            db=Depends(get_db), user=Depends(get_current_user)):
    """Den Preis bestaetigen -- auch wenn er derselbe bleibt.

    Das ist der haeufigste Handgriff dieses Moduls, und er ist bewusst ein
    eigener Endpunkt: "nachgesehen, stimmt noch" ist eine Auskunft und muss
    ``priced_at`` bewegen, sonst bleibt die Zeile ewig faellig.
    """
    preis = _preis(daten.price_eur)
    if preis is None:
        raise HTTPException(400, "Da steht kein Preis.")
    getroffen = await db.execute(
        "UPDATE cs2_positions SET price_eur=$3, priced_at=now() "
        " WHERE id=$1 AND user_id=$2", pid, user["id"], preis)
    if getroffen.endswith(" 0"):
        raise HTTPException(404, "Diese Position gibt es nicht.")
    return await _eine_position(db, user["id"], pid)


@router.delete("/api/cs2/positions/{pid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def position_loeschen(request: Request, pid: int,
                            db=Depends(get_db), user=Depends(get_current_user)):
    getroffen = await db.execute(
        "DELETE FROM cs2_positions WHERE id=$1 AND user_id=$2", pid, user["id"])
    if getroffen.endswith(" 0"):
        raise HTTPException(404, "Diese Position gibt es nicht.")
    return {"geloescht": pid}


async def _eine_position(db, user_id: int, pid: int) -> dict:
    row = await db.fetchrow(
        f"""SELECT p.id, p.item_id, p.storage_id, p.wear, p.stattrak, p.playskin,
                   p.quantity, p.price_eur, p.priced_at, p.created_at,
                   i.name AS item_name, i.category_id,
                   c.name AS category_name, s.name AS storage_name
            {_BESTAND_VON} WHERE p.id=$1 AND p.user_id=$2""", pid, user_id)
    if not row:
        raise HTTPException(404, "Diese Position gibt es nicht.")
    return _position_raus(row)


# =========================================================================
# Pflege
# =========================================================================

@router.get("/api/cs2/pflege")
async def pflege(db=Depends(get_db), user=Depends(get_current_user)):
    """Was einen neuen Preis braucht, aelteste zuerst.

    Die eigentliche Arbeit dieses Moduls. Weil kein Dienst die Preise liefert,
    ist die Reihenfolge das Werkzeug: wer oben anfaengt, arbeitet die Liste von
    der groessten Unsicherheit her ab.
    """
    wo, werte = _bestand_filter(user["id"], None, None, None, True)
    rows = await _zeilen(db, user["id"], wo, werte, "alter")
    alle = await db.fetchval(
        f"SELECT COUNT(*) {_BESTAND_VON} WHERE p.user_id=$1", user["id"])
    return {
        "faellig": [_position_raus(r) for r in rows],
        "offen": len(rows),
        "bestand": int(alle or 0),
        "alt_ab_tagen": rechnung.ALT_AB_TAGEN,
    }


# =========================================================================
# Stammdaten
# =========================================================================

@router.post("/api/cs2/items")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def item_anlegen(request: Request, daten: ItemNeu,
                       db=Depends(get_db), user=Depends(get_current_user)):
    iid = await _item_finden_oder_anlegen(db, user["id"], daten.category_id, daten.name)
    return ser(await db.fetchrow(
        "SELECT id, category_id, name FROM cs2_items WHERE id=$1", iid))


@router.put("/api/cs2/items/{iid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def item_umbenennen(request: Request, iid: int, daten: NameEingabe,
                          db=Depends(get_db), user=Depends(get_current_user)):
    """Umbenennen ist ein UPDATE an einer Stelle -- die Positionen zeigen hierher."""
    name = rechnung.item_name(daten.name)
    if not name:
        raise HTTPException(400, "Der Gegenstand braucht einen Namen.")
    alt = await db.fetchrow(
        "SELECT id, category_id FROM cs2_items WHERE id=$1 AND user_id=$2", iid, user["id"])
    if not alt:
        raise HTTPException(404, "Diesen Gegenstand gibt es nicht.")
    doppelt = await db.fetchval(
        "SELECT id FROM cs2_items WHERE user_id=$1 AND category_id=$2 AND name=$3 AND id<>$4",
        user["id"], alt["category_id"], name, iid)
    if doppelt:
        raise HTTPException(400, f"„{name}“ gibt es in dieser Kategorie schon.")
    await db.execute("UPDATE cs2_items SET name=$3 WHERE id=$1 AND user_id=$2",
                     iid, user["id"], name)
    return ser(await db.fetchrow(
        "SELECT id, category_id, name FROM cs2_items WHERE id=$1", iid))


@router.delete("/api/cs2/items/{iid}")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def item_loeschen(request: Request, iid: int,
                        db=Depends(get_db), user=Depends(get_current_user)):
    """Ein Gegenstand mit Positionen wird nicht geloescht.

    Sonst verschwindet mit dem Namen der Bestand -- und zwar still, weil der
    Fremdschluessel kaskadiert. Wer ihn loswerden will, loescht erst die
    Positionen; dann steht auch da, was dabei weggeht.
    """
    benutzt = await db.fetchval(
        "SELECT COUNT(*) FROM cs2_positions WHERE item_id=$1 AND user_id=$2", iid, user["id"])
    if benutzt:
        raise HTTPException(
            400, f"Dazu gibt es noch {benutzt} Position(en) im Bestand.")
    getroffen = await db.execute(
        "DELETE FROM cs2_items WHERE id=$1 AND user_id=$2", iid, user["id"])
    if getroffen.endswith(" 0"):
        raise HTTPException(404, "Diesen Gegenstand gibt es nicht.")
    return {"geloescht": iid}


@router.post("/api/cs2/storages")
@limiter.limit(LIMIT_WRITE_RARE)
async def lager_anlegen(request: Request, daten: NameEingabe,
                        db=Depends(get_db), user=Depends(get_current_user)):
    name = (daten.name or "").strip()
    if not name:
        raise HTTPException(400, "Das Lager braucht einen Namen.")
    vorhanden = await db.fetchval(
        "SELECT id FROM cs2_storages WHERE user_id=$1 AND name=$2", user["id"], name)
    if vorhanden:
        raise HTTPException(400, f"Ein Lager „{name}“ gibt es schon.")
    row = await db.fetchrow(
        "INSERT INTO cs2_storages (user_id, name, sort_order) "
        "VALUES ($1,$2,(SELECT COALESCE(MAX(sort_order),0)+1 FROM cs2_storages WHERE user_id=$1)) "
        "RETURNING id, name, is_default, sort_order", user["id"], name)
    return ser(row)


@router.put("/api/cs2/storages/{sid}")
@limiter.limit(LIMIT_WRITE_RARE)
async def lager_umbenennen(request: Request, sid: int, daten: NameEingabe,
                           db=Depends(get_db), user=Depends(get_current_user)):
    name = (daten.name or "").strip()
    if not name:
        raise HTTPException(400, "Das Lager braucht einen Namen.")
    doppelt = await db.fetchval(
        "SELECT id FROM cs2_storages WHERE user_id=$1 AND name=$2 AND id<>$3",
        user["id"], name, sid)
    if doppelt:
        raise HTTPException(400, f"Ein Lager „{name}“ gibt es schon.")
    getroffen = await db.execute(
        "UPDATE cs2_storages SET name=$3 WHERE id=$1 AND user_id=$2", sid, user["id"], name)
    if getroffen.endswith(" 0"):
        raise HTTPException(404, "Dieses Lager gibt es nicht.")
    return ser(await db.fetchrow(
        "SELECT id, name, is_default, sort_order FROM cs2_storages WHERE id=$1", sid))


@router.delete("/api/cs2/storages/{sid}")
@limiter.limit(LIMIT_WRITE_RARE)
async def lager_loeschen(request: Request, sid: int,
                         db=Depends(get_db), user=Depends(get_current_user)):
    """Lager loeschen, Positionen ziehen ins Auffanglager.

    Sie mit dem Lager zu loeschen waere der bequemere Weg und der falsche: ein
    Lagerort ist eine Ordnung, kein Besitz. Das Auffanglager selbst bleibt.
    """
    row = await db.fetchrow(
        "SELECT id, is_default FROM cs2_storages WHERE id=$1 AND user_id=$2", sid, user["id"])
    if not row:
        raise HTTPException(404, "Dieses Lager gibt es nicht.")
    if row["is_default"]:
        raise HTTPException(
            400, "Das Auffanglager bleibt — dorthin ziehen die Positionen "
                 "gelöschter Lager um.")
    ziel = await _lager_standard(db, user["id"])
    umgezogen = 0
    async with db.transaction():
        # Was im Ziel schon steht, wird zusammengefuehrt statt abgelehnt --
        # sonst scheitert das Loeschen an einer Dublette, die der Nutzer gar
        # nicht sieht.
        await db.execute(
            """UPDATE cs2_positions z SET quantity = COALESCE(z.quantity,0) + COALESCE(q.quantity,0)
                 FROM cs2_positions q
                WHERE q.storage_id=$1 AND z.storage_id=$2 AND z.user_id=$3
                  AND q.user_id=$3 AND q.item_id=z.item_id
                  AND q.wear IS NOT DISTINCT FROM z.wear
                  AND q.stattrak=z.stattrak AND q.playskin=z.playskin""",
            sid, ziel, user["id"])
        await db.execute(
            """DELETE FROM cs2_positions q
                WHERE q.storage_id=$1 AND q.user_id=$3
                  AND EXISTS (SELECT 1 FROM cs2_positions z
                               WHERE z.storage_id=$2 AND z.user_id=$3
                                 AND z.item_id=q.item_id
                                 AND z.wear IS NOT DISTINCT FROM q.wear
                                 AND z.stattrak=q.stattrak AND z.playskin=q.playskin)""",
            sid, ziel, user["id"])
        ergebnis = await db.execute(
            "UPDATE cs2_positions SET storage_id=$2 WHERE storage_id=$1 AND user_id=$3",
            sid, ziel, user["id"])
        umgezogen = int(ergebnis.rsplit(" ", 1)[-1] or 0)
        await db.execute("DELETE FROM cs2_storages WHERE id=$1 AND user_id=$2",
                         sid, user["id"])
    return {"geloescht": sid, "umgezogen": umgezogen, "ziel": ziel}


# =========================================================================
# Verlauf
# =========================================================================

@router.get("/api/cs2/snapshots")
async def snapshots(tage: int = Query(365, ge=0, le=3650),
                    db=Depends(get_db), user=Depends(get_current_user)):
    rows = await db.fetch(
        "SELECT id, taken_on, created_at, total_gross, total_net, playskin_gross, "
        "       playskin_net, rows_valid, rows_incomplete, stale_rows, note "
        "  FROM cs2_snapshots WHERE user_id=$1 "
        "   AND ($2 = 0 OR taken_on >= CURRENT_DATE - $2::int) "
        " ORDER BY taken_on DESC", user["id"], tage)
    return [ser(r, decimals_as_float=True) for r in rows]


@router.post("/api/cs2/snapshots")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def snapshot_festhalten(request: Request, daten: SnapshotEingabe,
                              db=Depends(get_db), user=Depends(get_current_user)):
    """Den heutigen Stand festhalten -- ueber den GANZEN Bestand.

    Ausdruecklich ohne Filter: ein Stand, der nur die gerade angezeigten Zeilen
    meint, waere im Verlauf nicht von einem vollen zu unterscheiden. Ein
    zweiter Aufruf am selben Tag ersetzt den Eintrag.
    """
    rows = await db.fetch(
        f"""SELECT p.quantity, p.price_eur, p.playskin, p.priced_at,
                   i.category_id, p.storage_id
            {_BESTAND_VON} WHERE p.user_id=$1""", user["id"])
    summe = rechnung.summiere([dict(r) for r in rows])

    async with db.transaction():
        snap = await db.fetchrow(
            """INSERT INTO cs2_snapshots
                   (user_id, taken_on, total_gross, total_net, playskin_gross,
                    playskin_net, rows_valid, rows_incomplete, stale_rows, note)
               VALUES ($1, CURRENT_DATE, $2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (user_id, taken_on) DO UPDATE SET
                   created_at=now(), total_gross=EXCLUDED.total_gross,
                   total_net=EXCLUDED.total_net, playskin_gross=EXCLUDED.playskin_gross,
                   playskin_net=EXCLUDED.playskin_net, rows_valid=EXCLUDED.rows_valid,
                   rows_incomplete=EXCLUDED.rows_incomplete,
                   stale_rows=EXCLUDED.stale_rows, note=EXCLUDED.note
               RETURNING id, taken_on""",
            user["id"], summe["brutto"], summe["netto"], summe["playskin_brutto"],
            summe["playskin_netto"], summe["positionen"], summe["unvollstaendig"],
            summe["veraltet"], (daten.note or "").strip() or None)
        await db.execute("DELETE FROM cs2_snapshot_categories WHERE snapshot_id=$1", snap["id"])
        await db.execute("DELETE FROM cs2_snapshot_storages WHERE snapshot_id=$1", snap["id"])
        for kid, wert in summe["je_kategorie"].items():
            await db.execute(
                "INSERT INTO cs2_snapshot_categories (snapshot_id, category_id, gross) "
                "VALUES ($1,$2,$3)", snap["id"], kid, wert)
        for lid, wert in summe["je_lager"].items():
            await db.execute(
                "INSERT INTO cs2_snapshot_storages (snapshot_id, storage_id, gross) "
                "VALUES ($1,$2,$3)", snap["id"], lid, wert)

    logger.info("CS2: Stand fuer %s festgehalten (%s Positionen, %s EUR)",
                snap["taken_on"], summe["positionen"], summe["brutto"])
    return ser(await db.fetchrow(
        "SELECT id, taken_on, created_at, total_gross, total_net, playskin_gross, "
        "       playskin_net, rows_valid, rows_incomplete, stale_rows, note "
        "  FROM cs2_snapshots WHERE id=$1", snap["id"]), decimals_as_float=True)


# =========================================================================
# Uebernahme aus einer Datei
# =========================================================================

class ImportEingabe(BaseModel):
    # Das Dokument selbst -- geprueft wird es in ``cs2_transfer``, nicht hier.
    # Ein Pydantic-Modell ueber die ganze Datei waere eine zweite Beschreibung
    # desselben Formats, und die beiden liefen auseinander.
    daten: dict
    # Vorgabe ist die Vorschau. Ein Import, der beim ersten Aufruf schreibt,
    # sieht sich niemand vorher an.
    uebernehmen: bool = False


@router.post("/api/cs2/import")
@limiter.limit(LIMIT_WRITE_RARE)
async def bestand_uebernehmen(request: Request, eingabe: ImportEingabe,
                              db=Depends(get_db), user=Depends(get_current_user)):
    """Einen Bestand aus einer Datei uebernehmen -- erst zeigen, dann tun.

    Ohne ``uebernehmen`` kommt nur die Vorschau zurueck: wie viele Positionen
    neu waeren, wie viele sich aenderten, und je fuenf Beispiele dazu. Das ist
    keine Hoeflichkeit -- eine Datei, die still 116 Zeilen umschreibt, ist
    nicht ueberpruefbar.

    Geloescht wird dabei nie. Was die Datei nicht nennt, bleibt stehen; die
    Vorschau sagt auch, wie viele das waeren.
    """
    try:
        daten = transfer.pruefen(eingabe.daten)
    except transfer.TransferFehler as e:
        raise HTTPException(400, str(e))

    if not eingabe.uebernehmen:
        return {"vorschau": await transfer.vorschau(db, user["id"], daten)}

    try:
        ergebnis = await transfer.einspielen(db, user["id"], daten)
    except transfer.TransferFehler as e:
        raise HTTPException(400, str(e))
    logger.info("CS2: Bestand uebernommen (%s neu, %s geaendert, %s Staende)",
                ergebnis["neu"], ergebnis["geaendert"], ergebnis["staende"])
    return {"uebernommen": ergebnis}
