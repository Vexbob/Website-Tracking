"""Deutscher Kassenbon-Parser.
Nimmt den OCR-Rohtext und extrahiert store/date/total/vat/items heuristisch.
Der User soll das Ergebnis danach editieren.
"""
import re
from datetime import datetime
from typing import Optional

KNOWN_STORES = [
    # DE Supermärkte
    "ALDI", "LIDL", "REWE", "EDEKA", "KAUFLAND", "PENNY", "NETTO",
    "REAL", "TEGUT", "HIT", "NORMA", "MARKTKAUF", "GLOBUS", "V-MARKT",
    # AT Supermärkte + Drogerien
    "BILLA", "BILLA PLUS", "HOFER", "SPAR", "INTERSPAR", "EUROSPAR",
    "MERKUR", "MPREIS", "ADEG", "UNIMARKT", "NAH & FRISCH", "MAXIMARKT",
    "BIPA", "BUDNI",
    # Drogerie
    "DM", "ROSSMANN", "MÜLLER", "MUELLER",
    # Elektronik
    "SATURN", "MEDIAMARKT", "MEDIA MARKT", "APPLE", "CONRAD",
    # Möbel / Baumarkt
    "IKEA", "BAUHAUS", "OBI", "HORNBACH", "TOOM", "HAGEBAU", "LAGERHAUS",
    # Kleidung
    "H&M", "ZARA", "C&A", "PRIMARK", "TK MAXX", "DECATHLON",
    # Fast Food / Café
    "MCDONALDS", "MC DONALDS", "BURGER KING", "KFC", "SUBWAY",
    "STARBUCKS", "BACKWERK", "KAMPS", "ANKER", "STROECK", "STRÖCK",
    # Tankstellen
    "SHELL", "ARAL", "ESSO", "JET", "TOTAL", "STAR", "AGIP", "HEM",
    "BP", "OMV", "AVANTI", "TURMÖL", "TURMOEL",
    # Versand / Post
    "DHL", "HERMES", "DPD", "AMAZON", "POST AG", "ÖSTERREICHISCHE POST",
    # Telko
    "A1", "MAGENTA", "T-MOBILE", "TELEKOM", "DREI", "HOT",
    # Verkehr
    "ÖBB", "OEBB", "WESTBAHN", "WIENER LINIEN", "DB BAHN",
    # Apotheken
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
    """MwSt-Betrag extrahieren. Ignoriert Prozent-Angaben (z.B. '19,00 %')."""
    candidates = []
    for i, line in enumerate(lines):
        if not any(kw in line.upper() for kw in _VAT_KEYWORDS):
            continue
        # Alle Zahlen finden — bei "B: 10.00% MwSt von 0.63 = 0.06"
        # wollen wir 0.06 (letzter Wert nach =), nicht 10.00 (Prozent).
        # Strategie: wenn "=" enthalten -> Zahl nach dem letzten "=", sonst letzte Zahl.
        segment = line
        if "=" in line:
            segment = line.rsplit("=", 1)[1]
        # Auch nächste Zeile prüfen (Aldi-Style: "MwSt A 19%" / "0,50")
        m = re.findall(r"(-?\d+[,.]\d{2})", segment)
        if m:
            # Prozent-Werte ausschließen: wenn direkt %-Zeichen folgt
            for match_str in m:
                idx = segment.find(match_str)
                after = segment[idx + len(match_str):idx + len(match_str) + 3]
                if "%" in after:
                    continue
                val = _parse_amount(match_str)
                if val is not None and 0 < val < 100:  # MwSt selten > 100 EUR bei Alltagseinkauf
                    candidates.append(val)
                    break
        elif i + 1 < len(lines):
            nxt = lines[i + 1]
            if _PRICE_ONLY_RE.match(nxt):
                val = _parse_amount(_PRICE_ONLY_RE.match(nxt).group(1))
                if val is not None:
                    candidates.append(val)
    # Falls mehrere MwSt-Sätze (z.B. 10% + 20%) — summieren wenn alle klein
    if candidates:
        return round(sum(candidates), 2)
    return None


_REDUZIERT_MARKERS = ("RABATT", "REDUZ", "AKTION", "SONDERANGEBOT", "-%", "PREISNACHLASS")

# Zeile enthält NUR einen Preis (evtl. mit EUR/€/A/B/C-Marker) — nichts sonst
_PRICE_ONLY_RE = re.compile(r"^\s*(-?\d+[,.]\d{2})\s*(?:EUR|€|[A-Z*]{1,3})?\s*$")

# Payment-Erkennung
_PAYMENT_PATTERNS = [
    (r"\b(BAR|CASH|BARZAHLUNG)\b",                           "cash"),
    (r"\bPAYPAL\b",                                          "paypal"),
    (r"\b(EC|MAESTRO|GIROCARD|DEBIT|BANKOMAT)\b",            "card"),
    (r"\b(VISA|MASTERCARD|AMEX|AMERICAN EXPRESS|KREDITKARTE|CREDIT)\b", "credit"),
    (r"\b(APPLE PAY|GOOGLE PAY|CONTACTLESS)\b",              "card"),
]


def _find_payment(text_upper):
    """Erkennt Zahlungsart im OCR-Text. Priorität: credit > card > paypal > cash."""
    priority = {"cash": 1, "paypal": 2, "card": 3, "credit": 4}
    found = None
    for pattern, method in _PAYMENT_PATTERNS:
        if re.search(pattern, text_upper):
            if found is None or priority[method] > priority[found]:
                found = method
    return found


def _looks_like_description(line):
    """Ist die Zeile eine plausible Item-Beschreibung? (Buchstaben + kein reines Meta)"""
    line = line.strip()
    if len(line) < 3 or len(line) > 60:
        return False
    if _SKIP_LINE_RE.match(line):
        return False
    if any(kw in line.upper() for kw in _TOTAL_KEYWORDS):
        return False
    if any(kw in line.upper() for kw in _VAT_KEYWORDS):
        return False
    # Muss mindestens 2 Buchstaben enthalten (nicht nur Zahlen/Sonderzeichen)
    letters = sum(1 for c in line if c.isalpha())
    if letters < 2:
        return False
    # Bloße Zahl / bloßer Preis raus
    if _PRICE_ONLY_RE.match(line):
        return False
    # Datum, Uhrzeit, Nummern-Zeilen raus
    if re.match(r"^[\d\s:./\-]+$", line):
        return False
    return True


def _extract_items(lines, total):
    """Extrahiert Positionen. Erkennt sowohl einzeilig (Desc + Preis) als auch
    zweizeilig (Desc auf Zeile N, Preis alleine auf Zeile N+1) — typisch für BILLA/REWE.
    """
    items = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if len(line) < 2:
            i += 1
            continue

        # Skip Meta / Total / Vat Zeilen
        if _SKIP_LINE_RE.match(line):
            i += 1
            continue
        line_upper = line.upper()
        if any(kw in line_upper for kw in _VAT_KEYWORDS):
            i += 1
            continue
        # Total-Zeile skippen (Summe wird separat erkannt)
        if any(kw in line_upper for kw in _TOTAL_KEYWORDS):
            i += 1
            continue

        # Fall 1: Zeile enthält Preis am Ende (einzeilig)
        m = _PRICE_RE.search(line)
        price = None
        desc = None
        if m:
            candidate_price = _parse_amount(m.group(1))
            candidate_desc = line[:m.start()].strip()
            candidate_desc = re.sub(r"\s+[A-Z*]{1,3}\s*$", "", candidate_desc).rstrip(" \t.-,")
            # Nur akzeptieren wenn Beschreibung sinnvoll ist
            if candidate_price is not None and len(candidate_desc) >= 2 and any(c.isalpha() for c in candidate_desc):
                price = candidate_price
                desc = candidate_desc

        # Fall 2: Beschreibung alleine, Preis auf nächster Zeile (zweizeilig)
        if price is None and i + 1 < n and _looks_like_description(line):
            # Nächste nicht-leere Zeile suchen (kann Kategorie-Marker "C" o.ä. dazwischen sein)
            j = i + 1
            skipped_marker = None
            while j < n and len(lines[j].strip()) <= 2 and re.match(r"^[A-Z*]$", lines[j].strip()):
                skipped_marker = lines[j].strip()
                j += 1
            if j < n:
                pm = _PRICE_ONLY_RE.match(lines[j])
                if pm:
                    candidate_price = _parse_amount(pm.group(1))
                    if candidate_price is not None:
                        # Beschreibung ggf. um Kategorie-Marker im gleichen Zeilenende bereinigen
                        cleaned = re.sub(r"\s+[A-Z*]{1,3}\s*$", "", line).rstrip(" \t.-,")
                        if len(cleaned) >= 2:
                            price = candidate_price
                            desc = cleaned
                            i = j  # Preis-Zeile mit-konsumieren

        if price is None or desc is None:
            i += 1
            continue

        # Total nie als Position
        if total is not None and abs(price - total) < 0.01:
            i += 1
            continue

        # Reduziert-Erkennung
        line_upper_full = line.upper()
        is_reduced = any(mk in line_upper_full for mk in _REDUZIERT_MARKERS) or price < 0

        # Negative Preise: Rabatt auf letzten Item anwenden
        if price < 0 and items:
            last = items[-1]
            original = last["total_price"]
            new_price = round(original + price, 2)
            if new_price > 0:
                last["original_price"] = original
                last["total_price"] = new_price
                last["is_reduced"] = True
            i += 1
            continue
        if price <= 0:
            i += 1
            continue

        # Mengenangabe "2 x 1,49" o.ä.
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
        i += 1
    return items


def parse_receipt(raw_text, user_stores=None):
    """Nimmt OCR-Rohtext, gibt strukturiertes Dict zurück."""
    if not raw_text:
        return {"store_hint": None, "purchase_date": None,
                "total_amount": None, "vat_amount": None,
                "payment_method": None, "items": []}
    text_upper = raw_text.upper()
    lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]
    extra = [s.upper() for s in (user_stores or [])]
    total = _find_total(lines)
    return {
        "store_hint": _find_store(text_upper, extra_stores=extra),
        "purchase_date": _find_date(raw_text),
        "total_amount": total,
        "vat_amount": _find_vat(lines),
        "payment_method": _find_payment(text_upper),
        "items": _extract_items(lines, total),
    }

