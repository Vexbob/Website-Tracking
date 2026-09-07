"""KI-gestützter Kassenbon-Parser (Gemini).

Nimmt OCR-Rohtext + User-Kategorien + User-Läden + bekannte Beleg-Typen entgegen
und gibt ein strukturiertes Dict im gleichen Format wie
``services.receipt_parser.parse_receipt`` zurück — zusätzlich mit den Feldern
``currency`` und ``expense_type`` sowie pro Item ``quantity`` (Stückzahl),
``brand_name`` und ``category_id``.

Die Zahlungsart wird bewusst NICHT mehr erkannt, und eine Mengeneinheit gibt es
nicht mehr: ``quantity`` ist die Stückzahl (fast immer 1), Gewicht und
Packungsgröße bleiben im ``original_text`` stehen.

Konfiguration per ENV:
    GEMINI_API_KEY   API-Key von Google AI Studio (https://aistudio.google.com/apikey)
    GEMINI_MODEL     Optional. Modellname, default ``gemini-flash-latest``.

Fehlt ``GEMINI_API_KEY`` oder schlägt der Aufruf fehl, wird transparent auf
den regex-basierten Parser (``receipt_parser.parse_receipt``) zurückgefallen.
Der Aufrufer bekommt in beiden Fällen ein Dict mit derselben Struktur.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional

from services.receipt_parser import parse_receipt as _regex_parse_receipt

logger = logging.getLogger("vexbob.ai_receipt")

# ---------------------------------------------------------------------------
# Client-Singleton (lazy)
# ---------------------------------------------------------------------------
_client = None
_client_init_tried = False
_client_init_error: Optional[str] = None  # Grund warum kein Client verfuegbar ist


def _get_model_name() -> str:
    # v1.16.0: Default auf "gemini-flash-latest" (staerkeres Modell) statt
    # flash-lite, weil der Lite-Modell zu oft Produktnamen kappt
    # ("gerösteter Mais" wurde nur zu "Mais"). Kann via ENV ueberschrieben werden.
    return os.getenv("GEMINI_MODEL", "gemini-flash-latest")


def _get_client():
    """Lazy-Init des Gemini-Clients. Gibt None zurueck, wenn nicht konfiguriert."""
    global _client, _client_init_tried, _client_init_error
    if _client_init_tried:
        return _client
    _client_init_tried = True

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        _client_init_error = "GEMINI_API_KEY nicht gesetzt"
        logger.warning("GEMINI_API_KEY nicht gesetzt - AI-Parser deaktiviert, Fallback auf Regex-Parser.")
        return None
    try:
        from google import genai  # type: ignore
        _client = genai.Client(api_key=api_key)
        logger.info("Gemini-Client initialisiert (Modell: %s)", _get_model_name())
    except ImportError as e:
        _client_init_error = f"google-genai Paket nicht installiert: {e}"
        logger.warning("google-genai Paket fehlt: %s", e)
        _client = None
    except Exception as e:
        _client_init_error = f"Client-Init-Fehler: {e}"
        logger.warning("Gemini-Client-Init fehlgeschlagen: %s", e)
        _client = None
    return _client


# ---------------------------------------------------------------------------
# System-Prompt (Template; {categories_json}/{stores_json} werden ersetzt)
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT_TEMPLATE = """Du bist ein präziser Kassenbon-Parser. Du extrahierst strukturierte Daten aus OCR-Texten von beliebigen Belegen (Supermarkt, Drogerie, Tankstelle, Bäcker, Restaurant, Online-Shop, Baumarkt, kleine Läden — jedes Format).

Antworte AUSSCHLIESSLICH mit einem einzigen validen JSON-Objekt. Kein Markdown, kein Kommentar, kein Prefix.

===== KONTEXT DES USERS =====

USER-KATEGORIEN (nutze exakt diese ID+Name wenn passend):
{categories_json}

USER-LÄDEN (matche case-insensitive gegen Namen, sonst erkannten Ladennamen vom Bon nutzen):
{stores_json}

BEKANNTE BELEG-TYPEN des Users (für expense_type bevorzugt EXAKT einen davon nehmen):
{expense_types_json}

===== KOPFDATEN (top-level Felder) =====

- store_hint (string|null): Name des Geschäfts. Wenn ein User-Laden case-insensitive matcht, exakt dessen Namen zurückgeben. Sonst: den Namen vom Bon lesbar formatieren ("BAECKEREI MUELLER" → "Bäckerei Müller"; "REWE" bleibt "Rewe"). Bei Online-Shops: Shop-Name (z.B. "Amazon", "Zalando"). Nicht erkennbar → null.

