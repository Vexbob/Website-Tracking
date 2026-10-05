"""Depot: den Trade-Republic-Kontoauszug (PDF) lesen (v2.38.0).

Trade Republic gibt den Verlauf als PDF heraus: einen Kontoauszug des
Cashkontos mit einer „Umsatzuebersicht“ -- Datum, Typ, Beschreibung,
Zahlungseingang, Zahlungsausgang, Saldo. Jede Wertpapierbewegung steht dort
als Geldbewegung: der Kauf als Ausgang, der Verkauf als Eingang, die
Dividende als Ertrag.

Drei Stufen, damit die Deutung ohne PDF pruefbar bleibt:

1. ``woerter_aus_pdf``: jedes Wort mit seiner Lage auf der Seite
   (pdfminer). Gearbeitet wird mit Einzelzeichen, nicht mit Zeilen: pdfminer
   legt Typ und Beschreibung gern in EINE Zeile („Ueberweisung PayOut to
   transit“), sobald sie dicht beieinander stehen.
2. ``kontoauszug_lesen``: die Woerter einer Seite gehen ueber ihre
   x-Lage in die Spalten, deren Grenzen jede Seite aus ihrer Kopfzeile
   bekommt. Eine Buchung ist ein Block, getrennt durch einen senkrechten
   Abstand.
3. ``buchung_deuten``: Art, ISIN, Name und -- wo der Auszug sie nennt --
   die Stueckzahl.

Gelesen wird nur, was sich PRUEFEN laesst: jede Zeile traegt den Saldo
danach, also muss Saldo vorher + Eingang - Ausgang den Saldo ergeben, und die
Summen muessen zur Kontouebersicht auf Seite 1 passen. Stimmt eins davon
nicht, wird die Datei abgelehnt statt mit falschen Zahlen gespeichert -- ein
falsch gelesener Betrag saehe genauso aus wie ein richtiger.
"""
import hashlib
import io
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

MAX_BYTES = 15 * 1024 * 1024

MONATE = {
    "jan": 1, "januar": 1, "feb": 2, "februar": 2, "mär": 3, "märz": 3, "mrz": 3,
    "apr": 4, "april": 4, "mai": 5, "jun": 6, "juni": 6, "jul": 7, "juli": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "okt": 10,
    "oktober": 10, "nov": 11, "november": 11, "dez": 12, "dezember": 12,
}

# Senkrechter Abstand (pt), ab dem eine neue Buchung beginnt. Innerhalb einer
# Buchung liegen die Zeilen 3-8 pt auseinander, zwischen zwei Buchungen > 20.
BLOCK_ABSTAND = 12
# Unter dieser Hoehe steht der Seitenfuss (Anschrift, Geschaeftsfuehrer).
FUSS_AB = 740

ISIN = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}[0-9])\b")
STUECK = re.compile(r"quantity:\s*([0-9]+(?:\.[0-9]+)?)", re.I)
# Krypto hat bei Trade Republic eine Pseudo-ISIN mit „XF“.
KRYPTO = {"XF000BTC0017": "Bitcoin", "XF000ETH0019": "Ethereum",
          "XF000SOL0012": "Solana", "XF000XRP0018": "XRP"}

ARTEN = {
    "einzahlung": "Einzahlung", "auszahlung": "Auszahlung",
    "kauf": "Kauf", "sparplan": "Sparplan", "verkauf": "Verkauf",
    "ertrag": "Ertrag", "zinsen": "Zinsen", "steuer": "Steuern",
    "geschenk": "Geschenk", "praemie": "Prämie", "karte": "Karte",
    "sonstiges": "Sonstiges",
}


class LeseFehler(ValueError):
    """Die Datei ist kein lesbarer Kontoauszug -- mit einem Satz, der sagt,
    woran es lag."""


def pruefsumme(roh: bytes) -> str:
    return hashlib.sha256(roh).hexdigest()


