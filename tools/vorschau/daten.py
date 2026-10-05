# -*- coding: utf-8 -*-
"""Die Antworten fuer die Vorschau -- aus dem ECHTEN Backend-Code gebaut.

Abgetippte Beispielantworten waeren die zweite Wahrheit ueber die
Schnittstelle und wuerden genau dort abweichen, wo es darauf ankommt. Was
sich aus ``food_calc`` und ``food_mahlzeit`` rechnen laesst, wird deshalb hier
wirklich gerechnet: Mahlzeitenliste, Stundengrenzen, Tagessummen, Richtwerte
und Beschriftungen kommen aus denselben Funktionen, die im Betrieb laufen.

Von Hand steht hier nur, was ohne Datenbank nicht zu holen ist: die Zeilen
eines Tages, der Bestand und die Gerichte. Ihre Schluessel sind aus
``_zeile_rechnen`` und ``_ser`` abgeschrieben -- weicht eine davon ab, bleibt
die Seite in der Vorschau leer, und genau das soll sie dann auch.
"""
import datetime
import json
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from services import food_calc as calc          # noqa: E402
from services import food_mahlzeit as mz        # noqa: E402
from services import full_export as _export    # noqa: E402
from services import achievement_sources as _quellen  # noqa: E402

HEUTE = datetime.date.today()
ICH = {"id": 1, "username": "etienne", "is_admin": True}


# ---------------------------------------------------------------- Tagebuch
def _tb_zeile(id_, label, level, meal, auto=False, zeit=None, note=None):
    return {"id": id_, "label": label, "level": level,
            "level_label": "übermäßig" if level == "viel" else "normal",
            "meal": meal, "meal_auto": auto, "note": note, "logged_time": zeit}


TB_EINTRAEGE = [
    _tb_zeile(1, "Haferflocken mit Banane", "normal", "fruehstueck", True, "08:12"),
    _tb_zeile(2, "Kaffee", "normal", "fruehstueck", True, "08:20"),
    _tb_zeile(3, "Pasta mit Pesto", "viel", "mittag", False, "12:45", "beim Italiener"),
    _tb_zeile(4, "Apfel", "normal", "snack", True, "15:30"),
    _tb_zeile(5, "Brot mit Käse", "normal", "abend", True, "19:10"),
]

TAGEBUCH_TAG = {
    "day": str(HEUTE),
    "entries": TB_EINTRAEGE,
    "counts": {"entries": len(TB_EINTRAEGE),
               "normal": sum(1 for e in TB_EINTRAEGE if e["level"] == "normal"),
               "viel": sum(1 for e in TB_EINTRAEGE if e["level"] == "viel")},
    "meals": mz.liste_raus(),
    "meal_hours": mz.grenzen_raus(),
    "levels": [{"key": "normal", "label": "normal"},
               {"key": "viel", "label": "übermäßig"}],
    "quick": [{"label": "Kaffee", "count": 61, "last": str(HEUTE)},
              {"label": "Haferflocken mit Banane", "count": 43, "last": str(HEUTE)},
              {"label": "Apfel", "count": 28, "last": str(HEUTE)},
              {"label": "Brot mit Käse", "count": 22, "last": str(HEUTE)},
              {"label": "Pasta mit Pesto", "count": 14, "last": str(HEUTE)},
              {"label": "Joghurt", "count": 9,
               "last": str(HEUTE - datetime.timedelta(days=2))}],
}

TAGEBUCH_HAEUFIG = {"suggestions": TAGEBUCH_TAG["quick"] + [
    {"label": "Rührei", "count": 7, "last": str(HEUTE - datetime.timedelta(days=4))},
    {"label": "Pizza", "count": 5, "last": str(HEUTE - datetime.timedelta(days=9))},
]}


# -------------------------------------------------------------- Naehrwerte
def _nw_zeile(id_, name, sub, kind, label, amount, unit, gramm, meal,
              kcal=None, auto=False, zeit=None, item_id=None, dish_id=None):
    return {"id": id_, "name": name, "sub": sub, "kind": kind,
            "amount_label": label, "amount": amount, "unit": unit,
            "item_id": item_id, "dish_id": dish_id, "grams": gramm,
            "meal": meal, "meal_auto": auto, "note": None, "logged_time": zeit,
            "has_nutrition": kcal is not None,
            "kcal": kcal}


NW_EINTRAEGE = [
    _nw_zeile(1, "Haferflocken", "Kölln", "item", "80 g", 80, "g", 80,
              "fruehstueck", 303, True, "08:12", item_id=3),
    _nw_zeile(2, "Milch 1,5 %", "Weihenstephan", "item", "200 ml", 200, "ml", 200,
              "fruehstueck", 94, True, "08:12", item_id=4),
    _nw_zeile(3, "Wraps mit Hähnchen", "Gericht", "dish", "1,5 Portionen", 1.5,
              "Portion", 450, "mittag", 620, False, "12:45", dish_id=7),
    _nw_zeile(4, "Apfel", "lose", "item", "1 Stück", 1, "Stück", 180,
              "snack", 94, True, "15:30", item_id=5),
    # Ohne Naehrwerte -- dafuer ist die gestrichelte Spur da.
    _nw_zeile(5, "Brot vom Markt", "selbst angelegt", "item", "2 Scheiben", 2,
              "Scheibe", 90, "abend", None, True, "19:10", item_id=6),
]

# Die Naehrwerte je Eintrag -- daraus rechnet der echte ``tages_summe_genau``.
_WERTE = [
    {"kcal": 303, "protein_g": 10.8, "fiber_g": 8.0, "carbs_g": 47.2, "fat_g": 5.6},
    {"kcal": 94, "protein_g": 6.8, "fiber_g": 0.0, "carbs_g": 9.6, "fat_g": 3.0},
    {"kcal": 620, "protein_g": 31.0, "fiber_g": None, "carbs_g": 60.0, "fat_g": 20.0},
    {"kcal": 94, "protein_g": 0.5, "fiber_g": 4.0, "carbs_g": 20.0, "fat_g": 0.3},
    {"kcal": None, "protein_g": None, "fiber_g": None, "carbs_g": None, "fat_g": None},
]


def _mahlzeit_summen():
    raus = {}
    for eintrag, werte in zip(NW_EINTRAEGE, _WERTE):
        topf = raus.setdefault(eintrag["meal"], {"kcal": 0, "incomplete": False})
        if werte.get("kcal") is None:
            topf["incomplete"] = True
        else:
            topf["kcal"] += werte["kcal"]
    for topf in raus.values():
        topf["kcal"] = round(topf["kcal"])
    return raus


NAEHRWERTE_TAG = {
    "day": str(HEUTE),
    "entries": NW_EINTRAEGE,
    "counts": {"entries": len(NW_EINTRAEGE),
               "unknown": sum(1 for e in NW_EINTRAEGE if not e["has_nutrition"])},
    "meals": mz.liste_raus(),
    "meal_hours": mz.grenzen_raus(),
    "meal_totals": _mahlzeit_summen(),
    "totals": calc.tages_summe_genau(_WERTE, None),
    "targets": {m: None for m in calc.MAKROS},
    "macros": list(calc.MAKROS),
    "macro_labels": dict(calc.MAKRO_LABEL),
    "reference_note": calc.RICHTWERT_QUELLE,
    "target_note": calc.ZIEL_QUELLE,
}

ZIELE = {
    "targets": {m: None for m in calc.MAKROS},
    "defaults": {m: float(calc.RICHTWERT[m]) for m in calc.MAKROS},
    "macros": list(calc.MAKROS),
    "macro_labels": dict(calc.MAKRO_LABEL),
    "reference_note": calc.RICHTWERT_QUELLE,
    "target_note": calc.ZIEL_QUELLE,
}