- purchase_date (string|null): Kaufdatum im ISO-Format YYYY-MM-DD. Bei mehreren Daten: das früheste. Nicht erkennbar → null.

- currency (string|null): "EUR" bei €/EUR/AT-DE-Bons, sonst ISO-3-Code. Nicht erkennbar → null.

- total_amount (float): Endsumme die gezahlt wurde. Keywords: "Summe", "Gesamt(betrag)", "Endsumme", "Zu zahlen", "Zahlbetrag", "Total". NICHT die Zwischensumme, NICHT die MwSt, NICHT das Rückgeld. Bei nur einem sichtbaren Betrag: diesen nehmen.

- vat_amount (float|null): Summe aller absoluten MwSt-Beträge (nicht Prozente). Bei mehreren Steuersätzen alle addieren. Beispiel: "10% MwSt = 0.06" + "20% MwSt = 1.84" → 1.90. Nicht erkennbar → null.

- expense_type (string): PFLICHT. Die grobe Art des Belegs — eine Ebene ÜBER den Positions-Kategorien.
  Nimm bevorzugt EXAKT einen dieser fünf Standard-Schlüssel:
    "receipt"       → Einkauf im Laden: Supermarkt, Drogerie, Bäcker, Tankstelle,
                      Baumarkt, Kiosk, Apotheke — der Normalfall.
    "online_order"  → Versandhandel / Online-Bestellung (Amazon, Zalando, Shop-Rechnung,
                      Beleg mit Bestellnummer und Versandadresse).
    "restaurant"    → Vor Ort verzehrt oder geliefert: Restaurant, Café, Bar, Imbiss,
                      Lieferdienst. Erkennbar an Tisch-/Kellner-Nummer, Gedeck, Trinkgeld.
    "subscription"  → Wiederkehrende Rechnung: Streaming, Mobilfunk, Internet, Strom, Gas,
                      Miete, Versicherung, Vereinsbeitrag, Software-Abo.
    "other"         → nur wenn nichts passt UND kein eigener Name sinnvoll ist.
  Passt keiner der fünf, hat der Beleg aber eine klar benennbare Art, dann gib stattdessen
  einen kurzen deutschen Namen im Singular zurück (z.B. "Arztrechnung", "Handwerker",
  "Ticket", "Spende", "Reparatur"). Steht diese Art schon in den BEKANNTEN BELEG-TYPEN
  oben, dann exakt deren Schreibweise nutzen — keine zweite Variante desselben Typs erfinden.

===== ITEMS (Array von Positions-Objekten) =====

Ein Objekt pro Zeile auf dem Bon. Kopfdaten (Summe/MwSt/Zwischensumme) NIEMALS als Item.

Pflichtfelder pro Item:

- base_name (string): sprechender deutscher PRODUKTNAME OHNE Menge/Einheit, ABER MIT
  charakterisierenden Adjektiven & Sorten-/Zubereitungs-Hinweisen.
  Regeln:
    · Erste Buchstabe groß, Umlaute korrekt (nicht "Aepfel" → "Äpfel").
    · Beschreibt das Produkt so präzise wie möglich: enthaltene Adjektive,
      Sorten, Zubereitungs-Hinweise (gebraten, geröstet, gewürzt, gesalzen,
      geräuchert, mariniert, tiefgekühlt, in Öl, in Salzlake, bio, vegan,
      laktosefrei, glutenfrei, vollkorn, halbfett, dunkel/hell, süß/sauer, ...)
      MÜSSEN erhalten bleiben.
    · Keine Marke im base_name (die kommt separat in ``brand_name``).
    · Keine Menge, keine Einheit, keine Packungsgröße — die bleiben im
      ``original_text`` stehen und werden sonst nicht ausgewertet.
    · Bei etablierten deutschen Bezeichnungen (Klopapier, Vollmilch) diese verwenden.
    · Bei generischen Kategorien wie "Diesel", "Zeitschrift", "Trinkgeld"
      steht dort nur die Gattung.
  Beispiele:
    · Bon "Clever Äpfel 2kg"                    → "Äpfel"
    · Bon "C1. ESL-Vollm. 1L"                   → "Vollmilch"
    · Bon "Gillette Rasiergel Sensitive"        → "Rasiergel sensitiv"
    · Bon "BI HOME TOPA 10X180 BLATT"           → "Klopapier"
    · Bon "Ye! Salted Roasted Corn 200g"        → "Mais geröstet gesalzen"
    · Bon "Chef Sel. Hendlbrust gegrillt 400g"  → "Hähnchenbrust gegrillt"
    · Bon "Iglo Fischstäbchen paniert 450g"     → "Fischstäbchen paniert"
    · Bon "Bio Vollkorn-Haferflocken 500g"      → "Haferflocken Vollkorn Bio"
    · Bon "Actimel Erdbeere 8x100g"             → "Trinkjoghurt Erdbeere"
    · Bon "Diesel"                              → "Diesel"

