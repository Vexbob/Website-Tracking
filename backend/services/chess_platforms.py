"""Lichess und Chess.com abfragen — Wertungszahlen und Partien.

Beide Plattformen geben oeffentlich heraus, was dieses Modul braucht: kein
Schluessel, kein Token, nur ein Benutzername. Was sie NICHT gleich machen,
steht hier an einer Stelle, damit der Router und das Frontend nur noch eine
Form kennen:

    Lichess                            Chess.com
    ------------------------------     ------------------------------------
    perfs.<disziplin>.rating           chess_<disziplin>.last.rating
    perfs.puzzle.rating (aktuell)      tactics.highest.rating (nur Bestwert!)
    /api/games/user/<name> (ndjson)    Monatsarchive, je Monat eine Abfrage
    Zeiten in Millisekunden            Zeiten in Sekunden

Der wichtigste Unterschied ist die Raetsel-Wertung: Lichess gibt den aktuellen
Stand heraus, Chess.com nur Hoechst- und Tiefstwert. Deshalb traegt jede
Wertung ein Flag ``is_best`` -- eine Zahl, die "jemals" bedeutet, darf nicht
unbeschriftet neben einer stehen, die "heute" bedeutet.

Bewusst mit ``urllib`` aus der Standardbibliothek statt mit httpx: es sind
wenige Abfragen, sie laufen ueber ``asyncio.to_thread``, und das Backend
kommt damit ohne eine weitere Abhaengigkeit aus.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# Chess.com weist Abfragen ohne aussagekraeftigen User-Agent ab (Cloudflare).
# Lichess bittet in seiner Dokumentation ebenfalls darum.
USER_AGENT = "Vexbob/1.0 (persoenlicher Tracker, Einzelnutzer)"

PLATTFORMEN = ("lichess", "chesscom")
PLATTFORM_LABEL = {"lichess": "Lichess", "chesscom": "Chess.com"}

# Die Disziplinen in der Reihenfolge, in der sie angezeigt werden. "daily"
# (Chess.com) und "classical" (Lichess) sind nicht dasselbe, bleiben aber
# beide erhalten -- sie einer gemeinsamen Zeile zuzuschlagen waere eine
# Gleichsetzung, die keine der beiden Plattformen macht.
PERFS = ("bullet", "blitz", "rapid", "classical", "daily", "puzzle")
PERF_LABEL = {
    "bullet": "Bullet", "blitz": "Blitz", "rapid": "Rapid",
    "classical": "Klassisch", "daily": "Fernschach", "puzzle": "Rätsel",
}

ZEITLIMIT = 30


class PlattformFehler(Exception):
    """Die Plattform hat nicht geliefert — mit einem Satz, der sagt warum."""


# ---------------------------------------------------------------------------
# Abrufen
# ---------------------------------------------------------------------------
def _hole(url: str, accept: str = "application/json") -> bytes:
    anfrage = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT) as antwort:
            return antwort.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise PlattformFehler("Diesen Benutzernamen gibt es dort nicht.")
        if e.code == 429:
            raise PlattformFehler(
                "Die Plattform bremst gerade (zu viele Abfragen). "
                "In ein paar Minuten noch einmal versuchen.")
        raise PlattformFehler(f"Die Plattform antwortete mit Fehler {e.code}.")
    except urllib.error.URLError as e:
        raise PlattformFehler(f"Die Plattform war nicht erreichbar: {e.reason}")


def _json(url: str) -> dict:
    try:
        return json.loads(_hole(url))
    except json.JSONDecodeError:
        raise PlattformFehler("Die Antwort der Plattform war nicht lesbar.")


def _zeit(wert, einheit: str):
    """Millisekunden (Lichess) oder Sekunden (Chess.com) -> datetime."""
    if not wert:
        return None
    sekunden = wert / 1000 if einheit == "ms" else wert
    return datetime.fromtimestamp(sekunden, tz=timezone.utc)


# ---------------------------------------------------------------------------
# Profil und Wertungszahlen
# ---------------------------------------------------------------------------
def hole_profil(platform: str, username: str) -> dict:
    """Prueft den Namen und liefert die aktuellen Wertungszahlen.

    Rueckgabe: {username, profile_url, ratings: [{perf, rating, rd, games,
    is_best}]}
    """
    name = (username or "").strip().lstrip("@")
    if not name:
        raise PlattformFehler("Bitte einen Benutzernamen angeben.")
    if platform == "lichess":
        return _profil_lichess(name)
    if platform == "chesscom":
        return _profil_chesscom(name)
    raise PlattformFehler(f"Unbekannte Plattform: {platform}")


def _profil_lichess(name: str) -> dict:
    d = _json(f"https://lichess.org/api/user/{urllib.parse.quote(name)}")
    if d.get("disabled") or d.get("closed"):
        raise PlattformFehler("Dieses Lichess-Konto ist geschlossen.")
    ratings = []
    for perf in PERFS:
        p = (d.get("perfs") or {}).get(perf) or {}
        if p.get("rating"):
            ratings.append({
                "perf": perf,
                "rating": int(p["rating"]),
                "rd": p.get("rd"),
                "games": p.get("games"),
                # Lichess markiert eine noch unsichere Zahl als "provisorisch";
                # sie ist trotzdem der aktuelle Stand, kein Bestwert.
                "is_best": False,
                "provisional": bool(p.get("prov")),
            })
    return {
        "username": d.get("username") or name,
        "profile_url": d.get("url") or f"https://lichess.org/@/{name}",
        "ratings": ratings,
    }


def _profil_chesscom(name: str) -> dict:
    kurz = urllib.parse.quote(name.lower())
    profil = _json(f"https://api.chess.com/pub/player/{kurz}")
    stats = _json(f"https://api.chess.com/pub/player/{kurz}/stats")
    ratings = []
    for perf in ("bullet", "blitz", "rapid", "daily"):
        block = stats.get(f"chess_{perf}") or {}
        letzte = block.get("last") or {}
        if letzte.get("rating"):
            satz = block.get("record") or {}
            gespielt = sum(int(satz.get(k) or 0) for k in ("win", "loss", "draw"))
            ratings.append({
                "perf": perf,
                "rating": int(letzte["rating"]),
                "rd": letzte.get("rd"),
                "games": gespielt or None,
                "is_best": False,
                "provisional": False,
            })
    # Raetsel: Chess.com gibt hier bewusst nur Hoechst- und Tiefstwert heraus.
    # Der aktuelle Stand ist ueber die oeffentliche Schnittstelle nicht zu
    # bekommen -- also wird der Bestwert gespeichert UND als solcher markiert,
    # statt ihn als heutige Zahl auszugeben.
    hoechst = ((stats.get("tactics") or {}).get("highest") or {})
    if hoechst.get("rating"):
        ratings.append({
            "perf": "puzzle",
            "rating": int(hoechst["rating"]),
            "rd": None,
            "games": None,
            "is_best": True,
            "provisional": False,
        })
    return {
        "username": profil.get("username") or name,
        "profile_url": profil.get("url") or f"https://www.chess.com/member/{name}",
        "ratings": ratings,
    }


# ---------------------------------------------------------------------------
# Partien
# ---------------------------------------------------------------------------
# Beide Generatoren liefern dieselbe Form:
#
#   {ext_id, played_at, perf, variant, rated, color, result, end_reason,
#    own_rating, rating_diff, opponent, opponent_rating, opening, eco,
#    moves, url, pgn}
#
# ``seit`` ist ein datetime oder None (= von Anfang an). Geliefert wird
# AUFSTEIGEND, von alt nach neu. Das ist der Grund, warum ein einziger Zeiger
# genuegt: jeder Lauf holt hoechstens ``hoechstens`` Partien, die juengste
# davon wird zum neuen Stand, und der naechste Lauf setzt genau dort fort.
# Ist die Historie einmal aufgeholt, fragt derselbe Aufruf nur noch das Neue
# ab -- Nachholen und Nachfuehren sind dieselbe Bewegung.

def hole_partien(platform: str, username: str, seit=None, hoechstens: int = 500):
    if platform == "lichess":
        return _partien_lichess(username, seit, hoechstens)
    if platform == "chesscom":
        return _partien_chesscom(username, seit, hoechstens)
    raise PlattformFehler(f"Unbekannte Plattform: {platform}")


def _ergebnis(gewonnen, remis) -> str:
    if remis:
        return "remis"
    return "sieg" if gewonnen else "niederlage"


LICHESS_ENDE = {
    "mate": "matt", "resign": "aufgegeben", "outoftime": "Zeit",
    "timeout": "Zeit", "draw": "Remis", "stalemate": "Patt",
    "cheat": "gesperrt", "noStart": "nicht angetreten",
    "unknownFinish": "unklar", "variantEnd": "Variante entschieden",
}


def _partien_lichess(name: str, seit, hoechstens: int):
    kurz = urllib.parse.quote(name)
    url = (f"https://lichess.org/api/games/user/{kurz}"
           f"?max={int(hoechstens)}&opening=true&moves=false&pgnInJson=true"
           f"&sort=dateAsc")
    if seit:
        # +1 Sekunde, damit die zuletzt gespeicherte Partie nicht erneut kommt.
        url += f"&since={int(seit.timestamp() * 1000) + 1000}"
    roh = _hole(url, accept="application/x-ndjson")
    ich = name.lower()
    for zeile in roh.decode("utf-8", "replace").splitlines():
        zeile = zeile.strip()
        if not zeile:
            continue
        try:
            g = json.loads(zeile)
        except json.JSONDecodeError:
            continue
        spieler = g.get("players") or {}
        farbe = None
        for seite in ("white", "black"):
            benutzer = ((spieler.get(seite) or {}).get("user") or {})
            if (benutzer.get("id") or benutzer.get("name") or "").lower() == ich:
                farbe = seite
        if farbe is None:
            continue                      # fremde Partie (sollte nicht vorkommen)
        gegenseite = "black" if farbe == "white" else "white"
        meins = spieler.get(farbe) or {}
        gegner = spieler.get(gegenseite) or {}
        gewinner = g.get("winner")
        yield {
            "ext_id": g.get("id"),
            "played_at": _zeit(g.get("lastMoveAt") or g.get("createdAt"), "ms"),
            "perf": g.get("perf") or g.get("speed"),
            "variant": g.get("variant"),
            "rated": bool(g.get("rated")),
            "color": "weiss" if farbe == "white" else "schwarz",
            "result": _ergebnis(gewinner == farbe, gewinner is None),
            "end_reason": LICHESS_ENDE.get(g.get("status"), g.get("status")),
            "own_rating": meins.get("rating"),
            "rating_diff": meins.get("ratingDiff"),
            "opponent": ((gegner.get("user") or {}).get("name")
                         or ("Computer" if gegner.get("aiLevel") else "Unbekannt")),
            "opponent_rating": gegner.get("rating"),
            "opening": (g.get("opening") or {}).get("name"),
            "eco": (g.get("opening") or {}).get("eco"),
            "moves": None,
            "url": f"https://lichess.org/{g.get('id')}",
            "pgn": g.get("pgn"),
        }


CHESSCOM_ENDE = {
    "win": "gewonnen", "checkmated": "matt", "resigned": "aufgegeben",
    "timeout": "Zeit", "abandoned": "abgebrochen", "agreed": "Remis vereinbart",
    "repetition": "Zugwiederholung", "stalemate": "Patt",
    "insufficient": "Material fehlt", "50move": "50-Zuege-Regel",
    "timevsinsufficient": "Zeit, Material fehlt",
}
REMIS_ERGEBNISSE = {"agreed", "repetition", "stalemate", "insufficient",
                    "50move", "timevsinsufficient"}


def _partien_chesscom(name: str, seit, hoechstens: int):
    kurz = urllib.parse.quote(name.lower())
    archive = (_json(f"https://api.chess.com/pub/player/{kurz}/games/archives")
               .get("archives") or [])
    # Die Liste kommt aufsteigend (aeltester Monat zuerst) und bleibt so.
    if seit:
        grenze = f"{seit.year:04d}/{seit.month:02d}"
        archive = [a for a in archive if a[-7:] >= grenze]
    ich = name.lower()
    geliefert = 0
    for monat in archive:
        if geliefert >= hoechstens:
            return
        for g in (_json(monat).get("games") or []):
            gespielt = _zeit(g.get("end_time"), "s")
            if seit and gespielt and gespielt <= seit:
                continue
            weiss = g.get("white") or {}
            schwarz = g.get("black") or {}
            if (weiss.get("username") or "").lower() == ich:
                farbe, meins, gegner = "weiss", weiss, schwarz
            elif (schwarz.get("username") or "").lower() == ich:
                farbe, meins, gegner = "schwarz", schwarz, weiss
            else:
                continue
            eigenes = meins.get("result")
            yield {
                "ext_id": g.get("uuid") or g.get("url"),
                "played_at": gespielt,
                "perf": g.get("time_class"),
                "variant": g.get("rules"),
                "rated": bool(g.get("rated")),
                "color": farbe,
                "result": _ergebnis(eigenes == "win",
                                    eigenes in REMIS_ERGEBNISSE),
                "end_reason": CHESSCOM_ENDE.get(eigenes, eigenes),
                "own_rating": meins.get("rating"),
                "rating_diff": None,      # Chess.com liefert keine Differenz mit
                "opponent": gegner.get("username") or "Unbekannt",
                "opponent_rating": gegner.get("rating"),
                # ``eco`` ist bei Chess.com eine Link-Adresse zur Eroeffnung;
                # der lesbare Name steht am Ende darin.
                "opening": _eroeffnung_aus_link(g.get("eco")),
                "eco": None,
                "moves": None,
                "url": g.get("url"),
                "pgn": g.get("pgn"),
            }
            geliefert += 1
            if geliefert >= hoechstens:
                return


def _eroeffnung_aus_link(wert):
    if not wert or not isinstance(wert, str):
        return None
    if not wert.startswith("http"):
        return wert
    name = wert.rstrip("/").rsplit("/", 1)[-1]
    return name.replace("-", " ") or None
