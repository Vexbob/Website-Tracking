"""Health-Shortcut-Service — Parser der Beta-Strecke "Apple Health per iPhone-Kurzbefehl".

Getrennt von ``services/health_ingest.py`` (Auto Health Export), weil beide
Strecken parallel laufen und sich nicht stoeren duerfen. Dieser Parser ist
bewusst deutlich toleranter: der Kurzbefehl, der ihn beliefert, ist ein
Versuch mit noch unbekanntem Ausgabeformat.

Leitlinien:
  * Ein kaputter Punkt kippt nie den ganzen Batch -- er landet mit einem
    benannten Grund in ``skipped``.
  * Jede Entscheidung, die der Parser rateweise trifft (Tausendertrennzeichen,
    unbekannte Metrik), taucht als Klartext in ``warnings`` auf, statt still zu
    passieren.
  * Nichts wird verworfen, nur weil es unbekannt ist. Eine neue Metrik
    funktioniert an dem Tag, an dem der Kurzbefehl sie zum ersten Mal schickt;
    ``SHORTCUT_METRICS`` liefert nur Label, Default-Einheit und Bucket-Art.

Akzeptierte Body-Formate (siehe ``extract_points``):
  1. Kanonisch   {"metrics": [{"metric": "steps", "date": "2026-09-05",
                               "value": 8421, "unit": "count"}, ...]}
  2. Blanke Liste  [{"metric": ..., "date": ..., "value": ...}, ...]
  3. Einzelobjekt  {"metric": ..., "date": ..., "value": ...}
  4. Auto-Health-Export-Struktur
                 {"data": {"metrics": [{"name": "step_count", "units": "count",
                                        "data": [{"date": ..., "qty": ...}]}]}}
     -- mitgenommen, damit die Strecke spaeter kompatibel umgeschaltet werden
     kann, ohne den Parser anzufassen.
  5. Textzeilen  "2026-09-05;steps;8421;count" (Trenner ; , oder Tab)
  6. Zweispaltig "2026-09-05;8421" zusammen mit ``?metric=steps`` an der URL --
     die kleinstmoegliche erste Version im Kurzbefehl.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import date, datetime, time, timezone
from typing import Any, Optional

logger = logging.getLogger("vexbob.health_shortcut")

# Eigener Source-Wert. Bewusst NICHT 'auto_health_export': die beiden Strecken
# duerfen sich gegenseitig nicht ueberschreiben.
SHORTCUT_SOURCE = "ios_shortcut"

DEFAULT_TZ_NAME = "Europe/Berlin"

# Schutzgrenzen. Der Kurzbefehl schickt drei Punkte am Tag; alles jenseits
# dieser Groessenordnung ist ein Versehen (versehentlicher Voll-Export) und
# soll nicht die halbe Datenbank fuellen.
MAX_POINTS = 2000
# Die Antwort wird auf dem iPhone gelesen -- lange Listen sind dort nutzlos.
MAX_REPORT_ITEMS = 25


# ---------------------------------------------------------------------------
# Metrik-Registry
# ---------------------------------------------------------------------------
# Eine neue Metrik dazuzunehmen ist EIN Eintrag hier -- mehr nicht. Weder
# Migration noch Endpoint noch Frontend muessen angefasst werden. Die Registry
# entscheidet nicht, OB ein Wert gespeichert wird (das tut sie ausdruecklich
# nicht, siehe ``normalize_metric_key``), sondern nur, wie er heisst, welche
# Einheit er bekommt, wenn der Kurzbefehl keine mitschickt, und ob er ein
# Tagesaggregat ist.
#
#   bucket 'day'   -> ein Wert je Tag, Wiederholung ueberschreibt
#   bucket 'point' -> mehrere Werte je Tag moeglich, der Zeitstempel ist der
#                     Schluessel
SHORTCUT_METRICS: dict[str, dict] = {
    "steps": {
        "label": "Schritte",
        "aliases": ("step_count", "stepcount", "schritte", "step count", "steps_count"),
        "unit": "count",
        "bucket": "day",
    },
}

# alias -> kanonischer Key. Der kanonische Key zeigt auf sich selbst.
_ALIAS_TO_KEY: dict[str, str] = {}
for _key, _meta in SHORTCUT_METRICS.items():
    _ALIAS_TO_KEY[_key] = _key
    for _alias in _meta.get("aliases", ()):
        _ALIAS_TO_KEY[_alias.lower().strip()] = _key

# Nach der Normalisierung muss ein Key so aussehen. Verhindert, dass ein
# verrutschtes Feld ("Schritte gestern, gemessen von der Uhr") als Metrikname
# in der Tabelle landet.
METRIC_KEY_RE = re.compile(r"^[a-z0-9_]{1,60}$")

# Feld-Aliase. Der Kurzbefehl darf jede dieser Schreibweisen benutzen; welche
# es am Ende wird, entscheidet sich erst beim Bauen des Kurzbefehls.
_METRIC_FIELDS = ("metric", "metric_key", "name", "key", "type", "metrik")
_DATE_FIELDS = ("date", "day", "datum", "timestamp", "time", "start",
                "recorded_at", "start_date", "sample_date")
_VALUE_FIELDS = ("value", "qty", "quantity", "amount", "sum", "wert", "count")
_UNIT_FIELDS = ("unit", "units", "einheit")
# Felder, an denen ein verschachtelter Metrik-Block (Auto-Health-Export-Stil)
# erkannt wird.
_NESTED_FIELDS = ("data", "points", "samples", "values")


def local_tz():
    """Zeitzone, in der ein Tag beginnt und endet.

    Relevant nur fuer Punkte, die einen vollen Zeitstempel mitbringen -- ein
    blankes ``2026-09-05`` wird woertlich genommen und braucht keine Zone.
    Faellt auf UTC zurueck, wenn die IANA-Datenbank fehlt (Windows ohne
    ``tzdata``); das ist dann eine laute Warnung im Log und kein stiller
    Tagesversatz, weil der empfohlene Weg ohnehin das blanke Datum ist.
    """
    name = (os.getenv("HEALTH_SHORTCUT_TZ") or DEFAULT_TZ_NAME).strip() or DEFAULT_TZ_NAME
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception as e:
        logger.warning("Zeitzone %r nicht ladbar (%s) -- benutze UTC", name, e)
        return timezone.utc


def metric_label(metric_key: str) -> str:
    meta = SHORTCUT_METRICS.get(metric_key)
    return meta["label"] if meta else metric_key


# ---------------------------------------------------------------------------
# Feld-Parser
# ---------------------------------------------------------------------------
def _first_field(d: dict, fields: tuple) -> tuple[Optional[str], Any]:
    """Erstes vorhandenes Feld aus ``fields`` (case-insensitiv). Gibt
    (gefundener_feldname, wert) zurueck, sonst (None, None)."""
    lower = {str(k).lower().strip(): k for k in d.keys()}
    for f in fields:
        orig = lower.get(f)
        if orig is None:
            continue
        v = d[orig]
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return str(orig), v
    return None, None


def normalize_metric_key(raw: Any) -> Optional[str]:
    """Metrikname -> kanonischer Key. Gibt None zurueck, wenn nichts Brauchbares
    uebrig bleibt; der Aufrufer entscheidet dann ueber den Skip-Grund.

    Unbekannte Namen werden NICHT verworfen -- sie werden nur normalisiert
    (klein, Leer-/Sonderzeichen zu ``_``) und durchgereicht.
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s:
        return None
    if s in _ALIAS_TO_KEY:
        return _ALIAS_TO_KEY[s]
    s = re.sub(r"[\s\-./]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_{2,}", "_", s).strip("_")
    if not s:
        return None
    return _ALIAS_TO_KEY.get(s, s)