- original_text (string): der bereinigte Text vom Kassenbon (ohne Steuer-Buchstaben,
  ohne Zeilenrauschen), MIT Menge und Packungsgröße. Bei zweizeiligen Artikeln beide
  Zeilen zusammenführen.
  Beispiele:
    · Bon "C1. ESL-Vollm. 1L"   → "ESL-Vollm. 1L"
    · Bon "A Clever Äpfel 2kg"  → "Clever Äpfel 2kg"

- brand_name (string|null): Erkannte Marke, wenn sie im Artikeltext steht.
  Regeln:
    · Marken-Namen in lesbarer Schreibweise zurückgeben ("Milbona" statt "MILBONA").
    · Bei generischen Waren ohne Marke (Obst/Gemuese lose, Backwaren aus der Theke,
      Kraftstoff, Trinkgeld, Rabatt, Pfand): null.
    · Im Zweifel null — auf den meisten Bons steht keine Marke.
    · Eigenmarken sollen NICHT als base_name auftauchen. Beispiel:
        Bon "Clever Äpfel 2kg" → base_name="Äpfel", brand_name="clever"

- quantity (int): STÜCKZAHL dieser Position — wie oft derselbe Artikel gekauft wurde.
  Standard ist 1, und 1 ist auch fast immer richtig.
  Größer als 1 NUR, wenn der Bon denselben Artikel in EINER Zeile mehrfach abrechnet:
    · "3 x 1,49        4,47"   → quantity=3, total_price=4.47
    · "2 Stk Butter"           → quantity=2
  Gewicht, Volumen und Packungsgröße sind KEINE Menge in diesem Sinn — sie bleiben
  im original_text und ergeben quantity=1:
    · "Äpfel 2kg"              → quantity=1
    · "0,652 kg x 2,99 EUR/kg" → quantity=1
    · "Haferflocken 500g"      → quantity=1
    · "Wasser 6x1,5L"          → quantity=1 (eine Packung)
  Es gibt kein Einheiten-Feld mehr. Gib niemals 500 (Gramm) oder 1.5 (Liter) zurück.

- unit_price (float|null): Preis pro Stück. Bei quantity=1 identisch mit total_price,
  bei "3 x 1,49" also 1.49. Nicht ermittelbar → null.

- total_price (float): Preis DIESER Position insgesamt (was für sie bezahlt wurde).
  Bei "3x1,49 = 4,47" → 4.47.

- price_comparable (bool): TRUE für Verbrauchsgüter, die man regelmäßig neu kauft und die
  deshalb in die Produktliste gehören. FALSE für Einmalkäufe, die dort nur Störrauschen sind.
  TRUE für: Lebensmittel, Getränke, Kaffee/Tee, Alkohol, Tabak, Drogerie, Haushalt-Reinigung,
    Kraftstoff, Tiernahrung, Baby-Verbrauch, Apotheke-Verbrauch.
  FALSE für: langlebige Gebrauchsgegenstände (Topf, Pfanne, Vorratsdose, Sieb),
    Elektronik/Werkzeug (Kabel, Ladegerät, Schraubendreher), Kleidung/Schuhe, Deko/Geschenke,
    Bücher, Möbel, einzelne Baumarkt-Sonderposten, Restaurant-Bestellungen, Blumen/Pflanzen,
    Pfand-, Rabatt- und Trinkgeld-Zeilen.
  Bei Unsicherheit → TRUE (Verbrauchsgut ist wahrscheinlicher).

- is_reduced (bool): TRUE wenn Artikel reduziert war. Erkennungsmuster:
  · zwei Preise nebeneinander, einer durchgestrichen → is_reduced=true, original_price = höherer Wert
  · "Reduziert" / "-50%" / "MHD" / "Sofort verzehr" / "Aktion" / "Sonderpreis" / "Angebot"
  Sonst FALSE.

- original_price (float|null): Wenn is_reduced=true UND ursprünglicher höherer Preis erkennbar:
  dieser Wert. Sonst null. NIE gleich total_price.

- category_id (int|null): Wenn category_name EXAKT einer User-Kategorie (case-insensitiv)
  entspricht: deren ID. Sonst null.

