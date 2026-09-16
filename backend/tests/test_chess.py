"""Tests fuer die Umrechnung der beiden Schach-Plattformen (v1.83.0).

Ohne Netz: die Abfragen werden durch aufgezeichnete Antworten ersetzt. Der
Fokus liegt auf dem, was die beiden Plattformen unterschiedlich machen --
genau dort entstehen sonst Zahlen, die nebeneinander stehen und nicht
dasselbe bedeuten.
"""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from services import chess_platforms as cp  # noqa: E402
from routers import chess_router as cr      # noqa: E402


# --------------------------------------------------------------------------
# Aufgezeichnete Antworten (gekuerzt auf die benutzten Felder)
# --------------------------------------------------------------------------
LICHESS_PROFIL = {
    "id": "spieler", "username": "Spieler", "url": "https://lichess.org/@/Spieler",
    "perfs": {
        "bullet": {"games": 120, "rating": 1774, "rd": 45, "prov": False},
        "blitz": {"games": 900, "rating": 1752, "rd": 50},
        "rapid": {"games": 40, "rating": 1802, "rd": 90, "prov": True},
        "puzzle": {"games": 5958, "rating": 1986, "rd": 60},
        "storm": {"runs": 3, "score": 40},
    },
}

CHESSCOM_STATS = {
    "chess_bullet": {"last": {"rating": 1712, "rd": 42},
                     "record": {"win": 10, "loss": 5, "draw": 1}},
    "chess_rapid": {"last": {"rating": 1904, "rd": 80},
                    "record": {"win": 3, "loss": 1, "draw": 0}},
    "tactics": {"highest": {"rating": 2096}, "lowest": {"rating": 1795}},
    "puzzle_rush": {"best": {"score": 40}},
}
CHESSCOM_PROFIL = {"username": "Spieler",
                   "url": "https://www.chess.com/member/spieler"}


def _antworten(monkeypatch, tabelle):
    def falsches_json(url):
        for teil, antwort in tabelle.items():
            if teil in url:
                return antwort
        raise AssertionError("unerwartete Adresse: " + url)
    monkeypatch.setattr(cp, "_json", falsches_json)


# --------------------------------------------------------------------------
# Wertungszahlen
# --------------------------------------------------------------------------
def test_lichess_wertungen_sind_aktuelle_staende(monkeypatch):
    _antworten(monkeypatch, {"/api/user/": LICHESS_PROFIL})
    profil = cp.hole_profil("lichess", " Spieler ")
    nach_perf = {w["perf"]: w for w in profil["ratings"]}

    assert profil["username"] == "Spieler"
    assert nach_perf["bullet"]["rating"] == 1774
    # Die Raetsel-Wertung von Lichess ist der aktuelle Stand, kein Bestwert.
    assert nach_perf["puzzle"]["rating"] == 1986
    assert nach_perf["puzzle"]["is_best"] is False
    assert nach_perf["rapid"]["provisional"] is True
    # "storm" hat keine Wertungszahl und darf deshalb gar nicht auftauchen.
    assert "storm" not in nach_perf


def test_chesscom_raetsel_ist_als_bestwert_markiert(monkeypatch):
    _antworten(monkeypatch, {"/stats": CHESSCOM_STATS,
                             "pub/player/spieler": CHESSCOM_PROFIL})
    profil = cp.hole_profil("chesscom", "Spieler")
    nach_perf = {w["perf"]: w for w in profil["ratings"]}

    assert nach_perf["bullet"]["rating"] == 1712
    assert nach_perf["bullet"]["games"] == 16        # 10 + 5 + 1
    # Chess.com gibt zur Raetsel-Wertung nur Hoechst- und Tiefstwert heraus.
    # Der Wert darf mit, aber nur mit Kennzeichnung -- sonst stuende "jemals"
    # unbeschriftet neben "heute".
    assert nach_perf["puzzle"]["rating"] == 2096
    assert nach_perf["puzzle"]["is_best"] is True
    # Ohne Wertung keine Zeile: blitz fehlt in der Antwort.
    assert "blitz" not in nach_perf


def test_unbekannte_plattform_fliegt_auf():
    try:
        cp.hole_profil("chess24", "Spieler")
    except cp.PlattformFehler as e:
        assert "chess24" in str(e)
    else:
        raise AssertionError("hätte auffallen müssen")


