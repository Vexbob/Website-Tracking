"""Schach: holen und wegschreiben — einmal fuer Knopfdruck und Automatik.

Hier steht, was der Router beim Knopfdruck und der Tagesjob im Hintergrund
gleichermassen tun. Zwei Fassungen davon waeren zwei Stellen, an denen sich
das Verhalten auseinanderentwickelt -- und die Automatik ist gerade die, bei
der niemand zusieht.

Der Tagesjob (``taeglicher_lauf``) laeuft im Backend-Prozess, nicht im
Browser. Er prueft stuendlich, fuer wen die eingestellte Stunde erreicht ist,
und laeuft je Konto hoechstens ``TAGESLAUF_RUNDEN`` Stuecke -- das reicht fuer
den taeglichen Zuwachs um ein Vielfaches. Die erste, lange Historie holt
weiterhin der Knopf auf der Seite, wo man ihr beim Wachsen zusehen kann.
"""
import asyncio
from datetime import datetime, timedelta, timezone

try:                                        # pragma: no cover - Umgebungsfrage
    from zoneinfo import ZoneInfo
    ORTSZEIT = ZoneInfo("Europe/Vienna")
except Exception:                           # pragma: no cover
    # Ohne tzdata im Image faellt die Stunde auf UTC zurueck. Lieber eine
    # Stunde daneben als ein Job, der gar nicht laeuft -- und die Oberflaeche
    # sagt dazu, in welcher Zeit die Stunde gemeint ist.
    ORTSZEIT = timezone.utc

from deps import logger
from services import chess_platforms as plattform

# Ein Stueck je Abfrage an die Plattform (siehe chess_router).
STUECK = 400
# Wie viele Stuecke der Tagesjob je Konto holt. 20 * 400 = 8.000 Partien --
# weit mehr, als an einem Tag dazukommen kann.
TAGESLAUF_RUNDEN = 20


# ---------------------------------------------------------------------------
# Wertungszahlen
# ---------------------------------------------------------------------------
async def wertungen_holen(conn, konto) -> int:
    """Holt den aktuellen Stand und schreibt die Tageszeile je Disziplin."""
    profil = await asyncio.to_thread(
        plattform.hole_profil, konto["platform"], konto["username"])
    for w in profil["ratings"]:
        await conn.execute(
            "INSERT INTO chess_ratings (account_id, perf, rating, rd, games, is_best) "
            "VALUES ($1,$2,$3,$4,$5,$6) "
            "ON CONFLICT (account_id, perf, taken_on) DO UPDATE "
            "   SET rating=EXCLUDED.rating, rd=EXCLUDED.rd, "
            "       games=EXCLUDED.games, is_best=EXCLUDED.is_best",
            konto["id"], w["perf"], w["rating"], w.get("rd"), w.get("games"),
            bool(w.get("is_best")))
    await conn.execute(
        "UPDATE chess_accounts SET ratings_at=now() WHERE id=$1", konto["id"])
    return len(profil["ratings"])


# ---------------------------------------------------------------------------
# Partien
# ---------------------------------------------------------------------------
async def partien_stueck(conn, user_id: int, konto, hoechstens: int = STUECK) -> dict:
    """Holt das naechste Stueck Historie und schreibt es weg.

    Rueckgabe: {seen, new, more, through}. ``more`` heisst: das Stueck war
    voll, es ist vermutlich noch Historie offen.
    """
    def _holen():
        return list(plattform.hole_partien(
            konto["platform"], konto["username"],
            seit=konto["games_through"], hoechstens=hoechstens))

    partien = await asyncio.to_thread(_holen)

    neu, juengste = 0, konto["games_through"]
    for p in partien:
        if not p.get("ext_id") or not p.get("played_at"):
            continue
        treffer = await conn.fetchrow(
            "INSERT INTO chess_games (user_id, account_id, platform, ext_id, "
            "   played_at, perf, variant, rated, color, result, end_reason, "
            "   own_rating, rating_diff, opponent, opponent_rating, opening, "
            "   eco, moves, url, pgn) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,"
            "        $17,$18,$19,$20) "
            "ON CONFLICT (account_id, ext_id) DO NOTHING RETURNING id",
            user_id, konto["id"], konto["platform"], str(p["ext_id"]),
            p["played_at"], p.get("perf"), p.get("variant"), p.get("rated"),
            p.get("color"), p.get("result"), p.get("end_reason"),
            p.get("own_rating"), p.get("rating_diff"), p.get("opponent"),
            p.get("opponent_rating"), p.get("opening"), p.get("eco"),
            p.get("moves"), p.get("url"), p.get("pgn"))
        if treffer:
            neu += 1
        if juengste is None or p["played_at"] > juengste:
            juengste = p["played_at"]

    await conn.execute(
        "UPDATE chess_accounts SET games_at=now(), games_through=$2 WHERE id=$1",
        konto["id"], juengste)
    return {"seen": len(partien), "new": neu,
            "more": len(partien) >= hoechstens, "through": juengste}


