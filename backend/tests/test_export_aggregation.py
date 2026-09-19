"""Tests fuer die Perioden-Zusammenfassung von Schach und Ernaehrung.

Drei Sektionen tragen in ``EXPORT_SECTIONS`` seit v1.60.0 ``aggregatable:
True``, bekamen die gewaehlte Stufe aber bis v2.6.0 gar nicht uebergeben:
"Pro Woche" liess die Datei unveraendert. Diese Tests pruefen das Gegenteil
-- dass aus Einzelzeilen wirklich Periodenzeilen werden und was dabei
zusammengezaehlt wird.

Geprueft wird ohne Datenbank: die Zusammenfassung ist eine reine Funktion
ueber Zeilen, und asyncpg-Zeilen verhalten sich beim Lesen wie dicts.
"""
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from services import full_export as fx


def _partie(tag, stunde, plattform, perf, ergebnis, diff, wertung):
    return {"played_at": datetime(tag.year, tag.month, tag.day, stunde),
            "platform": plattform, "perf": perf, "result": ergebnis,
            "rating_diff": diff, "own_rating": wertung}


def _spalten(zeilen):
    """Der Kopf einer Sektion: die erste Zeile, die kein Kommentar ist."""
    return next(z for z in zeilen if not z.startswith("#")).split(";")


def _daten(zeilen):
    kopf = _spalten(zeilen)
    start = zeilen.index(";".join(kopf)) + 1
    return [z for z in zeilen[start:] if z.strip()]


# ------------------------------------------------------------------ Schach

def test_schach_faellt_je_woche_plattform_und_disziplin_zusammen():
    rows = [
        _partie(date(2026, 9, 14), 20, "lichess", "blitz", "sieg", 8, 1800),
        _partie(date(2026, 9, 15), 20, "lichess", "blitz", "niederlage", -6, 1808),
        _partie(date(2026, 9, 16), 9, "lichess", "bullet", "remis", 3, 2000),
        _partie(date(2026, 9, 16), 9, "chesscom", "blitz", "sieg", 11, 1450),
        _partie(date(2026, 9, 23), 9, "chesscom", "blitz", "sieg", 9, 1461),
    ]
    zeilen = fx._chess_games_aggregiert(rows, "week")
    daten = _daten(zeilen)
    # Zwei Wochen, in der ersten drei Kombinationen aus Plattform und
    # Disziplin -- Bullet und Blitz duerfen NICHT in eine Zeile fallen.
    assert len(daten) == 4

    blitz = next(z for z in daten if z.startswith("2026-W38")
                 and '"Lichess";"blitz"' in z)
    felder = blitz.split(";")
    kopf = _spalten(zeilen)
    assert felder[kopf.index("Partien")] == "2"
    assert felder[kopf.index("Siege")] == "1"
    assert felder[kopf.index("Niederlagen")] == "1"
    assert felder[kopf.index("Wertung Anfang")] == "1800"
    assert felder[kopf.index("Wertung Ende")] == "1808"
    # Die Aenderung traegt ihr Vorzeichen: +8 und -6 ergeben +2.
    assert felder[kopf.index("Wertungsaenderung")] == "+2"


def test_schach_ohne_gemeldete_differenz_bleibt_die_summe_leer():
    rows = [
        _partie(date(2026, 9, 14), 20, "lichess", "blitz", "sieg", 8, 1800),
        _partie(date(2026, 9, 15), 20, "lichess", "blitz", "sieg", None, 1808),
    ]
    zeilen = fx._chess_games_aggregiert(rows, "week")
    kopf = _spalten(zeilen)
    felder = _daten(zeilen)[0].split(";")
    # Eine Summe, zu der Partien fehlen, ist keine Summe.
    assert felder[kopf.index("Wertungsaenderung")] == ""
    assert felder[kopf.index("Partien ohne Wertungsangabe")] == "1"
    # Die Wertungen selbst sagen weiter etwas.
    assert felder[kopf.index("Wertung Ende")] == "1808"


def test_schach_bleibt_ohne_stufe_eine_zeile_je_partie():
    assert fx._agg_on("none") is False
    assert fx._agg_on("auto") is False
    assert fx._agg_on("week") is True


# ---------------------------------------------------------------- Tagebuch

def test_tagebuch_zaehlt_eintraege_stufen_und_tage():
    rows = [
        {"day": date(2026, 9, 14), "level": "normal"},
        {"day": date(2026, 9, 14), "level": "viel"},
        {"day": date(2026, 9, 16), "level": "normal"},
        {"day": date(2026, 9, 23), "level": "normal"},
    ]
    zeilen = fx._diary_aggregiert(rows, "week")
    kopf = _spalten(zeilen)
    daten = _daten(zeilen)
    assert len(daten) == 2

    felder = daten[0].split(";")
    assert felder[0] == "2026-W38"
    # Drei Eintraege an zwei Tagen -- beides steht da, weil beides etwas
    # anderes beantwortet.
    assert felder[kopf.index("Tage mit Eintrag")] == "2"
    assert felder[kopf.index("Eintraege")] == "3"
    assert felder[kopf.index("normal")] == "2"
    assert felder[kopf.index("uebermaessig")] == "1"


# --------------------------------------------------------------- Naehrwerte

def _log(tag, gramm, kcal, gericht=None):
    return {"day": tag, "dish_name": gericht, "grams": gramm, "kcal": kcal,
            "protein_g": 10, "fiber_g": 5, "carbs_g": 50, "fat_g": 8}


