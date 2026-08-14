"""KI-gestützter Kassenbon-Parser (Gemini 2.5 Flash).

Nimmt OCR-Rohtext + User-Kategorien + User-Läden entgegen und gibt ein
strukturiertes Dict im gleichen Format wie ``services.receipt_parser.parse_receipt``
zurück — zusätzlich mit den Feldern ``currency`` sowie pro Item
``quantity``, ``quantity_unit`` und ``category_id``.

Konfiguration per ENV:
    GEMINI_API_KEY   API-Key von Google AI Studio (https://aistudio.google.com/apikey)
    GEMINI_MODEL     Optional. Modellname, default ``gemini-2.5-flash``.

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
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


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
_SYSTEM_PROMPT_TEMPLATE = """Du bist ein universeller Kassenbon- und Belegparser. Du extrahierst strukturierte Daten aus OCR-Texten von beliebigen Belegen: Supermärkte, Drogerien, Tankstellen, Bäcker, Metzger, Online-Bestellungen, Restaurants, kleine Tante-Emma-Läden — jedes Format, jede Kassensoftware.

Antworte AUSSCHLIESSLICH als gültiges JSON. Kein Markdown, kein Erklärungstext.

VERFÜGBARE KATEGORIEN DES USERS (weise jeden Artikel zu, "Sonstiges" als Fallback):
{categories_json}

BEKANNTE LÄDEN DES USERS (matche falls möglich, sonst erkannten Namen nehmen):
{stores_json}

EXTRAKTIONSREGELN:

1. store_hint: Name des Geschäfts/Ladens. Wenn in User-Liste (case-insensitive), nimm exakt den Namen aus der Liste. Bei unbekannten Läden: Namen vom Beleg, lesbar formatiert ("BAECKEREI MUELLER" → "Bäckerei Müller"). Bei Online-Bestellungen: Shop-Name. Falls nicht erkennbar: null.

2. purchase_date: Format YYYY-MM-DD (ISO). Bevorzugt Kaufdatum. Falls mehrere Daten: das frühere. Falls nicht erkennbar: null.

3. currency: "EUR" bei €, EUR, oder AT/DE Bons. Sonst ISO-Code. Falls nicht erkennbar: null.

4. total_amount: Die Endsumme die gezahlt wurde. Keywords: Summe, Gesamt, Gesamtbetrag, Endsumme, Zu zahlen, Zahlbetrag, Total, Betrag. NICHT die Zwischensumme, NICHT die MwSt, NICHT das Rückgeld. Falls nur ein Betrag auf dem Beleg: dieser. Als float.

5. vat_amount: Summe aller MwSt/USt-Beträge (absolute €-Beträge, NICHT Prozente). Bei mehreren Steuersätzen: addieren. z.B. "10% MwSt von 0.63 = 0.06" + "20% MwSt von 9.23 = 1.84" → 1.90. Falls nicht erkennbar: null.

6. payment_method: "cash" (Bar/Cash/Bargeld), "card" (EC/Maestro/Girocard/Bankomat/Debit/Contactless/Apple Pay/Google Pay), "credit" (Visa/Mastercard Credit/Amex), "paypal", "other". Debit Mastercard = "card". Falls nicht erkennbar: null.

7. items (Array, ein Eintrag pro Artikelposition):
   - description: Bereinigter Artikelname. Entferne Steuer-/Kategoriebuchstaben am Zeilenanfang (A, B, C, C1, H, *). Entferne Werbe-Texte, Rabatt-Codes, Pfand-Hinweise. Falls Artikelname über mehrere OCR-Zeilen geht: zusammenführen.
   - quantity: Menge als Zahl (1 wenn nicht angegeben). Bei "2kg" → 2, bei "10X180" → 10, bei "1L" → 1.
   - quantity_unit: "kg", "g", "L", "ml", "Stk", "Pack", "Btl", null
   - unit_price: Einzelpreis als float (falls erkennbar, sonst null). Falls quantity > 1 und total_price gegeben: unit_price = total_price / quantity.
   - total_price: Gesamtpreis des Artikels als float. Falls nur Einzelpreis × Menge: berechnen.
   - category_id: ID aus der User-Kategorienliste (int). NUR setzen wenn eine Kategorie exakt passt (case-insensitiv). Sonst IMMER null.
   - category_name: PFLICHTFELD — gib IMMER einen kurzen deutschen Kategorienamen an, auch wenn category_id gesetzt ist. NIEMALS null oder leer. Wähle bevorzugt aus dieser festen Liste (exakt so schreiben, mit Umlauten):
     * "Lebensmittel" — Grundnahrungsmittel, Obst, Gemüse, Brot, Milchprodukte, Eier, Fleisch, Wurst, Käse, Nudeln, Reis, Konserven, Tiefkühl
     * "Getränke" — Wasser, Saft, Limo, Bier, Wein, Kaffee, Tee (verpackt)
     * "Süßwaren" — Schokolade, Kekse, Bonbons, Chips, Snacks
     * "Drogerie" — Zahnpasta, Shampoo, Deo, Kosmetik, Rasierer, Rasierschaum, Windeln
     * "Haushalt" — Putzmittel, Waschmittel, Toilettenpapier, Küchenpapier, Müllbeutel, Batterien, Glühbirnen
     * "Tabak" — Zigaretten, Tabak, E-Zigarette
     * "Tiernahrung" — Katzenfutter, Hundefutter, Tierbedarf
     * "Baby" — Babynahrung, Windeln, Feuchttücher
     * "Apotheke" — Medikamente, Vitamine, Verbandsmaterial
     * "Kleidung" — Kleidung, Schuhe, Accessoires
     * "Elektronik" — Kabel, Ladegeräte, Gadgets
     * "Baumarkt" — Werkzeug, Schrauben, Farbe
     * "Kraftstoff" — Benzin, Diesel, AdBlue
     * "Restaurant" — Speisen/Getränke im Restaurant, Café, Bäckerei-Snack, Trinkgeld
     * "Pfand" — Leergut, Pfandflaschen
     * "Rabatt" — Rabatte, Aktionsminderungen, Coupons
     * "Sonstiges" — nur wenn wirklich nichts passt
     Verwende diese exakten Namen; erfinde keine neuen wenn eine der obigen passt. Nur wenn keine passt: eigenes einzelnes Wort im Singular.