async def _konto_nachfuehren(conn, user_id: int, konto) -> dict:
    """Holt so lange Stuecke, bis nichts mehr offen ist (gedeckelt)."""
    neu = gesehen = 0
    stand = dict(konto)
    for _ in range(TAGESLAUF_RUNDEN):
        ergebnis = await partien_stueck(conn, user_id, stand)
        neu += ergebnis["new"]
        gesehen += ergebnis["seen"]
        stand["games_through"] = ergebnis["through"]
        if not ergebnis["more"]:
            break
    return {"new": neu, "seen": gesehen}


# ---------------------------------------------------------------------------
# Der taegliche Lauf
# ---------------------------------------------------------------------------
async def lauf_fuer_nutzer(conn, user_id: int) -> dict:
    """Wertungen und neue Partien fuer alle Konten eines Nutzers."""
    konten = await conn.fetch(
        "SELECT id, platform, username, games_through FROM chess_accounts "
        " WHERE user_id=$1", user_id)
    neu, probleme = 0, []
    for konto in konten:
        name = plattform.PLATTFORM_LABEL.get(konto["platform"], konto["platform"])
        try:
            await wertungen_holen(conn, konto)
        except plattform.PlattformFehler as e:
            probleme.append(f"{name}: {e}")
        try:
            ergebnis = await _konto_nachfuehren(conn, user_id, konto)
            neu += ergebnis["new"]
        except plattform.PlattformFehler as e:
            probleme.append(f"{name}: {e}")
        except Exception as e:                              # pragma: no cover
            logger.exception("Schach-Automatik: Konto %s", konto["id"])
            probleme.append(f"{name}: unerwarteter Fehler")
    notiz = (f"{neu} neue Partien"
             + (" · " + " · ".join(probleme) if probleme else ""))
    await conn.execute(
        "INSERT INTO chess_settings (user_id, last_auto_at, last_auto_note) "
        "VALUES ($1, now(), $2) "
        "ON CONFLICT (user_id) DO UPDATE "
        "   SET last_auto_at=now(), last_auto_note=EXCLUDED.last_auto_note",
        user_id, notiz[:500])
    return {"new": neu, "problems": probleme}


async def _faellige_nutzer(conn, stunde: int, heute) -> list:
    """Wer hat die Automatik an, ist dran und lief heute noch nicht?

    Die Stunde allein reicht nicht: ein Neustart des Containers innerhalb
    derselben Stunde wuerde den Lauf sonst ein zweites Mal ausloesen.
    """
    rows = await conn.fetch(
        "SELECT DISTINCT a.user_id "
        "  FROM chess_accounts a "
        "  LEFT JOIN chess_settings s ON s.user_id = a.user_id "
        " WHERE COALESCE(s.auto_daily, TRUE) "
        "   AND COALESCE(s.daily_hour, 4) = $1 "
        "   AND (s.last_auto_at IS NULL OR s.last_auto_at < $2)",
        stunde, heute)
    return [r["user_id"] for r in rows]


async def taeglicher_lauf(get_pool):
    """Endlosschleife: zur vollen Stunde nachsehen, wer dran ist.

    Bewusst stuendlich statt minuetlich: die Einstellung ist eine Stunde, und
    ein Job, der 1.440-mal am Tag eine leere Abfrage macht, ist Last ohne
    Gegenwert.
    """
    while True:
        try:
            # Eine Minute nach der vollen Stunde -- nicht Punkt, damit der
            # Lauf nicht mit allem zusammenfaellt, was zur vollen Stunde
            # ohnehin anspringt.
            jetzt = datetime.now(timezone.utc)
            naechste = jetzt.replace(minute=1, second=0, microsecond=0)
            if naechste <= jetzt:
                naechste += timedelta(hours=1)
            await asyncio.sleep(max(30, (naechste - jetzt).total_seconds()))

            ortszeit = datetime.now(ORTSZEIT)
            pool = await get_pool()
            async with pool.acquire() as conn:
                heute = ortszeit.replace(hour=0, minute=0, second=0,
                                         microsecond=0)
                nutzer = await _faellige_nutzer(conn, ortszeit.hour, heute)
                for user_id in nutzer:
                    ergebnis = await lauf_fuer_nutzer(conn, user_id)
                    logger.info("Schach-Automatik fuer Nutzer %s: %s neue Partien%s",
                                user_id, ergebnis["new"],
                                " (" + "; ".join(ergebnis["problems"]) + ")"
                                if ergebnis["problems"] else "")
        except asyncio.CancelledError:                      # pragma: no cover
            raise
        except Exception as e:                              # pragma: no cover
            logger.exception("Schach-Automatik fehlgeschlagen: %s", e)
            await asyncio.sleep(600)