# ------------------------------------------------------------ 1) PDF -> Woerter
def woerter_aus_pdf(roh: bytes) -> list:
    """Je Seite eine Liste ``(oben, x0, x1, text)``; ``oben`` waechst nach
    unten. Ein Wort endet an einem Leerzeichen oder einer Luecke > 2,5 pt."""
    if not roh:
        raise LeseFehler("Die Datei ist leer.")
    if len(roh) > MAX_BYTES:
        raise LeseFehler("Die Datei ist größer als 15 MB.")
    if not roh.startswith(b"%PDF"):
        raise LeseFehler("Das ist kein PDF. Trade Republic gibt den Kontoauszug als PDF heraus.")
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTChar, LTTextContainer, LTTextLine
    from pdfminer.pdfparser import PDFSyntaxError

    seiten = []
    try:
        for page in extract_pages(io.BytesIO(roh)):
            woerter = []
            for el in page:
                if not isinstance(el, LTTextContainer):
                    continue
                for line in el:
                    if not isinstance(line, LTTextLine):
                        continue
                    oben = round(page.height - line.y1, 1)
                    wort, vorher = [], None

                    def fertig():
                        if wort:
                            t = "".join(c.get_text() for c in wort).strip()
                            if t:
                                woerter.append((oben, wort[0].x0, wort[-1].x1, t))
                        wort.clear()

                    for c in line:
                        # Ein geschuetztes Leerzeichen („0,00 €“) haelt
                        # Betrag und Waehrung zusammen -- es trennt kein Wort.
                        zeichen = c.get_text() if isinstance(c, LTChar) else " "
                        if not isinstance(c, LTChar) or (zeichen.isspace() and zeichen != "\xa0"):
                            fertig()
                            vorher = None
                            continue
                        if vorher is not None and c.x0 - vorher.x1 > 2.5:
                            fertig()
                        wort.append(c)
                        vorher = c
                    fertig()
            seiten.append(woerter)
    except PDFSyntaxError:
        raise LeseFehler("Das PDF ist beschädigt und lässt sich nicht lesen.")
    return seiten


# --------------------------------------------------------- 2) Woerter -> Zeilen
def betrag(text: str) -> Decimal:
    """„12.345,67 €“ -> Decimal('12345.67'). Leer -> 0."""
    t = (text or "").replace("€", "").replace("\xa0", "").replace(" ", "")
    if not t:
        return Decimal(0)
    t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        raise LeseFehler(f"Betrag nicht lesbar: „{text}“")


def datum(text: str) -> date:
    """„27 Juli 2021“, „24 Aug. 2021“, „04 Sept. 2021“ -> date."""
    teile = text.replace(".", " ").split()
    if len(teile) != 3:
        raise LeseFehler(f"Datum nicht lesbar: „{text}“")
    monat = MONATE.get(teile[1].lower())
    if not monat:
        raise LeseFehler(f"Monat nicht lesbar: „{text}“")
    return date(int(teile[2]), monat, int(teile[0]))


def _zeitraum(alle_woerter) -> tuple:
    """„01 Juli 2021 - 04 Okt. 2026“ aus dem Kopf der ersten Seite."""
    text = " ".join(w[3] for w in sorted(alle_woerter, key=lambda w: (w[0], w[1])))
    m = re.search(r"(\d{1,2} [A-Za-zäÄ]+\.? \d{4}) - (\d{1,2} [A-Za-zäÄ]+\.? \d{4})", text)
    if not m:
        return None, None
    return datum(m.group(1)), datum(m.group(2))


