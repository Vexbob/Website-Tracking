"""Mahlzeiten — die eine Liste, die beide Ernaehrungs-Module teilen.

Das Tagebuch und der Tracker haben getrennte Tabellen und getrennte Router;
geteilt wird nur, was wirklich **dieselbe Tatsache** ist. „Wann isst du?“ ist
so eine: dass um 8 Uhr Fruehstueck ist, gilt nicht je Modul verschieden.

Zwei Listen davon waeren eine, die man beim Ergaenzen vergisst -- dieselbe
Begruendung, aus der schon die Datenbank bewusst keinen CHECK auf ``meal``
haelt (Migration 044).

Der Tag wird nach Mahlzeiten gelesen und nicht nach Uhrzeit: „Mittag“ ist die
Auskunft, die man geben kann, „12:47“ waere eine, die man erfinden muesste.
Die Uhrzeit taucht hier nur als *Vermutung* auf, wohin ein Eintrag gehoert.
"""

MAHLZEITEN = ("fruehstueck", "mittag", "abend", "snack")
MAHLZEIT_LABEL = {
    "fruehstueck": "Frühstück",
    "mittag": "Mittag",
    "abend": "Abend",
    "snack": "Zwischendurch",
}
# Wohin alles faellt, was ohne Zuordnung eingetragen wurde -- ein eigener
# Topf und keine stille Einsortierung unter "Zwischendurch".
OHNE_MAHLZEIT = "ohne"
OHNE_MAHLZEIT_LABEL = "Ohne Zuordnung"

# Bis zu welcher Stunde welche Mahlzeit vermutet wird. Die Grenzen sind die
# aus v1.95.0; sie still zu verschieben waere eine Aenderung, die man erst am
# naechsten falsch einsortierten Eintrag merkt. Sie gehen auch an das
# Frontend raus (``GRENZEN_RAUS``), damit dort derselbe Vorschlag angezeigt
# wird, den der Server spaeter trifft -- und nicht ein zweiter, eigener.
GRENZEN = (
    (11, "fruehstueck"),
    (15, "mittag"),
    (21, "abend"),
)
SPAET = "snack"


def mahlzeit_sauber(wert):
    """Eine bekannte Mahlzeit oder None. Unbekanntes ist ein Fehler."""
    if wert in (None, "", OHNE_MAHLZEIT):
        return None
    if wert not in MAHLZEITEN:
        raise ValueError(
            "Unbekannte Mahlzeit. Möglich sind: "
            + ", ".join(MAHLZEIT_LABEL[m] for m in MAHLZEITEN))
    return wert


def mahlzeit_fuer_uhrzeit(stunde) -> str:
    """Welche Mahlzeit um diese Uhrzeit gemeint sein duerfte.

    ``stunde`` ist die ORTSZEIT des Nutzers und kommt deshalb vom Browser.
    Der Server darf hier nicht seine eigene Uhr nehmen: er laeuft in UTC, und
    ein Snack um 22:30 Ortszeit waere dort 20:30 und landete unter „Abend“.
    """
    try:
        h = int(stunde)
    except (TypeError, ValueError):
        return SPAET
    for grenze, mahlzeit in GRENZEN:
        if h < grenze:
            return mahlzeit
    return SPAET


def uhrzeit_sauber(wert):
    """„HH:MM“ -> (stunde, minute) oder None. Unbrauchbares ist kein Fehler.

    Die Uhrzeit ist Beiwerk: kommt sie kaputt an, wird eben nicht geraten.
    Deswegen einen Eintrag abzuweisen, waere eine Strenge am falschen Ort.
    """
    if not wert or not isinstance(wert, str):
        return None
    teile = wert.strip().split(":")
    if len(teile) < 2:
        return None
    try:
        stunde, minute = int(teile[0]), int(teile[1])
    except ValueError:
        return None
    if not (0 <= stunde <= 23 and 0 <= minute <= 59):
        return None
    return stunde, minute


def liste_raus() -> list:
    """Die Mahlzeiten fuer die Antwort — samt dem Topf ohne Zuordnung."""
    return ([{"key": m, "label": MAHLZEIT_LABEL[m]} for m in MAHLZEITEN]
            + [{"key": OHNE_MAHLZEIT, "label": OHNE_MAHLZEIT_LABEL}])


def grenzen_raus() -> dict:
    """Die Stundengrenzen fuer das Frontend.

    Es braucht sie, um den Vorschlag ANZUZEIGEN, bevor etwas gespeichert ist
    -- der vorausgewaehlte Chip im Eintragen-Dialog. Entschieden wird trotzdem
    hier: das Frontend schickt die Uhrzeit, nicht die Mahlzeit.
    """
    return {mahlzeit: grenze for grenze, mahlzeit in GRENZEN}
