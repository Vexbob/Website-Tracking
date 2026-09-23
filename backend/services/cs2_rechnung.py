"""CS2 — die Rechnung und die Schreibweise, ohne Datenbank und ohne Web.

Hier steht alles, was sich ohne Server pruefen laesst: was eine Position wert
ist, ab wann ein Preis als alt gilt, und wie ein Itemname geschrieben wird.
Der Router holt Zeilen und gibt sie heraus; gerechnet wird hier.

Zwei Dinge, die anderswo schon einmal schiefgingen und deshalb hier stehen:

1. **Geld ist ``Decimal``, nie ``float``.** 0,1 + 0,2 ist in Gleitkomma nicht
   0,3, und bei 5.557 Einzelstuecken summiert sich das sichtbar. Gerundet wird
   kaufmaennisch und je Position -- siehe ``summiere``, wo steht, warum die
   Gesamtsumme nicht einmal am Ende gerundet wird.

2. **Die Gebuehr ist eine Schaetzung und heisst hier auch so.** Steam nimmt
   5 % fuer sich und 10 % fuer das Spiel, rundet aber je Einzelverkauf und hat
   Mindestbetraege. ``netto`` ist deshalb ein Anhaltspunkt fuer den Erloes,
   keine Zusage -- und kein realisierter Betrag, denn verkauft wurde nichts.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Optional

# Steam nimmt 5 % Marktgebuehr und 10 % Spielgebuehr.
GEBUEHR = Decimal("0.15")
CENT = Decimal("0.01")

# Ab wann ein von Hand gepflegter Preis nicht mehr fuer sich spricht. Die
# beiden Zahlen stammen aus der Vorgaengerfassung, wo sie die Zeilenfarbe
# steuerten -- hier steuern sie zusaetzlich, was die Pflegeansicht vorlegt.
ALT_AB_TAGEN = 30
SEHR_ALT_AB_TAGEN = 60

WEAR_WERTE = ["FN", "MW", "FT", "WW", "BS"]
WEAR_LANG = {
    "FN": "Factory New",
    "MW": "Minimal Wear",
    "FT": "Field-Tested",
    "WW": "Well-Worn",
    "BS": "Battle-Scarred",
}


# =========================================================================
# Geld
# =========================================================================

def cent(wert: Any) -> Decimal:
    """Auf zwei Stellen kaufmaennisch runden."""
    return Decimal(str(wert)).quantize(CENT, rounding=ROUND_HALF_UP)


def brutto(menge: Optional[int], preis: Optional[Decimal]) -> Optional[Decimal]:
    """Menge mal Preis. ``None``, solange eine der beiden Angaben fehlt.

    Eine fehlende Angabe ergibt ausdruecklich nicht null: eine angefangene
    Zeile ist keine Zeile ueber null Euro.
    """
    if menge is None or preis is None:
        return None
    return cent(Decimal(menge) * Decimal(str(preis)))


def netto(brutto_wert: Optional[Decimal]) -> Optional[Decimal]:
    """Was nach der geschaetzten Steam-Gebuehr uebrig bliebe."""
    if brutto_wert is None:
        return None
    return cent(Decimal(str(brutto_wert)) * (Decimal("1") - GEBUEHR))


def preis_lesen(text: Any) -> Decimal:
    """``"1.234,56"``, ``"1234.56"`` und ``"12,34 €"`` ergeben dasselbe.

    Wirft ``ValueError`` mit einem deutschen Satz, wenn nichts zu lesen ist --
    der Satz landet unveraendert im Toast.
    """
    t = _text(text).replace("€", "").replace(" ", "").replace(" ", "")
    if not t:
        raise ValueError("Da steht kein Preis.")
    if t.count(",") == 1 and "." not in t:
        t = t.replace(",", ".")
    elif t.count(",") == 1 and "." in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        wert = cent(t)
    except Exception:
        raise ValueError(f"„{_text(text)}“ ist kein Preis.")
    if wert < 0:
        raise ValueError("Ein Preis unter null ergibt keinen Sinn.")
    return wert


# =========================================================================
# Alter eines Preises
# =========================================================================

def alter_in_tagen(preis_am: Any, jetzt: Optional[datetime] = None) -> Optional[int]:
    """Wie viele Tage der Preis schon steht. ``None``, wenn nie einer stand."""
    if preis_am is None:
        return None
    jetzt = jetzt or datetime.now(timezone.utc)
    stand = preis_am
    if isinstance(stand, str):
        try:
            stand = datetime.fromisoformat(stand.replace("Z", "+00:00"))
        except ValueError:
            return None
    if stand.tzinfo is None:
        stand = stand.replace(tzinfo=timezone.utc)
    if jetzt.tzinfo is None:
        jetzt = jetzt.replace(tzinfo=timezone.utc)
    return max(0, (jetzt - stand).days)


def frische(preis_am: Any, jetzt: Optional[datetime] = None) -> str:
    """``"frisch"``, ``"alt"``, ``"sehr_alt"`` oder ``"ohne"``.

    ``"ohne"`` heisst: es stand nie ein Preis. Das ist ein anderer Zustand als
    ein alter Preis und darf nicht wie einer aussehen.
    """
    tage = alter_in_tagen(preis_am, jetzt)
    if tage is None:
        return "ohne"
    if tage >= SEHR_ALT_AB_TAGEN:
        return "sehr_alt"
    if tage >= ALT_AB_TAGEN:
        return "alt"
    return "frisch"


# =========================================================================
# Bestand zusammenzaehlen
# =========================================================================

def summiere(zeilen: Iterable[dict], jetzt: Optional[datetime] = None) -> dict:
    """Kopfzahlen ueber einen Bestand.

    ``zeilen`` sind dicts mit ``quantity``, ``price_eur``, ``priced_at``
    und -- fuer die Aufteilung -- ``category_id``.

    Unvollstaendige Zeilen zaehlen NICHT mit und werden getrennt gezaehlt. Eine
    Summe, die fehlende Preise als null mitnimmt, ist nicht vorsichtig, sondern
    falsch: sie sieht aus wie eine vollstaendige Summe.

    Das Netto wird JE POSITION gerechnet und dann summiert, nicht einmal auf
    die Gesamtsumme. Beides ist vertretbar, aber nur das erste stimmt mit dem
    ueberein, was an der einzelnen Zeile steht -- und eine Kopfzahl, die sich
    nicht aus der Liste darunter aufaddiert, ist eine zweite Antwort auf
    dieselbe Frage. Der Unterschied ist klein und real: beim uebernommenen
    Bestand sind es sechs Cent.
    """
    gesamt_brutto = Decimal("0")
    gesamt_netto = Decimal("0")
    gueltig = 0
    unvollstaendig = 0
    veraltet = 0
    stueck = 0
    je_kategorie: dict[int, Decimal] = {}

    for z in zeilen:
        b = brutto(z.get("quantity"), z.get("price_eur"))
        if b is None:
            unvollstaendig += 1
            continue
        gueltig += 1
        stueck += int(z.get("quantity") or 0)
        gesamt_brutto += b
        gesamt_netto += netto(b)
        if frische(z.get("priced_at"), jetzt) in ("alt", "sehr_alt", "ohne"):
            veraltet += 1
        if z.get("category_id") is not None:
            je_kategorie[z["category_id"]] = je_kategorie.get(z["category_id"], Decimal("0")) + b

    gesamt_brutto = cent(gesamt_brutto)
    gesamt_netto = cent(gesamt_netto)
    return {
        "brutto": gesamt_brutto,
        "netto": gesamt_netto,
        # ``zeilen`` sind ALLE Positionen, ``positionen`` nur die, die einen
        # Wert beitragen. Die Kopfzahl nennt ``zeilen`` -- sonst stuende ueber
        # einer Liste mit 116 Eintraegen die Zahl 113, und der Unterschied
        # waere eine Rechenart und keine Auskunft. Wie viele unvollstaendig
        # sind, steht daneben.
        "zeilen": gueltig + unvollstaendig,
        "positionen": gueltig,
        "unvollstaendig": unvollstaendig,
        "veraltet": veraltet,
        "stueck": stueck,
        "je_kategorie": {k: cent(v) for k, v in je_kategorie.items()},
    }


# =========================================================================
# Schreibweise der Itemnamen
# =========================================================================

# Waffennamen, die keine Regel trifft. Uebernommen aus der Vorgaengerfassung
# und dort ueber ein Jahr gewachsen -- deshalb steht die Liste hier und nicht
# in einer Datenbank: sie ist Wissen ueber das Spiel, keine Nutzereingabe.
_SCHREIBWEISEN = {
    "Ak-47": "AK-47", "M4a1-S": "M4A1-S", "M4a4": "M4A4", "Usp-S": "USP-S",
    "Sg 553": "SG 553", "G3sg1": "G3SG1", "Awp": "AWP", "Cz75-Auto": "CZ75-Auto",
    "P2000": "P2000", "P250": "P250", "P90": "P90", "Pp-Bizon": "PP-Bizon",
    "Mp 7": "MP7", "Mp5-Sd": "MP5-SD", "Mp7": "MP7", "Mp9": "MP9",
    "Mag-7": "MAG-7", "Mac-10": "MAC-10", "Ssg 08": "SSG 08", "Scar-20": "SCAR-20",
    "Ump-45": "UMP-45", "Xm1014": "XM1014", "Tec-9": "Tec-9", "Famas": "FAMAS",
    "Galil Ar": "Galil AR", "M249": "M249", "Five-Seven": "Five-SeveN",
    "Zeus X27": "Zeus x27", "Nv": "NV", "R8 Revolver": "R8 Revolver",
    # Nach dem Doppelpunkt faengt fuer ``wort()`` kein neues Wort an, also wird
    # aus "cs:go" ein "Cs:go" und nicht "Cs:Go" -- die Liste muss die Form
    # treffen, die wirklich entsteht.
    "Cs:go": "CS:GO", "Cs:Go": "CS:GO",
}

# Tippfehler, die im Bestand wirklich vorkamen.
_TIPPFEHLER = [
    ("Sawad-Off", "Sawed-Off"),
    ("Gallary", "Gallery"),
    ("Dreams And Nightmare", "Dreams & Nightmares"),
    # Steht so im Bestand und ist keine Abkuerzung, die ``isupper`` erkennt --
    # die Punkte dazwischen sind ungecased.
    ("O.s.i.p.r.", "O.S.I.P.R."),
]


def _text(s: Any) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(s))).strip()


def item_name(roh: Any) -> str:
    """Einheitliche Schreibweise: ``ak47 | frontside misty`` wird lesbar.

    Der Name ist in diesem Modul der einzige Schluessel auf den Gegenstand --
    zwei Schreibweisen desselben Skins waeren zwei Items und damit zwei
    Positionen, die nie zusammenfinden.
    """
    s = _text(roh)
    if not s:
        return s
    s = re.sub(r"\s*\|\s*", " | ", s)

    def wort(w: str) -> str:
        # Schon durchgehend gross geschrieben heisst: eine Abkuerzung, die so
        # gemeint ist (USP-S, XM1014, MAG-7). Die bleibt, wie sie ist.
        if w.isupper():
            return w
        # Alles andere wird Teil fuer Teil grossgeschrieben, auch ueber
        # Bindestriche hinweg -- sonst blieb ``ak-47`` stehen, und die
        # Waffennamen-Liste unten griff nie, weil sie ``Ak-47`` sucht. Genau
        # das war in der Vorgaengerfassung der Fall.
        teile = []
        for t in w.split("-"):
            teile.append(t[0].upper() + t[1:].lower() if len(t) > 1
                         else t.upper())
        return "-".join(teile)

    def gross(stueck: str) -> str:
        return " ".join(wort(w) for w in stueck.split(" ") if w)

    s = " | ".join(gross(t.strip()) for t in s.split("|"))
    for alt, neu in _SCHREIBWEISEN.items():
        s = re.sub(rf"\b{re.escape(alt)}\b", neu, s)
    for falsch, richtig in _TIPPFEHLER:
        s = re.sub(re.escape(falsch), richtig, s, flags=re.IGNORECASE)
    return s


def markt_name(name: str, wear: Optional[str], stattrak: bool) -> str:
    """Der Name, wie der Steam-Markt ihn schreibt.

    Wird heute nirgends abgefragt -- Preise kommen von Hand. Die Funktion steht
    trotzdem hier, weil sie die einzige Stelle waere, an der ein spaeterer
    Preisabruf ansetzt, und weil sie ohne Netz pruefbar ist.
    """
    teil = "StatTrak™ " if stattrak else ""
    schluss = f" ({WEAR_LANG[wear]})" if wear in WEAR_LANG else ""
    return f"{teil}{name}{schluss}"
