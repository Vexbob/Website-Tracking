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
  GET    /api/chess/stats             — die ganze Auswertung eines Zeitraums
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

2. **Der Verlauf kommt aus den Partien, nicht aus den Tageszeilen.** Beide
   Plattformen geben nur den aktuellen Stand heraus; die Tageszeile je Abruf
   (``chess_ratings``) beginnt deshalb am Tag des Verbindens und ist zwei
   Wochen spaeter immer noch eine gerade Linie. Die eigentliche Historie steht
   laengst im Bestand: jede gewertete Partie traegt die eigene Wertung, und
   ``own_rating + rating_diff`` ist der Stand NACH dieser Partie -- bei
   Lichess, weil ``rating`` davor gilt und die Differenz mitkommt, bei
   Chess.com, weil ``rating`` schon der Stand danach ist und keine Differenz
   geliefert wird. Aus beiden Quellen entsteht eine Kurve ueber die ganze
   Spielzeit; die Tageszeile bleibt und fuellt die Tage, an denen nicht
   gespielt wurde (und den heutigen, bevor die Partien geholt sind).

3. **Ausgewertet wird im Server ueber den ganzen Bestand.** Vorher rechnete
   die Seite ueber die zuletzt geladenen 200 Partien und stellte diesen
   Ausschnitt neben Kopfzahlen ueber alles -- zwei Grundgesamtheiten auf einem
   Bildschirm. Jetzt gilt ein Zeitraum fuer die ganze Seite, und jede Zahl
   darauf beantwortet dieselbe Frage.