def _item(id_, name, marke, kcal, eiweiss, kh, fett, basis="g", groessen=(),
          ballast=None):
    return {"id": id_, "name": name, "brand": marke, "barcode": None,
            "source": "off", "base_unit": basis, "kcal": kcal,
            "protein_g": eiweiss, "carbs_g": kh, "sugar_g": None, "fat_g": fett,
            "sat_fat_g": None, "fiber_g": ballast, "salt_g": None,
            "portion_g": None, "portion_label": None, "package_g": None,
            "user_edited": False, "has_photo": False,
            "sizes": [{"label": l, "grams": g, "position": i}
                      for i, (l, g) in enumerate(groessen)],
            "units": ([{"key": basis, "label": basis}]
                      + [{"key": l, "label": l} for l, _ in groessen])}


BESTAND = {
    "items": [
        _item(3, "Haferflocken kernig", "Kölln", 379, 13.5, 59, 7, "g",
              [("Portion", 80)], 10),
        _item(4, "Milch 1,5 %", "Weihenstephan", 47, 3.4, 4.8, 1.5, "ml",
              [("Glas", 200)], 0),
        _item(5, "Apfel", None, 52, 0.3, 11.4, 0.2, "g", [("Stück", 180)], 2.4),
        _item(6, "Brot vom Markt", None, None, None, None, None, "g",
              [("Scheibe", 45)]),
    ],
    "total": 4,
    "size_suggestions": list(calc.GAENGIGE_GROESSEN),
}

GERICHTE = {
    "dishes": [{
        "id": 7, "name": "Wraps mit Hähnchen", "note": None, "has_photo": False,
        "portion": {"grams": 300, "kcal": 413, "protein_g": 20.7,
                    "fiber_g": None, "carbs_g": 40.0, "fat_g": 13.3,
                    "incomplete": ["fiber_g"]},
        "items": [
            {"link_id": 1, "item_id": 3, "name": "Weizen-Wrap", "brand": None,
             "amount": 2, "unit": "Stück", "grams": 128, "position": 0},
            {"link_id": 2, "item_id": 5, "name": "Hähnchenbrust", "brand": None,
             "amount": 150, "unit": "g", "grams": 150, "position": 1},
        ]}],
    "portions": [0.5, 1, 1.5, 2],
}

BRUECKE = {"suggestions": [
    {"name": "Pasta mit Pesto", "count": 14, "last": str(HEUTE)},
    {"name": "Brot mit Käse", "count": 22, "last": str(HEUTE)},
], "diary_days": 34}

NW_HAEUFIG = {"suggestions": [
    {"kind": "item", "dish_id": None, "item_id": 3, "name": "Haferflocken kernig",
     "count": 40, "last": str(HEUTE), "last_amount": 80.0, "last_unit": "g"},
    {"kind": "dish", "dish_id": 7, "item_id": None, "name": "Wraps mit Hähnchen",
     "count": 11, "last": str(HEUTE), "last_amount": 1.0, "last_unit": "Portion"},
]}


def _verlauf():
    tage = []
    muster = [1980, 2310, 1750, 2640, 2090, 1880, 2200,
              2450, 1920, 2010, 2780, 1660, 2130, 2260]
    for i, kcal in enumerate(muster):
        tag = HEUTE - datetime.timedelta(days=len(muster) - 1 - i)
        tage.append({
            "day": str(tag), "entries": 4 + (i % 3), "unknown": 1 if i % 5 == 0 else 0,
            "kcal": {"value": kcal, "incomplete": i % 5 == 0},
            "protein_g": {"value": 90 + (i * 3) % 40, "incomplete": False},
            "fiber_g": {"value": 18 + (i * 2) % 12, "incomplete": i % 5 == 0},
            "carbs_g": {"value": 210 + (i * 7) % 60, "incomplete": False},
            "fat_g": {"value": 70 + (i * 5) % 25, "incomplete": False},
        })
    # Die Form muss der echten Antwort von /api/food/track/history gleichen,
    # sonst zeigt die Vorschau eine Seite, die es so nicht gibt. Bis v2.5.0
    # fehlten hier `from`, `to` und `summary` -- die Seite las `v.summary`,
    # bekam `undefined` und brach ab: der Verlaufs-Reiter stand leer da, und
    # in seiner Kopfzeile stand "undefined bis undefined". Wer sich darauf
    # verlaesst, prueft das eine Blatt nie, das er gerade nicht sieht.
    voll = [t for t in tage if not t["unknown"]]
    return {
        "from": tage[0]["day"], "to": tage[-1]["day"],
        "days": tage,
        "truncated": False,
        "targets": {m: None for m in calc.MAKROS},
        "reference": {m: float(calc.RICHTWERT[m]) for m in calc.MAKROS},
        "macros": list(calc.MAKROS),
        "macro_labels": dict(calc.MAKRO_LABEL),
        "summary": {
            "days": len(tage),
            "days_logged": len(tage),
            "entries": sum(t["entries"] for t in tage),
            "complete_days": len(voll),
            "target_hit_days": sum(1 for t in voll if t["kcal"]["value"] <= 2400),
            "kcal_avg": round(sum(t["kcal"]["value"] for t in voll) / len(voll)),
            "protein_avg": round(sum(t["protein_g"]["value"] for t in voll) / len(voll)),
        },
    }


# ---------------------------------------------------------------- Sparziel
# Der Katalog der Meilenstein-Quellen kommt aus dem ECHTEN Register, nicht aus
# einer abgetippten Liste -- sonst faellt beim naechsten neuen Modul genau der
# Fehler nicht auf, den die Vorschau finden soll. Gefuellt wird er hier nur um
# die Optionen, die im Betrieb aus der Datenbank kaemen (Schachkonten usw.).
def _quellen_katalog():
    live = {
        ("chess.wertung", "disziplin"): [{"wert": "blitz", "label": "Blitz"},
                                         {"wert": "rapid", "label": "Rapid"}],
        ("chess.wertung", "konto"): [{"wert": "1", "label": "lichess · etienne"}],
        ("chess.partien", "disziplin"): [{"wert": "blitz", "label": "Blitz"}],
        ("musik.hoeren", "art"): [{"wert": "Musik", "label": "Musik"},
                                  {"wert": "Podcast", "label": "Podcast"}],
    }
    raus = []
    for key, q in _quellen.QUELLEN.items():
        felder = []
        for feld in q["params"]:
            kopie = dict(feld)
            if (key, feld["key"]) in live:
                kopie["optionen"] = live[(key, feld["key"])]
            felder.append(kopie)
        raus.append({"key": key, "label": q["label"], "modul": q["modul"],
                     "hinweis": q.get("hinweis"), "params": felder,
                     "verfuegbar": True, "grund": None})
    return raus


SPARZIEL = {
    "goal": {"id": 1, "name": "Neues Rennrad", "target_amount": 2400,
             "is_active": True, "is_general": False},
    "total_saved": 1465.5,
    "buffer": {"id": 9, "name": "Allgemein", "saved_amount": 212.0},
}

SPARZIELE = [
    {"id": 1, "name": "Neues Rennrad", "target_amount": 2400, "saved_amount": 1465.5,
     "is_active": True, "is_general": False, "link": "https://www.example.com/rennrad"},
    {"id": 2, "name": "Städtereise", "target_amount": 900, "saved_amount": 340.0,
     "is_active": False, "is_general": False},
    {"id": 9, "name": "Allgemein", "target_amount": None, "saved_amount": 212.0,
     "is_active": False, "is_general": True},
]

