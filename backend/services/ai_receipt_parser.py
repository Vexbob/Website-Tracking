"""KI-gestützter Kassenbon-Parser (Gemini 3.5 Flash-Lite).

Nimmt OCR-Rohtext + User-Kategorien + User-Läden entgegen und gibt ein
strukturiertes Dict im gleichen Format wie ``services.receipt_parser.parse_receipt``
zurück — zusätzlich mit den Feldern ``currency`` sowie pro Item
``quantity``, ``quantity_unit`` und ``category_id``.

Konfiguration per ENV:
    GEMINI_API_KEY   API-Key von Google AI Studio (https://aistudio.google.com/apikey)
    GEMINI_MODEL     Optional. Modellname, default ``gemini-3.5-flash-lite``.
                     Weitere Optionen: ``gemini-3.6-flash`` (mehr Qualität),
                     ``gemini-3.7-flash`` (aktuellstes), ``gemini-flash-latest`` (Alias).

Fehlt ``GEMINI_API_KEY`` oder schlägt der Aufruf fehl, wird transparent auf
den regex-basierten Parser (``receipt_parser.parse_receipt``) zurückgefallen.
Der Aufrufer bekommt in beiden Fällen ein Dict mit derselben Struktur.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
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
    return os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")


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

===== KOPFDATEN (top-level Felder) =====

- store_hint (string|null): Name des Geschäfts. Wenn ein User-Laden case-insensitive matcht, exakt dessen Namen zurückgeben. Sonst: den Namen vom Bon lesbar formatieren ("BAECKEREI MUELLER" → "Bäckerei Müller"; "REWE" bleibt "Rewe"). Bei Online-Shops: Shop-Name (z.B. "Amazon", "Zalando"). Nicht erkennbar → null.

- purchase_date (string|null): Kaufdatum im ISO-Format YYYY-MM-DD. Bei mehreren Daten: das früheste. Nicht erkennbar → null.

- currency (string|null): "EUR" bei €/EUR/AT-DE-Bons, sonst ISO-3-Code. Nicht erkennbar → null.

- total_amount (float): Endsumme die gezahlt wurde. Keywords: "Summe", "Gesamt(betrag)", "Endsumme", "Zu zahlen", "Zahlbetrag", "Total". NICHT die Zwischensumme, NICHT die MwSt, NICHT das Rückgeld. Bei nur einem sichtbaren Betrag: diesen nehmen.

- vat_amount (float|null): Summe aller absoluten MwSt-Beträge (nicht Prozente). Bei mehreren Steuersätzen alle addieren. Beispiel: "10% MwSt = 0.06" + "20% MwSt = 1.84" → 1.90. Nicht erkennbar → null.

- payment_method (string|null): einer von
    "cash"   → Bar/Cash/Bargeld
    "card"   → EC/Maestro/Girocard/Bankomat/Debit/Contactless/Apple Pay/Google Pay/Debit Mastercard
    "credit" → Visa Credit, Mastercard Credit, Amex, "Kredit"
    "paypal" → PayPal
    "other"  → sonstige (Gutschein, Rechnung, etc.)
  Debit Mastercard IMMER als "card", NIE als "credit". Nicht erkennbar → null.

===== ITEMS (Array von Positions-Objekten) =====

Ein Objekt pro Zeile auf dem Bon. Kopfdaten (Summe/MwSt/Zwischensumme) NIEMALS als Item.

Pflichtfelder pro Item:

- base_name (string): sprechender deutscher PRODUKTNAME OHNE Menge/Einheit.
  Regeln:
    · Erste Buchstabe groß, Umlaute korrekt (nicht "Aepfel" → "Äpfel").
    · Nur was das Produkt IST (Gattung/Sorte). Keine Marke, keine Menge, keine Verpackung.
    · Bei bekannten Bezeichnungen (Klopapier, Vollmilch) diese verwenden.
  Beispiele:
    · Bon "Clever Äpfel 2kg"             → "Äpfel"
    · Bon "C1. ESL-Vollm. 1L"            → "Vollmilch"
    · Bon "Gillette Rasiergel Sensitive" → "Rasiergel"
    · Bon "BI HOME TOPA 10X180 BLATT"    → "Klopapier"
    · Bon "Diesel"                       → "Diesel"
    · Bon "Wiener Melange"               → "Kaffee"

- original_text (string): der bereinigte Text vom Kassenbon (ohne Steuer-Buchstaben,
  ohne Zeilenrauschen). Bei zweizeiligen Artikeln beide Zeilen zusammenführen.
  Beispiele:
    · Bon "C1. ESL-Vollm. 1L"   → "ESL-Vollm. 1L"
    · Bon "A Clever Äpfel 2kg"  → "Clever Äpfel 2kg"

- quantity (float): Menge als Zahl. Default 1 wenn nicht angegeben.
  "2kg"→2, "10X180"→10, "1L"→1, "500g"→500, "3 Stk"→3.
- quantity_unit (string|null): EINE von "kg", "g", "L", "ml", "Stk", "Pack", "Btl", "Blatt".
  null wenn keine Einheit erkennbar.

- unit_price (float|null): Einzelpreis pro Stück/kg/L. Wenn nicht direkt sichtbar aber
  quantity>1 UND total_price gegeben: total_price/quantity. Sonst null.

- total_price (float): Preis DIESER Position (was für sie bezahlt wurde).
  Bei "3x1,49 = 4,47" → 4.47.

- price_comparable (bool): TRUE für Verbrauchsgüter, die man regelmäßig neu kauft (Preisvergleich
  über Zeit sinnvoll). FALSE für Einmalkäufe die keinen sinnvollen Preisverlauf bilden.
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
    · Wenn NICHTS passt: eigener kurzer Name (Singular). "Sonstiges" nur als absolut letzter Fallback.

===== SCHWIERIGE FÄLLE =====

· Mehrere gleiche Artikel (2× Milch je 1,29): als 2 separate Items, NICHT zusammenfassen.
· Rabatt-Zeile am Ende (z.B. "-5% Rabatt -2,50"): eigenes Item mit base_name="Rabatt",
  price_comparable=false, negativem total_price.
· Pfand: eigenes Item mit base_name="Pfand", price_comparable=false.
· Trinkgeld: eigenes Item, base_name="Trinkgeld", price_comparable=false.
· Tankstelle: Kraftstoff als Item, quantity=Liter, quantity_unit="L", price_comparable=true,
  category_name="Kraftstoff & Auto".
· Zweizeilige Positionen: Name in Zeile N, Preis in Zeile N+1 → zu einem Item zusammenführen.
· Beleg ohne erkennbare Einzelpositionen: items=[]. Keine Fake-Items erfinden.
· OCR-Fehler bei Preisen: "l.32" → 1.32, "0.6Q" → 0.69, "1,ЗЗ" → 1.33 (kyrillisch).
· Ganzzahlen ohne Komma sind gültige Preise: "3" = 3.00 (nur wenn Preis-Position klar).

===== IGNORIEREN =====

Ignoriere alles was nicht zu Kopfdaten oder Positionen gehört: Belegnummern, Trace-/Terminal-IDs,
Kassen-/Bediener-/Filialnummern, Steuer-IDs (ATU/USt-Id), Adressen, Telefon, Websites,
Werbetexte ("Vielen Dank", "Kundenbeleg"), Karten-Dummies (####1743), Zeitstempel,
Öffnungszeiten, Rückgeld-Betrag (NICHT mit total_amount verwechseln!).

===== JSON-STRUKTUR (Beispiel Billa-Bon) =====

{{
  "store_hint": "Billa",
  "purchase_date": "2026-08-13",
  "currency": "EUR",
  "total_amount": 17.72,
  "vat_amount": 2.18,
  "payment_method": "card",
  "items": [
    {{
      "base_name": "Äpfel",
      "original_text": "Clever Äpfel 2kg",
      "quantity": 2,
      "quantity_unit": "kg",
      "unit_price": 1.66,
      "total_price": 3.32,
      "price_comparable": true,
      "is_reduced": false,
      "original_price": null,
      "category_id": null,
      "category_name": "Obst & Gemüse"
    }},
    {{
      "base_name": "Klopapier",
      "original_text": "BI HOME TOPA 10X180 BLATT",
      "quantity": 10,
      "quantity_unit": "Blatt",
      "unit_price": 0.499,
      "total_price": 4.99,
      "price_comparable": true,
      "is_reduced": false,
      "original_price": null,
      "category_id": null,
      "category_name": "Haushalt & Reinigung"
    }}
  ]
}}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_VALID_PAYMENTS = {"cash", "card", "credit", "paypal", "other"}
_VALID_UNITS = {"kg", "g", "L", "ml", "Stk", "Pack", "Btl"}
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
        "payment_method": None,
        "items": [],
    }

    pm = _str_or_none(raw.get("payment_method"))
    if pm and pm.lower() in _VALID_PAYMENTS:
        out["payment_method"] = pm.lower()

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

        # Für Preisverlauf-Grouping brauchen wir den Basisnamen OHNE eventuell noch
        # eingebettete Menge/Einheit (falls AI das nicht sauber trennt).
        import re as _re
        base_name = _re.sub(
            r"\s*\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml|stk|pack|btl|blatt)\s*$",
            "", base_name, flags=_re.IGNORECASE
        ).strip() or base_name

        # Legacy-description als konkatenierter String für Bestandscode
        if original_text and original_text != base_name:
            description = f"{base_name} ({original_text})"
        else:
            description = base_name

        qty = _to_float(it.get("quantity"))
        if qty is None or qty == 0:
            qty = 1.0

        unit = _str_or_none(it.get("quantity_unit"))
        if unit and unit not in _VALID_UNITS:
            mapping = {"stk.": "Stk", "stueck": "Stk", "stück": "Stk",
                       "l": "L", "kg": "kg", "g": "g", "ml": "ml",
                       "pack": "Pack", "btl": "Btl", "flasche": "Btl",
                       "blatt": "Blatt"}
            unit = mapping.get(unit.lower(), None)

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

        out["items"].append({
            "base_name": base_name,
            "original_text": original_text,
            "description": description,  # Legacy für Bestandscode
            "quantity": qty,
            "quantity_unit": unit,
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
    """Regex-Fallback + Anreicherung mit currency/quantity_unit/category_id.

    Der ``reason``-Parameter wird in die Response als ``_parser`` und ``_fallback_reason``
    aufgenommen, damit man vom Client aus sehen kann warum kein AI-Parsing lief.
    """
    user_store_names = [s.get("name") for s in (stores or []) if isinstance(s, dict) and s.get("name")]
    parsed = _regex_parse_receipt(ocr_text or "", user_stores=user_store_names)
    parsed.setdefault("currency", None)
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
        it.setdefault("quantity_unit", None)
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
) -> dict:
    """Parst OCR-Text via Gemini (Modell laut GEMINI_MODEL, default Flash-Lite).
    Faellt bei Fehler auf Regex-Parser zurueck.

    Args:
        ocr_text: Der von OCR extrahierte Rohtext.
        categories: Liste von ``{"id": int, "name": str}``.
        stores: Liste von ``{"name": str}``.

    Returns:
        Dict analog ``receipt_parser.parse_receipt`` + Felder ``currency``
        sowie pro Item ``quantity``, ``quantity_unit``, ``category_id``.
    """
    categories = categories or []
    stores = stores or []

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
        "AI-Parser OK (Modell=%s, Tokens=%s, Items=%d, Total=%s)",
        _get_model_name(),
        tokens if tokens is not None else "?",
        len(parsed.get("items") or []),
        parsed.get("total_amount"),
    )
    return parsed

