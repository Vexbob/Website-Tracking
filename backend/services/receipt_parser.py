"""Deutscher Kassenbon-Parser.
Nimmt den OCR-Rohtext und extrahiert store/date/total/vat/items heuristisch.
Der User soll das Ergebnis danach editieren.
"""
import re
from datetime import datetime
from typing import Optional

KNOWN_STORES = [
    "ALDI", "LIDL", "REWE", "EDEKA", "KAUFLAND", "PENNY", "NETTO",
    "DM", "ROSSMANN", "MÜLLER", "BUDNI", "REAL", "TEGUT", "HIT",
    "NORMA", "MARKTKAUF", "GLOBUS", "V-MARKT",
    "SATURN", "MEDIAMARKT", "MEDIA MARKT", "APPLE", "CONRAD",
    "IKEA", "BAUHAUS", "OBI", "HORNBACH", "TOOM",
    "H&M", "ZARA", "C&A", "PRIMARK", "TK MAXX", "DECATHLON",
    "MCDONALDS", "MC DONALDS", "BURGER KING", "KFC", "SUBWAY",
    "STARBUCKS", "BACKWERK", "KAMPS",
    "SHELL", "ARAL", "ESSO", "JET", "TOTAL", "STAR", "AGIP", "HEM",
    "DHL", "HERMES", "DPD", "AMAZON",
    "APOTHEKE", "DOC MORRIS", "SHOP APOTHEKE",
]

_DATE_PATTERNS = [
    r"\b(\d{2})\.(\d{2})\.(\d{4})\b",
    r"\b(\d{2})\.(\d{2})\.(\d{2})\b",
    r"\b(\d{4})-(\d{2})-(\d{2})\b",
    r"\b(\d{2})/(\d{2})/(\d{4})\b",
]
_TOTAL_KEYWORDS = ["SUMME", "GESAMT", "GESAMTBETRAG", "GESAMTSUMME",
                   "ZU ZAHLEN", "ZAHLBETRAG", "BETRAG", "TOTAL", "ENDSUMME"]
_VAT_KEYWORDS = ["MWST", "MEHRWERTSTEUER", "UST", "STEUER"]
_PRICE_RE = re.compile(r"(-?\d+[,.]\d{2})\s*(?:EUR|€|[A-Z*]{1,3})?\s*$")
# Preis irgendwo in der Zeile (nicht nur am Ende) — fürs Total-Suchen
_PRICE_ANY_RE = re.compile(r"(-?\d+[,.]\d{2})")
_SKIP_LINE_RE = re.compile(
    r"^\s*(datum|uhrzeit|zeit|beleg|bon|kasse|bediener|kunde|karte|"
    r"mwst|ust|zwischen|summe|gesamt|zu zahlen|zahlbetrag|betrag|"
    r"total|bar|ec|paypal|rückgeld|wechselgeld|gutschein|"
    r"steuernr|ust[-\s]?id|tel|telefon|adresse|straße|www|http|"
    r"vielen dank|danke|besuch|öffnungszeiten|filiale)\b",
    re.IGNORECASE,
)


def _parse_amount(s):
    if s is None:
        return None
    s = s.strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _find_date(text):
    for pat in _DATE_PATTERNS:
        m = re.search(pat, text)
        if not m:
            continue
        try:
            if pat.startswith(r"\b(\d{4})"):
                y, mo, d = m.group(1), m.group(2), m.group(3)
            else:
                d, mo, y = m.group(1), m.group(2), m.group(3)
            if len(y) == 2:
                y = "20" + y
            dt = datetime(int(y), int(mo), int(d))
            if 2000 <= dt.year <= 2100:
                return dt.date().isoformat()
        except (ValueError, IndexError):
            continue
    return None


def _find_store(text_upper, extra_stores=None):
    stores = list(KNOWN_STORES)
    if extra_stores:
        stores = list(extra_stores) + stores
    head = text_upper[:400]
    for s in stores:
        if s.upper() in head:
            return s.title() if s.isupper() else s
    return None