# --------------------------------------------------------------------------
# Partien
# --------------------------------------------------------------------------
LICHESS_PARTIE = {
    "id": "abc123", "rated": True, "variant": "standard", "speed": "blitz",
    "perf": "blitz", "createdAt": 1700000000000, "lastMoveAt": 1700000600000,
    "status": "outoftime", "winner": "black",
    "players": {
        "white": {"user": {"name": "Gegner", "id": "gegner"}, "rating": 1700,
                  "ratingDiff": -8},
        "black": {"user": {"name": "Spieler", "id": "spieler"}, "rating": 1750,
                  "ratingDiff": 8},
    },
    "opening": {"eco": "B01", "name": "Skandinavisch"},
    "pgn": "1. e4 d5",
}


def test_lichess_partie_wird_aus_eigener_sicht_gelesen(monkeypatch):
    monkeypatch.setattr(cp, "_hole",
                        lambda url, accept=None: (json.dumps(LICHESS_PARTIE) + "\n").encode())
    partie = list(cp.hole_partien("lichess", "Spieler"))[0]

    assert partie["color"] == "schwarz"         # eigene Farbe, nicht Weiss
    assert partie["result"] == "sieg"           # winner == eigene Farbe
    assert partie["opponent"] == "Gegner"
    assert partie["own_rating"] == 1750 and partie["rating_diff"] == 8
    assert partie["end_reason"] == "Zeit"
    assert partie["ext_id"] == "abc123"
    assert partie["played_at"].year == 2023


CHESSCOM_ARCHIVE = {"archives": ["https://api.chess.com/pub/player/spieler/games/2024/01"]}
CHESSCOM_MONAT = {"games": [
    {"uuid": "u-1", "end_time": 1700000600, "time_class": "rapid",
     "rules": "chess", "rated": True,
     "white": {"username": "Spieler", "rating": 1500, "result": "agreed"},
     "black": {"username": "Gegner", "rating": 1520, "result": "agreed"},
     "eco": "https://www.chess.com/openings/Pirc-Defense-Classical",
     "url": "https://www.chess.com/game/live/1", "pgn": "1. e4 d6"},
    {"uuid": "u-2", "end_time": 1700000900, "time_class": "blitz",
     "rules": "chess", "rated": True,
     "white": {"username": "Gegner", "rating": 1520, "result": "win"},
     "black": {"username": "Spieler", "rating": 1500, "result": "checkmated"},
     "url": "https://www.chess.com/game/live/2", "pgn": "1. d4"},
]}


def test_chesscom_ergebnisse_und_eroeffnung(monkeypatch):
    _antworten(monkeypatch, {"/games/archives": CHESSCOM_ARCHIVE,
                             "/games/2024/01": CHESSCOM_MONAT})
    partien = list(cp.hole_partien("chesscom", "Spieler"))

    assert len(partien) == 2
    # "agreed" auf beiden Seiten ist ein Remis, kein verlorenes Spiel.
    assert partien[0]["result"] == "remis"
    assert partien[0]["color"] == "weiss"
    # Der lesbare Eroeffnungsname steckt bei Chess.com in einer Link-Adresse.
    assert partien[0]["opening"] == "Pirc Defense Classical"
    # Zweite Partie: als Schwarz matt gesetzt.
    assert partien[1]["color"] == "schwarz"
    assert partien[1]["result"] == "niederlage"
    assert partien[1]["end_reason"] == "matt"
    assert partien[1]["opponent"] == "Gegner"


def test_chesscom_deckel_haelt(monkeypatch):
    _antworten(monkeypatch, {"/games/archives": CHESSCOM_ARCHIVE,
                             "/games/2024/01": CHESSCOM_MONAT})
    assert len(list(cp.hole_partien("chesscom", "Spieler", hoechstens=1))) == 1


# --------------------------------------------------------------------------
# Was nicht gefuehrt wird
# --------------------------------------------------------------------------
def test_fernschach_und_turnierbedenkzeit_bleiben_draussen():
    # Fernschach heisst bei Chess.com "daily" und bei Lichess
    # "correspondence" -- beide Schreibweisen muessen fallen, sonst haengt es
    # an der Plattform, ob eine Partie ueber drei Tage mitgezaehlt wird.
    assert not cp.wird_gefuehrt("daily")
    assert not cp.wird_gefuehrt("correspondence")
    assert not cp.wird_gefuehrt("classical")
    assert cp.wird_gefuehrt("blitz")
    assert cp.wird_gefuehrt("ultraBullet")
    # Eine unbekannte Zeitkontrolle soll auftauchen und nicht still fehlen.
    assert cp.wird_gefuehrt("irgendwasNeues")
    assert "daily" not in cp.PERFS and "classical" not in cp.PERFS


