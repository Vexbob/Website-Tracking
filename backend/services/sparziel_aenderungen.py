"""Was am Sparziel-Modul veraendert wurde (v2.36.0).

Der Verlauf zeigte bis hierher nur, was Geld bewegt hat: Check-ins,
Meilensteine, Uebertraege. Dass ein Wochenziel angelegt, seine Belohnung von
5 auf 8 EUR gesetzt oder ein Achievement geloescht wurde, stand nirgends --
und genau das will man nachlesen, wenn sich ein Kontostand seltsam anfuehlt.

Jede Stelle in ``main.py``, die etwas am Modul aendert, ruft ``vermerken``.
Beim Bearbeiten beschreibt ``unterschiede`` nur die Felder, die sich wirklich
geaendert haben; ein Speichern ohne Aenderung hinterlaesst keine Zeile.

Gespeichert wird der Name zum Zeitpunkt der Aenderung, nicht nur die ID: das
Objekt kann spaeter umbenannt oder geloescht sein, und „Wochenziel #12
geloescht“ beantwortet keine Frage.
"""
from typing import Optional

# Wie ein Objekt im Verlauf heisst.
OBJEKTE = {
    "sparziel": "Sparziel",
    "wochenziel": "Wochenziel",
    "achievement": "Achievement",
    "wunsch": "Wunsch",
    "idee": "Idee",
    "trophaee": "Trophäe",
    "checkin": "Check-in",
    "meilenstein": "Meilenstein",
    "fortschritt": "Fortschritt",
    "buchung": "Buchung",
    "notiz": "Notiz",
    "reihenfolge": "Reihenfolge",
    "sicherung": "Sicherung",
}

# Was damit passiert ist -- als Partizip, damit „Wochenziel angelegt“ entsteht.
AKTIONEN = {
    "angelegt": "angelegt",
    "bearbeitet": "bearbeitet",
    "geloescht": "gelöscht",
    "aktiviert": "aktiviert",
    "pausiert": "pausiert",
    "zurueckgesetzt": "zurückgesetzt",
    "zurueckgenommen": "zurückgenommen",
    "abgeschlossen": "abgeschlossen",
    "geaendert": "geändert",
    "eingespielt": "eingespielt",
    "uebernommen": "übernommen",
}

RHYTHMEN = {"weekly": "pro Woche", "monthly": "pro Monat"}
RICHTUNGEN = {"increase": "steigend", "decrease": "fallend"}


def eur(betrag) -> str:
    """1465.5 -> "1.465,50 €"."""
    try:
        wert = float(betrag)
    except (TypeError, ValueError):
        return "–"
    return f"{wert:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def zahl(wert) -> str:
    """5.0 -> "5", 2.5 -> "2,5"."""
    try:
        f = float(wert)
    except (TypeError, ValueError):
        return "–"
    if f == int(f):
        return str(int(f))
    return f"{f:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _wert(art: str, v) -> str:
    if v is None or v == "":
        return "–"
    if art == "eur":
        return eur(v)
    if art == "zahl":
        return zahl(v)
    if art == "prozent":
        return zahl(v) + " %"
    if art == "rhythmus":
        return RHYTHMEN.get(v, str(v))
    if art == "richtung":
        return RICHTUNGEN.get(v, str(v))
    if art == "ziel":
        return "eigenes Ziel" if v else "automatisch"
    return str(v)


# Welche Felder je Objekt verglichen werden, mit Beschriftung und Format.
# Was hier fehlt (Sortierung, interne Zaehler), ist keine Aenderung, die man
# im Verlauf nachlesen will.
FELDER = {
    "wochenziel": [
        ("title", "Titel", "text"),
        ("reward_amount", "Belohnung", "eur"),
        ("rhythm_type", "Rhythmus", "rhythmus"),
        ("target_count", "Ziel", "zahl"),
        ("streak_bonus_amount", "Serienbonus", "eur"),
        ("streak_bonus_threshold", "Serie ab", "zahl"),
        ("partial_count", "Teilbelohnung ab", "zahl"),
        ("partial_percent", "Teilbelohnung", "prozent"),
        ("reward_goal_id", "Zahlt auf", "ziel"),
    ],
    "achievement": [
        ("title", "Titel", "text"),
        ("reward_amount", "Belohnung", "eur"),
        ("unit", "Einheit", "text"),
        ("start_value", "Start", "zahl"),
        ("threshold_increment", "Meilenstein alle", "zahl"),
        ("step_amount", "Schritt", "zahl"),
        ("target_value", "Zielwert", "zahl"),
        ("direction", "Richtung", "richtung"),
        ("reward_goal_id", "Zahlt auf", "ziel"),
        ("auto_source", "Quelle", "text"),
    ],
    "sparziel": [
        ("name", "Name", "text"),
        ("target_amount", "Zielbetrag", "eur"),
        ("link", "Link", "text"),
    ],
    "wunsch": [
        ("name", "Name", "text"),
        ("estimated_price", "Preis", "eur"),
        ("link", "Link", "text"),
    ],
}


def _gleich(a, b) -> bool:
    if a is None or a == "":
        return b is None or b == ""
    if b is None or b == "":
        return False
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a) == str(b)


def unterschiede(objekt: str, alt, neu) -> str:
    """„Belohnung 5,00 € → 8,00 €; Ziel 3 → 4“ -- nur, was sich geaendert hat.

    ``alt`` und ``neu`` sind Zeilen (oder dicts) VOR und NACH dem Speichern.
    Ein Link wird nicht ausgeschrieben: eine lange Adresse zweimal
    nebeneinander liest niemand.
    """
    teile = []
    for feld, beschriftung, art in FELDER.get(objekt, []):
        a = alt[feld] if feld in alt.keys() else None
        b = neu[feld] if feld in neu.keys() else None
        if _gleich(a, b):
            continue
        if feld == "link":
            teile.append("Link " + ("entfernt" if not b else "gesetzt" if not a else "geändert"))
        else:
            teile.append(f"{beschriftung} {_wert(art, a)} → {_wert(art, b)}")
    return "; ".join(teile)


async def vermerken(db, user_id: int, aktion: str, objekt: str,
                    objekt_id: Optional[int], titel: str,
                    details: Optional[str] = None) -> None:
    """Eine Aenderung festhalten. Unbekannte Aktionen oder Objekte sind ein
    Programmierfehler und fallen sofort auf -- eine Zeile, die im Verlauf als
    „x y“ steht, hilft niemandem."""
    if aktion not in AKTIONEN or objekt not in OBJEKTE:
        raise ValueError(f"Unbekannte Änderung: {objekt}/{aktion}")
    await db.execute(
        "INSERT INTO sparziel_aenderungen (user_id, aktion, objekt, objekt_id, titel, details) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        user_id, aktion, objekt, objekt_id, (titel or "").strip() or "–",
        (details or "").strip() or None)


def ereignis(r) -> dict:
    """Eine Zeile als Eintrag fuer den Verlauf -- ueber 0 EUR, nicht loeschbar."""
    titel = f"{OBJEKTE.get(r['objekt'], r['objekt'])} {AKTIONEN.get(r['aktion'], r['aktion'])}"
    beschreibung = f"„{r['titel']}“" if r["objekt"] not in ("reihenfolge", "sicherung") else r["titel"]
    if r["details"]:
        beschreibung += " · " + r["details"]
    return {
        "type": "aenderung",
        "date": r["created_at"].isoformat(),
        "title": titel,
        "description": beschreibung,
        "amount": 0.0,
        "log_id": r["id"],
        "note": "",
        "deletable": False,
    }