def _kontouebersicht(woerter) -> dict:
    """Die Zeile „Cashkonto“ unter KONTOÜBERSICHT: Anfangssaldo, Eingang,
    Ausgang, Endsaldo -- die Summen, gegen die die Buchungen geprueft werden."""
    zeile = next((w for w in woerter if w[3] == "Cashkonto"), None)
    if not zeile:
        return {}
    werte = [w for w in woerter if abs(w[0] - zeile[0]) < 2 and w[1] > zeile[2] and "€" in w[3]]
    werte.sort(key=lambda w: w[1])
    if len(werte) != 4:
        return {}
    a, e, aus, end = (betrag(w[3]) for w in werte)
    return {"anfangssaldo": a, "eingang": e, "ausgang": aus, "endsaldo": end}


def _spalten(woerter):
    """Die Spaltengrenzen aus der Kopfzeile der Umsatztabelle -- oder None,
    wenn die Seite keine hat."""
    kopf = [w for w in woerter if w[3] == "BESCHREIBUNG"]
    if not kopf:
        return None
    oben = kopf[0][0]
    zeile = {w[3]: w for w in woerter if abs(w[0] - oben) < 2}
    noetig = ("TYP", "BESCHREIBUNG", "ZAHLUNGSEINGANG", "ZAHLUNGSAUSGANG", "SALDO")
    if any(n not in zeile for n in noetig):
        return None
    # Die Betraege stehen rechtsbuendig: ihr LINKER Rand wandert mit der
    # Laenge der Zahl („6,66 €“ gegen „1.470,03 €“), ihr RECHTER steht fest
    # unter dem Ende der Spaltenueberschrift. Zugeordnet wird deshalb ueber
    # den rechten Rand.
    return {
        "oben": oben,
        "typ": zeile["TYP"][1],
        "besch": zeile["BESCHREIBUNG"][1],
        "betraege_ab": zeile["ZAHLUNGSEINGANG"][1] - 10,
        "ein_bis": zeile["ZAHLUNGSEINGANG"][2] + 2,
        "aus_bis": zeile["ZAHLUNGSAUSGANG"][2] + 2,
    }


# Was nach der Umsatztabelle kommt (Seite mit Barmitteln und Geldmarktfonds).
# Ab hier ist es keine Buchung des Cashkontos mehr.
TABELLEN_ENDE = ("BARMITTELÜBERSICHT", "TREUHANDKONTEN", "GELDMARKTFONDS",
                 "TRANSAKTIONSÜBERSICHT", "HINWEISE")


def _bloecke(woerter, sp) -> list:
    ende = min((w[0] for w in woerter if w[3] in TABELLEN_ENDE and w[0] > sp["oben"]),
               default=FUSS_AB)
    rumpf = sorted((w for w in woerter if sp["oben"] + 3 < w[0] < min(ende, FUSS_AB)),
                   key=lambda w: (w[0], w[1]))
    bloecke, jetzt, letzte = [], [], None
    for w in rumpf:
        if letzte is not None and w[0] - letzte > BLOCK_ABSTAND:
            bloecke.append(jetzt)
            jetzt = []
        jetzt.append(w)
        letzte = w[0]
    if jetzt:
        bloecke.append(jetzt)
    return bloecke


def _zeile_aus_block(block, sp) -> dict:
    spalte = defaultdict(list)
    for oben, x0, x1, t in sorted(block, key=lambda w: (w[0], w[1])):
        if x0 < sp["typ"] - 2:
            spalte["datum"].append(t)
        elif x0 < sp["besch"] - 2:
            spalte["typ"].append(t)
        elif x0 < sp["betraege_ab"]:
            spalte["besch"].append((oben, t))
        elif x1 <= sp["ein_bis"]:
            spalte["ein"].append(t)
        elif x1 <= sp["aus_bis"]:
            spalte["aus"].append(t)
        else:
            spalte["saldo"].append(t)
    # Die Beschreibung bricht ueber Zeilen um. Endet eine Zeile mit „-“, war
    # es eine Worttrennung („All-“ / „World“), sonst ein Leerzeichen.
    zeilen = defaultdict(list)
    for oben, t in spalte["besch"]:
        zeilen[oben].append(t)
    besch = ""
    for oben in sorted(zeilen):
        teil = " ".join(zeilen[oben])
        # Nur ein Strich AM Wort ist eine Trennung; ein freistehender („EUROPA
        # - Beispiel“) bleibt mit Leerzeichen stehen.
        getrennt = besch.endswith("-") and not besch.endswith(" -")
        besch = (besch + teil) if getrennt else (besch + " " + teil if besch else teil)
    return {
        "datum": " ".join(spalte["datum"]),
        "typ": " ".join(spalte["typ"]),
        "beschreibung": besch,
        "ein": " ".join(spalte["ein"]),
        "aus": " ".join(spalte["aus"]),
        "saldo": " ".join(spalte["saldo"]),
    }