- category_name (string): PFLICHT, nie null. Kurzer deutscher Name. Bevorzugt EXAKT aus dieser
  bereichsgegliederten Liste (Groß-/Kleinschreibung und "&" beachten):

  ▸ Lebensmittel:
    "Obst & Gemüse", "Milchprodukte", "Käse", "Eier",
    "Fleisch & Wurst", "Fisch & Meeresfrüchte",
    "Brot & Backwaren", "Nudeln, Reis & Getreide",
    "Konserven", "Tiefkühlkost", "Fertiggerichte",
    "Gewürze & Öl", "Aufstriche & Süßes zum Brot",
    "Süßwaren", "Snacks & Chips", "Nüsse & Trockenfrüchte",
    "Bio & Vegan"

  ▸ Getränke:
    "Wasser & Softdrinks", "Säfte", "Kaffee & Tee",
    "Bier", "Wein & Sekt", "Spirituosen"

  ▸ Drogerie & Gesundheit:
    "Körperpflege", "Kosmetik & Make-up", "Zahnpflege",
    "Rasur & Haarpflege", "Damenhygiene",
    "Apotheke & Medikamente", "Vitamine & Nahrungsergänzung",
    "Erste Hilfe & Verband"

  ▸ Haushalt:
    "Wasch- & Putzmittel", "Toilettenpapier & Küchentücher",
    "Müllbeutel & Zubehör", "Batterien & Glühbirnen",
    "Küchenzubehör (Verbrauch)", "Haushaltsgeräte (Anschaffung)",
    "Wäsche & Textilpflege"

  ▸ Wohnen & Fixkosten:
    "Miete", "Nebenkosten", "Strom", "Gas & Heizung", "Wasser",
    "Internet & Telefon", "Mobilfunk",
    "Rundfunkbeitrag", "Versicherung",
    "Möbel", "Dekoration", "Bettwäsche & Handtücher"

  ▸ Mobilität:
    "Kraftstoff", "Auto-Wartung & Reparatur", "Auto-Zubehör",
    "Parkgebühren & Maut", "Öffentlicher Verkehr",
    "Taxi & Sharing", "Fahrrad"

  ▸ Essen auswärts:
    "Restaurant", "Café & Bäckerei",
    "Fast Food", "Lieferdienst", "Trinkgeld"

  ▸ Kinder & Tier:
    "Baby-Nahrung", "Windeln & Babypflege",
    "Kinder-Spielzeug & Bedarf",
    "Tiernahrung", "Tierbedarf & Zubehör"

  ▸ Freizeit & Bildung:
    "Bücher & Zeitschriften", "Kino, Konzert & Events",
    "Museum & Kultur", "Sport & Fitness-Studio",
    "Sportartikel", "Streaming & Abos",
    "Software & Apps", "Kurse & Weiterbildung"

  ▸ Sonstige Anschaffungen:
    "Kleidung", "Schuhe", "Accessoires & Schmuck",
    "Elektronik", "Handy & Zubehör", "Computer & Zubehör",
    "Werkzeug & Baumarkt", "Garten & Pflanzen",
    "Hobby & Bastelbedarf"

  ▸ Sonstiges:
    "Post & Versand", "Bürobedarf",
    "Geschenke", "Spenden",
    "Tabak & Rauchwaren", "Glücksspiel & Lotto",
    "Bankgebühren",
    "Pfand", "Rabatt",
    "Sonstiges"

  Regeln:
    · Wähle die spezifischste passende Kategorie ("Käse" statt "Milchprodukte" wenn Käse).
    · "Milchprodukte" nur für Milch/Joghurt/Butter/Sahne/Quark/Skyr — Käse gehört zu "Käse".
    · "Küchenzubehör (Verbrauch)" = Schwämme, Backpapier, Alufolie, Frischhaltefolie, Papiertüten.
    · "Haushaltsgeräte (Anschaffung)" = Kaffeemaschine, Wasserkocher, Toaster (mit price_comparable=false).
    · "Möbel" und "Dekoration" nur bei tatsächlich langlebigen Möbeln/Deko (price_comparable=false).
    · Diese Namen exakt so schreiben — also "Snacks & Chips", nicht "Snacks & Knabberzeug".
    · Wenn NICHTS passt: eigener kurzer Name (Singular). "Sonstiges" nur als absolut letzter Fallback.

===== SCHWIERIGE FÄLLE =====

· Derselbe Artikel mehrfach: steht er als Multiplikator-Zeile auf dem Bon ("3 x 1,49  4,47"),
  ist das EIN Item mit quantity=3. Stehen die Artikel als getrennte Zeilen untereinander,
  bleiben es getrennte Items mit quantity=1 — nicht zusammenrechnen.