# Drei Kacheln, die zusammen alle drei Zustaende zeigen, die es geben kann:
# eine Quelle mit faelligem Meilenstein, eine Quelle ohne, und eine von Hand.
ACHIEVEMENTS = [
    {"id": 1, "title": "Abnehmen", "reward_amount": 20, "unit": "kg",
     "current_value": 145, "start_value": 150, "threshold_increment": 5,
     "step_amount": 1, "target_value": 120, "direction": "decrease",
     "credited_milestones": 1, "is_completed": False, "sort_order": 1,
     "reward_goal_id": None, "auto_source": "health.metrik",
     "auto_params": {"metrik": "weight", "modus": "mittel", "tage": "7"}},
    {"id": 2, "title": "Blitz-Wertung", "reward_amount": 15, "unit": "Punkte",
     "current_value": 1600, "start_value": 1500, "threshold_increment": 50,
     "step_amount": 10, "target_value": 1800, "direction": "increase",
     "credited_milestones": 2, "is_completed": False, "sort_order": 2,
     "reward_goal_id": None, "auto_source": "chess.wertung",
     "auto_params": {"disziplin": "blitz", "konto": "1"}},
    {"id": 3, "title": "Bücher gelesen", "reward_amount": 10, "unit": "Bücher",
     "current_value": 7, "start_value": 0, "threshold_increment": 2,
     "step_amount": 1, "target_value": 24, "direction": "increase",
     "credited_milestones": 3, "is_completed": False, "sort_order": 3,
     "reward_goal_id": None, "auto_source": None, "auto_params": {}},
]

AUTO_STATUS = [
    # 139,4 kg: unter 140 und damit ein faelliger Meilenstein -- das Band.
    {"achievement_id": 1, "quelle": "health.metrik",
     "quelle_label": "Gesundheit · Vitalwert", "wert": 139.4, "einheit": "kg",
     "beschriftung": "Gewicht · Ø 7 Tage (6 Messtage)", "stand": str(HEUTE),
     "offene_meilensteine": 1, "gutschrift": 20.0, "abweichung": -5.6},
    # 1624 Punkte: ueber dem gebuchten Stand, aber unter der naechsten Schwelle.
    {"achievement_id": 2, "quelle": "chess.wertung",
     "quelle_label": "Schach · Wertung", "wert": 1624, "einheit": "Punkte",
     "beschriftung": "Blitz · lichess · etienne", "stand": str(HEUTE),
     "offene_meilensteine": 0, "gutschrift": 0.0, "abweichung": 24.0},
]

# Seit v2.19.0 mit den Tagen der laufenden Woche (``current_dates``), aus
# denen die Kachel ihren Wochenstreifen zeichnet -- und mit drei Zuständen:
# unterwegs, knapp vor der Teilbelohnung, und ein Monatsziel, das voll ist.
_MONTAG = HEUTE - datetime.timedelta(days=HEUTE.weekday())
_BISHER = [_MONTAG + datetime.timedelta(days=i) for i in range(HEUTE.weekday() + 1)]


def _wochentage(*versatz):
    """Tage dieser Woche bis heute; Versatz 0 ist Montag."""
    return [str(_MONTAG + datetime.timedelta(days=v)) for v in versatz
            if _MONTAG + datetime.timedelta(days=v) <= HEUTE]


PROGRESS_GOALS = [
    {"id": 1, "title": "Dreimal Sport", "reward_amount": 5, "rhythm_type": "weekly",
     "target_count": 3, "streak": 4, "streak_bonus_amount": 10,
     "streak_bonus_threshold": 4, "sort_order": 1, "partial_count": 0,
     "partial_percent": 0, "reward_goal_id": None, "is_completed": False,
     "current_dates": _wochentage(0, 2)},
    {"id": 2, "title": "Lesen vor dem Schlafen", "reward_amount": 8, "rhythm_type": "weekly",
     "target_count": 5, "streak": 0, "streak_bonus_amount": 0,
     "streak_bonus_threshold": 0, "sort_order": 2, "partial_count": 3,
     "partial_percent": 50, "reward_goal_id": None, "is_completed": False,
     "current_dates": _wochentage(0, 0, 1)},
    {"id": 3, "title": "Kein Lieferdienst", "reward_amount": 15, "rhythm_type": "monthly",
     "target_count": 4, "streak": 2, "streak_bonus_amount": 0,
     "streak_bonus_threshold": 0, "sort_order": 3, "partial_count": 0,
     "partial_percent": 0, "reward_goal_id": None, "is_completed": False,
     "current_dates": [str(HEUTE.replace(day=1))] * 4},
]
for _g in PROGRESS_GOALS:
    _g["current_count"] = len(_g["current_dates"])


def _pg_verlauf():
    """Vergangene Wochen fuer den Dialog eines Wochenziels."""
    raus = []
    for n, (anzahl, voll) in enumerate([(2, False), (3, True), (3, True), (1, False), (3, True)]):
        start = _MONTAG - datetime.timedelta(days=7 * n)
        jahr, woche, _ = start.isocalendar()
        raus.append({
            "period_key": f"{jahr}-W{woche:02d}", "start": str(start),
            "end": str(start + datetime.timedelta(days=6)),
            "current_count": anzahl, "target_count": 3, "fulfilled": voll,
            "is_current": n == 0, "paid_out": voll and n > 0,
            "partial_paid": None,
            "log_dates": [str(start + datetime.timedelta(days=2 * i)) for i in range(anzahl)
                          if start + datetime.timedelta(days=2 * i) <= HEUTE]})
    return raus


def _sparkurve():
    """Vier Monate Sparstand, Tag fuer Tag, endend bei SPARZIEL["total_saved"]."""
    tage = 120
    zugang = {}
    for i in range(tage):
        if i == 0:
            zugang[i] = 600.0
        elif i % 9 == 0:
            zugang[i] = 45.0
        elif i % 4 == 0:
            zugang[i] = 15.0
        elif i % 7 == 3:
            zugang[i] = 8.0
    # Der Anfangsbestand nimmt, was bis zum Stand fehlt -- so endet die Kurve
    # genau bei der Zahl auf der Bühne.
    zugang[0] = round(SPARZIEL["total_saved"] - sum(v for k, v in zugang.items() if k), 2)
    punkte, stand = [], 0.0
    for i in range(tage):
        stand = round(stand + zugang.get(i, 0.0), 2)
        punkte.append({"date": str(HEUTE - datetime.timedelta(days=tage - 1 - i)),
                       "cumulative": stand, "added": zugang.get(i, 0.0)})
    return {"goal": SPARZIEL["goal"], "step": "tag", "points": punkte}


TROPHAEEN = [
    {"id": 1, "name": "Kamera gekauft", "icon": "🏆", "color": "gold",
     "final_amount": 850.0, "target_amount": 850.0,
     "completed_at": "2026-05-14T18:20:00", "duration_days": 142, "note": "Endlich!"},
    {"id": 2, "name": "Konzertreise", "icon": "🎉", "color": "purple",
     "final_amount": 420.0, "target_amount": 400.0,
     "completed_at": "2026-02-02T10:00:00", "duration_days": 61, "note": None},
]
WUENSCHE = [
    {"id": 1, "name": "Kopfhörer mit Geräuschunterdrückung", "estimated_price": 249.0,
     "link": "https://www.example.com/kopfhoerer"},
    {"id": 2, "name": "Kletterschuhe", "estimated_price": None},
]
IDEEN = [
    {"id": 1, "title": "Sprachkurs Spanisch", "category": "milestone"},
    # v2.36.0: eine fertig ausgearbeitete Idee -- mit einem Tipp aktiv.
    {"id": 4, "title": "Dreimal die Woche lesen", "category": "progress",
     "config": {"reward_amount": 4, "rhythm_type": "weekly", "target_count": 3,
                "streak_bonus_amount": 0, "streak_bonus_threshold": 0,
                "partial_count": 2, "partial_percent": 50, "reward_goal_id": None}},
    {"id": 2, "title": "Jeden Morgen zehn Minuten dehnen", "category": "progress"},
    {"id": 3, "title": "Wochenende in Wien", "category": None},
]


