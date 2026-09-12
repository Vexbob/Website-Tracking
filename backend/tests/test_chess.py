"""Tests fuer die Umrechnung der beiden Schach-Plattformen (v1.83.0).

Ohne Netz: die Abfragen werden durch aufgezeichnete Antworten ersetzt. Der
Fokus liegt auf dem, was die beiden Plattformen unterschiedlich machen --
genau dort entstehen sonst Zahlen, die nebeneinander stehen und nicht
dasselbe bedeuten.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services import chess_platforms as cp  # noqa: E402


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