· Rabatt-Zeile am Ende (z.B. "-5% Rabatt -2,50"): eigenes Item mit base_name="Rabatt",
  price_comparable=false, negativem total_price.
· Pfand: eigenes Item mit base_name="Pfand", price_comparable=false.
· Trinkgeld: eigenes Item, base_name="Trinkgeld", price_comparable=false.
· Tankstelle: Kraftstoff als Item, quantity=1 (die Liter stehen im original_text),
  price_comparable=true, category_name="Kraftstoff", expense_type="receipt".
· Zweizeilige Positionen: Name in Zeile N, Preis in Zeile N+1 → zu einem Item zusammenführen.
· Beleg ohne erkennbare Einzelpositionen: items=[]. Keine Fake-Items erfinden.
· OCR-Fehler bei Preisen: "l.32" → 1.32, "0.6Q" → 0.69, "1,ЗЗ" → 1.33 (kyrillisch).
· Ganzzahlen ohne Komma sind gültige Preise: "3" = 3.00 (nur wenn Preis-Position klar).

===== IGNORIEREN =====

Ignoriere alles was nicht zu Kopfdaten oder Positionen gehört: Belegnummern, Trace-/Terminal-IDs,
Kassen-/Bediener-/Filialnummern, Steuer-IDs (ATU/USt-Id), Adressen, Telefon, Websites,
Werbetexte ("Vielen Dank", "Kundenbeleg"), Karten-Dummies (####1743), Zeitstempel,
Öffnungszeiten, die Zahlungsart (Bar/EC/Karte/PayPal — wird bewusst nicht mehr erfasst),
Rückgeld-Betrag (NICHT mit total_amount verwechseln!).

===== JSON-STRUKTUR (Beispiel Billa-Bon) =====

{{
  "store_hint": "Billa",
  "purchase_date": "2026-08-13",
  "currency": "EUR",
  "total_amount": 17.72,
  "vat_amount": 2.18,
  "expense_type": "receipt",
  "items": [
    {{
      "base_name": "Äpfel",
      "brand_name": "clever",
      "original_text": "Clever Äpfel 2kg",
      "quantity": 1,
      "unit_price": 3.32,
      "total_price": 3.32,
      "price_comparable": true,
      "is_reduced": false,
      "original_price": null,
      "category_id": null,
      "category_name": "Obst & Gemüse"
    }},
    {{
      "base_name": "Klopapier",
      "brand_name": "BI HOME",
      "original_text": "BI HOME TOPA 10X180 BLATT",
      "quantity": 1,
      "unit_price": 4.99,
      "total_price": 4.99,
      "price_comparable": true,
      "is_reduced": false,
      "original_price": null,
      "category_id": null,
      "category_name": "Toilettenpapier & Küchentücher"
    }},
    {{
      "base_name": "Mais geröstet gesalzen",
      "brand_name": null,
      "original_text": "3 x Ye! Salted Roasted Corn 200g",
      "quantity": 3,
      "unit_price": 1.99,
      "total_price": 5.97,
      "price_comparable": true,
      "is_reduced": false,
      "original_price": null,
      "category_id": null,
      "category_name": "Snacks & Chips"
    }}
  ]
}}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Die fünf eingebauten Beleg-Typen. Alles andere, was das Modell liefert, ist ein
# frei benannter Typ des Users (z.B. "Arztrechnung") und wird als Klartext
# gespeichert -- der Router baut die Auswahlliste aus genau diesen Werten.
_BUILTIN_EXPENSE_TYPES = {"receipt", "online_order", "restaurant", "subscription", "other"}

# Deutsche Schreibweisen, die das Modell statt des Schlüssels liefern kann.
_EXPENSE_TYPE_ALIASES = {
    "kassenbon": "receipt", "bon": "receipt", "einkauf": "receipt",
    "supermarkt": "receipt", "beleg": "receipt", "kassenzettel": "receipt",
    "online": "online_order", "online-bestellung": "online_order",
    "onlinebestellung": "online_order", "bestellung": "online_order",
    "versandhandel": "online_order", "online_order": "online_order",
    "restaurant": "restaurant", "gastronomie": "restaurant", "lokal": "restaurant",
    "cafe": "restaurant", "café": "restaurant", "lieferdienst": "restaurant",
    "abo": "subscription", "abonnement": "subscription", "subscription": "subscription",
    "rechnung": "subscription", "fixkosten": "subscription",
    "sonstiges": "other", "sonstige": "other", "other": "other",
}
_MAX_EXPENSE_TYPE_LEN = 40


def normalize_expense_type(raw) -> Optional[str]:
    """Bringt den vom Modell gelieferten Typ auf einen Schlüssel oder einen
    kurzen Klartext-Namen. Gibt None zurück, wenn nichts Brauchbares kam."""
    v = _str_or_none(raw)
    if not v:
        return None
    low = v.strip().lower()
    if low in _BUILTIN_EXPENSE_TYPES:
        return low
    mapped = _EXPENSE_TYPE_ALIASES.get(low)
    if mapped:
        return mapped
    # Eigener Typ: Klartext behalten, aber gedeckelt und ohne Zeilenumbrüche.
    clean = re.sub(r"\s+", " ", v).strip()[:_MAX_EXPENSE_TYPE_LEN].strip()
    return clean or None


def _clean_quantity(raw) -> int:
    """``quantity`` ist seit v1.52.0 eine reine Stückzahl.

    Frühere Prompts liessen Gewichte zu ("500" mit Einheit "g"), und auch das
    aktuelle Modell rutscht gelegentlich noch dahin zurück. Alles, was keine
    plausible Stückzahl ist, wird deshalb auf 1 zurückgesetzt -- lieber ein
    verlorenes "3x" als eine Position, die als 500 Stück gezählt wird.
    """
    q = _to_float(raw)
    if q is None:
        return 1
    q = round(q)
    if q < 1 or q > 99:
        return 1
    return int(q)


# Menge + Einheit am Ende eines Artikelnamens ("Haferflocken 500g", "Milch 1 L").
# Der Name wird darum gekuerzt, damit "Haferflocken 500g" und "Haferflocken 1kg"
# zur selben Produktgruppe gehoeren. Der Wert selbst geht nicht verloren: er
# steht im ``original_text``, der den Bon-Text unveraendert mitfuehrt.
_NAME_QTY_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|kilogramm|kilo|gramm|gr|g|liter|ltr|l|milliliter|ml|cl|"
    r"stk\.?|st\.?|stueck|stück|pack(?:ung)?|pck|btl|beutel|flasche|blatt|rolle|dose|glas)"
    r"\s*$",
    re.IGNORECASE)
