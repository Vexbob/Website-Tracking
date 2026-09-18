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
    return {"days": tage, "macros": list(calc.MAKROS),
            "macro_labels": dict(calc.MAKRO_LABEL),
            "targets": {m: None for m in calc.MAKROS},
            "defaults": {m: float(calc.RICHTWERT[m]) for m in calc.MAKROS},
            "days_logged": len(tage), "reference_note": calc.RICHTWERT_QUELLE}


ANTWORTEN = {
    "/api/me": ICH,
    # Leere Liste heisst ausdruecklich 'alle an' -- ein fehlender
    # Schluessel waere die Werkseinstellung, und die laesst die
    # Naehrwerte ruhen.
    "/api/ui/prefs": {"prefs": {"ui_module_off": []}},
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
}
