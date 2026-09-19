"""Quellen, aus denen sich eine Meilenstein-Kachel ihren Stand holt.

Eine Kachel im Sparziel kann ihren aktuellen Wert aus einem anderen Modul
lesen, statt ihn von Hand zu bekommen: das Gewicht aus Health, die Wertung aus
dem Schachmodul, die Zahl der getrackten Tage aus der Ernaehrung. Drei Regeln
halten das ungefaehrlich -- sie sind der ganze Entwurf:

1. **Eine Quelle liest, sie schreibt nie.** ``achievements.current_value``
   bleibt der bestaetigte Stand. Die Automatik legt nur eine Zahl daneben, die
   Kachel zeigt sie an, und erst eine Bestaetigung traegt sie ein -- durch
   dieselbe Stelle, die auch der Knopf "Setzen" benutzt. Es gibt also weiter
   genau EINEN Weg zu einer Gutschrift, und damit weiter nur eine Stelle, die
   ``credited_milestones`` kennt.
2. **Der Server liest, nicht der Browser.** Die Bestaetigung holt den Wert
   erneut hier ab, statt den zu nehmen, den die Seite mitschickt -- sonst
   waere die Automatik ein Eingabefeld mit Umweg.
3. **Doppelzahlung ist schon verhindert.** ``credited_milestones`` zaehlt nur
   vorwaerts (siehe ``_milestones_at`` und ``upd_ach``). Wer von 143 auf 146
   zunimmt und wieder unter 145 faellt, bekommt den Meilenstein nicht ein
   zweites Mal. Das galt vor der Automatik und gilt mit ihr unveraendert; eine
   eigene Sperre waere eine zweite Wahrheit ueber dieselbe Frage.

Ein neues Modul ist ein Eintrag in ``QUELLEN`` und eine Lesefunktion -- kein
Umbau. Der Katalog (``katalog``) beschreibt jede Quelle samt ihrer Parameter
so vollstaendig, dass der Bearbeiten-Dialog sich daraus selbst baut; im
Frontend steht keine zweite Liste, die man beim Ergaenzen vergessen koennte.
Dieselbe Bauart wie ``EXPORT_SECTIONS`` in ``services/full_export.py``.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from services import chess_platforms as plattform
from services.health_ingest import SIMPLE_METRIC_MAP

logger = logging.getLogger("vexbob.ach_sources")

METRIK_TYPEN = sorted(set(SIMPLE_METRIC_MAP.values()))

# Beschriftung und Einheit je Vitalwert. Die Einheit steht hier und wird nicht
# aus der Messung uebernommen, weil eine Kachel ihre Einheit selbst traegt --
# die Quelle soll sie nur vorschlagen koennen.
METRIK_INFO = {
    "active_energy":    ("Aktive Energie", "kcal"),
    "blood_oxygen":     ("Sauerstoffsättigung", "%"),
    "cardio_recovery":  ("Erholungspuls", "bpm"),
    "heart_rate":       ("Herzfrequenz", "bpm"),
    "hrv":              ("Herzfrequenzvariabilität", "ms"),
    "resting_hr":       ("Ruhepuls", "bpm"),
    "steps":            ("Schritte", "Schritte"),
    "swim_distance":    ("Schwimmstrecke", "km"),
    "vo2_max":          ("VO2max", "ml/kg/min"),
    "walking_distance": ("Gehstrecke", "km"),
    "walking_hr_avg":   ("Gehpuls", "bpm"),
    "walking_speed":    ("Gehtempo", "km/h"),
    "weight":           ("Gewicht", "kg"),
}

# Welche Vitalwerte sich ueber einen Tag AUFSUMMIEREN und welche einen Stand
# beschreiben. Der Unterschied entscheidet, was "der Wert eines Tages" heisst:
# 12.000 Schritte sind die Summe des Tages, 84,2 kg sind sein Mittel. Wer das
# verwechselt, bekommt bei Schritten einen Mittelwert ueber Messpunkte -- eine
# Zahl, die es in keinem Zusammenhang gibt.
KUMULATIV = {"steps", "active_energy", "swim_distance", "walking_distance"}

FENSTER_OPTIONEN = [
    {"wert": "0", "label": "Gesamt"},
    {"wert": "30", "label": "Letzte 30 Tage"},
    {"wert": "90", "label": "Letzte 90 Tage"},
    {"wert": "365", "label": "Letztes Jahr"},
]


# ---------------------------------------------------------------------------
# Hilfsmittel
# ---------------------------------------------------------------------------
def params_lesen(roh) -> dict:
    """Die gespeicherten Parameter als dict -- was auch immer dasteht.

    Die Spalte ist TEXT mit JSON darin (Begruendung in Migration 050). Eine
    kaputte Zeile darf die Kachel nicht mitnehmen: sie verliert dann ihre
    Einstellung, aber die Seite laedt.
    """
    if isinstance(roh, dict):
        return roh
    if not roh:
        return {}
    try:
        wert = json.loads(roh)
        return wert if isinstance(wert, dict) else {}
    except (ValueError, TypeError):
        logger.warning("Unlesbare auto_params: %r", roh)
        return {}


def _int(params: dict, key: str, standard: int) -> int:
    roh = params.get(key)
    if roh in (None, ""):
        return standard
    try:
        return int(roh)
    except (ValueError, TypeError):
        return standard


def _tage_klausel(params: dict, spalte: str, idx: int):
    """``(SQL-Fragment, Werte)`` fuer ein optionales Zeitfenster.

    ``fenster = 0`` heisst "Gesamt" und darf deshalb NICHT auf einen Tag
    zusammenschnurren -- derselbe Fallstrick wie in ``_series_since``.
    """
    tage = _int(params, "fenster", 0)
    if tage <= 0:
        return "", []
    return f" AND {spalte} >= CURRENT_DATE - ${idx}::int", [min(tage, 3650)]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
async def _health_metrik(db, user_id: int, params: dict) -> Optional[dict]:
    metrik = str(params.get("metrik") or "")
    if metrik not in METRIK_TYPEN:
        return None
    name, einheit = METRIK_INFO.get(metrik, (metrik, ""))
    modus = str(params.get("modus") or "letzter")

    if modus == "letzter":
        zeile = await db.fetchrow(
            "SELECT qty, sample_date FROM health_metric_samples "
            " WHERE user_id=$1 AND metric_type=$2 "
            " ORDER BY recorded_at DESC LIMIT 1", user_id, metrik)
        if not zeile or zeile["qty"] is None:
            return None
        return {"wert": float(zeile["qty"]), "einheit": einheit,
                "stand": zeile["sample_date"],
                "beschriftung": f"{name} · letzter Messwert"}

    # Der Tageswert: Summe bei kumulativen Metriken, Mittel bei allen anderen.
    tagesrechnung = "SUM(qty)" if metrik in KUMULATIV else "AVG(qty)"
    tage = max(1, min(_int(params, "tage", 7), 365))
    zeile = await db.fetchrow(
        "SELECT AVG(tageswert) AS mittel, MAX(tag) AS letzter, COUNT(*)::int AS messtage "
        "  FROM (SELECT sample_date AS tag, " + tagesrechnung + " AS tageswert "
        "          FROM health_metric_samples "
        "         WHERE user_id=$1 AND metric_type=$2 "
        "           AND sample_date >= CURRENT_DATE - $3::int "
        "         GROUP BY sample_date) t", user_id, metrik, tage)
    if not zeile or zeile["mittel"] is None:
        return None
    return {"wert": float(zeile["mittel"]), "einheit": einheit,
            "stand": zeile["letzter"],
            "beschriftung": f"{name} · Ø {tage} Tage ({zeile['messtage']} Messtage)"}


async def _health_workouts(db, user_id: int, params: dict) -> Optional[dict]:
    klausel, werte = _tage_klausel(params, "start_at::date", 2)
    zeile = await db.fetchrow(
        "SELECT COUNT(*)::int AS anzahl, MAX(start_at)::date AS letzter "
        "  FROM health_workouts WHERE user_id=$1" + klausel, user_id, *werte)
    zusatz = "gesamt" if not werte else f"letzte {werte[0]} Tage"
    return {"wert": float(zeile["anzahl"] or 0), "einheit": "Trainings",
            "stand": zeile["letzter"], "beschriftung": f"Trainings · {zusatz}"}


# ---------------------------------------------------------------------------
# Schach
# ---------------------------------------------------------------------------
async def _chess_wertung(db, user_id: int, params: dict) -> Optional[dict]:
    disziplin = str(params.get("disziplin") or "")
    konto = params.get("konto")
    if not disziplin:
        return None
    bedingung = "a.user_id=$1 AND r.perf=$2 AND NOT r.is_best"
    werte = [user_id, disziplin]
    if konto not in (None, ""):
        try:
            werte.append(int(konto))
        except (ValueError, TypeError):
            return None
        bedingung += f" AND r.account_id=${len(werte)}"
    zeile = await db.fetchrow(
        "SELECT r.rating, r.taken_on, a.platform, a.username "
        "  FROM chess_ratings r JOIN chess_accounts a ON a.id = r.account_id "
        " WHERE " + bedingung + " ORDER BY r.taken_on DESC, r.rating DESC LIMIT 1", *werte)
    if not zeile or zeile["rating"] is None:
        return None
    art = plattform.PERF_LABEL.get(disziplin, disziplin)
    wer = f"{zeile['platform']} · {zeile['username']}"
    return {"wert": float(zeile["rating"]), "einheit": "Punkte",
            "stand": zeile["taken_on"], "beschriftung": f"{art} · {wer}"}


async def _chess_partien(db, user_id: int, params: dict) -> Optional[dict]:
    ergebnis = str(params.get("ergebnis") or "alle")
    disziplin = str(params.get("disziplin") or "")
    bedingung = "user_id=$1 AND (perf IS NULL OR perf <> ALL($2::text[]))"
    werte = [user_id, list(plattform.NICHT_GEFUEHRT)]
    if disziplin:
        werte.append(disziplin)
        bedingung += f" AND perf=${len(werte)}"
    if ergebnis in ("sieg", "remis", "niederlage"):
        werte.append(ergebnis)
        bedingung += f" AND result=${len(werte)}"
    klausel, fenster = _tage_klausel(params, "played_at::date", len(werte) + 1)
    werte += fenster
    zeile = await db.fetchrow(
        "SELECT COUNT(*)::int AS anzahl, MAX(played_at)::date AS letzte "
        "  FROM chess_games WHERE " + bedingung + klausel, *werte)
    art = plattform.PERF_LABEL.get(disziplin, disziplin) if disziplin else "alle Disziplinen"
    was = {"sieg": "Siege", "remis": "Remis",
           "niederlage": "Niederlagen"}.get(ergebnis, "Partien")
    return {"wert": float(zeile["anzahl"] or 0), "einheit": was,
            "stand": zeile["letzte"], "beschriftung": f"{was} · {art}"}


# ---------------------------------------------------------------------------
# Ausgaben
# ---------------------------------------------------------------------------
async def _ausgaben(db, user_id: int, params: dict) -> Optional[dict]:
    kennzahl = str(params.get("kennzahl") or "summe")
    klausel, werte = _tage_klausel(params, "purchase_date", 2)
    zeile = await db.fetchrow(
        "SELECT COALESCE(SUM(total_amount),0) AS summe, COUNT(*)::int AS anzahl, "
        "       MAX(purchase_date) AS letzte "
        "  FROM expenses WHERE user_id=$1" + klausel, user_id, *werte)
    zusatz = "gesamt" if not werte else f"letzte {werte[0]} Tage"
    if kennzahl == "anzahl":
        return {"wert": float(zeile["anzahl"] or 0), "einheit": "Einkäufe",
                "stand": zeile["letzte"], "beschriftung": f"Einkäufe · {zusatz}"}
    return {"wert": float(zeile["summe"] or 0), "einheit": "€",
            "stand": zeile["letzte"], "beschriftung": f"Ausgaben · {zusatz}"}


# ---------------------------------------------------------------------------
# Musik
# ---------------------------------------------------------------------------
async def _musik(db, user_id: int, params: dict) -> Optional[dict]:
    kennzahl = str(params.get("kennzahl") or "stunden")
    art = str(params.get("art") or "")
    bedingung = "user_id=$1"
    werte = [user_id]
    if art:
        werte.append(art)
        bedingung += f" AND kind=${len(werte)}"
    klausel, fenster = _tage_klausel(params, "period_end", len(werte) + 1)
    werte += fenster
    zeile = await db.fetchrow(
        "SELECT COALESCE(SUM(ms_played),0)::bigint AS ms, "
        "       COALESCE(SUM(plays),0)::bigint AS wiedergaben, "
        "       MAX(period_end) AS letzte "
        "  FROM music_entries WHERE " + bedingung + klausel, *werte)
    zusatz = "gesamt" if not fenster else f"letzte {fenster[0]} Tage"
    woran = (art or "Alles") + " · " + zusatz
    if kennzahl == "wiedergaben":
        return {"wert": float(zeile["wiedergaben"] or 0), "einheit": "Wiedergaben",
                "stand": zeile["letzte"], "beschriftung": f"Wiedergaben · {woran}"}
    return {"wert": round(float(zeile["ms"] or 0) / 3_600_000, 2), "einheit": "Stunden",
            "stand": zeile["letzte"], "beschriftung": f"Hörzeit · {woran}"}


# ---------------------------------------------------------------------------
# Ernaehrung
# ---------------------------------------------------------------------------
async def _ernaehrung_tage(db, user_id: int, params: dict) -> Optional[dict]:
    """Tage, an denen ueberhaupt etwas eingetragen wurde -- Tagebuch ODER Tracker.

    Bewusst die Zahl der TAGE und keine Kalorien: kcal sind nur fuer
    Lebensmittel eine Spalte, fuer ein Gericht rechnet sie ``zutaten_summe``
    aus den Zutaten. Eine Quelle, die nur die Lebensmittel summiert, waere
    stillschweigend zu niedrig -- und eine zu niedrige Zahl in einer Kachel,
    die Geld auszahlt, ist schlimmer als gar keine.
    """
    quelle = str(params.get("quelle") or "beide")
    klausel, werte = _tage_klausel(params, "day", 2)
    teile = []
    if quelle in ("beide", "tagebuch"):
        teile.append("SELECT day FROM food_diary WHERE user_id=$1" + klausel)
    if quelle in ("beide", "tracker"):
        teile.append("SELECT day FROM food_log WHERE user_id=$1" + klausel)
    if not teile:
        return None
    zeile = await db.fetchrow(
        "SELECT COUNT(DISTINCT day)::int AS tage, MAX(day) AS letzter FROM ("
        + " UNION ALL ".join(teile) + ") t", user_id, *werte)
    zusatz = "gesamt" if not werte else f"letzte {werte[0]} Tage"
    wo = {"tagebuch": "Tagebuch", "tracker": "Tracker"}.get(quelle, "Tagebuch + Tracker")
    return {"wert": float(zeile["tage"] or 0), "einheit": "Tage",
            "stand": zeile["letzter"], "beschriftung": f"{wo} · {zusatz}"}


# ---------------------------------------------------------------------------
# Das Register
# ---------------------------------------------------------------------------
# ``params`` beschreibt die Felder, die der Bearbeiten-Dialog zeichnet. Ein
# Feld mit ``wenn`` erscheint nur, solange ein anderes Feld den genannten Wert
# traegt -- so bleibt "ueber wie viele Tage" weg, wenn "letzter Messwert"
# gewaehlt ist. ``optionen`` darf leer bleiben und wird dann von ``katalog()``
# aus dem Bestand des Nutzers gefuellt (Schachkonten zum Beispiel).
QUELLEN = {
    "health.metrik": {
        "label": "Gesundheit · Vitalwert",
        "modul": "health",
        "hinweis": "Nimmt den Messwert aus Health. Das Mittel über mehrere Tage "
                   "glättet die Tagesschwankungen der Waage.",
        "params": [
            {"key": "metrik", "label": "Messwert", "typ": "auswahl", "pflicht": True,
             "optionen": [{"wert": m, "label": METRIK_INFO.get(m, (m, ""))[0]}
                          for m in sorted(METRIK_TYPEN,
                                          key=lambda x: METRIK_INFO.get(x, (x, ""))[0])]},
            {"key": "modus", "label": "Welcher Wert zählt", "typ": "auswahl",
             "standard": "mittel",
             "optionen": [{"wert": "mittel", "label": "Mittel über mehrere Tage"},
                          {"wert": "letzter", "label": "Letzter Messwert"}]},
            {"key": "tage", "label": "Über wie viele Tage", "typ": "auswahl",
             "standard": "7", "wenn": {"modus": "mittel"},
             "optionen": [{"wert": "3", "label": "3 Tage"},
                          {"wert": "7", "label": "7 Tage"},
                          {"wert": "14", "label": "14 Tage"},
                          {"wert": "30", "label": "30 Tage"}]},
        ],
        "lesen": _health_metrik,
    },
    "health.workouts": {
        "label": "Gesundheit · Trainings",
        "modul": "health",
        "params": [
            {"key": "fenster", "label": "Zeitraum", "typ": "auswahl", "standard": "0",
             "optionen": FENSTER_OPTIONEN},
        ],
        "lesen": _health_workouts,
    },
    "chess.wertung": {
        "label": "Schach · Wertung",
        "modul": "schach",
        "hinweis": "Die jüngste Wertungszahl. Bestwerte zählen nicht mit — ein "
                   "Wert, der „jemals“ bedeutet, wäre kein Stand.",
        "params": [
            {"key": "disziplin", "label": "Disziplin", "typ": "auswahl",
             "pflicht": True, "optionen": []},
            {"key": "konto", "label": "Konto", "typ": "auswahl", "optionen": [],
             "leer_label": "Höchste Wertung über alle Konten"},
        ],
        "lesen": _chess_wertung,
    },
    "chess.partien": {
        "label": "Schach · Partien und Siege",
        "modul": "schach",
        "params": [
            {"key": "ergebnis", "label": "Gezählt wird", "typ": "auswahl",
             "standard": "alle",
             "optionen": [{"wert": "alle", "label": "Alle Partien"},
                          {"wert": "sieg", "label": "Nur Siege"},
                          {"wert": "remis", "label": "Nur Remis"},
                          {"wert": "niederlage", "label": "Nur Niederlagen"}]},
            {"key": "disziplin", "label": "Disziplin", "typ": "auswahl",
             "optionen": [], "leer_label": "Alle Disziplinen"},
            {"key": "fenster", "label": "Zeitraum", "typ": "auswahl", "standard": "0",
             "optionen": FENSTER_OPTIONEN},
        ],
        "lesen": _chess_partien,
    },
    "ausgaben.summe": {
        "label": "Ausgaben · Betrag oder Anzahl",
        "modul": "ausgaben",
        "params": [
            {"key": "kennzahl", "label": "Gezählt wird", "typ": "auswahl",
             "standard": "summe",
             "optionen": [{"wert": "summe", "label": "Betrag (€)"},
                          {"wert": "anzahl", "label": "Anzahl Einkäufe"}]},
            {"key": "fenster", "label": "Zeitraum", "typ": "auswahl", "standard": "30",
             "optionen": FENSTER_OPTIONEN},
        ],
        "lesen": _ausgaben,
    },
    "musik.hoeren": {
        "label": "Musik · Hörzeit oder Wiedergaben",
        "modul": "musik",
        "params": [
            {"key": "kennzahl", "label": "Gezählt wird", "typ": "auswahl",
             "standard": "stunden",
             "optionen": [{"wert": "stunden", "label": "Hörzeit (Stunden)"},
                          {"wert": "wiedergaben", "label": "Wiedergaben"}]},
            {"key": "art", "label": "Art", "typ": "auswahl", "optionen": [],
             "leer_label": "Alles"},
            {"key": "fenster", "label": "Zeitraum", "typ": "auswahl", "standard": "0",
             "optionen": FENSTER_OPTIONEN},
        ],
        "lesen": _musik,
    },
    "ernaehrung.tage": {
        "label": "Ernährung · Tage mit Eintrag",
        "modul": "ernaehrung",
        "hinweis": "Zählt Tage, nicht Kalorien: die kcal eines Gerichts stehen "
                   "in seinen Zutaten, eine Summe nur über Lebensmittel wäre "
                   "stillschweigend zu niedrig.",
        "params": [
            {"key": "quelle", "label": "Woraus", "typ": "auswahl", "standard": "beide",
             "optionen": [{"wert": "beide", "label": "Tagebuch und Tracker"},
                          {"wert": "tagebuch", "label": "Nur Tagebuch"},
                          {"wert": "tracker", "label": "Nur Tracker"}]},
            {"key": "fenster", "label": "Zeitraum", "typ": "auswahl", "standard": "0",
             "optionen": FENSTER_OPTIONEN},
        ],
        "lesen": _ernaehrung_tage,
    },
}


async def katalog(db, user_id: int) -> list:
    """Alle Quellen samt Parametern -- die Vorlage, aus der sich der Dialog baut.

    Die leeren Optionslisten werden hier aus dem Bestand des Nutzers gefuellt.
    Eine Quelle, fuer die es beim Nutzer noch nichts gibt (kein Schachkonto,
    kein Musik-Import), kommt mit ``verfuegbar: false`` trotzdem mit, statt zu
    fehlen: dann steht im Dialog, WARUM sie nicht geht, und nicht bloss nichts.
    """
    disziplinen = [r["perf"] for r in await db.fetch(
        "SELECT DISTINCT perf FROM chess_games "
        " WHERE user_id=$1 AND perf IS NOT NULL ORDER BY perf", user_id)]
    konten = await db.fetch(
        "SELECT id, platform, username FROM chess_accounts "
        " WHERE user_id=$1 ORDER BY platform", user_id)
    arten = [r["kind"] for r in await db.fetch(
        "SELECT DISTINCT kind FROM music_entries "
        " WHERE user_id=$1 AND kind <> '' ORDER BY kind", user_id)]
    hat_metrik = bool(await db.fetchval(
        "SELECT 1 FROM health_metric_samples WHERE user_id=$1 LIMIT 1", user_id))
    hat_workout = bool(await db.fetchval(
        "SELECT 1 FROM health_workouts WHERE user_id=$1 LIMIT 1", user_id))
    hat_ausgaben = bool(await db.fetchval(
        "SELECT 1 FROM expenses WHERE user_id=$1 LIMIT 1", user_id))
    hat_essen = bool(await db.fetchval(
        "SELECT 1 FROM food_diary WHERE user_id=$1 LIMIT 1", user_id)) or bool(
        await db.fetchval("SELECT 1 FROM food_log WHERE user_id=$1 LIMIT 1", user_id))

    live = {
        "chess.wertung": {
            "disziplin": [{"wert": d, "label": plattform.PERF_LABEL.get(d, d)}
                          for d in disziplinen],
            "konto": [{"wert": str(k["id"]),
                       "label": f"{k['platform']} · {k['username']}"} for k in konten]},
        "chess.partien": {
            "disziplin": [{"wert": d, "label": plattform.PERF_LABEL.get(d, d)}
                          for d in disziplinen]},
        "musik.hoeren": {"art": [{"wert": a, "label": a} for a in arten]},
    }
    vorhanden = {
        "health.metrik": (hat_metrik, "Noch keine Messwerte aus Health importiert."),
        "health.workouts": (hat_workout, "Noch keine Trainings aus Health importiert."),
        "chess.wertung": (bool(konten), "Noch kein Schachkonto verbunden."),
        "chess.partien": (bool(disziplinen), "Noch keine Partien importiert."),
        "ausgaben.summe": (hat_ausgaben, "Noch keine Einkäufe erfasst."),
        "musik.hoeren": (bool(arten), "Noch kein Musik-Export eingespielt."),
        "ernaehrung.tage": (hat_essen, "Noch nichts gegessen eingetragen."),
    }

    raus = []
    for key, q in QUELLEN.items():
        felder = []
        for p in q["params"]:
            feld = dict(p)
            nach = live.get(key, {}).get(p["key"])
            if nach is not None:
                feld["optionen"] = nach
            felder.append(feld)
        ok, grund = vorhanden.get(key, (True, ""))
        raus.append({"key": key, "label": q["label"], "modul": q["modul"],
                     "hinweis": q.get("hinweis"), "params": felder,
                     "verfuegbar": ok, "grund": None if ok else grund})
    return raus


async def wert_lesen(db, user_id: int, key: Optional[str], params) -> Optional[dict]:
    """Der aktuelle Stand einer Quelle -- oder ``None``, wenn es keinen gibt.

    ``None`` ist der ehrliche Fall und kein Fehler: eine Kachel am Gewicht, auf
    dessen Waage noch nie jemand stand, hat keinen Stand. Sie zeigt das an,
    statt eine Null zu behaupten.
    """
    if not key or key not in QUELLEN:
        return None
    try:
        wert = await QUELLEN[key]["lesen"](db, user_id, params_lesen(params))
    except Exception as e:
        # Eine Quelle, die stolpert, darf die Sparziel-Seite nicht mitnehmen --
        # dort haengen die anderen Kacheln und das Sparziel selbst mit dran.
        logger.warning("Quelle %s fuer User %s fehlgeschlagen: %s", key, user_id, e)
        return None
    if not wert or wert.get("wert") is None:
        return None
    stand = wert.get("stand")
    if hasattr(stand, "isoformat"):
        wert["stand"] = stand.isoformat()
    wert["quelle"] = key
    wert["quelle_label"] = QUELLEN[key]["label"]
    return wert