def _find_total(lines):
    candidates = []
    for i, line in enumerate(lines):
        line_upper = line.upper()
        # MwSt-Zeilen NIE als Total zählen
        if any(v in line_upper for v in _VAT_KEYWORDS):
            continue
        for kw in _TOTAL_KEYWORDS:
            if kw not in line_upper:
                continue
            # Alle Preise in dieser Zeile finden, den letzten/größten nehmen
            all_prices = _PRICE_ANY_RE.findall(line)
            vals = [_parse_amount(p) for p in all_prices]
            vals = [v for v in vals if v and v > 0]
            if vals:
                # Bei "SUMME EUR 12,34" ist der letzte Preis der richtige
                val = vals[-1]
                priority = 3 if kw in ("SUMME", "GESAMT", "ZU ZAHLEN", "ENDSUMME") else 2
                candidates.append((priority, val))
            elif i + 1 < len(lines) and len(line.strip()) < 20:
                # Preis auf der nächsten Zeile suchen
                nxt = lines[i + 1]
                if not any(v in nxt.upper() for v in _VAT_KEYWORDS):
                    nxt_prices = _PRICE_ANY_RE.findall(nxt)
                    nxt_vals = [_parse_amount(p) for p in nxt_prices]
                    nxt_vals = [v for v in nxt_vals if v and v > 0]
                    if nxt_vals:
                        candidates.append((2, nxt_vals[-1]))
    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidates[0][1]
    # Fallback: größter Preis auf dem Bon (oft ist die Summe der größte Wert)
    all_amounts = []
    for line in lines:
        if any(v in line.upper() for v in _VAT_KEYWORDS):
            continue
        for p in _PRICE_ANY_RE.findall(line):
            v = _parse_amount(p)
            if v and v > 0:
                all_amounts.append(v)
    if all_amounts:
        return max(all_amounts)
    return None


def _find_vat(lines):
    for line in lines:
        if any(kw in line.upper() for kw in _VAT_KEYWORDS):
            matches = re.findall(r"(-?\d+[,.]\d{2})", line)
            if matches:
                val = _parse_amount(matches[-1])
                if val is not None:
                    return val
    return None


_REDUZIERT_MARKERS = ("RABATT", "REDUZ", "AKTION", "SONDERANGEBOT", "-%", "PREISNACHLASS")

def _extract_items(lines, total):
    items = []
    for line in lines:
        line = line.strip()
        if len(line) < 3:
            continue
        if _SKIP_LINE_RE.match(line):
            continue
        m = _PRICE_RE.search(line)
        if not m:
            continue
        price = _parse_amount(m.group(1))
        if price is None:
            continue
        desc = line[:m.start()].strip()
        desc = re.sub(r"\s+[A-Z*]{1,3}\s*$", "", desc)
        desc = desc.rstrip(" \t.-,")
        if not desc or len(desc) < 2:
            continue
        if total is not None and abs(price - total) < 0.01:
            continue

        # Reduziert-Erkennung
        line_upper = line.upper()
        is_reduced = any(mk in line_upper for mk in _REDUZIERT_MARKERS) or price < 0
        # Negative Preise (Rabatt-Zeilen) auf letzten Item als Rabatt anwenden
        if price < 0 and items:
            last = items[-1]
            original = last["total_price"]
            new_price = round(original + price, 2)
            if new_price > 0:
                last["original_price"] = original
                last["total_price"] = new_price
                last["is_reduced"] = True
            continue

        qty = 1.0
        unit_price = None
        qm = re.match(r"^(\d+)\s*[xX*]\s*(\d+[,.]\d{2})\s+(.+)$", desc)
        if qm:
            qty = float(qm.group(1))
            unit_price = _parse_amount(qm.group(2))
            desc = qm.group(3).strip()
        items.append({
            "description": desc,
            "quantity": qty,
            "unit_price": unit_price,
            "total_price": price,
            "is_reduced": is_reduced,
            "original_price": None,
        })
    return items


def parse_receipt(raw_text, user_stores=None):
    """Nimmt OCR-Rohtext, gibt strukturiertes Dict zurück."""
    if not raw_text:
        return {"store_hint": None, "purchase_date": None,
                "total_amount": None, "vat_amount": None, "items": []}
    text_upper = raw_text.upper()
    lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]
    extra = [s.upper() for s in (user_stores or [])]
    total = _find_total(lines)
    return {
        "store_hint": _find_store(text_upper, extra_stores=extra),
        "purchase_date": _find_date(raw_text),
        "total_amount": total,
        "vat_amount": _find_vat(lines),
        "items": _extract_items(lines, total),
    }

