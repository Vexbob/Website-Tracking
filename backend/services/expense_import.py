"""Ausgaben-Import: aus dem CSV-Export der Bank-App wird der Rueckblick.

Ab August 2026 entstehen Ausgaben in Vexbob selbst — als gescannter Bon oder
von Hand. Alles davor liegt nur in der C24-App und kommt als CSV:

    Buchungsdatum;Betrag;Zahlungsempfaenger;Kategorie;Unterkategorie
    31.07.2026;-35,50 €;Amazon;Shopping;Online-Shopping

Diese Datei ist aermer als ein Kassenbon: sie kennt **keine Positionen**, nur
den Gesamtbetrag. Daraus folgt fast alles, was dieser Ingest tut.

1. **Herkunft bleibt sichtbar.** Jede so entstandene Buchung traegt
   ``source='import'``. Eine Buchung ohne Positionen ist sonst spaeter nicht
   von einem Bon zu unterscheiden, bei dem das Abtippen vergessen wurde --
   und der Export koennte nicht erklaeren, warum der Rueckblick duenner ist
   als der laufende Betrieb.

2. **Ein Sammelposten je Buchung.** Die Kategorie-Statistik rechnet ueber
   ``expense_items``; ohne Position taucht die Buchung dort gar nicht auf und
   die Summe der Kategorien passt nicht mehr zur Gesamtsumme. Der Sammelposten
   traegt deshalb den vollen Betrag -- aber ``price_comparable=FALSE``, damit
   er nicht als Artikel in den Preisvergleich geraet. "Online-Shopping" ist
   kein Produkt, dessen Kilopreis man vergleicht.

3. **Der Import ersetzt seinen Zeitraum.** Beim zweiten Upload derselben
   Datei verschwindet erst, was frueher aus einem Import kam, dann wird neu
   geschrieben. Nur so ist derselbe Upload wiederholbar. Angefasst wird dabei
   **ausschliesslich** ``source='import'`` -- selbst erfasste Bons im selben
   Zeitraum bleiben unberuehrt, auch wenn sie sich mit dem Import ueberlappen.
   Die Vorschau sagt, wenn es zu so einer Ueberlappung kaeme.

4. **Gutschriften werden nicht uebernommen.** Positive Betraege sind Gehalt,
   Erstattungen, Umbuchungen. Vexbob ist ein Ausgaben-Tracker; eine Gutschrift
   als negative Ausgabe wuerde Monatssummen still verfaelschen. Die Vorschau
   nennt die Zahl, damit es nachvollziehbar bleibt statt verschluckt.

5. **Die Kategorien der Bank-App bleiben roh liegen.** "Weitere Ausgaben" ist
   keine Kategorie dieser Website. Was in der Datei stand, landet unveraendert
   in ``src_category``/``src_subcategory``; ``category_id`` bleibt leer. Die
   Zuordnung ist ein eigener, spaeterer Schritt -- und der braucht das
   Original.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Optional

# Lesen, Zeichensatz und Trennzeichen sind beim Musik-Import schon geloest.
# Eine zweite Fassung waere eine zweite Stelle, an der ein BOM Aerger macht.
from services.music_ingest import decode, sniff_delimiter

import csv
import io


class ExpenseImportError(Exception):
    """Fehler, den der Nutzer lesen soll (400, nicht 500)."""


# Ab hier gilt der laufende Betrieb. Wird nur fuer den Hinweistext gebraucht,
# nicht fuer die Logik -- was importiert wurde, steht in ``source``.
BACKLOG_UNTIL = date(2026, 8, 1)

MAX_ROWS = 20000


# ---------------------------------------------------------------------------
# Spaltenkoepfe
# ---------------------------------------------------------------------------
# Erkannt wird am Kopf, nicht an der Position: welche Spalten die Datei hat,
# entscheidet die App beim Export. Normalisiert wird wie beim Musik-Import
# (klein, ohne Sonderzeichen, Umlaute aufgeloest), damit "Zahlungsempfänger",
# "zahlungsempfaenger" und "Zahlungsempfänger " denselben Schluessel ergeben.

_UML = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                      "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (h or "").strip().lower().translate(_UML))


HEADER_ALIASES = {
    # Datum. C24 nennt es "Buchungsdatum"; andere Ausleitungen "Datum" oder
    # "Wertstellung". Buchungsdatum gewinnt, wenn beides da ist (siehe unten).
    "buchungsdatum":      "date",
    "datum":              "date",
    "belegdatum":         "date",
    "wertstellung":       "value_date",
    "valuta":             "value_date",
    "valutadatum":        "value_date",
    # Betrag
    "betrag":             "amount",
    "umsatz":             "amount",
    "betrageur":          "amount",
    "betragineur":        "amount",
    # Wer das Geld bekommen hat
    "zahlungsempfaenger": "payee",
    "empfaenger":         "payee",
    "beguenstigter":      "payee",
    "beguenstigterzahlungspflichtiger": "payee",
    "auftraggeberempfaenger": "payee",
    "name":               "payee",
    "haendler":           "payee",
    # Die Kategorien der Bank-App -- roh, nicht die dieser Website
    "kategorie":          "category",
    "unterkategorie":     "subcategory",
    "hauptkategorie":     "category",
    # Freitext
    "verwendungszweck":   "purpose",
    "buchungstext":       "purpose",
    "beschreibung":       "purpose",
    "notiz":              "purpose",
}


def read_table(raw: bytes) -> tuple[list[str], list[dict]]:
    """Kopfzeile und Zeilen als Feld-Woerterbuecher.

    Leerzeilen und Kommentarzeilen (``# ...``) fliegen raus -- die entstehen,
    wenn jemand einen Vexbob-Export versehentlich wieder einliest.
    """
    text = decode(raw)
    delim = sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header: list[str] = []
    fields: list[str] = []
    rows: list[dict] = []
    for parts in reader:
        if not parts or all(not p.strip() for p in parts):
            continue
        if parts[0].lstrip().startswith("#"):
            continue
        if not header:
            header = [p.strip() for p in parts]
            fields = [HEADER_ALIASES.get(_norm_header(h), "") for h in header]
            if "date" not in fields and "value_date" not in fields:
                raise ExpenseImportError(
                    "In der Kopfzeile steht keine Datumsspalte. Erwartet wird "
                    "eine CSV aus der Banking-App mit „Buchungsdatum“ und "
                    "„Betrag“.")
            if "amount" not in fields:
                raise ExpenseImportError(
                    "In der Kopfzeile steht keine Betragsspalte. Erwartet wird "
                    "eine CSV aus der Banking-App mit „Buchungsdatum“ und "
                    "„Betrag“.")
            continue
        row: dict = {}
        for i, value in enumerate(parts):
            key = fields[i] if i < len(fields) else ""
            if key and key not in row:
                row[key] = (value or "").strip()
        rows.append(row)
        if len(rows) > MAX_ROWS:
            raise ExpenseImportError(
                f"Die Datei hat mehr als {MAX_ROWS} Zeilen. Bitte in "
                f"Zeitraeume aufteilen.")
    if not header:
        raise ExpenseImportError("Die Datei enthält keine Kopfzeile.")
    return header, rows


# ---------------------------------------------------------------------------
# Werte
# ---------------------------------------------------------------------------

_DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y", "%m/%d/%Y")


def parse_date(v) -> Optional[date]:
    """``01.08.2026`` und ``2026-08-01``. Zweistellige Jahre bekommen 20xx --
    ein Kontoauszug aus dem letzten Jahrhundert ist keine reale Sorge."""
    s = str(v or "").strip()
    if not s:
        return None
    # Manche Ausleitungen haengen eine Uhrzeit an.
    s = s.split(" ")[0].split("T")[0]
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(s, fmt).date()
        except ValueError:
            continue
        if 2000 <= d.year <= 2100:
            return d
    return None


def parse_amount(v) -> Optional[float]:
    """``-9,99 €`` → ``-9.99``.

    Deutsche Schreibweise ist der Normalfall, englische kommt vor, wenn die
    App auf Englisch stand. Unterschieden wird am **letzten** Trennzeichen:
    steht dahinter genau eine Gruppe aus ein bis zwei Ziffern, ist es das
    Dezimaltrennzeichen. ``1.234,56`` und ``1,234.56`` landen so beide richtig.
    """
    s = str(v or "").strip()
    if not s:
        return None
    # Waehrung, geschuetzte Leerzeichen, Tausender-Apostroph
    s = (s.replace(" ", "").replace(" ", "").replace(" ", "")
          .replace("€", "").replace("EUR", "").replace("'", ""))
    # Ein nachgestelltes Minus ("9,99-") gibt es in Bank-Ausleitungen wirklich.
    neg = s.startswith("-") or s.endswith("-")
    s = s.strip("+-")
    if not s:
        return None
    last_sep = max(s.rfind(","), s.rfind("."))
    if last_sep >= 0:
        decimals = s[last_sep + 1:]
        if len(decimals) in (1, 2) and decimals.isdigit():
            s = re.sub(r"[.,]", "", s[:last_sep]) + "." + decimals
        else:
            s = re.sub(r"[.,]", "", s)
    if not re.fullmatch(r"\d*\.?\d*", s) or not s.strip("."):
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if neg else val


# ---------------------------------------------------------------------------
# Zahlungsempfaenger
# ---------------------------------------------------------------------------
# Der Empfaenger ist der einzige Anhaltspunkt fuer den Laden. Er kommt aber in
# der Schreibweise des Zahlungsdienstleisters:
#
#     Mol*PassaSports.de      S. Payment Solutions GmbH      AMZN Mktp DE
#     PayPal *STEAM GAMES     LIDL SAGT DANKE FIL 1234       REWE Markt GmbH
#
# Ohne Normalisierung entstuenden aus "Amazon", "AMAZON.DE" und "Amazon EU
# S.a.r.l." drei Laeden. Der Schluessel unten macht daraus einen.

# Praefixe von Zahlungsdienstleistern. Was VOR dem Stern steht, ist der
# Dienstleister, was dahinter steht, der eigentliche Haendler.
_STAR_SPLIT = re.compile(r"^[a-z0-9.\-/ ]{1,12}\*+\s*")

# Rechtsformen -- als eigenstaendiges Wort, damit "Agentur" nicht zu "entur"
# wird, weil "ag" darin vorkommt.
_LEGAL_FORMS = {
    "gmbh", "mbh", "ag", "kg", "kgaa", "ohg", "ug", "gbr", "eg", "ek", "se",
    "ltd", "limited", "inc", "llc", "bv", "nv", "sa", "sarl", "srl", "spa",
    "plc", "co", "cie", "und", "and",
}

# Was am Ende einer Kartenzahlung klebt und nichts ueber den Laden sagt.
_NOISE_WORDS = {
    "sagt", "danke", "fil", "filiale", "markt", "gmbhcokg",
    "de", "deu", "deutschland", "germany", "ger", "eu",
    "kartenzahlung", "lastschrift", "dauerauftrag", "ueberweisung",
    "onlinekauf", "einkauf", "zahlung", "pos",
}

_TLD = re.compile(r"\.(de|com|net|org|eu|at|ch|io|shop|co\.uk)\b")


def norm_payee(s: str) -> str:
    """Der Schluessel, unter dem zwei Schreibweisen derselbe Laden sind.

    Nur zum Vergleichen gedacht, nie zum Anzeigen -- dafuer gibt es
    :func:`pretty_payee`.
    """
    t = (s or "").strip().lower().translate(_UML)
    if not t:
        return ""
    t = _STAR_SPLIT.sub("", t)          # "mol*passasports.de" -> "passasports.de"
    t = t.replace("www.", " ")
    t = _TLD.sub(" ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    words = [w for w in t.split() if w]
    # Reine Zahlenblöcke (Filial- und Terminalnummern) und Rauschwoerter raus.
    words = [w for w in words
             if not w.isdigit() and w not in _LEGAL_FORMS and w not in _NOISE_WORDS]
    # Einzelbuchstaben am Rand sind Initialen und zerlegte Rechtsformen:
    # "S. Payment Solutions" vorne, "Amazon EU S.a.r.l." hinten. In der Mitte
    # koennen sie zum Namen gehoeren, deshalb wird nur an den Raendern gekuerzt
    # -- und nie das letzte verbliebene Wort.
    while len(words) > 1 and len(words[0]) == 1:
        words.pop(0)
    while len(words) > 1 and len(words[-1]) == 1:
        words.pop()
    return "".join(words)


def pretty_payee(s: str) -> str:
    """Ein Name, den man einem Laden geben kann.

    ``Mol*PassaSports.de`` → ``PassaSports``. Grossschreibung bleibt erhalten,
    wo sie im Original stand (``dm``, ``REWE``); durchgehend geschriebene
    Namen bekommen normale Schreibung, sonst schreit die Laden-Liste.
    """
    t = (s or "").strip()
    if not t:
        return ""
    t = re.sub(r"^[A-Za-z0-9.\-/ ]{1,12}\*+\s*", "", t)   # Dienstleister-Praefix
    t = re.sub(r"(?i)\bwww\.", "", t)
    t = re.sub(r"(?i)\.(de|com|net|org|eu|at|ch|io|shop)\b", "", t)
    t = re.sub(r"(?i)\b(sagt danke|fil(?:iale)?\.?\s*\d+|kartenzahlung)\b", " ", t)
    # Die Rechtsform am ENDE weg -- "S. Payment Solutions GmbH" ist als
    # Eintrag in der Laden-Liste unbrauchbar lang. In der Mitte bleibt sie
    # stehen, dort kann sie zum Namen gehoeren.
    t = re.sub(r"(?i)[\s,]*\b(gmbh(\s*&?\s*co\.?\s*kg)?|mbh|ag|kgaa|kg|ohg|ug|"
               r"e\.?\s?k\.?|se|ltd\.?|limited|inc\.?|llc|b\.?v\.?|n\.?v\.?|"
               r"s\.?\s?a\.?\s?r\.?\s?l\.?|s\.?a\.?|plc)\s*$", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" .,-/&")
    if not t:
        return (s or "").strip()[:60]
    # ALLES GROSS ist Terminal-Schreibweise, kein Markenauftritt. Kurze
    # Kuerzel (dm, ARAL) duerfen so bleiben.
    if t.isupper() and len(t) > 4:
        t = t.title()
    return t[:60]


# ---------------------------------------------------------------------------
# Zeilen deuten
# ---------------------------------------------------------------------------

def build_rows(rows: list[dict]) -> dict:
    """Rohzeilen zu Buchungen. Was nicht durchkommt, wird gezaehlt und
    begruendet -- eine stillschweigend verschluckte Zeile ist ein Loch, das
    man ein Jahr spaeter nicht mehr von fehlenden Daten unterscheiden kann."""
    out: list[dict] = []
    skipped = {"gutschrift": 0, "ohne_datum": 0, "ohne_betrag": 0, "null": 0}
    examples: dict[str, list[str]] = {}

    def _note(reason: str, row: dict):
        skipped[reason] = skipped.get(reason, 0) + 1
        ex = examples.setdefault(reason, [])
        if len(ex) < 3:
            label = " · ".join(x for x in (row.get("date"), row.get("amount"),
                                           row.get("payee")) if x)
            if label:
                ex.append(label[:80])

    for row in rows:
        d = parse_date(row.get("date")) or parse_date(row.get("value_date"))
        if not d:
            _note("ohne_datum", row)
            continue
        amt = parse_amount(row.get("amount"))
        if amt is None:
            _note("ohne_betrag", row)
            continue
        if amt > 0:
            # Gehalt, Erstattung, Umbuchung. Siehe Modulkopf.
            _note("gutschrift", row)
            continue
        if amt == 0:
            _note("null", row)
            continue
        payee = (row.get("payee") or "").strip()
        out.append({
            "date": d,
            "amount": round(abs(amt), 2),
            "payee": payee,
            "key": norm_payee(payee),
            "name": pretty_payee(payee),
            "category": (row.get("category") or "").strip() or None,
            "subcategory": (row.get("subcategory") or "").strip() or None,
            "purpose": (row.get("purpose") or "").strip() or None,
        })

    skipped = {k: v for k, v in skipped.items() if v}
    return {"entries": out, "skipped": skipped, "examples": examples}


def item_description(entry: dict) -> str:
    """Wie der Sammelposten heisst. Die Unterkategorie der Bank-App sagt am
    ehesten, wofuer das Geld war -- und ist genau das, was der spaetere
    Zuordnungs-Schritt in eine echte Kategorie uebersetzt."""
    return entry.get("subcategory") or entry.get("category") or "Sammelbuchung"


def item_original_text(entry: dict) -> Optional[str]:
    parts = [p for p in (entry.get("category"), entry.get("subcategory")) if p]
    if not parts:
        return None
    return "C24: " + " / ".join(parts)


# ---------------------------------------------------------------------------
# Laden-Zuordnung
# ---------------------------------------------------------------------------

def plan_stores(entries: list[dict], stores: list[dict]) -> dict:
    """Ordnet jeden Empfaenger einem vorhandenen Laden zu oder schlaegt einen
    neuen vor.

    ``stores`` sind die Laeden des Nutzers (``id``, ``name``). Verglichen wird
    ueber :func:`norm_payee` -- so trifft "AMAZON.DE" den vorhandenen Laden
    "Amazon", und zwei Schreibweisen desselben Empfaengers ergeben innerhalb
    eines Imports nur **einen** neuen Laden.
    """
    known: dict[str, dict] = {}
    for s in stores or []:
        k = norm_payee(s.get("name") or "")
        # Der erste gewinnt: die Laden-Liste kommt alphabetisch, und bei zwei
        # Schreibweisen desselben Ladens ist eine Wahl besser als eine zufaellige.
        if k and k not in known:
            known[k] = {"id": s.get("id"), "name": s.get("name")}

    matched: dict[str, dict] = {}    # key -> {store_id, store_name, rows, amount}
    new: dict[str, dict] = {}        # key -> {name, rows, amount, samples}
    without = {"rows": 0, "amount": 0.0}

    for e in entries:
        k = e["key"]
        if not k:
            without["rows"] += 1
            without["amount"] = round(without["amount"] + e["amount"], 2)
            continue
        if k in known:
            slot = matched.setdefault(k, {
                "store_id": known[k]["id"], "store_name": known[k]["name"],
                "rows": 0, "amount": 0.0, "payees": []})
        else:
            slot = new.setdefault(k, {
                "name": e["name"] or e["payee"], "rows": 0, "amount": 0.0,
                "payees": []})
        slot["rows"] += 1
        slot["amount"] = round(slot["amount"] + e["amount"], 2)
        if e["payee"] and e["payee"] not in slot["payees"] and len(slot["payees"]) < 4:
            slot["payees"].append(e["payee"])

    order = lambda d: sorted(d.values(), key=lambda x: -x["rows"])  # noqa: E731
    return {"matched": order(matched), "new": order(new), "without": without,
            "matched_keys": matched, "new_keys": new}


# ---------------------------------------------------------------------------
# Vorschau und Anwendung
# ---------------------------------------------------------------------------

async def _stores_of(db, user_id: int) -> list[dict]:
    rows = await db.fetch(
        "SELECT id, name FROM stores WHERE user_id=$1", user_id)
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def _span(entries: list[dict]) -> tuple[Optional[date], Optional[date]]:
    if not entries:
        return None, None
    days = [e["date"] for e in entries]
    return min(days), max(days)


async def preview(db, user_id: int, raw: bytes, filename: str) -> dict:
    """Was der Import taete, ohne etwas zu tun.

    Der Dialog zeigt das, bevor er fragt: ein Import, der einen Zeitraum
    leerraeumt und Laeden anlegt, darf keine Ueberraschung sein.
    """
    _header, rows = read_table(raw)
    built = build_rows(rows)
    entries = built["entries"]
    if not entries:
        raise ExpenseImportError(
            "Aus der Datei liess sich keine einzige Ausgabe lesen. Enthält sie "
            "nur Gutschriften, oder stimmt das Datums- bzw. Betragsformat nicht?")

    d_from, d_to = _span(entries)
    stores = await _stores_of(db, user_id)
    plan = plan_stores(entries, stores)

    # Was ein erneuter Import ersetzen wuerde -- und was er NICHT anfasst.
    replaced = await db.fetchval(
        """SELECT COUNT(*) FROM expenses
            WHERE user_id=$1 AND source='import'
              AND purchase_date BETWEEN $2 AND $3""",
        user_id, d_from, d_to) or 0
    own = await db.fetchrow(
        """SELECT COUNT(*) AS n, COALESCE(SUM(total_amount),0) AS total
             FROM expenses
            WHERE user_id=$1 AND source<>'import'
              AND purchase_date BETWEEN $2 AND $3""",
        user_id, d_from, d_to)

    total = round(sum(e["amount"] for e in entries), 2)
    return {
        "filename": filename,
        "rows_read": len(rows),
        "rows_ready": len(entries),
        "skipped": built["skipped"],
        "skipped_examples": built["examples"],
        "from": d_from.isoformat(),
        "to": d_to.isoformat(),
        "total": total,
        "replaces": replaced,
        "own_in_range": {"count": own["n"] if own else 0,
                         "total": float(own["total"]) if own else 0.0},
        "stores_matched": plan["matched"],
        "stores_new": plan["new"],
        "without_store": plan["without"],
        "categories": _category_overview(entries),
    }


def _category_overview(entries: list[dict]) -> list[dict]:
    """Welche Kategorien die Bank-App mitliefert. Sie werden NICHT zugeordnet
    -- die Uebersicht sagt nur, was auf den spaeteren Zuordnungs-Schritt
    zukommt."""
    seen: dict[tuple, dict] = {}
    for e in entries:
        key = (e.get("category") or "", e.get("subcategory") or "")
        slot = seen.setdefault(key, {"category": key[0] or "(ohne)",
                                     "subcategory": key[1] or "",
                                     "rows": 0, "amount": 0.0})
        slot["rows"] += 1
        slot["amount"] = round(slot["amount"] + e["amount"], 2)
    return sorted(seen.values(), key=lambda x: -x["rows"])


async def apply(db, user_id: int, raw: bytes, filename: str) -> dict:
    """Den Import wirklich schreiben.

    Reihenfolge: Zeitraum raeumen (nur eigene Importe), fehlende Laeden
    anlegen, Buchungen mit ihrem Sammelposten schreiben, Protokoll ablegen.
    Alles in einer Transaktion -- ein halb geschriebener Kontoauszug waere
    schlimmer als keiner.
    """
    _header, rows = read_table(raw)
    built = build_rows(rows)
    entries = built["entries"]
    if not entries:
        raise ExpenseImportError(
            "Aus der Datei liess sich keine einzige Ausgabe lesen. Enthält sie "
            "nur Gutschriften, oder stimmt das Datums- bzw. Betragsformat nicht?")
    d_from, d_to = _span(entries)

    async with db.transaction():
        stores = await _stores_of(db, user_id)
        plan = plan_stores(entries, stores)

        # Der Zeitraum-Ersatz trifft ausschliesslich frueher Importiertes.
        # ``fetchval`` auf ein blosses DELETE ... RETURNING liefert nur die
        # ERSTE Zeile -- die Zahl braucht den Umweg ueber die CTE.
        replaced = await db.fetchval(
            """WITH weg AS (
                   DELETE FROM expenses
                    WHERE user_id=$1 AND source='import'
                      AND purchase_date BETWEEN $2 AND $3
                 RETURNING 1)
               SELECT COUNT(*) FROM weg""", user_id, d_from, d_to) or 0

        store_id: dict[str, Optional[int]] = {}
        for key, slot in plan["matched_keys"].items():
            store_id[key] = slot["store_id"]
        created = 0
        for key, slot in plan["new_keys"].items():
            new_id = await db.fetchval(
                "INSERT INTO stores (user_id, name) VALUES ($1, $2) RETURNING id",
                user_id, slot["name"][:100] or "Unbekannt")
            store_id[key] = new_id
            created += 1

        imp_id = await db.fetchval(
            """INSERT INTO expense_imports
                   (user_id, filename, size_bytes, date_from, date_to,
                    rows_read, rows_written, rows_skipped, rows_replaced,
                    stores_created, notes)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb)
            RETURNING id""",
            user_id, filename[:200], len(raw), d_from, d_to,
            len(rows), len(entries), sum(built["skipped"].values()),
            replaced, created,
            json.dumps({"skipped": built["skipped"],
                        "examples": built["examples"]}, ensure_ascii=False))

        written = 0
        for e in entries:
            eid = await db.fetchval(
                """INSERT INTO expenses
                       (user_id, store_id, purchase_date, total_amount,
                        expense_type, note, source, src_payee, src_category,
                        src_subcategory, import_id)
                   VALUES ($1,$2,$3,$4,'receipt',$5,'import',$6,$7,$8,$9)
                RETURNING id""",
                user_id, store_id.get(e["key"]), e["date"], e["amount"],
                e.get("purpose"), e["payee"] or None,
                e.get("category"), e.get("subcategory"), imp_id)
            # Ein Sammelposten, damit die Kategorie-Statistik die Buchung
            # sieht. price_comparable=FALSE haelt ihn aus dem Preisvergleich.
            await db.execute(
                """INSERT INTO expense_items
                       (user_id, expense_id, description, quantity, unit_price,
                        total_price, category_id, sort_order, original_text,
                        price_comparable, user_edited)
                   VALUES ($1,$2,$3,1,$4,$4,NULL,0,$5,FALSE,FALSE)""",
                user_id, eid, item_description(e)[:200], e["amount"],
                item_original_text(e))
            written += 1

        await db.execute(
            "UPDATE expense_imports SET rows_written=$1 WHERE id=$2",
            written, imp_id)

    return {
        "import_id": imp_id,
        "filename": filename,
        "rows_read": len(rows),
        "rows_written": written,
        "rows_skipped": sum(built["skipped"].values()),
        "rows_replaced": replaced,
        "skipped": built["skipped"],
        "stores_created": created,
        "from": d_from.isoformat(),
        "to": d_to.isoformat(),
        "total": round(sum(e["amount"] for e in entries), 2),
    }


async def undo(db, user_id: int, import_id: int) -> dict:
    """Einen Import als Ganzes zuruecknehmen.

    Die Laeden, die er angelegt hat, bleiben stehen: sie koennten inzwischen
    an selbst erfassten Bons haengen, und eine leere Laden-Zeile ist auf der
    Laden-Seite mit einem Klick weg -- eine geloeschte Verknuepfung nicht.
    """
    async with db.transaction():
        row = await db.fetchrow(
            "SELECT id FROM expense_imports WHERE id=$1 AND user_id=$2",
            import_id, user_id)
        if not row:
            raise ExpenseImportError("Diesen Import gibt es nicht.")
        removed = await db.fetchval(
            """WITH weg AS (
                   DELETE FROM expenses
                    WHERE user_id=$1 AND import_id=$2 AND source='import'
                 RETURNING 1)
               SELECT COUNT(*) FROM weg""", user_id, import_id)
        await db.execute(
            "DELETE FROM expense_imports WHERE id=$1 AND user_id=$2",
            import_id, user_id)
    return {"import_id": import_id, "removed": removed or 0}