"""
import asyncio
from datetime import date, timedelta
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

# Fernschach und Turnierbedenkzeit werden nicht gefuehrt (siehe
# chess_platforms.NICHT_GEFUEHRT). Gefiltert wird beim Lesen und nicht beim
# Loeschen: wer die Entscheidung zurueckdreht, bekommt seine Partien wieder,
# und eine Migration, die Daten wegwirft, ist nicht zurueckzudrehen.
NICHT_GEFUEHRT = list(plattform.NICHT_GEFUEHRT)
# Die Stufen der Gegnerstaerke. Die Grenzen sind die, die im Schach zaehlen:
# 50 Punkte sind Tagesform, 200 Punkte sind eine Klasse.
# Die Beschriftung ist zugleich die Achse des Diagramms: zwei Woerter, die
# sich auf zwei Zeilen brechen lassen.
STUFEN = [
    ("weit_unter", "200+ schwächer"),
    ("unter", "50–200 schwächer"),
    ("augenhoehe", "±50 Augenhöhe"),
    ("ueber", "50–200 stärker"),
    ("weit_ueber", "200+ stärker"),
]


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
    # Der aelteste Stand innerhalb der letzten 30 Tage ist die Messlatte fuer
    # die Entwicklung. Bewusst der aelteste INNERHALB des Fensters und nicht
    # "vor genau 30 Tagen": der Verlauf beginnt erst mit dem ersten Abruf, und
    # eine Angabe "seit 9 Tagen: +24" ist ehrlicher als gar keine.
    basis = await db.fetch(
        "SELECT DISTINCT ON (r.account_id, r.perf) "
        "       r.account_id, r.perf, r.rating, r.taken_on "
        "  FROM chess_ratings r JOIN chess_accounts a ON a.id = r.account_id "
        " WHERE a.user_id=$1 AND r.taken_on >= CURRENT_DATE - 30 "
        "   AND NOT r.is_best "
        " ORDER BY r.account_id, r.perf, r.taken_on ASC", user_id)
    je_basis = {(b["account_id"], b["perf"]): b for b in basis}

    partien = await db.fetch(
        "SELECT account_id, COUNT(*) AS anzahl, MIN(played_at) AS von, "
        "       MAX(played_at) AS bis "
        "  FROM chess_games WHERE user_id=$1 "
        "   AND (perf IS NULL OR perf <> ALL($2::text[])) "
        " GROUP BY account_id", user_id, NICHT_GEFUEHRT)
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
            "ratings": [_mit_trend(w, je_basis.get((w["account_id"], w["perf"])))
                        for w in eigene],
            "games_count": zahl["anzahl"] if zahl else 0,
            "games_from": zahl["von"] if zahl else None,
            "games_to": zahl["bis"] if zahl else None,
        })
    return raus


def _mit_trend(wertung, basis) -> dict:
    """Die Wertung samt Entwicklung gegenueber dem aeltesten Stand im Fenster.

    ``trend`` bleibt None, solange es keinen zweiten Tag gibt -- ein Pfeil
    mit 0 daneben saehe aus wie "unveraendert", waehrend in Wahrheit noch gar
    nichts zu vergleichen ist. Bestwerte (Chess.com, Raetsel) bekommen gar
    keinen Trend: sie koennen nur steigen, eine Entwicklung ist das nicht.
    """
    d = {
        "perf": wertung["perf"],
        "label": plattform.PERF_LABEL.get(wertung["perf"], wertung["perf"]),
        "rating": wertung["rating"],
        "rd": wertung["rd"],
        "games": wertung["games"],
        "is_best": wertung["is_best"],
        "taken_on": wertung["taken_on"],
        "trend": None,
        "trend_since": None,
        "trend_days": None,
    }
    if wertung["is_best"] or not basis or basis["taken_on"] == wertung["taken_on"]:
        return d
    d["trend"] = wertung["rating"] - basis["rating"]
    d["trend_since"] = basis["taken_on"]
    d["trend_days"] = (wertung["taken_on"] - basis["taken_on"]).days
    return d


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
async def _tageswerte(db, user_id: int) -> dict:
    """Je Plattform und Disziplin: {Tag: Wertung}, ueber die ganze Spielzeit.

    Zwei Quellen, in dieser Reihenfolge:

    1. **Jede gewertete Partie.** ``own_rating + rating_diff`` ist der Stand
       NACH der Partie: Lichess liefert die Wertung davor plus die Differenz,
       Chess.com die Wertung danach und keine Differenz -- dieselbe Rechnung
       trifft beides. Je Tag zaehlt die letzte Partie.
    2. **Die Tageszeile** aus ``chess_ratings``. Sie ist die Zahl, die die
       Plattform selbst herausgibt, und gilt deshalb, wo es beide gibt. Sie
       deckt ausserdem ab, was keine Partie hergibt: Tage ohne Spiel und die
       Raetsel-Wertung, zu der es gar keine Partien gibt.

    Ohne Quelle 1 begann der Verlauf am Tag des Verbindens -- und das waren
    zwei gerade Linien, egal welcher Zeitraum eingestellt war.
    """
    aus_partien = await db.fetch(
        "SELECT DISTINCT ON (platform, perf, played_at::date) "
        "       platform, perf, played_at::date AS tag, "
        "       own_rating + COALESCE(rating_diff, 0) AS rating "
        "  FROM chess_games "
        " WHERE user_id=$1 AND rated AND own_rating IS NOT NULL "
        "   AND perf IS NOT NULL AND perf <> ALL($2::text[]) "
        " ORDER BY platform, perf, played_at::date, played_at DESC",
        user_id, NICHT_GEFUEHRT)
    aus_zeilen = await db.fetch(
        "SELECT a.platform, r.perf, r.taken_on AS tag, r.rating "
        "  FROM chess_ratings r JOIN chess_accounts a ON a.id = r.account_id "
        " WHERE a.user_id=$1 AND NOT r.is_best AND r.perf <> ALL($2::text[]) "
        " ORDER BY r.taken_on", user_id, NICHT_GEFUEHRT)

    werte: dict = {}
    for reihe in (aus_partien, aus_zeilen):
        for r in reihe:
            if r["rating"] is None:
                continue
            werte.setdefault((r["platform"], r["perf"]), {})[r["tag"]] = int(r["rating"])
    return werte


def _eimer(tag: date, koernung: str) -> date:
    """Der Anfang der Periode, in die ein Tag faellt (Montag bzw. Monatserster).

    Dieselbe Rechnung wie ``date_trunc`` in der Aktivitaets-Abfrage -- beide
    Reihen liegen auf derselben Achse, und zwei Fassungen davon waeren zwei
    Achsen, die sich um einen Tag unterscheiden.
    """
    if koernung == "woche":
        return tag - timedelta(days=tag.weekday())
    if koernung == "monat":
        return tag.replace(day=1)
    return tag


def _achse(von: date, bis: date, koernung: str) -> list:
    """Die lueckenlose Achse des Zeitraums (DESIGN.md 7)."""
    achse, lauf = [], _eimer(von, koernung)
    grenze = _eimer(bis, koernung)
    while lauf <= grenze and len(achse) < 4000:
        achse.append(lauf)
        if koernung == "woche":
            lauf = lauf + timedelta(days=7)
        elif koernung == "monat":
            lauf = (lauf.replace(day=28) + timedelta(days=7)).replace(day=1)
        else:
            lauf = lauf + timedelta(days=1)
    return achse


def _reihe(tage: dict, achse: list, von: date, bis: date, koernung: str) -> dict:
    """Eine Linie auf der Achse -- lueckenlos, mit dem Stand von davor.

    Eine Wertungszahl bewegt sich nur nach einer Partie: an Tagen ohne Partie
    gilt der letzte bekannte Stand weiter. ``start`` ist der Stand VOR dem
    Fenster; ohne ihn begaenne eine 30-Tage-Ansicht leer, bis zur ersten
    Partie darin.
    """
    sortiert = sorted(tage.items())
    vorher = [w for t, w in sortiert if t < von]
    start = vorher[-1] if vorher else None

    innen = [(t, w) for t, w in sortiert if von <= t <= bis]
    je_eimer = {}
    for t, w in innen:
        je_eimer[_eimer(t, koernung)] = w

    werte, letzter = [], start
    for e in achse:
        if e in je_eimer:
            letzter = je_eimer[e]
        werte.append(letzter)

    hoch = max(innen, key=lambda x: x[1], default=None)
    return {
        "werte": werte,
        "start": start,
        "punkte": len(innen),
        "erste": innen[0][1] if innen else start,
        "letzte": innen[-1][1] if innen else start,
        "hoch": {"rating": hoch[1], "tag": hoch[0]} if hoch else None,
    }


@router.get("/api/chess/ratings")
async def wertungsverlauf(perf: Optional[str] = None, days: Optional[int] = None,
                          db=Depends(get_db), user=Depends(get_current_user)):
    """Der Verlauf je Plattform und Disziplin, aufsteigend nach Datum.

    Die Form der Antwort bleibt, die Quelle nicht: gezaehlt werden jetzt auch
    die Wertungen aus den Partien selbst (siehe ``_tageswerte``). Bestwerte
    kommen nicht mehr mit -- ein Wert, der "jemals" bedeutet, gehoert in keine
    Kurve, die von Tag zu Tag laeuft.
    """
    werte = await _tageswerte(db, user["id"])
    grenze = date.today() - timedelta(days=int(days)) if days else None
    punkte = []
    for (pf, art), tage in werte.items():
        if perf and art != perf:
            continue
        for tag, rating in sorted(tage.items()):
            if grenze and tag < grenze:
                continue
            punkte.append({"platform": pf, "perf": art, "rating": rating,
                           "is_best": False, "taken_on": tag})
    punkte.sort(key=lambda x: (x["platform"], x["perf"], x["taken_on"]))
    return {"points": punkte}


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
    bedingungen = ["user_id=$1", "(perf IS NULL OR perf <> ALL($2::text[]))"]
    werte = [user["id"], NICHT_GEFUEHRT]
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
    # Die Eroeffnungsfamilie kommt aus derselben Funktion wie in der
    # Auswertung. Sie im Frontend ein zweites Mal zu bilden hiesse, dass
    # Rangliste und Zeile dieselbe Partie verschieden benennen koennen.
    partien_raus = []
    for r in rows:
        d = dict(r)
        d["opening_family"] = plattform.eroeffnungs_familie(d.get("opening"))
        d["perf_label"] = plattform.PERF_LABEL.get(d.get("perf"), d.get("perf"))
        partien_raus.append(d)
    return {"total": gesamt, "games": partien_raus,
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
        "  FROM chess_games WHERE user_id=$1 "
        "   AND (perf IS NULL OR perf <> ALL($2::text[])) "
        " GROUP BY platform", user["id"], NICHT_GEFUEHRT)
    # Welche Zeitkontrollen im Bestand ueberhaupt vorkommen -- fuer die
    # Auswahl in der Partienliste. Aus den Wertungszahlen liesse sie sich
    # nicht bilden: eine Zeitkontrolle ohne gewertete Partie hat dort keine
    # Zeile, steht aber in den Partien.
    arten = await db.fetch(
        "SELECT perf, COUNT(*)::int AS partien FROM chess_games "
        " WHERE user_id=$1 AND perf IS NOT NULL AND perf <> ALL($2::text[]) "
        " GROUP BY perf ORDER BY 2 DESC", user["id"], NICHT_GEFUEHRT)
    return {
        "per_platform": [dict(r) for r in rows],
        "time_controls": [
            {"perf": r["perf"], "partien": r["partien"],
             "label": plattform.PERF_LABEL.get(r["perf"], r["perf"])}
            for r in arten],
        "accounts": await _konten_mit_wertung(db, user["id"]),
        "settings": await _einstellungen(db, user["id"]),
    }

# ---------------------------------------------------------------------------
# Die Auswertung
# ---------------------------------------------------------------------------
# Alles, was der Ueberblick zeigt, in EINER Antwort und ueber EINEN Zeitraum.
# Vorher rechnete die Seite selbst -- ueber die zuletzt geladenen 200 Partien
# -- und stellte das Ergebnis neben Kopfzahlen ueber den ganzen Bestand. Zwei
# Grundgesamtheiten auf einem Bildschirm sind zwei Antworten auf dieselbe
# Frage, und man sieht ihnen nicht an, welche gerade gilt.
# Die Klammern um jedes FILTER sind Absicht: ohne sie haengt der Cast am
# Rand der Aggregat-Grammatik, und ein Zaehler, der nicht als Zahl ankommt,
# faellt erst auf der Seite auf.
ZAEHLER = ("COUNT(*)::int AS partien, "
           "(COUNT(*) FILTER (WHERE result='sieg'))::int AS siege, "
           "(COUNT(*) FILTER (WHERE result='remis'))::int AS remis, "
           "(COUNT(*) FILTER (WHERE result='niederlage'))::int AS niederlagen")


# Die Koernung heisst nach innen deutsch, weil die Antwort sie so ausgibt und
# die Seite sie so beschriftet. Postgres kennt aber nur seine eigenen Namen --
# "tag" ist dort keine Einheit, sondern ein Fehler.
PG_EINHEIT = {"tag": "day", "woche": "week", "monat": "month"}


def _koernung(tage: int) -> str:
    """Tag, Woche oder Monat -- nach der Laenge des Zeitraums.

    Zehn Jahre tageweise waeren 3.650 Saeulen auf 600 Pixeln: eine Flaeche,
    keine Kurve. Die Grenzen liegen da, wo eine Saeule schmaler als ein Pixel
    wuerde.
    """
    if tage <= 70:
        return "tag"
    if tage <= 550:
        return "woche"
    return "monat"


@router.get("/api/chess/stats")
async def auswertung(von: Optional[date] = Query(None, alias="from"),
                     bis: Optional[date] = Query(None, alias="to"),
                     db=Depends(get_db), user=Depends(get_current_user)):
    """Bilanz, Verlauf, Aktivitaet, Gegnerstaerke, Ranglisten — ein Zeitraum.

    Ohne ``from`` gilt der ganze Bestand. Der Zeitraum steht in der Antwort,
    damit die Seite beschriften kann, worueber gerechnet wurde.
    """
    uid = user["id"]
    heute = date.today()
    spanne = await db.fetchrow(
        "SELECT MIN(played_at)::date AS von, MAX(played_at)::date AS bis "
        "  FROM chess_games WHERE user_id=$1 "
        "   AND (perf IS NULL OR perf <> ALL($2::text[]))", uid, NICHT_GEFUEHRT)
    erste = spanne["von"] if spanne else None

    bis = bis or heute
    von = von or erste or heute
    if von > bis:
        von = bis
    tage = (bis - von).days + 1
    koernung = _koernung(tage)

    wo = ("user_id=$1 AND (perf IS NULL OR perf <> ALL($2::text[])) "
          "AND played_at >= $3::date AND played_at < ($4::date + 1)")
    basis = [uid, NICHT_GEFUEHRT, von, bis]

    je_plattform = await db.fetch(
        f"SELECT platform, {ZAEHLER}, MIN(played_at) AS von, MAX(played_at) AS bis "
        f"  FROM chess_games WHERE {wo} GROUP BY platform ORDER BY platform", *basis)

    # Aktivitaet: wie viel gespielt wurde und wie es ausging, je Periode.
    roh_aktivitaet = await db.fetch(
        f"SELECT date_trunc($5, played_at)::date AS eimer, {ZAEHLER} "
        f"  FROM chess_games WHERE {wo} GROUP BY 1 ORDER BY 1",
        *basis, PG_EINHEIT[koernung])

    # Gegnerstaerke: die Frage, die eine Siegquote allein nie beantwortet --
    # 60 % gegen Schwaechere und 60 % gegen Staerkere sind nicht dasselbe.
    roh_stufen = await db.fetch(
        f"SELECT CASE WHEN opponent_rating - own_rating <= -200 THEN 0 "
        f"            WHEN opponent_rating - own_rating <   -50 THEN 1 "
        f"            WHEN opponent_rating - own_rating <=   50 THEN 2 "
        f"            WHEN opponent_rating - own_rating <   200 THEN 3 "
        f"            ELSE 4 END AS stufe, {ZAEHLER} "
        f"  FROM chess_games WHERE {wo} AND own_rating IS NOT NULL "
        f"   AND opponent_rating IS NOT NULL GROUP BY 1 ORDER BY 1", *basis)

    zeitkontrollen = await db.fetch(
        f"SELECT perf, {ZAEHLER} FROM chess_games WHERE {wo} "
        f" GROUP BY perf ORDER BY 2 DESC", *basis)

    farben = await db.fetch(
        f"SELECT color, {ZAEHLER} FROM chess_games WHERE {wo} GROUP BY color", *basis)

    roh_eroeffnungen = await db.fetch(
        f"SELECT opening, {ZAEHLER} FROM chess_games WHERE {wo} "
        f"   AND opening IS NOT NULL AND opening <> '' GROUP BY opening", *basis)

    gegner = await db.fetch(
        f"SELECT opponent, MAX(opponent_rating)::int AS hoechste, {ZAEHLER} "
        f"  FROM chess_games WHERE {wo} AND opponent IS NOT NULL "
        f"   AND opponent <> '' GROUP BY opponent HAVING COUNT(*) > 1 "
        f" ORDER BY 3 DESC, 2 DESC LIMIT 8", *basis)

    # 60 Partien reichen fuer die Form (24 Marken) und fuer eine Serie, die
    # laenger sein darf, als die Reihe zeigt.
    letzte = await db.fetch(
        f"SELECT id, platform, played_at, perf, result, opponent, "
        f"       opponent_rating, opening, rating_diff, own_rating "
        f"  FROM chess_games WHERE {wo} ORDER BY played_at DESC LIMIT 60", *basis)

    stark = await db.fetchrow(
        f"SELECT id, opponent, opponent_rating, played_at, platform, perf "
        f"  FROM chess_games WHERE {wo} AND result='sieg' "
        f"   AND opponent_rating IS NOT NULL "
        f" ORDER BY opponent_rating DESC LIMIT 1", *basis)

    schnitt = await db.fetchval(
        f"SELECT AVG(opponent_rating)::int FROM chess_games WHERE {wo} "
        f"   AND opponent_rating IS NOT NULL", *basis)

    # --- Eroeffnungen zu Familien zusammenlegen ---------------------------
    familien: dict = {}
    for r in roh_eroeffnungen:
        name = plattform.eroeffnungs_familie(r["opening"])
        if not name:
            continue
        topf = familien.setdefault(name, {"name": name, "partien": 0, "siege": 0,
                                          "remis": 0, "niederlagen": 0})
        for feld in ("partien", "siege", "remis", "niederlagen"):
            topf[feld] += r[feld]
    eroeffnungen = sorted(familien.values(), key=lambda x: -x["partien"])[:8]

    # --- Achse, Aktivitaet und Verlauf auf derselben Achse -----------------
    achse = _achse(von, bis, koernung)
    je_eimer = {r["eimer"]: r for r in roh_aktivitaet}
    aktivitaet = []
    for e in achse:
        r = je_eimer.get(e)
        aktivitaet.append({
            "eimer": e,
            "partien": r["partien"] if r else 0,
            "siege": r["siege"] if r else 0,
            "remis": r["remis"] if r else 0,
            "niederlagen": r["niederlagen"] if r else 0,
        })

    tageswerte = await _tageswerte(db, uid)
    ordnung = {art: i for i, art in enumerate(plattform.PERFS)}
    reihen = []
    for (pf, art), werte in tageswerte.items():
        r = _reihe(werte, achse, von, bis, koernung)
        if r["start"] is None and not r["punkte"]:
            continue
        reihen.append({"platform": pf, "perf": art,
                       "label": plattform.PERF_LABEL.get(art, art), **r})
    reihen.sort(key=lambda r: (ordnung.get(r["perf"], 99), r["platform"]))

    # --- Stufen auffuellen, damit die Achse stehen bleibt ------------------
    nach_stufe = {r["stufe"]: r for r in roh_stufen}
    gegnerstaerke = []
    for i, (schluessel, beschriftung) in enumerate(STUFEN):
        r = nach_stufe.get(i)
        gegnerstaerke.append({
            "key": schluessel, "label": beschriftung,
            "partien": r["partien"] if r else 0,
            "siege": r["siege"] if r else 0,
            "remis": r["remis"] if r else 0,
            "niederlagen": r["niederlagen"] if r else 0,
        })

    # --- Serie ------------------------------------------------------------
    serie = None
    if letzte:
        art = letzte[0]["result"]
        anzahl = 0
        for g in letzte:
            if g["result"] != art:
                break
            anzahl += 1
        # Reicht die Serie bis ans Ende der geholten 60, ist sie vermutlich
        # laenger -- das zu behaupten waere falsch, es zu verschweigen auch.
        serie = {"art": art, "n": anzahl, "offen": anzahl >= len(letzte)}

    return {
        "von": von, "bis": bis, "tage": tage, "koernung": koernung,
        "erste_partie": erste,
        "ganzer_bestand": erste is not None and von <= erste,
        "perfs": list(plattform.PERFS),
        "perf_labels": plattform.PERF_LABEL,
        "plattformen": [dict(r) for r in je_plattform],
        "aktivitaet": aktivitaet,
        "gegnerstaerke": gegnerstaerke,
        "gegner_schnitt": schnitt,
        "zeitkontrollen": [
            {**dict(r), "label": plattform.PERF_LABEL.get(r["perf"], r["perf"])}
            for r in zeitkontrollen],
        "farben": [dict(r) for r in farben],
        "eroeffnungen": eroeffnungen,
        "gegner": [dict(r) for r in gegner],
        "form": [dict(r) for r in letzte[:24]],
        "serie": serie,
        "staerkster_sieg": dict(stark) if stark else None,
        "verlauf": {"achse": achse, "reihen": reihen},
    }
