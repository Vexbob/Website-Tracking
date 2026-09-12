"""Schach-Router — Konten verbinden, Wertungszahlen führen, Partien holen.

Endpoints:
  GET    /api/chess/accounts          — verbundene Konten samt aktueller Wertung
  POST   /api/chess/accounts          — Konto verbinden (prueft den Namen sofort)
  DELETE /api/chess/accounts/{id}     — Konto loesen (Partien bleiben nicht)
  POST   /api/chess/refresh           — Wertungszahlen neu holen
  POST   /api/chess/import            — Partien holen, stueckweise fortsetzbar
  GET    /api/chess/ratings           — Verlauf der Wertungszahlen
  GET    /api/chess/games             — gespeicherte Partien
  GET    /api/chess/summary           — Kopfzahlen (Bilanz, Zeitraum, Stand)
  GET    /api/chess/settings          — Einstellungen der Automatik
  PUT    /api/chess/settings          — Automatik einstellen

Zwei Entscheidungen tragen das Ganze:

1. **Der Import laeuft in Stuecken und ist fortsetzbar.** Zehn Jahre Partien
   sind bei Chess.com ueber hundert Monatsarchive; das in einer Anfrage zu
   holen, laeuft entweder in einen Zeitablauf oder blockiert den Server
   minutenlang. Ein Aufruf holt deshalb hoechstens ``HOECHSTENS_JE_LAUF``
   Partien und sagt in der Antwort, ob noch mehr kommt (``more``). Das
   Frontend ruft, solange das so ist -- und ein Abbruch mittendrin verliert
   nichts, weil der Stand am Konto steht.

2. **Wertungen werden je Tag festgehalten.** Beide Plattformen geben nur den
   aktuellen Stand heraus. Ein Abruf schreibt deshalb eine Tageszeile je
   Disziplin (``ON CONFLICT`` hebt sie), und aus taeglichem Nachsehen wird von
   selbst der Verlauf, den keine der beiden Plattformen herausgibt.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from auth import get_current_user
from database import get_db
from deps import logger, limiter, LIMIT_WRITE_RARE, LIMIT_WRITE_STANDARD
from services import chess_platforms as plattform
from services import chess_sync as sync

router = APIRouter(tags=["chess"])

# Ein Lauf holt hoechstens so viele Partien. 400 ist ein Kompromiss: bei
# Lichess ist das eine einzige Abfrage, bei Chess.com selten mehr als drei
# Monatsarchive -- beides bleibt deutlich unter jedem ueblichen Zeitablauf.
HOECHSTENS_JE_LAUF = sync.STUECK

# Womit sich die Partienliste sortieren laesst. Feste Liste statt
# durchgereichtem Spaltennamen -- sonst steht die Sortierung als Einfallstor
# in der Abfrage.
SORTIERBAR = {
    "datum": "played_at",
    "gegner": "opponent_rating",
    "eigen": "own_rating",
    "differenz": "rating_diff",
}


class KontoEingabe(BaseModel):
    platform: str
    username: str


class Automatik(BaseModel):
    # Taeglicher Lauf des Servers (neue Partien + eine Tageszeile Wertung).
    auto_daily: bool = True
    daily_hour: int = 4
    # Takt bei offener Seite, in Minuten. 0 = aus. Die Liste ist geschlossen:
    # ein freies Feld liesse "1" zu, und das waeren 1.400 Abfragen am Tag fuer
    # eine Zahl, die sich meist nicht bewegt.
    live_minutes: int = 15


def _pruefe_plattform(name: str) -> str:
    if name not in plattform.PLATTFORMEN:
        raise HTTPException(400, "Unbekannte Plattform.")
    return name


# ---------------------------------------------------------------------------
# Konten
# ---------------------------------------------------------------------------
async def _konten_mit_wertung(db, user_id: int) -> list:
    """Konten samt der jeweils juengsten Wertung je Disziplin."""
    konten = await db.fetch(
        "SELECT id, platform, username, profile_url, linked_at, ratings_at, "
        "       games_at, games_through "
        "  FROM chess_accounts WHERE user_id=$1 ORDER BY platform", user_id)
    if not konten:
        return []
    # Je Konto und Disziplin die neueste Zeile. DISTINCT ON ist hier genau
    # richtig: eine Unterabfrage mit MAX(taken_on) braeuchte denselben Index
    # und zwei Durchlaeufe.
    wertungen = await db.fetch(
        "SELECT DISTINCT ON (r.account_id, r.perf) "
        "       r.account_id, r.perf, r.rating, r.rd, r.games, r.is_best, r.taken_on "
        "  FROM chess_ratings r JOIN chess_accounts a ON a.id = r.account_id "
        " WHERE a.user_id=$1 "
        " ORDER BY r.account_id, r.perf, r.taken_on DESC", user_id)
    partien = await db.fetch(
        "SELECT account_id, COUNT(*) AS anzahl, MIN(played_at) AS von, "
        "       MAX(played_at) AS bis "
        "  FROM chess_games WHERE user_id=$1 GROUP BY account_id", user_id)
    je_konto = {r["account_id"]: r for r in partien}

    reihenfolge = {p: i for i, p in enumerate(plattform.PERFS)}
    raus = []
    for k in konten:
        eigene = [w for w in wertungen if w["account_id"] == k["id"]]
        eigene.sort(key=lambda w: reihenfolge.get(w["perf"], 99))
        zahl = je_konto.get(k["id"])
        raus.append({
            "id": k["id"],
            "platform": k["platform"],
            "platform_label": plattform.PLATTFORM_LABEL[k["platform"]],
            "username": k["username"],
            "profile_url": k["profile_url"],
            "linked_at": k["linked_at"],
            "ratings_at": k["ratings_at"],
            "games_at": k["games_at"],
            "games_through": k["games_through"],
            "ratings": [{
                "perf": w["perf"],
                "label": plattform.PERF_LABEL.get(w["perf"], w["perf"]),
                "rating": w["rating"],
                "rd": w["rd"],
                "games": w["games"],
                "is_best": w["is_best"],
                "taken_on": w["taken_on"],
            } for w in eigene],
            "games_count": zahl["anzahl"] if zahl else 0,
            "games_from": zahl["von"] if zahl else None,
            "games_to": zahl["bis"] if zahl else None,
        })
    return raus


@router.get("/api/chess/accounts")
async def konten(db=Depends(get_db), user=Depends(get_current_user)):
    return {"accounts": await _konten_mit_wertung(db, user["id"])}


async def _wertungen_schreiben(db, konto) -> int:
    """Nur noch eine duenne Huelle -- geschrieben wird im Dienst, damit
    Knopfdruck und Automatik dasselbe tun."""
    return await sync.wertungen_holen(db, konto)


@router.post("/api/chess/accounts")
@limiter.limit(LIMIT_WRITE_RARE)
async def konto_verbinden(request: Request, daten: KontoEingabe,
                          db=Depends(get_db), user=Depends(get_current_user)):
    """Verbindet ein Konto — und prueft dabei sofort, ob es den Namen gibt.

    Ein Name, der erst beim naechsten Abruf auffliegt, waere ein Konto, das
    aussieht wie verbunden und keines ist.
    """
    art = _pruefe_plattform(daten.platform)
    try:
        profil = await asyncio.to_thread(plattform.hole_profil, art, daten.username)
    except plattform.PlattformFehler as e:
        raise HTTPException(400, str(e))

    zeile = await db.fetchrow(
        "INSERT INTO chess_accounts (user_id, platform, username, profile_url) "
        "VALUES ($1,$2,$3,$4) "
        "ON CONFLICT (user_id, platform) DO UPDATE "
        "   SET username=EXCLUDED.username, profile_url=EXCLUDED.profile_url "
        "RETURNING id, platform, username, games_through",
        user["id"], art, profil["username"], profil["profile_url"])
    await _wertungen_schreiben(db, zeile)
    return {"ok": True, "accounts": await _konten_mit_wertung(db, user["id"])}


@router.delete("/api/chess/accounts/{konto_id}")
@limiter.limit(LIMIT_WRITE_RARE)
async def konto_loesen(request: Request, konto_id: int, db=Depends(get_db),
                       user=Depends(get_current_user)):
    """Loest das Konto — samt Wertungen und Partien.

    Die Daten haengen am Konto: sie stehenzulassen hiesse, einen Verlauf zu
    behalten, den man nicht mehr fortschreiben kann.
    """
    treffer = await db.fetchrow(
        "DELETE FROM chess_accounts WHERE id=$1 AND user_id=$2 RETURNING id",
        konto_id, user["id"])
    if not treffer:
        raise HTTPException(404, "Dieses Konto gibt es nicht.")
    return {"ok": True, "accounts": await _konten_mit_wertung(db, user["id"])}


@router.post("/api/chess/refresh")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def wertungen_aktualisieren(request: Request, db=Depends(get_db),
                                  user=Depends(get_current_user)):
    """Holt fuer jedes verbundene Konto den aktuellen Stand."""
    konten = await db.fetch(
        "SELECT id, platform, username, games_through FROM chess_accounts "
        " WHERE user_id=$1", user["id"])
    if not konten:
        raise HTTPException(400, "Es ist noch kein Konto verbunden.")

    geholt, probleme = 0, []
    for k in konten:
        try:
            geholt += await _wertungen_schreiben(db, k)
        except plattform.PlattformFehler as e:
            # Eine Plattform, die gerade nicht antwortet, darf die andere nicht
            # mitreissen -- gemeldet wird sie trotzdem.
            probleme.append(f"{plattform.PLATTFORM_LABEL[k['platform']]}: {e}")

    return {"ok": not probleme, "updated": geholt, "problems": probleme,
            "accounts": await _konten_mit_wertung(db, user["id"])}


# ---------------------------------------------------------------------------
# Partien holen
# ---------------------------------------------------------------------------
@router.post("/api/chess/import")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def partien_holen(request: Request, account_id: int = Query(...),
                        db=Depends(get_db), user=Depends(get_current_user)):
    """Holt das naechste Stueck Partien-Historie.

    Aufsteigend ab dem gespeicherten Stand. Antwortet mit ``more: true``,
    solange das Stueck voll war -- dann ist noch Historie offen und der
    naechste Aufruf setzt fort.
    """
    konto = await db.fetchrow(
        "SELECT id, platform, username, games_through FROM chess_accounts "
        " WHERE id=$1 AND user_id=$2", account_id, user["id"])
    if not konto:
        raise HTTPException(404, "Dieses Konto gibt es nicht.")

    lauf = await db.fetchrow(
        "INSERT INTO chess_imports (user_id, account_id) VALUES ($1,$2) RETURNING id",
        user["id"], konto["id"])

    try:
        ergebnis = await sync.partien_stueck(db, user["id"], konto,
                                             hoechstens=HOECHSTENS_JE_LAUF)
    except plattform.PlattformFehler as e:
        await db.execute(
            "UPDATE chess_imports SET finished_at=now(), ok=FALSE, note=$2 "
            " WHERE id=$1", lauf["id"], str(e))
        raise HTTPException(502, str(e))
    except Exception as e:                                  # pragma: no cover
        logger.exception("Schach-Import fehlgeschlagen")
        await db.execute(
            "UPDATE chess_imports SET finished_at=now(), ok=FALSE, note=$2 "
            " WHERE id=$1", lauf["id"], repr(e)[:500])
        raise HTTPException(502, "Die Partien konnten nicht geholt werden.")

    await db.execute(
        "UPDATE chess_imports SET finished_at=now(), games_seen=$2, games_new=$3 "
        " WHERE id=$1", lauf["id"], ergebnis["seen"], ergebnis["new"])

    # Volles Stueck heisst: da ist vermutlich noch mehr. Ein halb volles ist
    # das Ende der Historie -- ab dann holt derselbe Aufruf nur noch Neues.
    return {
        "ok": True,
        "seen": ergebnis["seen"],
        "new": ergebnis["new"],
        "more": ergebnis["more"],
        "through": ergebnis["through"],
        "total": await db.fetchval(
            "SELECT COUNT(*) FROM chess_games WHERE account_id=$1", konto["id"]),
    }


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------
@router.get("/api/chess/ratings")
async def wertungsverlauf(perf: Optional[str] = None, days: Optional[int] = None,
                          db=Depends(get_db), user=Depends(get_current_user)):
    """Der Verlauf je Konto und Disziplin, aufsteigend nach Datum."""
    bedingungen = ["a.user_id=$1"]
    werte = [user["id"]]
    if perf:
        werte.append(perf)
        bedingungen.append(f"r.perf=${len(werte)}")
    if days:
        werte.append(int(days))
        bedingungen.append(f"r.taken_on >= CURRENT_DATE - ${len(werte)}::int")
    rows = await db.fetch(
        "SELECT a.platform, r.perf, r.rating, r.is_best, r.taken_on "
        "  FROM chess_ratings r JOIN chess_accounts a ON a.id = r.account_id "
        f" WHERE {' AND '.join(bedingungen)} "
        " ORDER BY a.platform, r.perf, r.taken_on", *werte)
    return {"points": [dict(r) for r in rows]}


@router.get("/api/chess/games")
async def partien(limit: int = Query(50, le=200), offset: int = 0,
                  platform: Optional[str] = None, perf: Optional[str] = None,
                  result: Optional[str] = None, rated: Optional[bool] = None,
                  q: Optional[str] = None,
                  sort: str = "datum", direction: str = "desc",
                  db=Depends(get_db), user=Depends(get_current_user)):
    """Die gespeicherten Partien, gefiltert und sortiert.

    Sortiert wird ueber eine feste Liste erlaubter Felder (``SORTIERBAR``):
    ein durchgereichter Spaltenname stuende sonst ungeprueft in der Abfrage.
    """
    bedingungen = ["user_id=$1"]
    werte = [user["id"]]
    for feld, wert in (("platform", platform), ("perf", perf), ("result", result)):
        if wert:
            werte.append(wert)
            bedingungen.append(f"{feld}=${len(werte)}")
    if rated is not None:
        werte.append(rated)
        bedingungen.append(f"rated=${len(werte)}")
    if q and q.strip():
        # Suche nach Gegner oder Eroeffnung -- beides ist das, wonach man in
        # einer Partienliste tatsaechlich sucht.
        werte.append(f"%{q.strip()}%")
        bedingungen.append(
            f"(opponent ILIKE ${len(werte)} OR opening ILIKE ${len(werte)})")

    wo = " AND ".join(bedingungen)
    spalte = SORTIERBAR.get(sort, "played_at")
    richtung = "ASC" if str(direction).lower() == "asc" else "DESC"
    # NULLS LAST: eine Partie ohne Wertungsdifferenz soll beim Sortieren nach
    # Differenz nicht die erste Seite fuellen.
    gesamt = await db.fetchval(
        f"SELECT COUNT(*) FROM chess_games WHERE {wo}", *werte)
    rows = await db.fetch(
        "SELECT id, platform, played_at, perf, rated, color, result, end_reason, "
        "       own_rating, rating_diff, opponent, opponent_rating, opening, url "
        f"  FROM chess_games WHERE {wo} "
        f" ORDER BY {spalte} {richtung} NULLS LAST, played_at DESC "
        f" LIMIT {int(limit)} OFFSET {int(offset)}", *werte)
    return {"total": gesamt, "games": [dict(r) for r in rows],
            "sort": sort, "direction": richtung.lower()}


LIVE_TAKTE = (0, 5, 15, 30, 60)


async def _einstellungen(db, user_id: int) -> dict:
    row = await db.fetchrow(
        "SELECT auto_daily, daily_hour, live_minutes, last_auto_at, last_auto_note "
        "  FROM chess_settings WHERE user_id=$1", user_id)
    if not row:
        # Kein Eintrag heisst nicht "aus": die Voreinstellung gilt, bis jemand
        # sie aendert. Sonst laeuft die Automatik bei niemandem, der die
        # Einstellungen nie geoeffnet hat.
        return {"auto_daily": True, "daily_hour": 4, "live_minutes": 15,
                "last_auto_at": None, "last_auto_note": None,
                "live_choices": list(LIVE_TAKTE), "timezone": str(sync.ORTSZEIT)}
    d = dict(row)
    d["live_choices"] = list(LIVE_TAKTE)
    d["timezone"] = str(sync.ORTSZEIT)
    return d


@router.get("/api/chess/settings")
async def automatik_lesen(db=Depends(get_db), user=Depends(get_current_user)):
    return await _einstellungen(db, user["id"])


@router.put("/api/chess/settings")
@limiter.limit(LIMIT_WRITE_STANDARD)
async def automatik_setzen(request: Request, daten: Automatik,
                           db=Depends(get_db), user=Depends(get_current_user)):
    if not 0 <= daten.daily_hour <= 23:
        raise HTTPException(400, "Die Stunde muss zwischen 0 und 23 liegen.")
    if daten.live_minutes not in LIVE_TAKTE:
        raise HTTPException(
            400, "Erlaubt sind " + ", ".join(str(m) for m in LIVE_TAKTE) + " Minuten.")
    await db.execute(
        "INSERT INTO chess_settings (user_id, auto_daily, daily_hour, live_minutes) "
        "VALUES ($1,$2,$3,$4) "
        "ON CONFLICT (user_id) DO UPDATE "
        "   SET auto_daily=EXCLUDED.auto_daily, daily_hour=EXCLUDED.daily_hour, "
        "       live_minutes=EXCLUDED.live_minutes",
        user["id"], daten.auto_daily, daten.daily_hour, daten.live_minutes)
    return await _einstellungen(db, user["id"])


@router.get("/api/chess/summary")
async def kennzahlen(db=Depends(get_db), user=Depends(get_current_user)):
    """Bilanz und Zeitraum — je Plattform getrennt, weil ihre Zahlen es sind."""
    rows = await db.fetch(
        "SELECT platform, COUNT(*) AS partien, "
        "       COUNT(*) FILTER (WHERE result='sieg')        AS siege, "
        "       COUNT(*) FILTER (WHERE result='remis')       AS remis, "
        "       COUNT(*) FILTER (WHERE result='niederlage')  AS niederlagen, "
        "       MIN(played_at) AS von, MAX(played_at) AS bis "
        "  FROM chess_games WHERE user_id=$1 GROUP BY platform", user["id"])
    return {
        "per_platform": [dict(r) for r in rows],
        "accounts": await _konten_mit_wertung(db, user["id"]),
        "settings": await _einstellungen(db, user["id"]),
    }
