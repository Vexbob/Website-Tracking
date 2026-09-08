"""Tests fuer das Musik-Modul und den dynamischen Export.

Geprueft wird das, was ohne Datenbank pruefbar ist: das Deuten der CSV
(Perioden, Bloecke, Zahlen, Gruppierung) und die beiden neuen
Export-Faehigkeiten (Aggregationsstufen, Spaltenauswahl). Die
DB-Operationen -- Zeitraum ersetzen, Zeilen schreiben -- haengen an asyncpg
und gehoeren in einen Integrationstest gegen eine echte Postgres-Instanz.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from services import music_ingest as mi
from services import full_export as fx


# ---------------------------------------------------------------- Perioden

def test_period_week_becomes_monday_to_sunday():
    grain, key, start, end = mi.parse_period("2026-KW01")
    assert (grain, key) == ("woche", "2026-KW01")
    assert (start, end) == (date(2025, 12, 29), date(2026, 1, 4))


def test_period_week_key_is_padded():
    """2026-KW1 und 2026-KW01 sind dieselbe Woche -- sonst stuende sie
    zweimal im Register."""
    assert mi.parse_period("2026-KW1")[1] == "2026-KW01"
    assert mi.parse_period("2026-W01")[1] == "2026-KW01"


def test_period_month_year_day():
    assert mi.parse_period("2026-09")[0] == "monat"
    assert mi.parse_period("2026-09")[3] == date(2026, 9, 30)
    assert mi.parse_period("2016")[2:] == (date(2016, 1, 1), date(2016, 12, 31))
    assert mi.parse_period("2026-09-08")[0] == "tag"


def test_period_rejects_nonsense():
    for bad in ("", "Gesamt", "2026-13", "2026-KW99", "irgendwas"):
        assert mi.parse_period(bad) is None


def test_block_range_from_label():
    assert mi.parse_block_range("2016-01-01 bis 2019-12-31 · monatlich") == \
        (date(2016, 1, 1), date(2019, 12, 31))
    # Offene Enden: der Zeitraum kommt dann aus den Zeilen selbst.
    assert mi.parse_block_range("Anfang bis heute · wöchentlich") == (None, None)
    assert mi.parse_block_range("ohne Zeitangabe") == (None, None)


# ------------------------------------------------------------------ Zahlen

@pytest.mark.parametrize("text,expected", [
    ("6", 6.0), ("3,5", 3.5), ("1.234", 1234.0), ("1.234,5", 1234.5),
    ("1,234.5", 1234.5), ("", None), ("keine Zahl", None),
])
def test_number_formats(text, expected):
    assert mi._num(text) == expected


# -------------------------------------------------------------------- Plan

HEADER = "Block;Periode;Interpret;Titel;Wiedergaben"


def _csv(*rows: str) -> bytes:
    return ("\n".join([HEADER, *rows]) + "\n").encode("utf-8")


def test_plan_reads_rows_and_blocks():
    plan = mi.build_plan(_csv(
        "Anfang bis heute · wöchentlich · nach Titel;2026-KW01;Marsimoto;Illegalize It;5",
        "Anfang bis heute · wöchentlich · nach Titel;2025-KW52;Peter Fox;Das zweite Gesicht;4",
    ), "probe.csv")
    assert plan["rows_written"] == 2
    assert len(plan["blocks"]) == 1
    block = plan["blocks"][0]
    assert block["grains"] == ["woche"]
    assert block["plays"] == 9
    # Offener Block: der Zeitraum kommt aus den Zeilen.
    assert block["replace_from"] == date(2025, 12, 22)
    assert block["replace_to"] == date(2026, 1, 4)


def test_plan_uses_declared_range_even_when_wider_than_the_data():
    """Ein Block ueber 2016-2019 raeumt 2016 auch dann leer, wenn dort keine
    Zeile steht -- gehoert hat man in dem Jahr eben nichts."""
    plan = mi.build_plan(_csv(
        "2016-01-01 bis 2019-12-31 · monatlich · nach Titel;2019-03;Clueso;Keinen Zentimeter;3",
    ))
    block = plan["blocks"][0]
    assert block["replace_from"] == date(2016, 1, 1)
    assert block["replace_to"] == date(2019, 12, 31)


def test_plan_separates_blocks():
    plan = mi.build_plan(_csv(
        "2016-01-01 bis 2019-12-31 · monatlich · nach Titel;2019-03;Clueso;Keinen Zentimeter;3",
        "2020-01-01 bis heute · wöchentlich · nach Titel;2026-KW01;Marsimoto;Illegalize It;5",
    ))
    assert [b["replace_from"] for b in plan["blocks"]] == [date(2016, 1, 1), date(2020, 1, 1)]


def test_rows_without_period_are_skipped_not_fatal():
    plan = mi.build_plan(_csv(
        "ohne Zeitraster · nach Titel;;Marsimoto;Illegalize It;5",
        "Anfang bis heute · wöchentlich · nach Titel;2026-KW01;Peter Fox;Haus am See;4",
    ))
    assert plan["rows_written"] == 1
    assert plan["rows_skipped"] == 1


def test_file_without_any_period_is_rejected_with_advice():
    with pytest.raises(mi.MusicImportError) as err:
        mi.build_plan(_csv("ohne Zeitraster · nach Titel;;Marsimoto;Illegalize It;5"))
    assert "Zeitraster" in str(err.value)


def test_group_is_read_from_the_filled_columns():
    plan = mi.build_plan(_csv(
        "B;2026-01;Clueso;;12",             # nur Interpret -> Interpreten-Zeile
        "B;2026-01;Clueso;Cello;7",         # mit Titel     -> Titel-Zeile
    ))
    assert [e["group_by"] for e in plan["entries"]] == ["interpret", "titel"]


def test_tab_and_bom_and_umlauts_survive():
    raw = ("﻿" + "Block\tPeriode\tInterpret\tTitel\tWiedergaben\n"
           "B\t2026-KW01\tGoran Bregović\tGas Gas\t4\n").encode("utf-8")
    plan = mi.build_plan(raw)
    assert plan["entries"][0]["artist"] == "Goran Bregović"


def test_minutes_column_becomes_milliseconds():
    raw = ("Block;Periode;Interpret;Titel;Wiedergaben;Minuten\n"
           "B;2026-KW01;Marsimoto;Illegalize It;5;12,5\n").encode("utf-8")
    assert mi.build_plan(raw)["entries"][0]["ms_played"] == 750000


def test_raw_export_is_condensed_into_register_rows():
    """Die Rohansicht (eine Zeile = eine Wiedergabe) hat keine Spalte
    'Wiedergaben' -- sie wird beim Import verdichtet."""
    raw = ("Zeitpunkt;Art;Titel;Interpret;Minuten\n"
           "2026-01-02 10:00:00;Musik;Illegalize It;Marsimoto;3\n"
           "2026-01-02 11:00:00;Musik;Illegalize It;Marsimoto;3\n").encode("utf-8")
    plan = mi.build_plan(raw)
    assert plan["aggregated"] is False
    assert len(plan["entries"]) == 1
    assert plan["entries"][0]["plays"] == 2
    assert plan["entries"][0]["grain"] == "tag"


def test_unknown_header_is_a_clear_error():
    with pytest.raises(mi.MusicImportError):
        mi.build_plan(b"a;b;c\n1;2;3\n")


# ------------------------------------------------------ Export: Aggregation

def test_new_aggregation_levels_exist():
    assert fx.AGG_KEYS == ["none", "auto", "day", "week", "month", "year"]
    assert fx._period_key(date(2026, 9, 8), "day") == "2026-09-08"
    assert fx._period_key(date(2026, 9, 8), "year") == "2026"
    assert fx._period_key(date(2026, 9, 8), "week") == "2026-W37"


def test_period_words_never_produce_woches():
    assert fx._period_prefix("week") == "Wochen"
    assert fx._period_prefix("year") == "Jahres"
    assert fx._period_adverb("day") == "tageweise"


def test_auto_picks_by_span_and_falls_back_to_year():
    assert fx.resolve_auto(date(2026, 1, 1), date(2026, 2, 1)) == "day"
    assert fx.resolve_auto(date(2024, 1, 1), date(2026, 1, 1)) == "week"
    assert fx.resolve_auto(date(2020, 1, 1), date(2026, 1, 1)) == "month"
    assert fx.resolve_auto(date(2010, 1, 1), date(2026, 1, 1)) == "year"
    # Offener Zeitraum: bei zehn Jahren Historie ist alles ausser Jahr unlesbar.
    assert fx.resolve_auto(None, None) == "year"


def test_aggregate_map_resolves_auto_and_keeps_old_calls_valid():
    m = fx.clean_aggregate_map({"musik": "auto"}, "none",
                               date(2010, 1, 1), date(2026, 1, 1))
    assert m["musik"] == "year"
    assert m["ausgaben"] == "none"
    # Der alte Aufruf mit nur ``aggregate`` gilt weiter fuer alle Gruppen.
    assert set(fx.clean_aggregate_map(None, "month").values()) == {"month"}


def test_music_group_and_sections_are_registered():
    assert any(g["key"] == "musik" for g in fx.EXPORT_GROUPS)
    keys = [s["key"] for s in fx.EXPORT_SECTIONS]
    assert "music_register" in keys and "music_imports" in keys


# --------------------------------------------------- Export: Spaltenauswahl

SECTION = [
    "# SEKTION: Musik - Hoerregister",
    "Periode;Interpret;Titel;Wiedergaben",
    "2026-KW01;Marsimoto;Illegalize It;5",
    "",
]


def test_columns_are_read_from_the_built_lines():
    assert fx._section_columns(SECTION) == ["Periode", "Interpret", "Titel", "Wiedergaben"]


def test_column_filter_keeps_the_chosen_ones_in_file_order():
    out = fx._filter_columns(SECTION, {"Titel", "Periode"})
    assert out[1] == "Periode;Titel"
    assert out[2] == "2026-KW01;Illegalize It"


def test_column_filter_leaves_a_block_alone_when_nothing_matches():
    """Zwei Tabellen in einer Sektion (Bons + Positionen): eine Auswahl fuer
    die eine darf die andere nicht auf null Spalten schrumpfen."""
    two = SECTION + [
        "# SEKTION: Musik - Protokoll",
        "Hochgeladen;Datei",
        "2026-09-08T10:00:00Z;export.csv",
        "",
    ]
    out = fx._filter_columns(two, {"Titel"})
    assert out[1] == "Titel"
    assert out[5] == "Hochgeladen;Datei"
    assert out[6] == "2026-09-08T10:00:00Z;export.csv"


def test_empty_column_choice_means_everything():
    assert fx._filter_columns(SECTION, None) == SECTION
    assert fx.clean_column_map({"music_register": []}) == {}
    assert fx.clean_column_map({"gibtsnicht": ["Titel"]}) == {}