def test_naehrwerte_summieren_und_je_tag_teilen():
    rows = [
        _log(date(2026, 9, 14), 100, 400),
        _log(date(2026, 9, 15), 200, 300),
    ]
    zeilen = fx._track_log_aggregiert(rows, "week")
    kopf = _spalten(zeilen)
    felder = _daten(zeilen)[0].split(";")
    # 400 * 100/100 + 300 * 200/100 = 400 + 600
    assert felder[kopf.index("kcal")] == "1000"
    assert felder[kopf.index("Tage mit Eintrag")] == "2"
    # Der Schnitt teilt durch die Tage MIT Eintrag.
    assert felder[kopf.index("kcal je Tag")] == "500"


def test_naehrwerte_zaehlen_eintraege_ohne_angabe_gesondert():
    rows = [
        _log(date(2026, 9, 14), 100, 400),
        _log(date(2026, 9, 14), 300, None, gericht="Wraps"),
        _log(date(2026, 9, 15), 100, None),
    ]
    zeilen = fx._track_log_aggregiert(rows, "week")
    kopf = _spalten(zeilen)
    felder = _daten(zeilen)[0].split(";")
    assert felder[kopf.index("Eintraege")] == "3"
    # Das Gericht traegt seine Naehrwerte im Rezept, der Eintrag ohne kcal gar
    # keine -- beide zaehlen als Eintrag, aber nicht in die Summe.
    assert felder[kopf.index("Eintraege ohne Naehrwerte")] == "2"
    assert felder[kopf.index("kcal")] == "400"


# ------------------------------------------------- Registry und Durchreichen

def test_die_drei_sektionen_versprechen_aggregation_und_halten_es():
    nach_key = {s["key"]: s for s in fx.EXPORT_SECTIONS}
    for key in ("chess_games", "diary_log", "track_log"):
        assert nach_key[key]["aggregatable"] is True

    # Die Sektionsfunktionen nehmen die Stufe wirklich entgegen -- genau das
    # fehlte bis v2.6.0.
    import inspect
    for fn in (fx._sec_chess_games, fx._sec_diary, fx._sec_track_log):
        assert "aggregate" in inspect.signature(fn).parameters


def test_wertungsverlauf_bleibt_bewusst_unaggregierbar():
    nach_key = {s["key"]: s for s in fx.EXPORT_SECTIONS}
    # Ein Mittelwert ueber Wertungen verschiedener Disziplinen waere eine Zahl
    # ohne Bedeutung.
    assert nach_key["chess_ratings"]["aggregatable"] is False
    assert nach_key["chess_pgn"]["aggregatable"] is False


# ------------------------------------------- Verdichtungsgrenze (v2.8.0)

def test_vor_der_grenze_wird_mindestens_monatlich_verdichtet():
    # Feiner als der Monat wird auf den Monat angehoben ...
    assert fx._mindestens_monat("none") == "month"
    assert fx._mindestens_monat("day") == "month"
    assert fx._mindestens_monat("week") == "month"
    assert fx._mindestens_monat("month") == "month"
    # ... groeber bleibt groeber: wer jahresweise exportiert, will vor der
    # Grenze keine feineren Zeilen.
    assert fx._mindestens_monat("year") == "year"


def test_nur_datierte_und_zusammenfassbare_sektionen_werden_geteilt():
    teilbar = fx._teilbare_sektionen()
    assert "chess_games" in teilbar
    assert "diary_log" in teilbar
    assert "ausgaben" in teilbar
    # Zugfolgen lassen sich nicht verdichten, Stammdaten haben kein Datum.
    assert "chess_pgn" not in teilbar
    assert "food_stock" not in teilbar
    assert "sparziel_meta" not in teilbar


def test_ein_block_ohne_zeilen_gilt_als_leer():
    leer = ["# SEKTION: Irgendwas", "Datum;Wert", ""]
    voll = ["# SEKTION: Irgendwas", "Datum;Wert", "2026-01-01;3", ""]
    assert fx._hat_daten(leer) is False
    assert fx._hat_daten(voll) is True


def test_der_vorspann_nennt_die_grenze():
    user = {"username": "test"}
    kopf = fx._export_header(user, fx.ALL_SECTION_KEYS, None, None,
                             {g["key"]: "none" for g in fx.EXPORT_GROUPS},
                             None, date(2026, 8, 1))
    assert any("2026-08-01" in z and "Verdichtet" in z for z in kopf)
    # Ohne Grenze steht die Zeile nicht da.
    ohne = fx._export_header(user, fx.ALL_SECTION_KEYS, None, None,
                             {g["key"]: "none" for g in fx.EXPORT_GROUPS})
    assert not any("Verdichtet" in z for z in ohne)


# ------------------------------------------ Voreinstellung (v2.8.0)

def test_export_voreinstellung_nimmt_nur_bekannte_gruppen_und_stufen():
    from routers.ui_router import _check_export
    wert = _check_export({"aggregate": {"schach": "week", "erfunden": "week",
                                        "musik": "quatsch"},
                          "compact_before": "2026-08-01"})
    assert wert["aggregate"] == {"schach": "week"}
    assert wert["compact_before"] == "2026-08-01"


def test_export_voreinstellung_weist_ein_kaputtes_datum_zurueck():
    import pytest
    from routers.ui_router import _check_export
    # Eine stillschweigend verworfene Grenze saehe am Ergebnis genauso aus
    # wie eine, die es nie gab.
    with pytest.raises(ValueError):
        _check_export({"compact_before": "August 2026"})
    assert _check_export({"compact_before": ""})["compact_before"] is None
