"""Essenstagebuch — hinschreiben, was es gab. Mehr nicht.

Endpoints:
  GET    /api/food/diary/day        — ein Tag samt Schnellwahl
  POST   /api/food/diary/log        — eintragen
  PATCH  /api/food/diary/log/{id}   — Stufe, Mahlzeit, Name, Notiz richtigstellen
  DELETE /api/food/diary/log/{id}   — Eintrag entfernen
  GET    /api/food/diary/frequent   — was oft eingetragen wird

Drei Entscheidungen tragen dieses Modul:

1. **Es rechnet nicht.** Keine Kalorien, keine Naehrwerte, keine Ziele, kein
   Verlauf. Ein Tagebuch beantwortet eine andere Frage als eine Waage, und die
   Antwortform sagt das: in ``_tag()`` gibt es schlicht kein Feld, in dem eine
   Zahl stehen koennte. Bis v1.96.0 lagen Tagebuch und Tracker in derselben
   Tabelle, und wer im Tracker 100 g eintrug, fand den Eintrag anschliessend
   im Tagebuch -- weil der Schreibweg den eingestellten Modus nie gelesen hat.
   Jetzt ist es nicht verboten, sondern unmoeglich: ``food_diary`` hat keine
   Spalte, in die eine Menge passt.

2. **Es braucht keine Einrichtung.** Kein Bestand, keine Rezepte, kein
   Strichcode. ``label`` ist Text; was man tippt, steht ab dem zweiten Mal in
   der Schnellwahl. Nach ein paar Tagen ist Eintragen ein einziger Tipp --
   und das ist der Punkt, nicht eine Auswertung darueber.

3. **Die Mahlzeit wird geraten, aber nie still.** Die Uhrzeit kommt vom
   Browser (der Server laeuft in UTC), entschieden wird hier, und die Zeile
   traegt ``meal_auto``, damit man der Vermutung ansieht, dass sie eine ist.
   Wer ueber das Plus einer bestimmten Mahlzeit eintraegt, wird gar nicht erst
   gefragt: der Ort sagt den Zusammenhang.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from auth import get_current_user
from database import get_db
from deps import limiter, LIMIT_WRITE_FREQUENT
from services import food_mahlzeit as mz

router = APIRouter(tags=["tagebuch"])

# Die einzige Mengenangabe, die es hier gibt. Die Grenzen sind bewusst grob:
# wer sie feiner macht, misst wieder -- und dafuer gibt es das andere Modul.
STUFEN = ("normal", "viel")
STUFEN_LABEL = {"normal": "normal", "viel": "übermäßig"}

# So lang darf ein Name sein. 120 Zeichen sind mehr als jedes Essen braucht
# und wenig genug, dass niemand eine Notiz daraus macht -- dafuer gibt es
# ``note``.
LABEL_MAX = 120

SPALTEN = ("id, day, label, level, meal, note, logged_time, meal_auto, created_at")

# Woraus die Schnellwahl entsteht. Zwei Monate sind lang genug fuer eine
# Gewohnheit und kurz genug, dass Vergangenes wieder verschwindet.
SCHNELL_TAGE = 60
SCHNELL_ZAHL = 6
# Die Vorschlagsliste im Dialog darf weiter zurueckreichen: dort sucht man.
HAEUFIG_TAGE = 120


class EintragEingabe(BaseModel):
    label: str
    level: str
    meal: Optional[str] = None
    note: Optional[str] = None
    day: Optional[str] = None
    # Ortszeit des Browsers, "HH:MM". Freiwillig: fehlt sie, wird nicht
    # geraten, und der Eintrag landet ohne Zuordnung.
    at: Optional[str] = None


class EintragAendern(BaseModel):
    label: Optional[str] = None
    level: Optional[str] = None
    meal: Optional[str] = None
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------
def _stufe_sauber(wert: str) -> str:
    if wert not in STUFEN:
        raise HTTPException(
            400, "Es gibt zwei Stufen: " + " oder ".join(STUFEN_LABEL.values()) + ".")
    return wert


def _name_sauber(wert) -> str:
    name = (wert or "").strip()
    if not name:
        raise HTTPException(400, "Ohne Namen geht es nicht — ein Wort reicht.")
    if len(name) > LABEL_MAX:
        raise HTTPException(
            400, f"Das ist zu lang für einen Eintrag (höchstens {LABEL_MAX} Zeichen). "
                 "Für mehr ist die Notiz da.")
    return name


def _tag_sauber(wert) -> date:
    if not wert:
        return date.today()
    try:
        return datetime.fromisoformat(str(wert)).date()
    except ValueError:
        raise HTTPException(400, "Das Datum ist nicht lesbar.")


def _mahlzeit_sauber(wert):
    try:
        return mz.mahlzeit_sauber(wert)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _zeile_raus(z) -> dict:
    return {
        "id": z["id"],
        "label": z["label"],
        "level": z["level"],
        "level_label": STUFEN_LABEL.get(z["level"], z["level"]),
        "meal": z["meal"] or mz.OHNE_MAHLZEIT,
        "meal_auto": bool(z["meal_auto"]),
        "note": z["note"],
        "logged_time": z["logged_time"].strftime("%H:%M") if z["logged_time"] else None,
    }


async def _schnellwahl(db, user_id: int, tage: int, zahl: int) -> list:
    """Was oft eingetragen wird — je Schreibweise EINE Zeile.

    Gruppiert wird ueber ``lower(label)``; herausgegeben wird die haeufigste
    Schreibweise. Sonst stuenden „Müsli" und „müsli" zweimal nebeneinander,
    und die Schnellwahl waere genau dort unbrauchbar, wo sie gebraucht wird.
    """
    rows = await db.fetch(
        "SELECT (ARRAY_AGG(label ORDER BY day DESC))[1] AS label, "
        "       COUNT(*)::int AS anzahl, MAX(day) AS zuletzt "
        "  FROM food_diary "
        " WHERE user_id=$1 AND day >= CURRENT_DATE - $2::int "
        " GROUP BY lower(label) "
        " ORDER BY 2 DESC, 3 DESC LIMIT $3", user_id, tage, zahl)
    return [{"label": r["label"], "count": r["anzahl"], "last": r["zuletzt"]}
            for r in rows]


async def _tag(db, user_id: int, tag: date) -> dict:
    """Ein Tag. Was hier NICHT drinsteht, ist die halbe Zusicherung."""
    zeilen = await db.fetch(
        f"SELECT {SPALTEN} FROM food_diary "
        " WHERE user_id=$1 AND day=$2 ORDER BY created_at", user_id, tag)
    eintraege = [_zeile_raus(z) for z in zeilen]
    return {
        "day": str(tag),
        "entries": eintraege,
        "counts": {
            "entries": len(eintraege),
            "normal": sum(1 for e in eintraege if e["level"] == "normal"),
            "viel": sum(1 for e in eintraege if e["level"] == "viel"),
        },
        "meals": mz.liste_raus(),
        "meal_hours": mz.grenzen_raus(),
        "levels": [{"key": s, "label": STUFEN_LABEL[s]} for s in STUFEN],
        "quick": await _schnellwahl(db, user_id, SCHNELL_TAGE, SCHNELL_ZAHL),
    }


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------
@router.get("/api/food/diary/day")
async def tag_lesen(date_: Optional[str] = Query(None, alias="date"),
                    db=Depends(get_db), user=Depends(get_current_user)):
    return await _tag(db, user["id"], _tag_sauber(date_))


@router.get("/api/food/diary/frequent")
async def haeufig(limit: int = Query(14, le=40),
                  db=Depends(get_db), user=Depends(get_current_user)):
    return {"suggestions": await _schnellwahl(
        db, user["id"], HAEUFIG_TAGE, max(1, int(limit)))}


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------
@router.post("/api/food/diary/log")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def eintragen(request: Request, daten: EintragEingabe,
                    db=Depends(get_db), user=Depends(get_current_user)):
    """Ein Eintrag: Name, Stufe, fertig.

    Eine Menge wird hier nicht abgewiesen, weil ein Feld fehlt -- es gibt sie
    im Eingabemodell gar nicht. Wer Gramm eintragen will, ist im anderen Modul.
    """
    name = _name_sauber(daten.label)
    stufe = _stufe_sauber(daten.level)
    tag = _tag_sauber(daten.day)
    mahlzeit = _mahlzeit_sauber(daten.meal)

    zeit = mz.uhrzeit_sauber(daten.at)
    geraten = False
    # Geraten wird nur fuer heute: „es ist jetzt Abend" ist kein Argument
    # darueber, was letzten Dienstag auf dem Teller lag.
    if mahlzeit is None and zeit and tag == date.today():
        mahlzeit = mz.mahlzeit_fuer_uhrzeit(zeit[0])
        geraten = True

    await db.execute(
        "INSERT INTO food_diary (user_id, day, label, level, meal, note, "
        "                        logged_time, meal_auto) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
        user["id"], tag, name, stufe, mahlzeit,
        (daten.note or "").strip() or None,
        f"{zeit[0]:02d}:{zeit[1]:02d}" if zeit else None, geraten)
    return await _tag(db, user["id"], tag)


@router.patch("/api/food/diary/log/{eintrag_id}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def aendern(request: Request, eintrag_id: int, daten: EintragAendern,
                  db=Depends(get_db), user=Depends(get_current_user)):
    """Richtigstellen, ohne loeschen und neu eintragen zu muessen.

    Wer eine Mahlzeit von Hand setzt, widerspricht der Vermutung -- deshalb
    faellt dabei ``meal_auto`` weg. Eine korrigierte Zuordnung darf nicht
    weiter als geraten markiert sein.
    """
    zeile = await db.fetchrow(
        "SELECT id, day FROM food_diary WHERE id=$1 AND user_id=$2",
        eintrag_id, user["id"])
    if not zeile:
        raise HTTPException(404, "Diesen Eintrag gibt es nicht.")

    setzen, werte = [], [eintrag_id, user["id"]]
    if daten.label is not None:
        werte.append(_name_sauber(daten.label))
        setzen.append(f"label=${len(werte)}")
    if daten.level is not None:
        werte.append(_stufe_sauber(daten.level))
        setzen.append(f"level=${len(werte)}")
    if daten.meal is not None:
        werte.append(_mahlzeit_sauber(daten.meal))
        setzen.append(f"meal=${len(werte)}")
        setzen.append("meal_auto=FALSE")
    if daten.note is not None:
        werte.append((daten.note or "").strip() or None)
        setzen.append(f"note=${len(werte)}")
    if not setzen:
        raise HTTPException(400, "Es steht nichts zum Ändern da.")

    await db.execute(
        f"UPDATE food_diary SET {', '.join(setzen)} WHERE id=$1 AND user_id=$2",
        *werte)
    return await _tag(db, user["id"], zeile["day"])


@router.delete("/api/food/diary/log/{eintrag_id}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def entfernen(request: Request, eintrag_id: int,
                    db=Depends(get_db), user=Depends(get_current_user)):
    zeile = await db.fetchrow(
        "DELETE FROM food_diary WHERE id=$1 AND user_id=$2 RETURNING day",
        eintrag_id, user["id"])
    if not zeile:
        raise HTTPException(404, "Diesen Eintrag gibt es nicht.")
    return await _tag(db, user["id"], zeile["day"])