SCHWIERIGE FÄLLE:
- Mehrere gleiche Artikel (2× Milch): als separate Items, NICHT zusammenfassen
- Rabatt/Minus-Zeilen: als separates Item mit negativem total_price, description "Rabatt: <Artikel>"
- Pfand: als separates Item, description "Pfand"
- Artikel ohne Preis (Name auf Zeile N, Preis auf Zeile N+1): zusammenführen
- Tankstellenbons: Kraftstoff als Item, Liter als quantity, "L" als unit
- Restaurantbons: Speisen/Getränke als Items, Trinkgeld als separates Item "Trinkgeld"
- Beleg ohne Einzelpositionen (nur Gesamtbetrag): items = []
- Ganzzahlen ohne Komma sind gültige Preise ("3" = 3.00)
- OCR-Fehler bei Preisen: "l.32" → 1.32, "0.6Q" → 0.69

WAS IGNORIERT WIRD:
- Belegnummern, Transaktionsnummern, Trace-Nummern, Terminal-IDs
- Kassen-/Bediener-Nummern, Filial-Nummern
- Steuer-Nummern, ATU/USt-Id
- Adressen, Telefonnummern, Websites
- Werbesprüche, "Vielen Dank", "Kundenbeleg", "Händlerbeleg"
- Kartendummy-Nummern (####1743)
- Zeitstempel, Öffnungszeiten
- Rückgeld-Betrag (nicht verwechseln mit total_amount!)

JSON-FORMAT (exakt diese Struktur):
{{
  "store_hint": "string oder null",
  "purchase_date": "YYYY-MM-DD oder null",
  "currency": "EUR oder null",
  "total_amount": 17.72,
  "vat_amount": 1.90,
  "payment_method": "card",
  "items": [
    {{
      "description": "Clever Äpfel 2kg",
      "quantity": 2,
      "quantity_unit": "kg",
      "unit_price": 1.66,
      "total_price": 3.32,
      "category_id": null,
      "category_name": "Lebensmittel"
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
        desc = _str_or_none(it.get("description"))
        total_price = _to_float(it.get("total_price"))
        if not desc or total_price is None:
            continue

        qty = _to_float(it.get("quantity"))
        if qty is None or qty == 0:
            qty = 1.0

        unit = _str_or_none(it.get("quantity_unit"))
        if unit and unit not in _VALID_UNITS:
            mapping = {"stk.": "Stk", "stueck": "Stk", "stück": "Stk",
                       "l": "L", "kg": "kg", "g": "g", "ml": "ml",
                       "pack": "Pack", "btl": "Btl", "flasche": "Btl"}
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

        # category_name IMMER durchreichen (auch wenn cat_id gesetzt ist).
        # Das Frontend kann so als Fallback anlegen, falls cat_id nicht auffindbar ist,
        # und der User bekommt zumindest eine passende Kategorie ins Dropdown.
        cat_name = _str_or_none(it.get("category_name"))
        if cat_name:
            # Häufige Halluzinationen/Nulls normalisieren
            if cat_name.strip().lower() in ("null", "none", "n/a", "unbekannt", ""):
                cat_name = None

        is_reduced = False
        if total_price < 0 or desc.lower().startswith(("rabatt", "ermäßigung", "reduziert")):
            is_reduced = True

        out["items"].append({
            "description": desc,
            "quantity": qty,
            "quantity_unit": unit,
            "unit_price": unit_price,
            "total_price": total_price,
            "category_id": cat_id,
            "category_name": cat_name,
            "is_reduced": is_reduced,
            "original_price": None,
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
        it.setdefault("category_id", None)
        it.setdefault("category_name", None)
        it.setdefault("quantity_unit", None)
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
    """Parst OCR-Text via Gemini 2.5 Flash. Faellt bei Fehler auf Regex-Parser zurueck.

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

