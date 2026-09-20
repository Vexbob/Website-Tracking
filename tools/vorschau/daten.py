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
     "is_active": True, "is_general": False},
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

PROGRESS_GOALS = [
    {"id": 1, "title": "Dreimal Sport", "reward_amount": 5, "rhythm_type": "weekly",
     "target_count": 3, "current_count": 2, "streak": 4, "streak_bonus_amount": 10,
     "streak_bonus_threshold": 4, "period_key": "2026-KW38", "sort_order": 1,
     "reward_goal_id": None, "is_completed": False},
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
    "/api/potential-goals": [],
    "/api/future-ideas": [],
    "/api/trophies": [],
    "/api/activity-log": {"entries": []},
    "/api/stats/savings-progress": {"points": []},

    "/api/export/preview": EXPORT_PREVIEW,
    "/api/export/fit": EXPORT_FIT,
}
