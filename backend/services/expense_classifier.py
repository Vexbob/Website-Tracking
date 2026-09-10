"""Importierte Buchungen nachträglich einordnen — Beleg-Typ und Kategorie.

Der CSV-Import aus der Banking-App bringt zwei Dinge mit, die er bewusst
NICHT deutet: den Zahlungsempfänger und die Kategorien der Bank. Beide sind
Vorgaben von C24 ("Weitere Ausgaben", "Digitale Produkte & Dienste") und
nicht die dieser Website. Dieser Dienst holt das nach.

Zwei Felder werden gesetzt:

  * ``expenses.expense_type`` — Kassenbon, Online-Bestellung, Restaurant,
    Abo oder Sonstiges. Aus dem Empfänger meist eindeutig ableitbar: Lidl ist
    ein Kassenbon, Netflix ein Abo, Lieferando ein Restaurant.
  * ``expense_items.category_id`` am Sammelposten — die eigene Kategorie.

**Gruppiert, nicht je Buchung.** Ein Jahr Kontoauszug hat 800 Zeilen, aber
nur rund 150 verschiedene Kombinationen aus Empfänger und Bank-Kategorie.
"Lidl / Lebensmittel / Supermarkt" kommt hundertmal vor und ist hundertmal
dieselbe Antwort. Gefragt wird deshalb einmal je Kombination — das ist nicht
nur billiger, sondern auch konsistent: sonst könnte dieselbe Lidl-Buchung im
Januar anders einsortiert werden als im März.

**Nichts wird überschrieben, was von Hand kam.** Angefasst werden nur
Buchungen aus einem Import, deren Sammelposten noch nicht bearbeitet wurde.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class ClassifyError(Exception):
    """Fehler, den der Nutzer lesen soll (400, nicht 500)."""


# Wie viele Kombinationen in einem Aufruf. Mehr passt ins Fenster, aber die
# Antwortqualität fällt spürbar ab, wenn das Modell 300 Zeilen am Stück
# durchhalten muss.
BATCH = 80

# Die fünf eingebauten Typen. Klartext für das Modell, Schlüssel für die DB.
TYP_LISTE = [
    ("receipt", "Kassenbon — im Laden bezahlt (Supermarkt, Drogerie, Tankstelle, Bäckerei)"),
    ("online_order", "Online-Bestellung — Versandhandel (Amazon, Zalando, AliExpress)"),
    ("restaurant", "Restaurant — Gastronomie und Lieferdienste (McDonalds, Lieferando)"),
    ("subscription", "Abo — wiederkehrende Zahlung (Versicherung, Strom, Miete, Streaming, Mobilfunk)"),
    ("other", "Sonstiges — alles, was in keine der vier Gruppen passt"),
]
TYP_KEYS = {k for k, _ in TYP_LISTE}


PROMPT = """Du ordnest Bankbuchungen in einem privaten Ausgaben-Tracker ein.

Du bekommst eine Liste von Kombinationen aus Zahlungsempfänger und den
Kategorien der Banking-App. Für jede lieferst du zwei Dinge:

1. "typ" — genau einer dieser Schlüssel:
{typen}

2. "kategorie" — wofür das Geld ausgegeben wurde. Nimm bevorzugt eine
   Kategorie aus dieser vorhandenen Liste (exakte Schreibweise übernehmen):
{kategorien}
   Passt keine, gib einen kurzen neuen Namen (ein bis zwei Wörter, deutsch,
   Substantiv). Erfinde keine Kategorie, wenn eine vorhandene passt — die
   Liste soll nicht wachsen.

Wichtig:
- Die Kategorien der Bank sind ein Hinweis, keine Vorgabe. "Weitere Ausgaben"
  heißt, dass die Bank es nicht wusste; entscheide dann selbst nach dem
  Empfänger.
- Ein Zahlungsdienstleister als Empfänger (PayPal, SumUp, Zettle) sagt nichts
  über den Zweck. Nutze dann die Bank-Kategorie und gib bei "typ" "other",
  wenn du unsicher bist.
- Miete, Versicherung, Strom, Mobilfunk und Streaming sind "subscription",
  auch wenn sie nur einmal in der Liste stehen.

Antworte als JSON-Objekt:
{{"zuordnung": [{{"nr": 1, "typ": "receipt", "kategorie": "Lebensmittel"}}, ...]}}

