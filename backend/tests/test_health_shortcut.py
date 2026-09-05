"""Tests fuer den Parser der Kurzbefehl-Beta-Strecke (v1.47.0).

Kein Postgres notwendig -- getestet wird ausschliesslich die Logik zwischen
Rohbody und dem fertigen Zeilen-Dict. Genau dort liegt das Risiko: der
Kurzbefehl, der diesen Endpoint beliefert, existiert beim Schreiben dieser
Tests noch nicht, sein Ausgabeformat ist eine Annahme.

Schwerpunkte:
- jedes akzeptierte Body-Format wird erkannt
- jeder Skip-Grund ist erreichbar und heisst wie dokumentiert
- ein kaputter Punkt reisst die uebrigen nicht mit
- ein blankes Datum wird NICHT durch eine Zeitzone gedreht, ein Zeitstempel schon
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import json  # noqa: E402
from datetime import date, datetime, timezone  # noqa: E402

import pytest  # noqa: E402

from services.health_shortcut import (  # noqa: E402
    build_summary, cap, extract_points, normalize_metric_key, normalize_point,
    parse_number, parse_when, to_bucket,
)

try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover - Windows ohne tzdata
    BERLIN = None

needs_tz = pytest.mark.skipif(BERLIN is None, reason="IANA-Zeitzonendaten nicht verfuegbar")
UTC = timezone.utc


def _b(s: str) -> bytes:
    return s.encode("utf-8")


# ---------------------------------------------------------------------------
# Format-Erkennung
# ---------------------------------------------------------------------------
def test_canonical_json():
    body = _b(json.dumps({"metrics": [
        {"metric": "steps", "date": "2026-09-03", "value": 7120, "unit": "count"},
        {"metric": "steps", "date": "2026-09-04", "value": 9033},
    ]}))
    fmt, points, skipped = extract_points(body)
    assert fmt == "json"
    assert len(points) == 2
    assert skipped == []


def test_bare_json_array():
    body = _b('[{"metric": "steps", "date": "2026-09-03", "value": 7120}]')
    fmt, points, _ = extract_points(body)
    assert fmt == "json-array"
    assert len(points) == 1


def test_single_json_object():
    body = _b('{"metric": "steps", "date": "2026-09-03", "value": 7120}')
    fmt, points, _ = extract_points(body)
    assert fmt == "json-single"
    assert len(points) == 1


def test_auto_health_export_shape_is_accepted():
    """Die HAE-Struktur wird mitgelesen, damit die Strecke spaeter kompatibel
    umgeschaltet werden kann, ohne den Parser anzufassen."""
    body = _b(json.dumps({"data": {"metrics": [
        {"name": "step_count", "units": "count",
         "data": [{"date": "2026-09-03 00:00:00 +0200", "qty": 7120},
                  {"date": "2026-09-04 00:00:00 +0200", "qty": 9033}]},
    ]}}))
    fmt, points, _ = extract_points(body)
    assert fmt == "json-hae"
    assert len(points) == 2
    # Name und Einheit des Blocks landen in jedem einzelnen Punkt.
    assert points[0]["metric"] == "step_count"
    assert points[0]["unit"] == "count"
    assert points[0]["qty"] == 7120

    norm, skip, _ = normalize_point(points[0], None, UTC)
    assert skip is None
    assert norm["metric_key"] == "steps"      # ueber den Alias aufgeloest
    assert norm["value"] == 7120.0


def test_text_lines_four_and_three_columns():
    fmt, points, skipped = extract_points(
        _b("2026-09-03;steps;7120;count\n2026-09-04;steps;9033\n"))
    assert fmt == "text"
    assert skipped == []
    assert points[0]["unit"] == "count"
    assert "unit" not in points[1]


def test_text_lines_two_columns_need_default_metric():
    """Die kleinstmoegliche erste Version im Kurzbefehl: nur Datum und Wert,
    die Metrik kommt als ?metric=steps an der URL."""
    fmt, points, _ = extract_points(_b("2026-09-05;8421"), default_metric="steps")
    assert fmt == "text"
    norm, skip, _ = normalize_point(points[0], "steps", UTC)
    assert skip is None
    assert norm["metric_key"] == "steps"
    assert norm["value"] == 8421.0

    # ...ohne default_metric ist genau dieselbe Zeile ein benannter Skip.
    _, points2, _ = extract_points(_b("2026-09-05;8421"))
    _, skip2, _ = normalize_point(points2[0], None, UTC)
    assert skip2["reason"] == "no_metric"


def test_text_accepts_comma_and_tab_and_ignores_comments():
    _, points, _ = extract_points(_b("# Kommentar\n2026-09-03,steps,7120\n\n"
                                     "2026-09-04\tsteps\t9033\n"))
    assert len(points) == 2


# ---------------------------------------------------------------------------
# CSV mit Kopfzeile
# ---------------------------------------------------------------------------
def test_csv_long_format():
    fmt, points, skipped = extract_points(_b(
        "Datum;Metrik;Wert;Einheit\n"
        "2026-09-03;steps;7120;count\n"
        "2026-09-04;steps;9033;count\n"))
    assert fmt == "csv"
    assert skipped == []
    assert len(points) == 2
    norm, skip, _ = normalize_point(points[0], None, UTC)
    assert skip is None
    assert (norm["metric_key"], norm["value"], norm["unit"]) == ("steps", 7120.0, "count")


def test_csv_column_order_does_not_matter():
    """Die Kopfzeile sagt, welche Spalte was ist -- nicht die Position."""
    _, points, _ = extract_points(_b("Wert;Datum;Metrik\n8421;2026-09-05;steps\n"))
    norm, skip, _ = normalize_point(points[0], None, UTC)
    assert skip is None
    assert norm["value"] == 8421.0
    assert norm["sample_date"] == date(2026, 9, 5)


def test_csv_narrow_uses_default_metric():
    """Datum;Wert ohne Metrikspalte -- die Metrik kommt aus ?metric=steps.
    Ohne diese Sonderbehandlung wuerde "Wert" als Metrikname gelesen."""
    fmt, points, _ = extract_points(_b("Datum;Wert\n2026-09-05;8421\n"),
                                    default_metric="steps")
    assert fmt == "csv"
    norm, skip, _ = normalize_point(points[0], "steps", UTC)
    assert skip is None
    assert norm["metric_key"] == "steps"
    assert norm["value"] == 8421.0


def test_csv_wide_one_column_per_metric():
    fmt, points, _ = extract_points(_b(
        "Datum;Schritte;Aktive Energie\n"
        "2026-09-03;7120;512\n"
        "2026-09-04;9033;603\n"))
    assert fmt == "csv"
    assert len(points) == 4
    got = []
    for p in points:
        norm, skip, _ = normalize_point(p, None, UTC)
        assert skip is None
        got.append((norm["sample_date"].isoformat(), norm["metric_key"], norm["value"]))
    assert got == [("2026-09-03", "steps", 7120.0),
                   ("2026-09-03", "aktive_energie", 512.0),
                   ("2026-09-04", "steps", 9033.0),
                   ("2026-09-04", "aktive_energie", 603.0)]


def test_csv_wide_reads_unit_from_the_header():
    """Auto Health Export beschriftet seine Tages-CSV genau so."""
    _, points, _ = extract_points(_b("Datum;Schritte (count)\n2026-09-05;8421\n"))
    norm, _, _ = normalize_point(points[0], None, UTC)
    assert norm["unit"] == "count"


def test_csv_wide_skips_empty_cells_without_complaining():
    """Ein Tag ohne Wert in einer Spalte ist kein Fehler, sondern eine Luecke."""
    _, points, skipped = extract_points(_b(
        "Datum;Schritte;Aktive Energie\n2026-09-05;8421;\n"))
    assert skipped == []
    assert len(points) == 1


def test_header_detection_does_not_swallow_a_data_row():
    """Faengt die erste Zeile mit einem Datum an, ist sie Daten -- egal wie die
    uebrigen Spalten heissen."""
    fmt, points, _ = extract_points(_b("2026-09-03;steps;7120\n2026-09-04;steps;9033\n"))
    assert fmt == "text"
    assert len(points) == 2


def test_unrecognisable_first_line_is_not_treated_as_a_header():
    """Eine Zeile aus lauter Unbekanntem darf nicht still als Kopfzeile
    verschwinden -- sie soll als benannter Skip auffallen."""
    fmt, points, skipped = extract_points(_b("blah;bloed;quatsch\n"))
    assert fmt == "text"
    _, skip, _ = normalize_point(points[0], None, UTC)
    assert skip["reason"] == "bad_date"


def test_csv_accepts_comma_separator_and_bom():
    fmt, points, _ = extract_points(
        "Datum,Schritte\n2026-09-05,8421\n".encode("utf-8-sig"))
    assert fmt == "csv"
    norm, skip, _ = normalize_point(points[0], None, UTC)
    assert skip is None
    assert norm["metric_key"] == "steps"


def test_empty_and_unreadable_bodies():
    assert extract_points(b"")[0] == "empty"
    assert extract_points(b"   ")[0] == "empty"

    fmt, points, skipped = extract_points(_b('{"metrics": [oops}'))
    assert fmt == "unreadable"
    assert points == []
    assert skipped[0]["reason"] == "bad_json"

    fmt, _, skipped = extract_points(_b('{"foo": "bar"}'))
    assert fmt == "unreadable"
    assert skipped[0]["reason"] == "no_points_in_json"


# ---------------------------------------------------------------------------
# Metriknamen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw", ["steps", "Steps", " step_count ", "Schritte",
                                 "step count", "STEPCOUNT"])
def test_known_metric_aliases_map_to_steps(raw):
    assert normalize_metric_key(raw) == "steps"


def test_unknown_metric_is_kept_not_dropped():
    """Kernanforderung: eine neue Metrik funktioniert an dem Tag, an dem der
    Kurzbefehl sie zum ersten Mal schickt -- ohne Codeaenderung."""
    assert normalize_metric_key("Active Energy") == "active_energy"
    norm, skip, warnings = normalize_point(
        {"metric": "Active Energy", "date": "2026-09-05", "value": 512}, None, UTC)
    assert skip is None
    assert norm["metric_key"] == "active_energy"
    assert norm["known"] is False
    assert norm["bucket"] == "day"
    # ...faellt aber in der Antwort auf, statt still zu passieren.
    assert any("active_energy" in w for w in warnings)


def test_junk_metric_name_is_skipped_with_reason():
    _, skip, _ = normalize_point({"metric": "***", "date": "2026-09-05", "value": 1},
                                 None, UTC)
    assert skip["reason"] == "bad_metric_key"


# ---------------------------------------------------------------------------
# Zahlen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    (8421, 8421.0),
    (8421.0, 8421.0),
    ("8421", 8421.0),
    ("8.421", 8421.0),          # deutsche Tausendertrennung
    ("1.234.567", 1234567.0),
    ("8 421", 8421.0),
    ("8 421", 8421.0),     # geschuetztes Leerzeichen aus Kurzbefehle
    ("8421 Schritte", 8421.0),
    ("70,5", 70.5),
])
def test_parse_number_variants(raw, expected):
    value, _ = parse_number(raw)
    assert value == expected


def test_parse_number_flags_its_guesses():
    """Wenn der Parser raet, muss das in der Antwort stehen."""
    _, note = parse_number("8.421")
    assert note and "Tausendertrennzeichen" in note
    _, note = parse_number("8421")
    assert note is None


@pytest.mark.parametrize("raw", [None, "", "abc", True, float("nan")])
def test_parse_number_rejects_junk(raw):
    assert parse_number(raw)[0] is None


# ---------------------------------------------------------------------------
# Zeitangaben
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("2026-09-05", date(2026, 9, 5)),
    ("2026-9-5", date(2026, 9, 5)),
    ("2026/09/05", date(2026, 9, 5)),
    ("05.09.2026", date(2026, 9, 5)),
])
def test_plain_dates_stay_dates(raw, expected):
    kind, when = parse_when(raw, UTC)
    assert kind == "date"
    assert when == expected


@pytest.mark.parametrize("raw", [
    "2026-09-05T12:30:00+02:00",
    "2026-09-05 12:30:00 +0200",
    "2026-09-05T10:30:00Z",
    "2026-09-05 12:30:00",
    "05.09.2026, 12:30",
    "1757068200",              # Epoch-Sekunden
    "1757068200000",           # Epoch-Millisekunden
])
def test_timestamp_variants_parse(raw):
    kind, when = parse_when(raw, UTC)
    assert kind == "datetime"
    assert when.tzinfo is not None


def test_bad_date_is_skipped_with_reason():
    assert parse_when("gestern", UTC) == (None, None)
    _, skip, _ = normalize_point({"metric": "steps", "date": "gestern", "value": 1},
                                 None, UTC)
    assert skip["reason"] == "bad_date"
    assert skip["detail"] == "gestern"


def test_plain_date_ignores_timezone():
    """Ein blankes Datum meint den Tag, egal wo der Server steht -- sonst
    landete der 5. September je nach Zone am 4. oder 6."""
    for tz in (UTC, BERLIN or UTC):
        norm, skip, _ = normalize_point(
            {"metric": "steps", "date": "2026-09-05", "value": 8421}, None, tz)
        assert skip is None
        assert norm["sample_date"] == date(2026, 9, 5)


@needs_tz
def test_timestamp_is_bucketed_in_local_day():
    """23:30 UTC ist in Berlin schon der naechste Tag -- der Wert gehoert
    dorthin, sonst waere die Tageszuordnung um einen Tag verschoben."""
    norm, skip, _ = normalize_point(
        {"metric": "steps", "date": "2026-09-05T23:30:00+00:00", "value": 8421},
        None, BERLIN)
    assert skip is None
    assert norm["sample_date"] == date(2026, 9, 6)
    assert norm["bucket"] == "day"
    # Tageswerte rasten auf Mitternacht ein -- damit ueberschreibt ein zweiter
    # Lauf desselben Tages, egal zu welcher Uhrzeit er lief.
    assert norm["bucket_start"].astimezone(BERLIN).hour == 0


@needs_tz
def test_same_day_different_times_share_one_bucket():
    """Der Kern der Duplikat-Freiheit: zwei Laeufe am selben Tag erzeugen
    denselben Unique-Schluessel und ueberschreiben sich damit."""
    a, _, _ = normalize_point(
        {"metric": "steps", "date": "2026-09-05T08:00:00+02:00", "value": 3000},
        None, BERLIN)
    b, _, _ = normalize_point(
        {"metric": "steps", "date": "2026-09-05T22:00:00+02:00", "value": 8421},
        None, BERLIN)
    key = ("metric_key", "bucket", "bucket_start")
    assert tuple(a[k] for k in key) == tuple(b[k] for k in key)
    assert a["value"] != b["value"]


def test_point_bucket_keeps_the_real_timestamp():
    """Vorbereitung fuer spaetere Metriken mit mehreren Werten pro Tag: mit
    bucket='point' ist der Zeitstempel selbst der Schluessel."""
    when = datetime(2026, 9, 5, 12, 30, tzinfo=UTC)
    day, start = to_bucket("datetime", when, "point", UTC)
    assert day == date(2026, 9, 5)
    assert start == when


# ---------------------------------------------------------------------------
# Skip-Gruende & Toleranz
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("point,reason", [
    ({"date": "2026-09-05", "value": 1}, "no_metric"),
    ({"metric": "steps", "value": 1}, "no_date"),
    ({"metric": "steps", "date": "2026-09-05"}, "no_value"),
    ({"metric": "steps", "date": "2026-09-05", "value": "keine Ahnung"}, "bad_value"),
    ({"metric": "steps", "date": "irgendwann", "value": 1}, "bad_date"),
    ({"metric": "!!!", "date": "2026-09-05", "value": 1}, "bad_metric_key"),
])
def test_every_documented_skip_reason_is_reachable(point, reason):
    norm, skip, _ = normalize_point(point, None, UTC)
    assert norm is None
    assert skip["reason"] == reason
    # Der Rohpunkt haengt am Skip, damit im Kurzbefehl sichtbar ist, WAS
    # uebersprungen wurde -- nicht nur, dass etwas uebersprungen wurde.
    assert skip["raw"]


def test_non_object_point_is_skipped():
    _, skip, _ = normalize_point("nur ein String", None, UTC)
    assert skip["reason"] == "not_an_object"


def test_one_broken_point_does_not_take_the_others_down():
    """Die zentrale Toleranz-Anforderung."""
    body = _b(json.dumps({"metrics": [
        {"metric": "steps", "date": "2026-09-03", "value": 7120},
        {"metric": "steps", "date": "gestern", "value": 9033},
        {"metric": "steps", "date": "2026-09-05", "value": 4210},
    ]}))
    _, points, skipped = extract_points(body)
    ok = []
    for p in points:
        norm, skip, _ = normalize_point(p, None, UTC)
        (skipped if skip else ok).append(skip or norm)
    assert len(ok) == 2
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "bad_date"


def test_field_aliases_are_interchangeable():
    variants = [
        {"metric": "steps", "date": "2026-09-05", "value": 8421},
        {"name": "steps", "day": "2026-09-05", "qty": 8421},
        {"key": "steps", "timestamp": "2026-09-05", "amount": 8421},
        {"type": "steps", "recorded_at": "2026-09-05", "wert": 8421},
    ]
    for v in variants:
        norm, skip, _ = normalize_point(v, None, UTC)
        assert skip is None, v
        assert norm["metric_key"] == "steps"
        assert norm["value"] == 8421.0
        assert norm["sample_date"] == date(2026, 9, 5)


def test_unit_falls_back_to_the_registry():
    norm, _, _ = normalize_point({"metric": "steps", "date": "2026-09-05", "value": 1},
                                 None, UTC)
    assert norm["unit"] == "count"
    norm, _, _ = normalize_point(
        {"metric": "steps", "date": "2026-09-05", "value": 1, "unit": "Schritte"},
        None, UTC)
    assert norm["unit"] == "Schritte"


def test_raw_date_is_preserved_verbatim():
    """Damit sich ein falsch einsortierter Tag dem Kurzbefehl oder dem Parser
    zuordnen laesst."""
    norm, _, _ = normalize_point(
        {"metric": "steps", "date": "05.09.2026, 23:50", "value": 1}, None, UTC)
    assert norm["raw_date"] == "05.09.2026, 23:50"


# ---------------------------------------------------------------------------
# Antwort
# ---------------------------------------------------------------------------
def test_summary_counts_new_and_overwritten_separately():
    accepted = [{"action": "inserted"}, {"action": "updated"}, {"action": "updated"}]
    s = build_summary(accepted, [{"reason": "bad_date"}], "json")
    assert "4 Punkte" in s
    assert "1 neu" in s
    assert "2 überschrieben" in s
    assert "1 übersprungen" in s


def test_summary_uses_singular_for_one_point():
    """Steht taeglich als Mitteilung auf dem Sperrbildschirm -- "1 Punkte"
    waere jeden Tag zu sehen."""
    s = build_summary([{"action": "inserted"}], [], "json")
    assert s.startswith("1 Punkt ·"), s


def test_summary_names_the_empty_and_unreadable_cases():
    assert "Leerer Body" in build_summary([], [], "empty")
    assert "nicht lesbar" in build_summary([], [{"reason": "bad_json"}], "unreadable")


def test_cap_reports_that_it_truncated():
    capped = cap([{"reason": "x"}] * 30, 25)
    assert len(capped) == 26
    assert "5 weitere" in capped[-1]["raw"]