# ---------------------------------------------------------------- Export
# Der Export-Dialog fragt drei Endpunkte. Ohne Antwort darauf steht er mit
# einer Fehlermeldung da, wo im Betrieb Zahlen stehen -- und ein Bild davon
# beantwortet nichts. Die Zeilenzahlen sind erfunden, die FORM nicht: sie
# kommt aus ``build_export_preview`` und ``fit_export_to_size``.
def _export_vorschau(stufe="none", mit_rohdaten=False):
    """Eine erfundene Vorschau in der ECHTEN Form.

    ``mit_rohdaten=False`` bildet nach, was der Dialog mit „Zum Auswerten“
    anfragt: alles ausser den ``bulk``-Sektionen. Ohne diese Nachbildung
    stuende im Bild eine Zeile „Zugfolgen als PGN: 2.600“ unter einer
    Einstellung, die sie gerade abwaehlt -- und ein Bild, das etwas anderes
    zeigt als der Betrieb, ist schlimmer als keines.
    """
    teile = []
    for eintrag in _export.EXPORT_SECTIONS:
        if eintrag.get("bulk") and not mit_rohdaten:
            continue
        # Grob nach Modul gestaffelt, damit die Balken unterschiedlich lang
        # sind -- ein Diagramm aus lauter gleichen Balken zeigt nichts.
        roh = {"ausgaben": 4200, "health_vitals": 9800, "chess_games": 2600,
               "chess_pgn": 2600, "music_register": 5100, "track_log": 1900,
               "diary_log": 1400, "sparziel_log": 480}.get(eintrag["key"], 60)
        if stufe == "month" and eintrag.get("aggregatable"):
            roh = max(12, roh // 30)
        teile.append({"key": eintrag["key"], "label": eintrag["label"],
                      "rows": roh, "bytes": roh * 90,
                      "columns": ["Datum", "Wert", "Einheit"]})
    zeilen = sum(t["rows"] for t in teile)
    return {
        "sections": teile,
        "total_rows": zeilen,
        "bytes": zeilen * 90,
        "lines": zeilen + len(teile) * 2,
        "aggregate": {g["key"]: stufe for g in _export.EXPORT_GROUPS},
        "compact_before": None,
        "sample": \
            "# Vexbob Gesamt-Export;user=\"etienne\"\n"
            "# Konventionen: Feldtrenner ist ';'. ALLE Zahlen nutzen Punkt-Dezimal.\n"
            "\n# SEKTION: Sparziele\n"
            "id;name;typ;target_amount;saved_amount;is_active\n"
            "1;Neues Rennrad;ziel;2400.00;1465.50;true",
        "truncated": True,
    }


EXPORT_PREVIEW = _export_vorschau("none")
EXPORT_FIT = {
    "fits": True,
    "max_bytes": 1048576,
    "bytes": _export_vorschau("month")["bytes"],
    "aggregate": {g["key"]: "month" for g in _export.EXPORT_GROUPS},
    "changed": {g["key"]: "month" for g in _export.EXPORT_GROUPS},
    "builds": 3,
    "note": "",
    "largest_section": {"key": "health_vitals", "label": "Vitalwerte",
                        "bytes": 29400},
    "preview": _export_vorschau("month"),
}


# ==========================================================================
# Die Module, die bis v2.11.4 keine Vorschau hatten
# --------------------------------------------------------------------------
# Ausgaben (neun Seiten!), Gesundheit, Musik, Notizen, Blog und Verwaltung
# liessen sich bis dahin nicht ansehen -- ihre Darstellung war unbelegt,
# waehrend fuenf andere Module bei jeder Aenderung im Bild geprueft wurden.
# Die Schluessel sind aus den Render-Funktionen der jeweiligen Seite
# abgeschrieben; weicht einer ab, bleibt der Block leer, und genau das soll
# er dann auch.
# ==========================================================================

def _tag(minus):
    return (HEUTE - datetime.timedelta(days=minus)).isoformat()


# ---------------------------------------------------------------- Ausgaben
LAEDEN = [
    {"id": 1, "name": "REWE", "color": "#e11d48", "icon": "R", "receipt_count": 48},
    {"id": 2, "name": "Aldi Süd", "color": "#0ea5e9", "icon": "A", "receipt_count": 31},
    {"id": 3, "name": "dm", "color": "#22c55e", "icon": "D", "receipt_count": 12},
]

KATEGORIEN = [
    {"id": 1, "name": "Lebensmittel", "icon": "🛒", "color": "#22c55e", "item_count": 412},
    {"id": 2, "name": "Drogerie", "icon": "🧴", "color": "#0ea5e9", "item_count": 63},
    {"id": 3, "name": "Haushalt", "icon": "🏠", "color": "#a78bfa", "item_count": 21},
]

AUSGABEN_TYPEN = [
    {"key": "receipt", "label": "Kassenbon", "icon": "🧾"},
    {"key": "online", "label": "Online-Bestellung", "icon": "📦"},
    {"key": "bill", "label": "Rechnung", "icon": "📄"},
]

BONS = [
    {"id": 101, "store_name": "REWE", "store_color": "#e11d48", "store_icon": "R",
     "expense_type": "receipt", "purchase_date": _tag(0), "item_count": 14,
     "total_amount": 43.87, "has_image": True, "is_recurring": False},
    {"id": 102, "store_name": "dm", "store_color": "#22c55e", "store_icon": "D",
     "expense_type": "receipt", "purchase_date": _tag(0), "item_count": 3,
     "total_amount": 11.45, "has_image": False, "is_recurring": False},
    {"id": 103, "store_name": "Aldi Süd", "store_color": "#0ea5e9", "store_icon": "A",
     "expense_type": "receipt", "purchase_date": _tag(1), "item_count": 9,
     "total_amount": 27.10, "has_image": True, "is_recurring": False},
    {"id": 104, "store_name": "Netflix", "store_color": "#a78bfa", "store_icon": "N",
     "expense_type": "bill", "purchase_date": _tag(3), "item_count": 1,
     "total_amount": 13.99, "has_image": False, "is_recurring": True},
    {"id": 105, "store_name": "REWE", "store_color": "#e11d48", "store_icon": "R",
     "expense_type": "receipt", "purchase_date": _tag(5), "item_count": 21,
     "total_amount": 61.24, "has_image": True, "is_recurring": False},
]

AUSGABEN_SUMME = {
    "today": 55.32, "this_week": 142.41, "this_month": 486.90,
    "prev_month": 531.08, "prev_month_to_date": 512.40,
    "this_year": 4820.55, "total": 9614.02, "count": 213,
}


# -------------------------------------------------------------- Gesundheit
# Die Zusammenfassung ist je Metrik ein Objekt mit ``last`` und ``week_sum``
# -- abgeschrieben aus ``renderHeartOverview`` und ``loadDashboard``.
# ---------------------------------------------------------------- Gesundheit
# Seit v2.20.0 in der FORM des echten Servers: ``sample_date``/``recorded_at``
# an jeder Messreihe, ``sleep_date``/``sleep_start``/``sleep_end`` an jeder
# Nacht, ``start_at``/``active_energy_kcal``/``distance_m`` an jedem Workout.
# Die Fassung davor hatte eigene Feldnamen -- die Seite schnitt jede Reihe
# nach ``sample_date`` zu, fand keins, und jedes Bild zeigte leere Karten.
# Neunzig Tage, mit Wochenrhythmus und ein paar Luecken, damit Kurven,
# Mittelwerte und Messluecken so aussehen wie im Betrieb. Und wie im Betrieb
# endet alles GESTERN: der Upload kommt einmal am Tag und bringt die Tage
# bis gestern; heute steht noch nichts da.
_GTAGE = 90


def _welle(i, basis, hub, woche=0.0, rauschen=0.0):
    """Ein gleichmaessiges, aber nicht glattes Signal ohne Zufall."""
    import math
    return (basis + hub * math.sin(i / 6.0) + woche * math.sin(i * 2 * math.pi / 7)
            + rauschen * math.sin(i * 12.9898) * math.cos(i * 4.1414))


def _g_reihe(fn, luecken=(), rund=0, einheit=None, mittel=False):
    raus = []
    for i in range(_GTAGE):
        if i in luecken:
            continue
        tag = HEUTE - datetime.timedelta(days=_GTAGE - i)
        wert = round(fn(i), rund) if rund else int(round(fn(i)))
        zeile = {"sample_date": tag.isoformat(),
                 "recorded_at": tag.isoformat() + "T00:00:00+02:00",
                 "qty": wert, "unit": einheit}
        if mittel:
            zeile["avg_value"] = wert
        raus.append(zeile)
    return raus


SCHRITTE_REIHE = _g_reihe(lambda i: _welle(i, 8600, 1400, 1300, 900),
                          luecken={23, 51}, einheit="count")
ENERGIE_REIHE = _g_reihe(lambda i: _welle(i, 470, 90, 80, 60),
                         luecken={23, 51}, einheit="kcal")
PULS_REIHE = _g_reihe(lambda i: _welle(i, 74, 2, 1.5, 1.5), einheit="bpm", mittel=True)
RUHEPULS_REIHE = _g_reihe(lambda i: _welle(i, 58.5 - i * 0.02, 1.2, 0.5, 0.8), einheit="bpm", mittel=True)
HRV_REIHE = _g_reihe(lambda i: _welle(i, 42, 5, 2, 4), einheit="ms", mittel=True)
GEWICHT_REIHE = _g_reihe(lambda i: 145.2 - i * 0.065 + 0.4 * ((i * 7) % 5) / 5, rund=1,
                         luecken=set(range(0, _GTAGE, 3)) | {1, 2}, einheit="kg")
VO2_REIHE = _g_reihe(lambda i: 37.6 + i * 0.009, rund=1,
                     luecken={i for i in range(_GTAGE) if i % 6}, einheit="ml/kg/min")
STRECKE_REIHE = _g_reihe(lambda i: _welle(i, 6.1, 1.0, 0.9, 0.7), rund=1,
                         luecken={23, 51}, einheit="km")
SAUERSTOFF_REIHE = _g_reihe(lambda i: _welle(i, 96.5, 0.6, 0.3, 0.5), rund=1, einheit="%")

# v2.37.0: eine eigene Messgroesse (Messwert) und eine Tagessumme, dazu die
# Liste der letzten Handeintraege -- der Dialog zeigt sie unter dem Formular.
SCHMERZ_REIHE = _g_reihe(lambda i: 3 + ((i * 5) % 4), rund=0,
                         luecken={i for i in range(_GTAGE) if i % 2}, einheit="1–10")
WASSER_REIHE = _g_reihe(lambda i: 5 + ((i * 3) % 4), rund=0, einheit="Gläser")
EIGENE_GROESSEN = [
    {"id": 1, "key": "eigen_1", "name": "Rückenschmerzen", "einheit": "1–10",
     "kumulativ": False, "anzahl": len(SCHMERZ_REIHE), "zuletzt": None},
    {"id": 2, "key": "eigen_2", "name": "Wasser", "einheit": "Gläser",
     "kumulativ": True, "anzahl": len(WASSER_REIHE), "zuletzt": None},
]
VON_HAND = [
    {"art": "eigen", "id": 31, "metrik": "eigen_1", "wert": 4.0,
     "recorded_at": "2026-10-05T08:10:00+00:00", "created_at": "2026-10-05T08:10:00+00:00"},
    {"art": "wert", "id": 32, "metrik": "weight", "wert": 141.4,
     "recorded_at": "2026-10-05T07:30:00+00:00", "created_at": "2026-10-05T07:31:00+00:00"},
    {"art": "blutdruck", "id": 33, "metrik": "blood_pressure", "systolisch": 128.0,
     "diastolisch": 82.0, "recorded_at": "2026-10-04T19:00:00+00:00",
     "created_at": "2026-10-04T19:01:00+00:00"},
]


def _nacht(i, dauer, bett, start_min):
    """Eine Nacht: Zubettgehen am Vorabend, Aufstehen am ``sleep_date``."""
    tag = HEUTE - datetime.timedelta(days=i + 1)
    start = datetime.datetime.combine(tag - datetime.timedelta(days=1), datetime.time(22, 0)) \
        + datetime.timedelta(minutes=start_min)
    ende = start + datetime.timedelta(minutes=bett)
    return {"id": 500 + i, "sleep_date": tag.isoformat(),
            "sleep_start": start.isoformat() + "+02:00", "sleep_end": ende.isoformat() + "+02:00",
            "in_bed_minutes": bett, "asleep_minutes": dauer,
            "core_minutes": int(dauer * 0.55), "deep_minutes": int(dauer * 0.17),
            "rem_minutes": int(dauer * 0.23), "awake_minutes": bett - dauer}


SCHLAF_NAECHTE = [
    _nacht(i, int(_welle(i, 430, 25, 20, 15)), int(_welle(i, 470, 20, 18, 10)),
           int(_welle(i, 70, 25, 20, 18)))
    for i in range(_GTAGE - 1, -1, -1) if i not in (9, 30)
]

GESUNDHEIT_SUMME = {
    "steps": {"last": {"qty": SCHRITTE_REIHE[-1]["qty"], "unit": "count",
                       "recorded_at": SCHRITTE_REIHE[-1]["recorded_at"]},
              "week_sum": sum(r["qty"] for r in SCHRITTE_REIHE[-7:])},
    "active_energy": {"last": {"qty": ENERGIE_REIHE[-1]["qty"], "unit": "kcal",
                               "recorded_at": ENERGIE_REIHE[-1]["recorded_at"]},
                      "week_sum": sum(r["qty"] for r in ENERGIE_REIHE[-7:])},
    "heart_rate": {"last": {"qty": PULS_REIHE[-1]["qty"], "unit": "bpm"}, "week_sum": 0},
    "resting_hr": {"last": {"qty": RUHEPULS_REIHE[-1]["qty"], "unit": "bpm"}, "week_sum": 0},
    "hrv": {"last": {"qty": HRV_REIHE[-1]["qty"], "unit": "ms"}, "week_sum": 0},
    "vo2_max": {"last": {"qty": VO2_REIHE[-1]["qty"], "unit": "ml/kg/min"}, "week_sum": 0},
    "weight": {"last": {"qty": GEWICHT_REIHE[-1]["qty"], "unit": "kg"}, "week_sum": 0},
    # ``renderSleepBlock`` liest die letzte Nacht aus der Zusammenfassung,
    # nicht aus /sleep.
    "sleep_last": SCHLAF_NAECHTE[-1],
    "blood_pressure_last": None,
    "workouts_this_week": 3,
}

BLUTDRUCK = [
    {"id": 700 + i, "recorded_at": (HEUTE - datetime.timedelta(days=i * 4)).isoformat() + "T07:30:00+02:00",
     "systolic": s_, "diastolic": d_, "unit": "mmHg"}
    for i, (s_, d_) in enumerate([(128, 82), (131, 84), (126, 80), (133, 86), (129, 83),
                                  (127, 81), (132, 85), (125, 79)])
][::-1]

BLUTZUCKER = [
    {"id": 800 + i, "recorded_at": (HEUTE - datetime.timedelta(days=i * 5)).isoformat() + "T08:00:00+02:00",
     "value": v, "unit": "mg/dL"}
    for i, v in enumerate([92, 88, 97, 90, 94, 89])
][::-1]


def _training(id_, art, vor_tagen, uhr, dauer, kcal, meter=None, puls=None, hoch=None):
    start = datetime.datetime.combine(HEUTE - datetime.timedelta(days=vor_tagen),
                                      datetime.time(*uhr))
    return {"id": id_, "workout_type": art, "start_at": start.isoformat() + "+02:00",
            "end_at": (start + datetime.timedelta(minutes=dauer)).isoformat() + "+02:00",
            "duration_min": dauer, "active_energy_kcal": kcal,
            "total_energy_kcal": int(kcal * 1.18), "distance_m": meter,
            "avg_heart_rate": puls, "max_heart_rate": (puls + 28) if puls else None,
            "min_heart_rate": (puls - 30) if puls else None, "elevation_m": hoch}


WORKOUTS = [
    _training(1, "Outdoor Laufen", 1, (18, 30), 42, 468, 7420, 152, 64),
    _training(2, "Schwimmbad Schwimmen", 3, (7, 5), 45, 390, 1600, 128),
    _training(3, "StrengthTraining", 4, (19, 5), 52, 330, None, 112),
    _training(4, "Cycling", 6, (9, 10), 68, 610, 24600, 126, 210),
    _training(5, "Outdoor Laufen", 8, (18, 45), 38, 431, 6710, 149, 51),
    _training(6, "Outdoor Spaziergang", 9, (13, 20), 55, 212, 4820, 98, 22),
    _training(7, "StrengthTraining", 11, (19, 0), 48, 305, None, 110),
    _training(8, "Schwimmbad Schwimmen", 13, (7, 0), 40, 352, 1450, 125),
]
# v2.27.0: Vier Monate dahinter, damit der Wochenrhythmus im Workout-Reiter
# etwas zu zeigen hat -- mit einer Lücke (Urlaub) und ruhigen Wochen.
_PLAN = [("Outdoor Laufen", (18, 30), 40, 450, 7000, 150, 55),
         ("StrengthTraining", (19, 0), 50, 320, None, 112, None),
         ("Schwimmbad Schwimmen", (7, 0), 42, 370, 1500, 127, None),
         ("Cycling", (9, 30), 75, 640, 26000, 128, 220),
         ("Outdoor Spaziergang", (13, 0), 55, 210, 4800, 97, 20)]
for _i, _vor in enumerate(range(15, 125, 2)):
    if 52 <= _vor <= 64 or _vor % 7 == 3:          # Urlaub, ruhige Tage
        continue
    _art, _uhr, _dauer, _kcal, _m, _puls, _hoch = _PLAN[_i % len(_PLAN)]
    _f = 0.85 + (_i % 5) * 0.07
    WORKOUTS.append(_training(9 + _i, _art, _vor, _uhr, int(_dauer * _f), int(_kcal * _f),
                              int(_m * _f) if _m else None, _puls + (_i % 4) - 2,
                              int(_hoch * _f) if _hoch else None))


# ------------------------------------------------------------------- Musik
# v2.11.9: Alle vier Musik-Antworten standen hier in einer Form, die es nie
# gegeben hat -- `count` statt `rows`, `minutes` statt `ms_played`, englische
# Artnamen ("music") statt der deutschen, die die Datenbank fuehrt
# ("Musik | Podcast | Hörbuch"), und Rasterschluessel "week"/"month" statt
# "woche"/"monat". Die Oberflaeche uebersetzt ueber genau diese Schluessel
# (VOCAB, STEP_LABEL in musik.js); mit den falschen zeigte die Vorschau fuer
# jede Zeile das Musik-Zeichen und schrieb das Raster roh hin. Massgeblich ist
# `backend/routers/music_router.py`.
def _ms(minuten):
    return minuten * 60 * 1000


MUSIK_FACETTEN = {
    "kinds": [{"key": "Musik", "rows": 18422, "plays": 18422},
              {"key": "Podcast", "rows": 913, "plays": 913},
              {"key": "Hörbuch", "rows": 44, "plays": 44}],
    "grains": [{"key": "tag", "label": "täglich", "rows": 2140},
               {"key": "woche", "label": "wöchentlich", "rows": 15200},
               {"key": "monat", "label": "monatlich", "rows": 2039}],
    "groups": [{"key": "titel", "rows": 19379}],
    "rows": 19379, "from": "2024-01-01", "to": _tag(0),
}

MUSIK_SUMME = {
    "by_kind": [
        {"kind": "Musik", "plays": 18422, "ms_played": _ms(58900),
         "titles": 7311, "artists": 1284, "rows": 18422},
        {"kind": "Podcast", "plays": 913, "ms_played": _ms(2180),
         "titles": 604, "artists": 38, "rows": 913},
        {"kind": "Hörbuch", "plays": 44, "ms_played": _ms(160),
         "titles": 44, "artists": 6, "rows": 44},
    ],
    "plays": 19379, "rows": 19379, "ms_played": _ms(61240),
    "titles": 7311, "artists": 1284,
    "from": "2024-01-01", "to": _tag(0),
    "grains": [{"grain": "tag", "rows": 2140, "from": "2026-06-01", "to": _tag(0)},
               {"grain": "woche", "rows": 15200, "from": "2024-01-01", "to": _tag(0)},
               {"grain": "monat", "rows": 2039, "from": "2024-01-01", "to": "2025-12-31"}],
}

MUSIK_TOP = {
    "by": "interpret", "metric": "plays",
    "items": [
        {"label": "Radiohead", "sub": None, "plays": 812, "titles": 94,
         "ms_played": _ms(3140), "from": "2024-01-01", "to": _tag(0)},
        {"label": "Bonobo", "sub": None, "plays": 604, "titles": 61,
         "ms_played": _ms(2480), "from": "2024-02-05", "to": _tag(3)},
        {"label": "Nils Frahm", "sub": None, "plays": 431, "titles": 48,
         "ms_played": _ms(2210), "from": "2024-01-14", "to": _tag(9)},
        {"label": "Four Tet", "sub": None, "plays": 388, "titles": 52,
         "ms_played": _ms(1620), "from": "2024-03-02", "to": _tag(21)},
        {"label": "Kiasmos", "sub": None, "plays": 301, "titles": 27,
         "ms_played": _ms(1410), "from": "2024-05-11", "to": _tag(30)},
    ],
}

# v2.11.9: Die Form stammt jetzt aus dem echten Endpunkt
# (`routers/music_router.py`, /api/music/entries): `items`, `total`, `plays`,
# `limit`, `offset` -- und je Zeile `period_key`, `grain`, `ms_played`. Vorher
# stand hier `rows`/`period`/`minutes`/`page`, eine Form, die es nie gab; das
# Register war in der Vorschau deshalb immer leer, und genau deshalb ist neun
# Versionen lang niemandem aufgefallen, wie es aussieht.
MUSIK_EINTRAEGE = {
    "total": 128, "plays": 1462, "limit": 100, "offset": 0,
    "items": [
        {"id": 1, "period_key": "2026-KW38", "grain": "woche", "kind": "Musik",
         "artist": "Radiohead", "title": "Weird Fishes / Arpeggi",
         "album": "In Rainbows", "plays": 12, "ms_played": _ms(62)},
        {"id": 2, "period_key": "2026-KW38", "grain": "woche", "kind": "Musik",
         "artist": "Bonobo", "title": "Kerala", "album": "Migration",
         "plays": 9, "ms_played": _ms(44)},
        {"id": 3, "period_key": "2026-KW38", "grain": "woche", "kind": "Musik",
         "artist": "Fontaines D.C.", "title": "Starburster", "album": "Romance",
         "plays": 8, "ms_played": _ms(29)},
        {"id": 4, "period_key": "2026-KW37", "grain": "woche", "kind": "Podcast",
         "artist": "Lage der Nation", "title": "LdN 412 — Haushalt, Netzausbau",
         "album": "", "plays": 1, "ms_played": _ms(118)},
        {"id": 5, "period_key": "2026-KW37", "grain": "woche", "kind": "Musik",
         "artist": "Khruangbin", "title": "May Ninth", "album": "Mordechai",
         "plays": 7, "ms_played": _ms(26)},
        {"id": 6, "period_key": "2026-08", "grain": "monat", "kind": "Musik",
         "artist": "Nils Frahm", "title": "Says", "album": "Spaces",
         "plays": 6, "ms_played": _ms(52)},
    ],
}


# ---------------------------------------------------------------- Notizen
NOTIZEN = [
    {"id": 1, "title": "Einkaufsliste Samstag", "content":
     "<ul><li>Haferflocken</li><li>Kaffeebohnen</li><li>Olivenöl</li></ul>",
     "color": "green", "pinned": True, "archived": False, "format": "html",
     "created_at": _tag(2) + "T10:12:00", "updated_at": _tag(0) + "T08:40:00"},
    {"id": 2, "title": "Ideen fürs Rennrad", "content":
     "<p>Erst Laufräder, dann Sattel. Bremsbeläge halten noch.</p>",
     "color": "blue", "pinned": False, "archived": False, "format": "html",
     "created_at": _tag(9) + "T21:02:00", "updated_at": _tag(4) + "T19:15:00"},
    {"id": 3, "title": "Schach: Eröffnungen üben", "content":
     "<p>Caro-Kann gegen e4, Slawisch gegen d4.</p>",
     "color": "default", "pinned": False, "archived": False, "format": "html",
     "created_at": _tag(20) + "T12:00:00", "updated_at": _tag(11) + "T12:00:00"},
]


# ------------------------------------------------------------- Verwaltung
KONTEN = [
    {"id": 1, "username": "etienne", "is_admin": True, "is_active": True,
     "created_at": _tag(400) + "T12:00:00", "last_login": _tag(0) + "T07:55:00"},
    {"id": 2, "username": "gast", "is_admin": False, "is_active": True,
     "created_at": _tag(30) + "T12:00:00", "last_login": _tag(6) + "T18:22:00"},
]


# ------------------------------------------------------------------- Blog
BLOG_BEITRAEGE = [
    {"id": 1, "slug": "warum-vexbob", "title": "Warum ich Vexbob gebaut habe",
     "subtitle": "Ein Tracker, der mir gehört", "tags": ["projekt", "vexbob"],
     "published_at": _tag(14) + "T18:00:00", "is_published": True,
     "cover_image_id": None, "excerpt": "Jede App wollte mein Abo. Also habe ich angefangen."},
    {"id": 2, "slug": "ein-jahr-ausgaben", "title": "Ein Jahr Bons scannen",
     "subtitle": "Was dabei herauskam", "tags": ["ausgaben"],
     "published_at": _tag(40) + "T09:30:00", "is_published": True,
     "cover_image_id": None, "excerpt": "213 Bons, 9.614 Euro, und eine Erkenntnis."},
]


# ---- Aktivitaets-Log (v2.11.8) ----
# Die Liste ist der Ausschnitt, LOG_SUMMEN die Auskunft ueber das Ganze. Hier
# decken sich beide -- das ist der normale Fall, und das Bild soll ihn zeigen.
# Dass die Zahl groesser sein kann als die Liste, faengt der Hinweis in
# renderLog ab; geprueft wird das in backend/tests/test_activity_log.py.
LOG_EREIGNISSE = [
    # v2.36.0: Aenderungen am Modul selbst -- ueber 0 EUR.
    {"type": "aenderung", "date": "2026-09-20T09:12:00", "title": "Wochenziel bearbeitet",
     "description": "„Laufen“ · Belohnung 5,00 € → 8,00 €; Ziel 3 → 4", "amount": 0.0,
     "log_id": 950, "note": "", "deletable": False},
    {"type": "aenderung", "date": "2026-09-20T09:10:00", "title": "Achievement angelegt",
     "description": "„Bücher gelesen“ · 3,00 € alle 1 Buch", "amount": 0.0,
     "log_id": 951, "note": "", "deletable": False},
    {"type": "checkin", "date": "2026-09-19T18:20:00", "log_date": "2026-09-19",
     "title": "Laufen", "description": "3/3 · 2026-W38", "amount": 15.0,
     "log_id": 901, "source_id": 11, "fulfilled": True, "note": "", "deletable": True},
    {"type": "milestone", "date": "2026-09-18", "title": "100 km gelaufen",
     "description": "Erreicht bei 100 km", "achieved_value": 100.0, "unit": "km",
     "amount": 50.0, "log_id": 902, "source_id": 4, "note": "", "deletable": True},
    {"type": "progress", "date": "2026-09-17T07:05:00", "title": "100 km gelaufen",
     "description": "92,5 → 97,5 km", "amount": 0.0, "delta": 5.0, "unit": "km",
     "hit_milestone": False, "log_id": 903, "source_id": 4, "note": "",
     "deletable": True},
    {"type": "streak_bonus", "date": "2026-09-15T21:00:00", "title": "Laufen",
     "description": "3 Wochen in Folge", "amount": 20.0, "log_id": 904,
     "source_id": 11, "note": "", "deletable": True},
    {"type": "transfer", "date": "2026-09-12T12:00:00", "title": "Übertrag",
     "description": "Auf „Neues Fahrrad“", "amount": 120.0, "log_id": 905,
     "source_id": 2, "note": "", "deletable": True},
    {"type": "initial", "date": "2026-01-02T09:00:00", "title": "Anfangsbestand",
     "description": "Start ins Jahr", "amount": 250.0, "log_id": 906,
     "note": "", "deletable": True},
]

LOG_SUMMEN = {
    "all": {"count": 6, "amount": 455.00},
    "by_type": {
        "checkin":      {"count": 1, "amount": 15.00},
        "milestone":    {"count": 1, "amount": 50.00},
        "progress":     {"count": 1, "amount": 0.0},
        "streak_bonus": {"count": 1, "amount": 20.00},
        "transfer":     {"count": 1, "amount": 120.00},
        "initial":      {"count": 1, "amount": 250.00},
    },
}

# Anzahl und Summe ueber ALLE Bons des Filters -- bewusst groesser als die
# sechs Zeilen in BONS, damit der Hinweis „Liste zeigt die neuesten …“ im
# Bild auftaucht.
AUSGABEN_GEFILTERT = {"count": 247, "total": 3184.92}


ANTWORTEN = {
    "/api/me": ICH,
    # Die Export-Registry kommt aus dem echten Modul -- eine nachgebaute
    # Liste waere beim naechsten neuen Modul falsch.
    "/api/export/sections": {"sections": _export.EXPORT_SECTIONS,
                             "groups": _export.EXPORT_GROUPS,
                             "aggregates": _export.EXPORT_AGGREGATES},
    # Leere Liste heisst ausdruecklich 'alle an' -- ein fehlender
    # Schluessel waere die Werkseinstellung, und die laesst die
    # Naehrwerte ruhen.
    # Mit gespeicherter Export-Voreinstellung: nur so laesst sich im Bild
    # pruefen, ob der Dialog sie beim Oeffnen wirklich uebernimmt.
    "/api/ui/prefs": {"prefs": {"ui_module_off": [],
                               "ui_export": {"aggregate": {"ausgaben": "month",
                                                           "health": "week"},
                                             "compact_before": "2026-08-01",
                                             # Abgeschaltet (v2.11.0): die Zeile
                                             # muss zuruecktreten, aber stehen
                                             # bleiben.
                                             "off": ["notizen"]}}},
    "/api/ui/nav-tabs": {"tabs": []},

    # ---- Ausgaben ----
    "/api/stores": LAEDEN,
    "/api/stores/merge-suggestions": [],
    "/api/expense-categories": KATEGORIEN,
    "/api/expense-types": AUSGABEN_TYPEN,
    "/api/category-rules": [],
    "/api/expenses": BONS,
    "/api/expenses/stats/summary": AUSGABEN_SUMME,
    "/api/expenses/stats/filtered": AUSGABEN_GEFILTERT,
    "/api/expenses/recurring/suggestions": [],
    "/api/expenses/duplicates": [],
    "/api/expenses/ocr/status": {"available": True, "engine": "tesseract"},
    "/api/receipts": [],

    # ---- Gesundheit ----
    "/api/health/summary": GESUNDHEIT_SUMME,
    "/api/health/metrics/steps": SCHRITTE_REIHE,
    "/api/health/metrics/active_energy": ENERGIE_REIHE,
    "/api/health/metrics/heart_rate": PULS_REIHE,
    "/api/health/metrics/resting_hr": RUHEPULS_REIHE,
    "/api/health/metrics/hrv": HRV_REIHE,
    "/api/health/metrics/weight": GEWICHT_REIHE,
    "/api/health/metrics/vo2_max": VO2_REIHE,
    "/api/health/metrics/walking_distance": STRECKE_REIHE,
    "/api/health/metrics/blood_oxygen": SAUERSTOFF_REIHE,
    "/api/health/metrics/eigen_1": SCHMERZ_REIHE,
    "/api/health/metrics/eigen_2": WASSER_REIHE,
    "/api/health/eigene": EIGENE_GROESSEN,
    "/api/health/manuell": VON_HAND,
    "/api/health/metrics/*": [],
    "/api/health/sleep": SCHLAF_NAECHTE,
    "/api/health/blood-pressure": BLUTDRUCK,
    "/api/health/blood-glucose": BLUTZUCKER,
    "/api/health/workouts": WORKOUTS,
    "/api/health/metric-order": {"order": []},
    "/api/health/workouts/*": {
        "extra_metrics": [{"metric_key": "cadence_spm", "value": 168, "unit": "spm"},
                          {"metric_key": "step_count", "value": 6980, "unit": None},
                          {"metric_key": "temperature_c", "value": 14.5, "unit": "°C"}],
        "hr_series": [{"recorded_at": f"{_tag(1)}T18:{30 + m:02d}:00+02:00",
                       "avg_bpm": 118 + int(34 * min(1, m / 8)) + (m % 5)} for m in range(0, 29, 2)],
        "hr_recovery": [{"recorded_at": f"{_tag(1)}T19:{12 + m:02d}:00+02:00",
                         "avg_bpm": 150 - m * 9} for m in range(0, 6)]},
    "/api/health/api-keys": [
        {"id": 1, "label": "iPhone", "created_at": _tag(160) + "T20:14:00+02:00",
         "last_used_at": _tag(0) + "T07:12:00+02:00", "revoked_at": None},
        {"id": 2, "label": "Altes iPhone", "created_at": _tag(420) + "T09:00:00+02:00",
         "last_used_at": _tag(170) + "T06:40:00+02:00", "revoked_at": _tag(160) + "T20:15:00+02:00"}],
    "/api/health/imports": [
        {"id": 31, "created_at": _tag(0) + "T07:12:00+02:00", "kind": "json",
         "filename": "HealthAutoExport-" + _tag(0) + ".json", "size_bytes": 184320,
         "truncated": False, "preview": '{"data":{"metrics":[{"name":"step_count","units":"count"',
         "stats": {"metrics_imported": 42, "sleep_imported": 1, "workouts_imported": 0}},
        {"id": 30, "created_at": _tag(1) + "T19:20:00+02:00", "kind": "json",
         "filename": "HealthAutoExport-" + _tag(1) + ".json", "size_bytes": 212992,
         "truncated": False, "preview": '{"data":{"workouts":[{"name":"Outdoor Run"',
         "stats": {"metrics_imported": 38, "workouts_imported": 1}}],

    # ---- Musik ----
    "/api/music/facets": MUSIK_FACETTEN,
    "/api/music/summary": MUSIK_SUMME,
    "/api/music/series": [],
    "/api/music/top": MUSIK_TOP,
    "/api/music/entries": MUSIK_EINTRAEGE,
    "/api/music/imports": [],

    # ---- Notizen ----
    "/api/notes": NOTIZEN,

    # ---- Verwaltung ----
    "/api/admin/users": KONTEN,

    # ---- Blog ----
    "/api/blog/posts": BLOG_BEITRAEGE,
    "/api/blog/tags": [{"tag": "projekt", "count": 4}, {"tag": "ausgaben", "count": 2}],


    "/api/food/diary/day": TAGEBUCH_TAG,
    "/api/food/diary/frequent": TAGEBUCH_HAEUFIG,

    "/api/food/track/day": NAEHRWERTE_TAG,
    "/api/food/track/targets": ZIELE,
    "/api/food/track/history": _verlauf(),
    "/api/food/track/frequent": NW_HAEUFIG,
    "/api/food/track/bridge": BRUECKE,
    "/api/food/items": BESTAND,
    "/api/food/dishes": GERICHTE,
    "/api/food/catalog": {"count": 372814, "newest": 1758000000,
                          "may_import": True},
    "/api/food/search": {"results": [], "origin": "katalog"},

    "/api/savings-goal": SPARZIEL,
    "/api/savings-goals": SPARZIELE,
    "/api/achievements": ACHIEVEMENTS,
    "/api/achievements/auto-status": AUTO_STATUS,
    "/api/achievements/auto-sources": _quellen_katalog(),
    "/api/progress-goals": PROGRESS_GOALS,
    "/api/progress-goals/*/history": _pg_verlauf(),
    "/api/progress-goals/*/checkin": {"current_count": 3, "target_count": 3, "fulfilled": True,
                                      "paid_out": True, "streak_bonus_paid": False, "streak": 5},
    "/api/potential-goals": WUENSCHE,
    "/api/future-ideas": IDEEN,
    "/api/trophies": TROPHAEEN,
    "/api/activity-log": LOG_EREIGNISSE,
    "/api/activity-log/summary": LOG_SUMMEN,
    "/api/stats/savings-progress": _sparkurve(),

    "/api/export/preview": EXPORT_PREVIEW,
    "/api/export/fit": EXPORT_FIT,
}

# Seit v2.18.0: echte Antworten fuer die Seiten, die bis dahin gar keine
# Vorschau-Daten hatten -- CS2, Schach, der oeffentliche Blog und die
# Ausgaben-Unterseiten (Statistik, Bon, Marken, Import). Mitgeschnitten aus
# einem lokalen Backend mit Testdaten, damit die FORM genau stimmt; von Hand
# nachgebaut waere sie beim ersten Feld daneben, das die Seite liest.
# Nur ergaenzend: was oben von Hand steht, hat Vorrang.
_AUFNAHMEN = json.loads((pathlib.Path(__file__).resolve().parent
                         / "aufnahmen.json").read_text(encoding="utf-8"))
for _pfad, _antwort in _AUFNAHMEN.items():
    ANTWORTEN.setdefault(_pfad, _antwort)