def test_chesscom_liefert_keine_fernschach_wertung_mehr(monkeypatch):
    stats = dict(CHESSCOM_STATS)
    stats["chess_daily"] = {"last": {"rating": 1400},
                            "record": {"win": 2, "loss": 0, "draw": 0}}
    _antworten(monkeypatch, {"/stats": stats, "pub/player/spieler": CHESSCOM_PROFIL})
    perfs = {w["perf"] for w in cp.hole_profil("chesscom", "Spieler")["ratings"]}
    assert "daily" not in perfs
    assert "bullet" in perfs


# --------------------------------------------------------------------------
# Eroeffnungsfamilien
# --------------------------------------------------------------------------
def test_varianten_derselben_eroeffnung_landen_in_einer_familie():
    # Lichess trennt mit Doppelpunkt, Chess.com haengt Variante und Zugfolge
    # an. Ohne Zusammenlegen stuende dieselbe Eroeffnung zwanzigmal in der
    # Rangliste, jedes Mal mit einer Partie.
    assert (cp.eroeffnungs_familie("Sicilian Defense: Najdorf Variation")
            == "Sicilian Defense")
    assert (cp.eroeffnungs_familie("Sicilian Defense Najdorf Variation 6.Be3")
            == "Sicilian Defense")
    assert cp.eroeffnungs_familie("Pirc Defense Classical") == "Pirc Defense"
    assert cp.eroeffnungs_familie("") is None
    assert cp.eroeffnungs_familie(None) is None


# --------------------------------------------------------------------------
# Die Achse des Verlaufs
# --------------------------------------------------------------------------
def test_koernung_waechst_mit_dem_zeitraum():
    assert cr._koernung(30) == "tag"
    assert cr._koernung(365) == "woche"
    assert cr._koernung(3650) == "monat"


def test_achse_ist_lueckenlos_und_trifft_date_trunc():
    # Wochen beginnen am Montag, Monate am Ersten -- dieselbe Rechnung wie
    # date_trunc in der Aktivitaets-Abfrage. Zwei Fassungen davon waeren zwei
    # Achsen, die sich um einen Tag unterscheiden.
    assert cr._eimer(date(2026, 9, 16), "woche") == date(2026, 9, 14)
    assert cr._eimer(date(2026, 9, 16), "monat") == date(2026, 9, 1)

    tage = cr._achse(date(2026, 9, 1), date(2026, 9, 5), "tag")
    assert tage == [date(2026, 9, d) for d in range(1, 6)]

    monate = cr._achse(date(2025, 11, 20), date(2026, 2, 3), "monat")
    assert monate == [date(2025, 11, 1), date(2025, 12, 1),
                      date(2026, 1, 1), date(2026, 2, 1)]


def test_reihe_schreibt_den_letzten_stand_fort():
    # Eine Wertungszahl bewegt sich nur nach einer Partie: Tage ohne Partie
    # tragen den letzten bekannten Stand, nicht null und nichts Interpoliertes.
    tage = {date(2026, 8, 20): 1700, date(2026, 9, 2): 1750,
            date(2026, 9, 4): 1742}
    achse = cr._achse(date(2026, 9, 1), date(2026, 9, 5), "tag")
    r = cr._reihe(tage, achse, date(2026, 9, 1), date(2026, 9, 5), "tag")

    # Der Stand VOR dem Fenster ist der Startwert -- ohne ihn begaenne eine
    # kurze Ansicht leer, bis zur ersten Partie darin.
    assert r["start"] == 1700
    assert r["werte"] == [1700, 1750, 1750, 1742, 1742]
    assert r["hoch"] == {"rating": 1750, "tag": date(2026, 9, 2)}
    assert r["punkte"] == 2


def test_reihe_ohne_stand_davor_beginnt_leer():
    tage = {date(2026, 9, 3): 1800}
    achse = cr._achse(date(2026, 9, 1), date(2026, 9, 4), "tag")
    r = cr._reihe(tage, achse, date(2026, 9, 1), date(2026, 9, 4), "tag")
    # Vor der ersten bekannten Zahl gab es sie nicht -- dort bleibt die Reihe
    # leer, statt eine Zahl zu behaupten.
    assert r["werte"] == [None, None, 1800, 1800]
    assert r["start"] is None
