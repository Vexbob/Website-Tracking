"""Essenstagebuch — hinschreiben, was es gab. Mehr nicht.

Endpoints:
  GET    /api/food/diary/day        — ein Tag samt Schnellwahl (?at=HH:MM: nach Uhrzeit)
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
# v2.33.0: die Schnellwahl richtet sich nach der Uhrzeit. Als „um diese Zeit“
# zaehlt, was hoechstens anderthalb Stunden neben jetzt eingetragen wurde.
# Ein Essen rueckt nach vorn, sobald es mindestens fuenfmal um diese Zeit
# dastand -- vorher ist es keine Gewohnheit, sondern Zufall, und die
# Rangfolge nach Haeufigkeit ist die bessere Antwort.
ZEIT_FENSTER_MIN = 90
ZEIT_AB = 5
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
    # v2.42.0: die Uhrzeit, „HH:MM“; leer nimmt sie weg.
    time: Optional[str] = None


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


def _passt_zur_zeit(z, minute_jetzt: int, mahlzeit_jetzt: str) -> bool:
    """Wurde diese Zeile „um diese Zeit“ eingetragen?

    Mit Uhrzeit zaehlt der Abstand auf der Uhr (rund um Mitternacht herum,
    23:30 liegt neben 00:15). Nachgetragene Tage haben keine Uhrzeit -- dort
    zaehlt die Mahlzeit.
    """
    zeit = z.get("logged_time")
    if zeit is not None:
        abstand = abs(zeit.hour * 60 + zeit.minute - minute_jetzt)
        return min(abstand, 1440 - abstand) <= ZEIT_FENSTER_MIN
    return z.get("meal") == mahlzeit_jetzt


def schnellwahl_rang(zeilen, zahl: int, jetzt=None, schon=()) -> list:
    """Die Schnellwahl aus Rohzeilen -- eine reine Funktion, ohne Datenbank.

    ``zeilen`` kommen neueste zuerst (label, day, meal, logged_time).
    Zusammengefasst wird je Schreibweise klein geschrieben; herausgegeben wird
    die juengste. Sonst stuenden „Müsli“ und „müsli“ zweimal nebeneinander.

    ``jetzt`` ist (stunde, minute) in Ortszeit oder None. Was mindestens
    ``ZEIT_AB``-mal um diese Uhrzeit eingetragen wurde, steht vorn -- unter
    sich danach geordnet, wie oft es um diese Zeit vorkam. Den Rest fuellt
    die Rangfolge nach Haeufigkeit auf.

    ``schon`` sind die klein geschriebenen Namen, die gerade nicht vorgeschlagen
    werden sollen, weil sie in dieser Mahlzeit schon drinstehen -- ein
    angetippter Vorschlag macht so Platz fuer den naechsten.
    """
    minute_jetzt = jetzt[0] * 60 + jetzt[1] if jetzt else None
    mahlzeit_jetzt = mz.mahlzeit_fuer_uhrzeit(jetzt[0]) if jetzt else None
    toepfe: dict = {}
    for z in zeilen:
        name = (z["label"] or "").strip()
        if not name:
            continue
        t = toepfe.setdefault(name.lower(), {
            "label": name, "count": 0, "last": z["day"], "passend": 0})
        t["count"] += 1
        if z["day"] > t["last"]:
            t["last"] = z["day"]
        if jetzt and _passt_zur_zeit(z, minute_jetzt, mahlzeit_jetzt):
            t["passend"] += 1

    kandidaten = [t for k, t in toepfe.items() if k not in schon]

    def rang(t):
        gewohnt = t["passend"] >= ZEIT_AB
        return (0 if gewohnt else 1,
                -t["passend"] if gewohnt else 0,
                -t["count"], -t["last"].toordinal())
    kandidaten.sort(key=rang)
    return [{"label": t["label"], "count": t["count"], "last": t["last"]}
            for t in kandidaten[:zahl]]


async def _schnellwahl(db, user_id: int, tage: int, zahl: int,
                       jetzt=None, schon=()) -> list:
    """Was oft eingetragen wird -- je Schreibweise EINE Zeile.

    Seit v2.33.0 rechnet ``schnellwahl_rang`` in Python statt eine
    GROUP-BY-Abfrage: die Uhrzeit-Rangfolge braucht die einzelnen Zeilen, und
    zwei Monate Tagebuch sind ein paar hundert davon.
    """
    # Was aus „Meine Lebensmittel“ genommen wurde, schlaegt sie nicht mehr vor.
    zeilen = await db.fetch(
        "SELECT label, day, meal, logged_time FROM food_diary d "
        " WHERE user_id=$1 AND day >= CURRENT_DATE - $2::int "
        "   AND NOT EXISTS (SELECT 1 FROM food_diary_ausgeblendet a "
        "                    WHERE a.user_id=d.user_id AND a.schluessel=lower(btrim(d.label))) "
        " ORDER BY day DESC, created_at DESC", user_id, tage)
    return schnellwahl_rang(zeilen, zahl, jetzt, schon)


async def _tag(db, user_id: int, tag: date, jetzt=None) -> dict:
    """Ein Tag. Was hier NICHT drinsteht, ist die halbe Zusicherung.

    ``jetzt`` ist die Ortszeit des Browsers als (stunde, minute). Sie zaehlt
    nur fuer heute: an einem vergangenen Tag sagt die Uhr nichts darueber,
    was damals um diese Zeit gegessen wurde.
    """
    zeilen = await db.fetch(
        f"SELECT {SPALTEN} FROM food_diary "
        " WHERE user_id=$1 AND day=$2 ORDER BY created_at", user_id, tag)
    eintraege = [_zeile_raus(z) for z in zeilen]
    if tag != date.today():
        jetzt = None
    # Was in der Mahlzeit von jetzt schon steht, wird nicht noch einmal
    # vorgeschlagen -- der Kaffee am Morgen kommt nachmittags wieder. An einem
    # nachgetragenen Tag faellt alles weg, was an dem Tag schon steht.
    if jetzt:
        mahlzeit_jetzt = mz.mahlzeit_fuer_uhrzeit(jetzt[0])
        schon = {e["label"].lower() for e in eintraege if e["meal"] == mahlzeit_jetzt}
    else:
        schon = {e["label"].lower() for e in eintraege}
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
        "quick": await _schnellwahl(db, user_id, SCHNELL_TAGE, SCHNELL_ZAHL,
                                    jetzt, schon),
    }


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------
@router.get("/api/food/diary/day")
async def tag_lesen(date_: Optional[str] = Query(None, alias="date"),
                    at: Optional[str] = Query(None),
                    db=Depends(get_db), user=Depends(get_current_user)):
    return await _tag(db, user["id"], _tag_sauber(date_), mz.uhrzeit_sauber(at))


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
    # Die Uhr des Browsers sagt, wie spaet es JETZT ist -- nicht, wann am
    # letzten Dienstag gegessen wurde. An einem vergangenen Tag traegt sie
    # deshalb weder die Mahlzeit noch die Uhrzeit an der Zeile: eine Zeit,
    # die nur sagt, wann jemand getippt hat, stuende dort sonst als
    # Essenszeit -- und im Export in der Spalte Uhrzeit.
    if tag != date.today():
        zeit = None
    geraten = False
    if mahlzeit is None and zeit:
        mahlzeit = mz.mahlzeit_fuer_uhrzeit(zeit[0])
        geraten = True

    await db.execute(
        "INSERT INTO food_diary (user_id, day, label, level, meal, note, "
        "                        logged_time, meal_auto) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
        user["id"], tag, name, stufe, mahlzeit,
        (daten.note or "").strip() or None,
        mz.uhrzeit_fuer_spalte(zeit), geraten)
    # Wieder eingetragen ist wieder da (v2.42.0).
    await db.execute("DELETE FROM food_diary_ausgeblendet WHERE user_id=$1 AND schluessel=$2",
                     user["id"], name.strip().lower())
    return await _tag(db, user["id"], tag, zeit)


@router.patch("/api/food/diary/log/{eintrag_id}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def aendern(request: Request, eintrag_id: int, daten: EintragAendern,
                  at: Optional[str] = Query(None),
                  db=Depends(get_db), user=Depends(get_current_user)):
    """Richtigstellen, ohne loeschen und neu eintragen zu muessen.

    Wer eine Mahlzeit von Hand setzt, widerspricht der Vermutung -- deshalb
    faellt dabei ``meal_auto`` weg. Eine korrigierte Zuordnung darf nicht
    weiter als geraten markiert sein.
    """
    zeile = await db.fetchrow(
        "SELECT id, day, meal_auto FROM food_diary WHERE id=$1 AND user_id=$2",
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
    # v2.42.0: die Uhrzeit richtigstellen. War die Mahlzeit aus der alten
    # Uhrzeit nur geraten, wird sie aus der neuen neu geraten; eine von Hand
    # gesetzte bleibt -- der Ort schlaegt die Uhr.
    if daten.time is not None:
        neu = mz.uhrzeit_sauber(daten.time) if daten.time.strip() else None
        if daten.time.strip() and neu is None:
            raise HTTPException(400, "Die Uhrzeit ist nicht lesbar (HH:MM).")
        werte.append(mz.uhrzeit_fuer_spalte(neu))
        setzen.append(f"logged_time=${len(werte)}")
        if neu and daten.meal is None and zeile["meal_auto"]:
            werte.append(mz.mahlzeit_fuer_uhrzeit(neu[0]))
            setzen.append(f"meal=${len(werte)}")
    if not setzen:
        raise HTTPException(400, "Es steht nichts zum Ändern da.")

    await db.execute(
        f"UPDATE food_diary SET {', '.join(setzen)} WHERE id=$1 AND user_id=$2",
        *werte)
    return await _tag(db, user["id"], zeile["day"], mz.uhrzeit_sauber(at))


@router.get("/api/food/diary/foods")
async def meine_lebensmittel(db=Depends(get_db), user=Depends(get_current_user)):
    """Alles, was je eingetragen wurde -- je Schreibweise klein geschrieben
    EINE Zeile mit der juengsten Schreibweise, wie in der Schnellwahl. Was
    herausgenommen wurde, fehlt."""
    zeilen = await db.fetch(
        "SELECT lower(btrim(label)) AS schluessel, "
        "       (array_agg(label ORDER BY day DESC, created_at DESC))[1] AS label, "
        "       COUNT(*) AS anzahl, MAX(day) AS zuletzt, MIN(day) AS zuerst "
        "  FROM food_diary d WHERE user_id=$1 "
        "   AND NOT EXISTS (SELECT 1 FROM food_diary_ausgeblendet a "
        "                    WHERE a.user_id=d.user_id AND a.schluessel=lower(btrim(d.label))) "
        " GROUP BY lower(btrim(label)) ORDER BY COUNT(*) DESC, MAX(day) DESC", user["id"])
    return {"foods": [{"label": z["label"], "anzahl": int(z["anzahl"]),
                       "zuletzt": z["zuletzt"].isoformat(), "zuerst": z["zuerst"].isoformat()}
                      for z in zeilen]}


@router.delete("/api/food/diary/foods")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def lebensmittel_entfernen(request: Request, label: str = Query(..., min_length=1, max_length=200),
                                 eintraege: bool = Query(False),
                                 db=Depends(get_db), user=Depends(get_current_user)):
    """Aus „Meine Lebensmittel“ und der Schnellwahl nehmen. Mit
    ``eintraege=1`` verschwinden zusaetzlich alle Tagebuch-Eintraege mit
    diesem Namen -- sonst bleiben die Tage, wie sie waren."""
    schluessel = label.strip().lower()
    weg = 0
    async with db.transaction():
        await db.execute(
            "INSERT INTO food_diary_ausgeblendet (user_id, schluessel) VALUES ($1,$2) "
            "ON CONFLICT (user_id, schluessel) DO UPDATE SET ausgeblendet_at=NOW()",
            user["id"], schluessel)
        if eintraege:
            r = await db.execute(
                "DELETE FROM food_diary WHERE user_id=$1 AND lower(btrim(label))=$2",
                user["id"], schluessel)
            try:
                weg = int(str(r).rsplit(" ", 1)[-1])
            except ValueError:
                weg = 0
    return {"status": "ok", "eintraege_geloescht": weg}


@router.delete("/api/food/diary/log/{eintrag_id}")
@limiter.limit(LIMIT_WRITE_FREQUENT)
async def entfernen(request: Request, eintrag_id: int,
                    at: Optional[str] = Query(None),
                    db=Depends(get_db), user=Depends(get_current_user)):
    zeile = await db.fetchrow(
        "DELETE FROM food_diary WHERE id=$1 AND user_id=$2 RETURNING day",
        eintrag_id, user["id"])
    if not zeile:
        raise HTTPException(404, "Diesen Eintrag gibt es nicht.")
    return await _tag(db, user["id"], zeile["day"], mz.uhrzeit_sauber(at))