Gib für JEDE Nummer genau einen Eintrag zurück, in derselben Reihenfolge."""


def _typ_block() -> str:
    return "\n".join("   - %s: %s" % (k, t) for k, t in TYP_LISTE)


def _kat_block(kategorien: list[str]) -> str:
    if not kategorien:
        return "   (noch keine vorhanden — vergib passende neue Namen)"
    return "\n".join("   - %s" % k for k in kategorien)


async def collect(db, user_id: int) -> list[dict]:
    """Die Kombinationen, die eingeordnet werden müssen.

    Nur importierte Buchungen, und je Kombination eine Zeile — mit der Zahl
    der Buchungen dahinter, damit die Vorschau sagen kann, wie viel an einer
    einzelnen Entscheidung hängt.
    """
    rows = await db.fetch(
        """SELECT COALESCE(NULLIF(e.src_payee, ''), s.name, '')  AS payee,
                  COALESCE(e.src_category, '')                    AS bank_kat,
                  COALESCE(e.src_subcategory, '')                 AS bank_unterkat,
                  COUNT(*)                                        AS buchungen,
                  COALESCE(SUM(e.total_amount), 0)                AS summe,
                  MIN(e.purchase_date)                            AS von,
                  MAX(e.purchase_date)                            AS bis
             FROM expenses e
             LEFT JOIN stores s ON s.id = e.store_id
            WHERE e.user_id = $1 AND e.source = 'import'
            GROUP BY 1, 2, 3
            ORDER BY COUNT(*) DESC, 1""", user_id)
    return [{
        "payee": r["payee"], "bank_kat": r["bank_kat"],
        "bank_unterkat": r["bank_unterkat"],
        "buchungen": r["buchungen"], "summe": float(r["summe"] or 0),
        "von": r["von"].isoformat() if r["von"] else None,
        "bis": r["bis"].isoformat() if r["bis"] else None,
    } for r in rows]


async def _kategorien(db, user_id: int) -> list[str]:
    rows = await db.fetch(
        "SELECT name FROM expense_categories WHERE user_id=$1 ORDER BY LOWER(name)",
        user_id)
    return [r["name"] for r in rows if (r["name"] or "").strip()]


def _parse_antwort(text: str, erwartet: int) -> dict[int, dict]:
    """Die Antwort des Modells auf Nummern abbilden.

    Robust gegen die üblichen Abweichungen: Code-Zäune um das JSON, eine
    blanke Liste statt des Objekts, fehlende oder doppelte Nummern.
    """
    roh = (text or "").strip()
    roh = re.sub(r"^```(?:json)?\s*|\s*```$", "", roh).strip()
    if not roh:
        raise ClassifyError("Das Modell hat nichts geantwortet.")
    try:
        data = json.loads(roh)
    except ValueError as e:
        raise ClassifyError("Die Antwort des Modells war kein gültiges JSON: %s" % e)
    liste = data.get("zuordnung") if isinstance(data, dict) else data
    if not isinstance(liste, list):
        raise ClassifyError("Die Antwort des Modells hatte nicht die erwartete Form.")

    out: dict[int, dict] = {}
    for i, eintrag in enumerate(liste):
        if not isinstance(eintrag, dict):
            continue
        nr = eintrag.get("nr")
        try:
            nr = int(nr)
        except (TypeError, ValueError):
            # Ohne Nummer gilt die Reihenfolge -- besser als die Zeile zu
            # verwerfen, denn das Modell haelt sie meistens ein.
            nr = i + 1
        if not (1 <= nr <= erwartet) or nr in out:
            continue
        typ = str(eintrag.get("typ") or "").strip().lower()
        if typ not in TYP_KEYS:
            typ = "other"
        kat = re.sub(r"\s+", " ", str(eintrag.get("kategorie") or "")).strip()[:60]
        out[nr] = {"typ": typ, "kategorie": kat or None}
    return out


async def classify(kombis: list[dict], kategorien: list[str]) -> list[dict]:
    """Fragt das Modell, in Blöcken. Gibt je Kombination Typ und Kategorie."""
    from services.ai_receipt_parser import _call_gemini_sync, _get_client
    import asyncio

    if _get_client() is None:
        raise ClassifyError(
            "Der KI-Dienst ist nicht eingerichtet (GEMINI_API_KEY fehlt). "
            "Ohne ihn lassen sich die Buchungen nicht automatisch einordnen.")

    prompt = PROMPT.format(typen=_typ_block(), kategorien=_kat_block(kategorien))
    ergebnis: list[dict] = []

    for start in range(0, len(kombis), BATCH):
        teil = kombis[start:start + BATCH]
        zeilen = [{
            "nr": i + 1,
            "empfaenger": k["payee"] or "(ohne)",
            "bank_kategorie": k["bank_kat"] or "",
            "bank_unterkategorie": k["bank_unterkat"] or "",
        } for i, k in enumerate(teil)]
        text, _tokens = await asyncio.to_thread(
            _call_gemini_sync, prompt,
            json.dumps(zeilen, ensure_ascii=False, indent=0))
        zuordnung = _parse_antwort(text, len(teil))
        for i, k in enumerate(teil):
            treffer = zuordnung.get(i + 1) or {}
            ergebnis.append({
                **k,
                "typ": treffer.get("typ") or "other",
                "kategorie": treffer.get("kategorie"),
                # Ohne Antwort bleibt die Zeile stehen, wird aber nicht
                # geschrieben -- eine geratene Einordnung ist schlechter als
                # keine.
                "beantwortet": bool(treffer),
            })
    return ergebnis


def zusammenfassung(ergebnis: list[dict], vorhandene: list[str]) -> dict:
    """Was der Lauf bedeuten würde, in Zahlen — für die Vorschau."""
    bekannt = {k.lower() for k in vorhandene}
    neue: dict[str, int] = {}
    je_typ: dict[str, int] = {}
    offen = 0
    buchungen = 0
    for e in ergebnis:
        if not e.get("beantwortet"):
            offen += e["buchungen"]
            continue
        buchungen += e["buchungen"]
        je_typ[e["typ"]] = je_typ.get(e["typ"], 0) + e["buchungen"]
        kat = e.get("kategorie")
        if kat and kat.lower() not in bekannt:
            neue[kat] = neue.get(kat, 0) + e["buchungen"]
    return {
        "kombinationen": len(ergebnis),
        "buchungen": buchungen,
        "ohne_antwort": offen,
        "je_typ": je_typ,
        "neue_kategorien": sorted(neue.items(), key=lambda kv: -kv[1]),
    }


async def apply(db, user_id: int, ergebnis: list[dict]) -> dict:
    """Schreibt die Einordnung.

    Angefasst wird nur, was aus einem Import stammt und dessen Sammelposten
    nicht von Hand bearbeitet wurde -- eine eigene Korrektur darf ein
    späterer Lauf nicht wieder wegräumen.
    """
    vorhandene = {k.lower(): None for k in await _kategorien(db, user_id)}
    rows = await db.fetch(
        "SELECT id, name FROM expense_categories WHERE user_id=$1", user_id)
    kat_id = {(r["name"] or "").lower(): r["id"] for r in rows}

    gesetzt_typ = 0
    gesetzt_kat = 0
    angelegt = 0

    async with db.transaction():
        for e in ergebnis:
            if not e.get("beantwortet"):
                continue
            payee = e["payee"] or ""
            bank_kat = e["bank_kat"] or ""
            bank_unter = e["bank_unterkat"] or ""

            # Die Kategorie ggf. anlegen -- einmal, nicht je Buchung.
            cid = None
            name = (e.get("kategorie") or "").strip()
            if name:
                cid = kat_id.get(name.lower())
                if cid is None:
                    cid = await db.fetchval(
                        "INSERT INTO expense_categories (user_id, name) "
                        "VALUES ($1, $2) RETURNING id", user_id, name[:60])
                    kat_id[name.lower()] = cid
                    angelegt += 1

            ids = [r["id"] for r in await db.fetch(
                """SELECT id FROM expenses
                    WHERE user_id=$1 AND source='import'
                      AND COALESCE(NULLIF(src_payee,''), '') = $2
                      AND COALESCE(src_category,'') = $3
                      AND COALESCE(src_subcategory,'') = $4""",
                user_id, payee, bank_kat, bank_unter)]
            if not ids:
                continue

            n = await db.fetchval(
                """WITH um AS (
                       UPDATE expenses SET expense_type=$1
                        WHERE user_id=$2 AND id = ANY($3::int[])
                      RETURNING 1)
                   SELECT COUNT(*) FROM um""",
                e["typ"], user_id, ids) or 0
            gesetzt_typ += n

            if cid is not None:
                n = await db.fetchval(
                    """WITH um AS (
                           UPDATE expense_items SET category_id=$1
                            WHERE user_id=$2 AND expense_id = ANY($3::int[])
                              AND COALESCE(user_edited, FALSE) = FALSE
                          RETURNING 1)
                       SELECT COUNT(*) FROM um""",
                    cid, user_id, ids) or 0
                gesetzt_kat += n

    logger.info("User %s reclassify: %s Typen, %s Kategorien, %s neu angelegt",
                user_id, gesetzt_typ, gesetzt_kat, angelegt)
    return {"buchungen_typ": gesetzt_typ, "positionen_kategorie": gesetzt_kat,
            "kategorien_angelegt": angelegt}