def kontoauszug_lesen(seiten) -> dict:
    """Alle Buchungen samt Pruefung. Wirft ``LeseFehler``, wenn es kein
    Trade-Republic-Kontoauszug ist oder die Zahlen nicht aufgehen."""
    if not seiten or not any(seiten):
        raise LeseFehler("Im PDF steht kein Text – ist es ein eingescanntes Bild?")
    erste = seiten[0]
    if not any("TRADE" in w[3] for w in erste) or not any(w[3] == "UMSATZÜBERSICHT" for w in erste):
        raise LeseFehler("Das ist kein Trade-Republic-Kontoauszug (keine Umsatzübersicht auf Seite 1).")
    von, bis = _zeitraum(erste)
    uebersicht = _kontouebersicht(erste)
    if not uebersicht:
        raise LeseFehler("Die Kontoübersicht auf Seite 1 ist nicht lesbar.")

    buchungen, saldo, fehler = [], uebersicht["anfangssaldo"], []
    for nr, woerter in enumerate(seiten, start=1):
        sp = _spalten(woerter)
        if not sp:
            continue
        for block in _bloecke(woerter, sp):
            z = _zeile_aus_block(block, sp)
            if not z["datum"] or not z["saldo"]:
                continue
            ein, aus, nach = betrag(z["ein"]), betrag(z["aus"]), betrag(z["saldo"])
            tag = datum(z["datum"])
            if saldo + ein - aus != nach:
                fehler.append(f"Seite {nr}, {tag.strftime('%d.%m.%Y')}: Saldo {nach} passt nicht "
                              f"zu {saldo} + {ein} − {aus}")
            saldo = nach
            gedeutet = buchung_deuten(z["typ"], z["beschreibung"], ein, aus)
            buchungen.append({
                "datum": tag, "typ": z["typ"], "beschreibung": z["beschreibung"],
                "betrag": ein - aus, "saldo": nach, "seite": nr, **gedeutet,
            })
    if not buchungen:
        raise LeseFehler("Keine Buchungen gefunden.")
    summe_ein = sum((b["betrag"] for b in buchungen if b["betrag"] > 0), Decimal(0))
    summe_aus = -sum((b["betrag"] for b in buchungen if b["betrag"] < 0), Decimal(0))
    if summe_ein != uebersicht["eingang"] or summe_aus != uebersicht["ausgang"] \
            or saldo != uebersicht["endsaldo"]:
        fehler.append(
            f"Summen passen nicht zur Kontoübersicht: Eingang {summe_ein} statt "
            f"{uebersicht['eingang']}, Ausgang {summe_aus} statt {uebersicht['ausgang']}, "
            f"Endsaldo {saldo} statt {uebersicht['endsaldo']}")
    if fehler:
        raise LeseFehler("Der Auszug ließ sich nicht fehlerfrei lesen – nichts gespeichert. "
                         + fehler[0] + (f" (und {len(fehler) - 1} weitere)" if len(fehler) > 1 else ""))
    return {
        "von": von or buchungen[0]["datum"], "bis": bis or buchungen[-1]["datum"],
        "anfangssaldo": uebersicht["anfangssaldo"], "endsaldo": saldo,
        "summe_ein": summe_ein, "summe_aus": summe_aus, "buchungen": buchungen,
    }


