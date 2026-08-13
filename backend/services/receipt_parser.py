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
_PRICE_RE = re.compile(r"(-?\d+[,.]\d{2})\s*(?:EUR|€|[A-Z])?\s*$")
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
            if kw in line_upper:
                m = _PRICE_RE.search(line)
                if m:
                    val = _parse_amount(m.group(1))
                    if val and val > 0:
                        priority = 3 if kw in ("SUMME", "GESAMT", "ZU ZAHLEN") else 2
                        candidates.append((priority, val))
                # Nächste Zeile nur, wenn diese wirklich NUR das Keyword war
                elif i + 1 < len(lines) and len(line.strip()) < 15:
                    nxt = lines[i + 1]
                    if not any(v in nxt.upper() for v in _VAT_KEYWORDS):
                        m2 = _PRICE_RE.search(nxt)
                        if m2:
                            val = _parse_amount(m2.group(1))
                            if val and val > 0:
                                candidates.append((2, val))
    if candidates:
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidates[0][1]
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
        desc = re.sub(r"\s+[A-Z]\s*$", "", desc)
        desc = desc.rstrip(" \t.-,")
        if not desc or len(desc) < 2:
            continue
        if total is not None and abs(price - total) < 0.01:
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