_MAX_OCR_CHARS = 20_000  # DoS-/Kostenschutz; typische Bons < 2k


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    if isinstance(v, str):
        s = v.strip().replace(" ", "")
        if not s:
            return None
        # "1.234,56" -> "1234.56"; "1,66" -> "1.66"
        if "," in s and s.count(",") == 1 and s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _to_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _str_or_none(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _normalize_parsed(raw: dict, valid_cat_ids: set) -> dict:
    """Normalisiert & sanitisiert das rohe AI-JSON auf unser Zielformat."""
    out: dict = {
        "store_hint": _str_or_none(raw.get("store_hint")),
        "purchase_date": _str_or_none(raw.get("purchase_date")),
        "currency": _str_or_none(raw.get("currency")),
        "total_amount": _to_float(raw.get("total_amount")),
        "vat_amount": _to_float(raw.get("vat_amount")),
        "expense_type": normalize_expense_type(raw.get("expense_type")) or "receipt",
        "items": [],
    }

    items_raw = raw.get("items") or []
    if not isinstance(items_raw, list):
        items_raw = []

    for it in items_raw:
        if not isinstance(it, dict):
            continue

        # --- Struktur: base_name + original_text (neu) mit Legacy-Fallback ---
        base_name = _str_or_none(it.get("base_name"))
        original_text = _str_or_none(it.get("original_text"))
        legacy_desc = _str_or_none(it.get("description"))
        # Falls Legacy-Format kommt: "Basisname 2kg (Original)" auseinandernehmen
        if not base_name and legacy_desc:
            if "(" in legacy_desc and legacy_desc.endswith(")"):
                base_part, orig_part = legacy_desc.rsplit("(", 1)
                base_name = base_part.strip()
                if not original_text:
                    original_text = orig_part.rstrip(")").strip()
            else:
                base_name = legacy_desc

        total_price = _to_float(it.get("total_price"))
        if not base_name or total_price is None:
            continue

        # Fuer die Produkt-Gruppierung brauchen wir den Basisnamen OHNE
        # eingebettete Menge/Einheit ("Haferflocken 500g" -> "Haferflocken").
        # Die Angabe geht nicht verloren, sie steht im original_text.
        m_qty = _NAME_QTY_RE.search(base_name)
        if m_qty:
            stripped = base_name[:m_qty.start()].strip(" -,;")
            if stripped:
                base_name = stripped

        # Legacy-description als konkatenierter String für Bestandscode
        if original_text and original_text != base_name:
            description = f"{base_name} ({original_text})"
        else:
            description = base_name

        qty = _clean_quantity(it.get("quantity"))

        unit_price = _to_float(it.get("unit_price"))
        if unit_price is None and qty:
            try:
                unit_price = round(total_price / qty, 4)
            except ZeroDivisionError:
                unit_price = None

        cat_id = _to_int(it.get("category_id"))
        if cat_id is not None and cat_id not in valid_cat_ids:
            cat_id = None  # halluzinierte ID verwerfen

        cat_name = _str_or_none(it.get("category_name"))
        if cat_name and cat_name.strip().lower() in ("null", "none", "n/a", "unbekannt", ""):
            cat_name = None

        # price_comparable: AI-Flag, mit sinnvollem Default
        pc_raw = it.get("price_comparable")
        if isinstance(pc_raw, bool):
            price_comparable = pc_raw
        else:
            price_comparable = True  # Default: als Verbrauchsgut behandeln
        # Rabatt/Pfand/Trinkgeld explizit als NICHT vergleichbar markieren
        low = base_name.lower()
        if low in ("rabatt", "pfand", "trinkgeld") or total_price < 0:
            price_comparable = False

        is_reduced_raw = it.get("is_reduced")
        is_reduced = bool(is_reduced_raw) if is_reduced_raw is not None else False
        # Heuristischer Fallback wenn AI es nicht gesetzt hat
        if not is_reduced and (total_price < 0 or low.startswith(("rabatt", "ermäßigung", "reduziert"))):
            is_reduced = True

        original_price = _to_float(it.get("original_price"))
        # Sanity: Original-Preis darf nicht kleiner als aktueller Preis sein
        if original_price is not None and total_price is not None and original_price <= total_price:
            original_price = None

        # v1.16.0: brand_name aus AI-Response uebernehmen (nur Name — die
        # eigentliche Verknuepfung mit ``brands.id`` macht der Router beim
        # Speichern, weil dort die User-DB verfuegbar ist.
        brand_name = _str_or_none(it.get("brand_name"))
        out["items"].append({
            "base_name": base_name,
            "brand_name": brand_name,
            "original_text": original_text,
            "description": description,  # Legacy für Bestandscode
            "quantity": qty,
            "unit_price": unit_price,
            "total_price": total_price,
            "category_id": cat_id,
            "category_name": cat_name,
            "price_comparable": price_comparable,
            "is_reduced": is_reduced,
            "original_price": original_price,
        })

    return out


def _fallback_regex(ocr_text: str, stores: list, reason: str = "unknown") -> dict:
    """Regex-Fallback + Anreicherung mit currency/expense_type/category_id.

    Der ``reason``-Parameter wird in die Response als ``_parser`` und ``_fallback_reason``
    aufgenommen, damit man vom Client aus sehen kann warum kein AI-Parsing lief.
    """
    user_store_names = [s.get("name") for s in (stores or []) if isinstance(s, dict) and s.get("name")]
    parsed = _regex_parse_receipt(ocr_text or "", user_stores=user_store_names)
    parsed.setdefault("currency", None)
    # Die Zahlungsart wird nicht mehr erfasst; der Regex-Parser liefert sie noch.
    parsed.pop("payment_method", None)
    # Ohne KI keine Typ-Erkennung -- der haeufigste Fall ist ein Kassenbon.
    parsed.setdefault("expense_type", "receipt")
    for it in parsed.get("items") or []:
        # Regex-Parser liefert nur description -> base_name/original_text ableiten
        desc = it.get("description") or ""
        if "(" in desc and desc.endswith(")"):
            bp, op = desc.rsplit("(", 1)
            it.setdefault("base_name", bp.strip())
            it.setdefault("original_text", op.rstrip(")").strip())
        else:
            it.setdefault("base_name", desc)
            it.setdefault("original_text", None)
        it.setdefault("category_id", None)
        it.setdefault("category_name", None)
        it.setdefault("brand_name", None)  # v1.16.0
        it["quantity"] = _clean_quantity(it.get("quantity"))
        # Regex kann price_comparable nicht schätzen -> Default TRUE, außer Pfand/Rabatt
        low = (it.get("base_name") or "").lower()
        it.setdefault("price_comparable",
                      False if low in ("rabatt", "pfand", "trinkgeld")
                      or (it.get("total_price") or 0) < 0 else True)
    parsed["_parser"] = "regex"
    parsed["_fallback_reason"] = reason
    return parsed



def _call_gemini_sync(prompt: str, ocr_text: str):
    """Synchroner Gemini-Aufruf. Wird via asyncio.to_thread genutzt.

    Returns:
        (response_text, total_token_count_or_None)
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("Gemini-Client nicht verfuegbar")

    from google.genai import types  # type: ignore

    config = types.GenerateContentConfig(
        system_instruction=prompt,
        response_mime_type="application/json",
        temperature=0.1,
    )
    response = client.models.generate_content(
        model=_get_model_name(),
        contents=ocr_text,
        config=config,
    )
    text = getattr(response, "text", None) or ""
    tokens = None
    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        tokens = getattr(usage, "total_token_count", None)
    return text, tokens


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def ai_parse_receipt(
    ocr_text: str,
    categories: list,
    stores: list,
    expense_types: list | None = None,
) -> dict:
    """Parst OCR-Text via Gemini (Modell laut GEMINI_MODEL, default flash-latest v1.16.0).
    Faellt bei Fehler auf Regex-Parser zurueck.

    Args:
        ocr_text: Der von OCR extrahierte Rohtext.
        categories: Liste von ``{"id": int, "name": str}``.
        stores: Liste von ``{"name": str}``.
        expense_types: Optionale Liste der beim User schon vorhandenen
                Beleg-Typen (Strings). Damit waehlt das Modell einen bestehenden
                eigenen Typ, statt jedesmal eine neue Schreibweise zu erfinden
                (v1.52.0).

    Returns:
        Dict analog ``receipt_parser.parse_receipt`` + Felder ``currency`` und
        ``expense_type`` sowie pro Item ``quantity`` (Stueckzahl),
        ``category_id`` und ``brand_name``.
    """
    categories = categories or []
    stores = stores or []
    expense_types = expense_types or []

    if not ocr_text or not ocr_text.strip():
        return _fallback_regex("", stores, reason="empty_ocr")

    if _get_client() is None:
        return _fallback_regex(ocr_text, stores,
                               reason=_client_init_error or "client_unavailable")

    ocr_input = ocr_text[:_MAX_OCR_CHARS]

    try:
        prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            categories_json=json.dumps(categories, ensure_ascii=False),
            stores_json=json.dumps(stores, ensure_ascii=False),
            expense_types_json=json.dumps(
                [t for t in expense_types if isinstance(t, str) and t.strip()][:50],
                ensure_ascii=False),
        )
    except Exception as e:
        logger.warning("Prompt-Erstellung fehlgeschlagen: %s", e)
        return _fallback_regex(ocr_text, stores, reason=f"prompt_error: {e}")

    valid_cat_ids = {int(c["id"]) for c in categories if isinstance(c, dict) and "id" in c}

    try:
        text, tokens = await asyncio.wait_for(
            asyncio.to_thread(_call_gemini_sync, prompt, ocr_input),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.warning("Gemini-Aufruf Timeout (30s) - Fallback auf Regex-Parser.")
        return _fallback_regex(ocr_text, stores, reason="gemini_timeout_30s")
    except Exception as e:
        logger.warning("Gemini-Aufruf fehlgeschlagen (%s) - Fallback auf Regex-Parser.", e)
        return _fallback_regex(ocr_text, stores, reason=f"gemini_call_error: {e}")

    if not text:
        logger.warning("Gemini lieferte leere Antwort - Fallback auf Regex-Parser.")
        return _fallback_regex(ocr_text, stores, reason="gemini_empty_response")

    # Falls Modell trotzdem Markdown-Fence liefert: entfernen
    text_stripped = text.strip()
    if text_stripped.startswith("```"):
        text_stripped = text_stripped.strip("`")
        if text_stripped.lower().startswith("json"):
            text_stripped = text_stripped[4:]
        text_stripped = text_stripped.strip()

    try:
        raw = json.loads(text_stripped)
        if not isinstance(raw, dict):
            raise ValueError("Root ist kein JSON-Objekt")
    except Exception as e:
        logger.warning("Gemini-JSON konnte nicht geparst werden (%s) - Fallback. Auszug: %r",
                       e, text_stripped[:200])
        return _fallback_regex(ocr_text, stores, reason=f"gemini_json_error: {e}")

    parsed = _normalize_parsed(raw, valid_cat_ids)
    parsed["_parser"] = "ai"
    parsed["_model"] = _get_model_name()
    logger.info(
        "AI-Parser OK (Modell=%s, Tokens=%s, Items=%d, Total=%s, Typ=%s)",
        _get_model_name(),
        tokens if tokens is not None else "?",
        len(parsed.get("items") or []),
        parsed.get("total_amount"),
        parsed.get("expense_type"),
    )
    return parsed