# ------------------------------------------------------- 3) Buchung deuten
def _name(beschreibung: str, isin: str) -> str:
    """Der Wertpapiername nach der ISIN, ohne Auftragsnummer und Stueckzahl.
    Englische Zeilen schreiben „Emittent - Fondsname“; gezeigt wird der
    Fondsname."""
    if isin in KRYPTO:
        return KRYPTO[isin]
    rest = beschreibung.split(isin, 1)[1] if isin in beschreibung else ""
    rest = re.split(r",\s*quantity:", rest, flags=re.I)[0]
    rest = re.sub(r"\s+[A-Z]?\d{8,}(\s+\S+)?\s*$", "", rest)   # Auftragsnummer (+ Kuerzel)
    rest = rest.strip(" ,")
    # „Emittent - Fondsname“: der Fondsname ist die Auskunft. Ist der Teil
    # nach dem Strich aber nur ein Anhaengsel („… UCITS ETF - EUR“), bleibt
    # der Teil davor.
    if " - " in rest and re.search(r"[a-z]", rest):
        vorne, hinten = rest.split(" - ", 1)
        rest = hinten if len(hinten.split()) >= 3 else vorne
    return rest or isin


def bester_name(namen) -> str:
    """Aus allen Schreibweisen eines Wertpapiers die lesbarste: eine mit
    Kleinbuchstaben („Beispiel Core Index 500 …“) vor dem Boersenkuerzel
    („BSPVII-CORE IDX500 DLACC“), unter gleichen die haeufigste."""
    from collections import Counter
    zaehler = Counter(n for n in namen if n)
    if not zaehler:
        return ""
    lesbar = [n for n in zaehler if re.search(r"[a-z]", n) and not ISIN.fullmatch(n)]
    kandidaten = lesbar or [n for n in zaehler if not ISIN.fullmatch(n)] or list(zaehler)
    return max(kandidaten, key=lambda n: (zaehler[n], len(n)))


def buchung_deuten(typ: str, beschreibung: str, ein: Decimal, aus: Decimal) -> dict:
    """Art, ISIN, Name und Stueck einer Buchung. Was der Auszug nicht nennt,
    bleibt leer -- eine Stueckzahl wird nie aus Betrag und Kurs geraten."""
    t, b = (typ or "").strip().lower(), beschreibung or ""
    bl = b.lower()
    m = ISIN.search(b)
    isin = m.group(1) if m else None
    s = STUECK.search(b)
    stueck = Decimal(s.group(1)) if s else None
    eingang = ein > 0

    if t == "handel":
        if "savings plan" in bl or "sparplan" in bl:
            art = "sparplan"
        elif "verkauf" in bl or "sell" in bl:
            art = "verkauf"
        elif "kauf" in bl or "buy" in bl:
            art = "kauf"
        else:
            art = "verkauf" if eingang else "kauf"
    elif t in ("überweisung", "ueberweisung"):
        art = "einzahlung" if eingang else "auszahlung"
    elif t == "ertrag":
        art = "ertrag"
    elif t == "zinsen":
        art = "zinsen"
    elif t == "steuern":
        art = "steuer"
    elif t == "geschenk":
        art = "geschenk"
    elif t in ("empfehlung", "prämie", "praemie", "bonus"):
        art = "praemie"
    elif "karte" in t or "card" in t:
        art = "karte"
    else:
        art = "sonstiges"
    return {
        "art": art,
        "isin": isin,
        "name": _name(b, isin) if isin and art in ("kauf", "sparplan", "verkauf", "ertrag", "geschenk") else None,
        "stueck": stueck,
    }


def lesen(roh: bytes) -> dict:
    """PDF -> gepruefter Kontoauszug."""
    return kontoauszug_lesen(woerter_aus_pdf(roh))