_NUM_THOUSANDS = re.compile(r"^[-+]?\d{1,3}(\.\d{3})+$")
_NUM_DE_DECIMAL = re.compile(r"^[-+]?\d{1,3}(\.\d{3})*,\d+$")
_NUM_LEAD = re.compile(r"^[-+]?[\d.,]+")


def parse_number(raw: Any) -> tuple[Optional[float], Optional[str]]:
    """Zahl aus allem, was der Kurzbefehl liefern koennte.

    Gibt (wert, hinweis) zurueck. ``hinweis`` ist gesetzt, wenn der Parser
    geraten hat -- etwa bei ``"8.421"``, das in deutscher Formatierung 8421
    meint. Der Hinweis landet in der Antwort, damit eine falsch geratene Zahl
    auffaellt statt still danebenzuliegen.
    """
    if raw is None or isinstance(raw, bool):
        return None, None
    if isinstance(raw, (int, float)):
        f = float(raw)
        return (f, None) if math.isfinite(f) else (None, None)

    # Kurzbefehle formatiert Zahlen je nach Gebietsschema mit geschuetzten
    # oder schmalen Leerzeichen als Tausendertrennung ("8 421"). Pythons
    # \s deckt U+00A0, U+202F und U+2009 mit ab.
    s = re.sub(r"\s+", "", str(raw).strip())
    if not s:
        return None, None

    m = _NUM_LEAD.match(s)          # "8421 Schritte" -> "8421"
    if not m:
        return None, None
    num = m.group(0).rstrip(".,")
    if not num or num in ("+", "-"):
        return None, None

    note = None
    if _NUM_THOUSANDS.match(num):
        plain = num.replace(".", "")
        note = f"Zahl {num} als Tausendertrennzeichen gelesen -> {plain}"
        num = plain
    elif _NUM_DE_DECIMAL.match(num):
        note = f"Zahl {num} als deutsche Schreibweise gelesen"
        num = num.replace(".", "").replace(",", ".")
    elif num.count(",") == 1 and "." not in num:
        num = num.replace(",", ".")

    try:
        f = float(num)
    except ValueError:
        return None, None
    if not math.isfinite(f):
        return None, None
    return f, note


_DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DATE_SLASH = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")
_DATE_DE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_EPOCH = re.compile(r"^\d{9,13}$")

# Zeitstempel MIT Zonenangabe
_DT_AWARE_FORMATS = (
    "%Y-%m-%d %H:%M:%S %z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S%z",
)
# Zeitstempel OHNE Zonenangabe -- bekommen die konfigurierte Zone. Die
# Punkt-Varianten decken die deutsche Ausgabe von "Datum formatieren" in
# Kurzbefehle ab ("05.09.2026, 23:50").
_DT_NAIVE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%d.%m.%Y, %H:%M:%S",
    "%d.%m.%Y, %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
)


def parse_when(raw: Any, tz) -> tuple[Optional[str], Any]:
    """Zeitangabe -> ('date', date) oder ('datetime', aware datetime).

    Ein blankes Datum bleibt bewusst ein ``date`` und wird NICHT durch eine
    Zeitzone gedreht: ``2026-09-05`` meint den 5. September, egal wo der Server
    steht. Nur echte Zeitstempel werden in die konfigurierte Zone umgerechnet.
    """
    if raw is None:
        return None, None
    if isinstance(raw, datetime):
        return "datetime", (raw if raw.tzinfo else raw.replace(tzinfo=tz))
    if isinstance(raw, date):
        return "date", raw
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = str(int(raw))

    s = str(raw).strip()
    if not s:
        return None, None

    m = _DATE_ISO.match(s) or _DATE_SLASH.match(s)
    if m:
        try:
            return "date", date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None, None
    m = _DATE_DE.match(s)
    if m:
        try:
            return "date", date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None, None

    if _EPOCH.match(s):
        try:
            secs = int(s)
            if len(s) >= 12:        # Millisekunden
                secs = secs / 1000.0
            return "datetime", datetime.fromtimestamp(secs, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None, None

    for fmt in _DT_AWARE_FORMATS:
        try:
            return "datetime", datetime.strptime(s, fmt)
        except ValueError:
            pass
    for fmt in _DT_NAIVE_FORMATS:
        try:
            return "datetime", datetime.strptime(s, fmt).replace(tzinfo=tz)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
        return "datetime", (dt if dt.tzinfo else dt.replace(tzinfo=tz))
    except ValueError:
        return None, None


def to_bucket(kind: str, when: Any, bucket: str, tz) -> tuple[date, datetime]:
    """(sample_date, bucket_start) fuer die Unique-Spalten der Tabelle."""
    if kind == "date":
        day = when
        return day, datetime.combine(day, time(0, 0), tzinfo=tz)
    local = when.astimezone(tz)
    day = local.date()
    if bucket == "point":
        return day, when
    return day, datetime.combine(day, time(0, 0), tzinfo=tz)


# ---------------------------------------------------------------------------
# Extraktion: Rohbytes -> Liste von Punkt-Dicts
# ---------------------------------------------------------------------------
def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _looks_like_point(d: dict) -> bool:
    return any(_first_field(d, group)[0]
               for group in (_METRIC_FIELDS, _DATE_FIELDS, _VALUE_FIELDS))


def _expand(items: list) -> list[dict]:
    """Loest verschachtelte Metrik-Bloecke (Auto-Health-Export-Stil) auf.

    Ein Block ``{"name": "step_count", "units": "count", "data": [{...}, ...]}``
    wird zu einem Punkt je Eintrag in ``data``, wobei Name und Einheit des
    Blocks in jeden Punkt hineinkopiert werden -- der Punkt selbst gewinnt,
    falls er die Felder auch hat.
    """
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            out.append({"__raw": item})
            continue
        nested_field, nested = _first_field(item, _NESTED_FIELDS)
        if nested_field and isinstance(nested, list):
            _, block_name = _first_field(item, _METRIC_FIELDS)
            _, block_unit = _first_field(item, _UNIT_FIELDS)
            for sub in nested:
                if not isinstance(sub, dict):
                    out.append({"__raw": sub})
                    continue
                merged: dict = {}
                if block_name is not None:
                    merged["metric"] = block_name
                if block_unit is not None:
                    merged["unit"] = block_unit
                merged.update(sub)
                out.append(merged)
        else:
            out.append(item)
    return out


def _split_line(line: str) -> list[str]:
    for sep in (";", "\t", ","):
        if sep in line:
            return [p.strip() for p in line.split(sep)]
    return [line.strip()]


def _points_from_text(text: str, default_metric: Optional[str]) -> tuple[list[dict], list[dict]]:
    points: list[dict] = []
    skipped: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = _split_line(line)
        while parts and parts[-1] == "":
            parts.pop()
        if len(parts) >= 4:
            points.append({"date": parts[0], "metric": parts[1], "value": parts[2],
                           "unit": parts[3], "__line": line})
        elif len(parts) == 3:
            points.append({"date": parts[0], "metric": parts[1], "value": parts[2],
                           "__line": line})
        elif len(parts) == 2:
            # Zweispaltig: die Metrik kommt aus ?metric=... an der URL.
            points.append({"date": parts[0], "value": parts[1],
                           "metric": default_metric, "__line": line})
        else:
            skipped.append({"reason": "bad_line", "raw": line[:200]})
    return points, skipped


def extract_points(raw: bytes, content_type: str = "",
                   default_metric: Optional[str] = None) -> tuple[str, list[dict], list[dict]]:
    """Rohbody -> (format, punkte, uebersprungene).

    Reihenfolge bewusst inhaltsgetrieben statt Content-Type-getrieben: was
    Kurzbefehle als Content-Type setzt, haengt davon ab, ob der Body als JSON,
    Text oder Datei verschickt wird, und ist erfahrungsgemaess kein
    verlaesslicher Hinweis. ``content_type`` wandert daher nur ins Protokoll.
    """
    if not raw:
        return "empty", [], []

    text = _decode(raw).strip()
    if not text:
        return "empty", [], []

    if text[0] in "[{":
        try:
            parsed = json.loads(text)
        except (ValueError, RecursionError) as e:
            return "unreadable", [], [{"reason": "bad_json", "raw": text[:200],
                                       "detail": str(e)[:160]}]

        if isinstance(parsed, list):
            return "json-array", _expand(parsed), []
        if isinstance(parsed, dict):
            # Auto-Health-Export: {"data": {"metrics": [...], "workouts": [...]}}
            inner = parsed.get("data")
            if isinstance(inner, dict):
                blocks = inner.get("metrics")
                if isinstance(blocks, list):
                    return "json-hae", _expand(blocks), []
            for envelope in ("metrics", "points", "data", "samples"):
                items = parsed.get(envelope)
                if isinstance(items, list):
                    return "json", _expand(items), []
                if isinstance(items, dict):
                    return "json", _expand([items]), []
            if _looks_like_point(parsed):
                return "json-single", _expand([parsed]), []
            return "unreadable", [], [{"reason": "no_points_in_json", "raw": text[:200]}]
        return "unreadable", [], [{"reason": "bad_json", "raw": text[:200]}]

    points, skipped = _points_from_text(text, default_metric)
    if not points and not skipped:
        return "unreadable", [], [{"reason": "empty_after_parse", "raw": text[:200]}]
    return "text", points, skipped


# ---------------------------------------------------------------------------
# Normalisierung eines einzelnen Punktes
# ---------------------------------------------------------------------------
def _raw_for_report(p: dict) -> Any:
    """Das, was im Skip-Eintrag der Antwort steht. Kurz genug fuers iPhone und
    garantiert JSON-serialisierbar."""
    if "__line" in p:
        return str(p["__line"])[:200]
    if "__raw" in p:
        return str(p["__raw"])[:200]
    out = {}
    for k, v in list(p.items())[:8]:
        if str(k).startswith("__"):
            continue
        out[str(k)[:40]] = (v if isinstance(v, (int, float, bool)) or v is None
                            else str(v)[:80])
    return out


def normalize_point(p: Any, default_metric: Optional[str],
                    tz) -> tuple[Optional[dict], Optional[dict], list[str]]:
    """Ein Rohpunkt -> (normalisiert, skip, warnungen).

    Genau eines von ``normalisiert`` und ``skip`` ist gesetzt. ``skip`` traegt
    immer einen festen ``reason``-Schluessel, damit die Antwort im Kurzbefehl
    lesbar bleibt: not_an_object, no_metric, bad_metric_key, no_date, bad_date,
    no_value, bad_value.
    """
    warnings: list[str] = []
    if not isinstance(p, dict):
        return None, {"reason": "not_an_object", "raw": str(p)[:200]}, warnings

    raw_report = _raw_for_report(p)

    _, raw_metric = _first_field(p, _METRIC_FIELDS)
    if raw_metric is None and default_metric:
        raw_metric = default_metric
    if raw_metric is None:
        return None, {"reason": "no_metric", "raw": raw_report}, warnings
    metric_key = normalize_metric_key(raw_metric)
    if not metric_key or not METRIC_KEY_RE.match(metric_key):
        return None, {"reason": "bad_metric_key", "raw": raw_report,
                      "detail": str(raw_metric)[:80]}, warnings

    _, raw_date = _first_field(p, _DATE_FIELDS)
    if raw_date is None:
        return None, {"reason": "no_date", "raw": raw_report}, warnings
    kind, when = parse_when(raw_date, tz)
    if kind is None:
        return None, {"reason": "bad_date", "raw": raw_report,
                      "detail": str(raw_date)[:80]}, warnings

    _, raw_value = _first_field(p, _VALUE_FIELDS)
    if raw_value is None:
        return None, {"reason": "no_value", "raw": raw_report}, warnings
    value, num_note = parse_number(raw_value)
    if value is None:
        return None, {"reason": "bad_value", "raw": raw_report,
                      "detail": str(raw_value)[:80]}, warnings
    if num_note:
        warnings.append(f"{metric_key}: {num_note}")

    meta = SHORTCUT_METRICS.get(metric_key) or {}
    bucket = meta.get("bucket", "day")
    _, raw_unit = _first_field(p, _UNIT_FIELDS)
    unit = (str(raw_unit).strip()[:40] if raw_unit is not None else meta.get("unit"))

    if metric_key not in SHORTCUT_METRICS:
        warnings.append(f"unbekannte Metrik '{metric_key}' gespeichert "
                        f"(laeuft als Tageswert)")

    sample_date, bucket_start = to_bucket(kind, when, bucket, tz)
    return {
        "metric_key": metric_key,
        "bucket": bucket,
        "bucket_start": bucket_start,
        "sample_date": sample_date,
        "value": value,
        "unit": unit,
        "raw_date": str(raw_date)[:120],
        "known": metric_key in SHORTCUT_METRICS,
    }, None, warnings


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def build_summary(accepted: list[dict], skipped: list[dict], fmt: str) -> str:
    """Ein deutscher Einzeiler fuer "Mitteilung anzeigen" im Kurzbefehl."""
    if fmt == "empty":
        return "Leerer Body — nichts angekommen"
    if fmt == "unreadable":
        return f"Body nicht lesbar — {len(skipped)} übersprungen"
    inserted = sum(1 for a in accepted if a.get("action") == "inserted")
    updated = len(accepted) - inserted
    total = len(accepted) + len(skipped)
    noun = "Punkt" if total == 1 else "Punkte"
    return (f"{total} {noun} · {inserted} neu · {updated} überschrieben "
            f"· {len(skipped)} übersprungen")


def cap(items: list, limit: int = MAX_REPORT_ITEMS) -> list:
    """Kuerzt eine Report-Liste und haengt einen Hinweis an, statt still
    abzuschneiden."""
    if len(items) <= limit:
        return items
    rest = len(items) - limit
    return items[:limit] + [{"reason": "gekuerzt", "raw": f"und {rest} weitere"}]
