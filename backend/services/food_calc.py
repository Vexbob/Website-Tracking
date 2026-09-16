"""Die Rechnung des Ernaehrungs-Trackers — Mengen, Naehrwerte, Massstab.

Seit v1.98.0 rechnet dieses Modul mit ZAHLEN, nicht mit Spannen. Der Grund
ist die Aufteilung in zwei Module: die Grobstufen ("normal"/"uebermaessig"),
aus denen die Spannen kamen, sind Sache des Essenstagebuchs und haben hier
nichts mehr zu suchen.

    Ein LEBENSMITTEL wird in einer Menge eingetragen: 100 g, zwei Scheiben,
    eine Packung. Was auf der Packung steht, weiss man.

    Ein GERICHT wird in PORTIONEN eingetragen: 0,5 / 1 / 1,5. ``food_dishes``
    kennt die Naehrwerte einer Portion, also ist auch das eine Zahl und keine
    Schaetzung. Vorher stand dort eine Stufe -- und aus zwei Grobstufen eine
    Kalorienzahl zu machen, war die Genauigkeit, die es nie gab.

Was bleibt, ist die Luecke. Wenn eine Zutat keine Ballaststoffe angibt, ist
die Ballaststoff-Summe des Tages **unvollstaendig** -- nicht niedriger. Der
Unterschied ist der zwischen "du hast wenig gegessen" und "wir wissen es
nicht", und er ist der Grund, warum dieses Modul ueberhaupt Luecken ausweist
statt sie mit Nullen zu fuellen.

Naehrwerte stehen je 100 g bzw. 100 ml. Umgerechnet wird beim SPEICHERN, nie
beim Anzeigen -- sonst aendert eine korrigierte Scheibengroesse einen
vergangenen Tag.
"""


# Die Mahlzeiten stehen seit v1.97.0 in einem eigenen Dienst: sie sind das
# Einzige, was sich Tagebuch und Tracker wirklich teilen -- dass um 8 Uhr
# Fruehstueck ist, gilt nicht je Modul verschieden. Hier weiter unter den
# alten Namen erreichbar, damit der Tracker-Router nichts davon merkt.
from services.food_mahlzeit import (         # noqa: F401  (Weiterreichen)
    MAHLZEITEN, MAHLZEIT_LABEL, OHNE_MAHLZEIT, OHNE_MAHLZEIT_LABEL,
    mahlzeit_sauber,
)


# Die Grobstufen ("normal"/"uebermaessig") sind seit v1.98.0 Sache des
# Tagebuchs (routers/tagebuch_router.py). Hier wird gerechnet, nicht
# geschaetzt: ein Gericht wird in Portionen eingetragen, ein Lebensmittel in
# einer Menge, und beides ergibt eine Zahl. Damit fielen eintrag_spanne(),
# exakte_spanne() und tages_summe() weg -- eine Spanne, deren beide Enden
# gleich sind, ist keine.

# Die Naehrwerte, die der Tag zeigt -- in dieser Reihenfolge.
MAKROS = ("kcal", "protein_g", "fiber_g", "carbs_g", "fat_g")

MAKRO_LABEL = {
    "kcal": "Kalorien",
    "protein_g": "Eiweiß",
    "fiber_g": "Ballaststoffe",
    "carbs_g": "Kohlenhydrate",
    "fat_g": "Fett",
}

# Richtwerte fuer einen Tag, damit die Balken einen Massstab haben. Sie sind
# ausdruecklich KEIN persoenliches Ziel, sondern die uebliche Groessenordnung
# fuer einen Erwachsenen (D-A-CH-Referenzwerte, gerundet). Ohne Massstab
# waere ein Balken nur Dekoration; mit einem persoenlichen Ziel waere er eine
# Bewertung, um die niemand gebeten hat.
RICHTWERT = {
    "kcal": 2400,
    "protein_g": 60,
    "fiber_g": 30,
    "carbs_g": 300,
    "fat_g": 80,
}
RICHTWERT_QUELLE = "Übliche Größenordnung für einen Tag, kein persönliches Ziel."

# Wer eigene Tagesziele hinterlegt, bekommt sie als Massstab. Gesetzt wird
# jedes einzeln: wer nur auf Eiweiss achtet, soll nicht fuenf Zahlen erfinden
# muessen. Wo nichts steht, gilt weiter der allgemeine Richtwert -- und die
# Antwort sagt je Naehrwert, welcher von beiden gerade den Massstab stellt.
ZIEL_SPALTEN = {
    "kcal": "kcal_target",
    "protein_g": "protein_target",
    "fiber_g": "fiber_target",
    "carbs_g": "carbs_target",
    "fat_g": "fat_target",
}
ZIEL_QUELLE = "Dein eigenes Tagesziel."


def massstab(ziele) -> dict:
    """Je Naehrwert: {wert, eigen}. Ohne eigenes Ziel gilt der Richtwert."""
    ziele = ziele or {}
    raus = {}
    for makro in MAKROS:
        eigen = _zahl(ziele.get(ZIEL_SPALTEN[makro]))
        raus[makro] = ({"wert": eigen, "eigen": True} if eigen and eigen > 0
                       else {"wert": float(RICHTWERT[makro]), "eigen": False})
    return raus

# Hat ein Lebensmittel keine uebliche Portion hinterlegt, wird mit 100 g
# gerechnet -- der Bezug, in dem alle Naehrwerte stehen. Die Antwort sagt das
# dazu (``assumed_portion``), damit die Zahl nicht genauer aussieht als sie ist.
PORTION_FALLBACK = 100.0


def _zahl(wert):
    return None if wert is None else float(wert)


# ---------------------------------------------------------------------------
# Einheiten
# ---------------------------------------------------------------------------
# Naehrwerte stehen je 100 g bzw. je 100 ml. Alles andere -- Stueck, Portion,
# Packung -- ist eine BENANNTE Menge, deren Groesse am Lebensmittel steht.
# Umgerechnet wird beim Speichern, nicht bei jeder Anzeige: sonst aendert
# sich ein altes Rezept, sobald jemand die Portionsgroesse korrigiert.
# 'g' und 'ml' sind die Basis, in der die Naehrwerte stehen -- sie sind
# deshalb als Bezeichnung gesperrt. Alles andere ist frei benannt und steht
# als eigene Zeile am Lebensmittel: Scheibe, Becher, Riegel, halbe Packung.
# Der Schluessel IST die Bezeichnung: mit beliebig vielen Groessen gibt es
# keine feste Liste mehr, gegen die man pruefen koennte, und ein sprechender
# Wert ("Scheibe") bleibt auch in einem alten Rezept lesbar.
RESERVIERT = ("g", "ml")

# Vorschlaege fuer das Auswahlfeld -- reine Bequemlichkeit, keine Vorschrift.
GAENGIGE_GROESSEN = ("Stück", "Scheibe", "Portion", "Packung", "Glas",
                     "Becher", "Riegel", "Handvoll", "Esslöffel", "Teelöffel")


def groessen_sauber(rohe) -> list:
    """Prueft eine eingegebene Groessenliste — und sagt, was nicht geht.

    Rueckgabe: (liste, fehler). Die Liste ist entdoppelt und nummeriert.
    """
    raus, gesehen = [], set()
    for eintrag in rohe or ():
        label = str(eintrag.get("label") or "").strip()
        gramm = _zahl(eintrag.get("grams"))
        if not label and not gramm:
            continue            # eine leere Zeile ist keine Eingabe
        if not label:
            return [], "Eine Größe ohne Bezeichnung lässt sich nicht auswählen."
        if label.lower() in RESERVIERT:
            return [], ("„g“ und „ml“ sind schon vergeben — sie sind "
                        "die Grundeinheit. Nimm ein eigenes Wort: Stück, "
                        "Scheibe, Becher …")
        if not gramm or gramm <= 0:
            return [], f"Wie schwer ist eine Einheit „{label}“?"
        if label.lower() in gesehen:
            return [], f"„{label}“ steht zweimal in der Liste."
        gesehen.add(label.lower())
        raus.append({"label": label, "grams": round(gramm, 2),
                     "position": len(raus)})
    return raus, None


def einheiten_fuer(lebensmittel: dict, groessen=()) -> list:
    """Welche Einheiten dieses Lebensmittel anbietet — mit Beschriftung.

    Immer dabei: die Basis (g oder ml). Dazu jede eigene Groesse, die am
    Lebensmittel hinterlegt ist. Was nicht hinterlegt ist, wird nicht
    angeboten: ein Auswahlfeld mit "Packung", das dann 100 g rechnet, waere
    geraten.
    """
    basis = lebensmittel.get("base_unit") or "g"
    raus = [{"key": basis, "label": basis, "grams": 1.0}]
    for g in groessen or ():
        label = str(g.get("label") or "").strip()
        gramm = _zahl(g.get("grams"))
        if not label or not gramm or label.lower() in RESERVIERT:
            continue
        raus.append({"key": label, "label": label, "grams": round(gramm, 2)})
    return raus


def in_basis(menge, einheit: str, lebensmittel: dict, groessen=()):
    """Rechnet eine Eingabe in Gramm bzw. Milliliter um.

    Rueckgabe: (wert, hinweis) -- der Hinweis ist gesetzt, wenn geraten
    werden musste (eine Bezeichnung, zu der keine Groesse mehr passt).
    """
    menge = float(menge or 0)
    if menge <= 0:
        return 0.0, "Eine Menge von null ergibt keine Portion."
    basis = lebensmittel.get("base_unit") or "g"
    if einheit in RESERVIERT:
        return menge, None
    gesucht = str(einheit or "").strip().lower()
    for g in groessen or ():
        label = str(g.get("label") or "").strip()
        gramm = _zahl(g.get("grams"))
        if gramm and label.lower() == gesucht:
            return menge * gramm, None
    # Bis v1.89.0 hiessen die Einheiten 'portion' und 'packung'. Zeilen aus
    # der Zeit sind migriert, aber ein alter Tab im Browser kann sie noch
    # schicken -- die Spalten dafuer gibt es weiter.
    alt = {"portion": "portion_g", "packung": "package_g"}.get(gesucht)
    if alt:
        gramm = _zahl(lebensmittel.get(alt))
        if gramm:
            return menge * gramm, None
    return menge * PORTION_FALLBACK, (
        f"Zu „{einheit}“ ist keine Größe hinterlegt — gerechnet wird mit "
        f"{PORTION_FALLBACK:.0f} {basis}.")


def je_menge(lebensmittel: dict, gramm) -> dict:
    """Die Naehrwerte fuer eine bestimmte Menge, nicht fuer 100."""
    anteil = float(gramm or 0) / 100.0
    return {m: (None if lebensmittel.get(m) is None
                else round(float(lebensmittel[m]) * anteil, 1))
            for m in MAKROS}


def zutaten_summe(zutaten) -> dict:
    """Naehrwerte eines Gerichts aus seinen Zutaten (eine normale Portion).

    ``zutaten``: Folge von (gramm, lebensmittel-dict).
    Rueckgabe: {makro: wert oder None, "grams": gesamt, "incomplete": [makros]}
    """
    summe = {m: 0.0 for m in MAKROS}
    fehlt = set()
    gramm_gesamt = 0.0
    for gramm, lebensmittel in zutaten:
        gramm = float(gramm or 0)
        gramm_gesamt += gramm
        anteil = gramm / 100.0
        for makro in MAKROS:
            wert = _zahl(lebensmittel.get(makro))
            if wert is None:
                # Eine fehlende Angabe macht die ganze Summe unvollstaendig.
                # Sie einfach wegzulassen hiesse: die Summe faellt zu niedrig
                # aus, und niemand sieht warum.
                fehlt.add(makro)
            else:
                summe[makro] += wert * anteil
    return {
        **{m: (None if m in fehlt else round(summe[m], 1)) for m in MAKROS},
        "grams": round(gramm_gesamt, 1),
        "incomplete": sorted(fehlt),
    }


def tages_summe_genau(eintraege, ziele=None) -> dict:
    """Die Tagessumme je Naehrwert, gemessen am eigenen Ziel oder am Richtwert.

    ``eintraege``: Folge von Dicts {makro: Zahl oder None} -- je Eintrag die
    Naehrwerte der tatsaechlich gegessenen Menge.
    ``ziele``: die Zeile aus ``food_settings`` oder None.

    Rueckgabe je Makro: {label, value, incomplete, reference, own_target,
    share, remaining, over}.

    ``incomplete`` ist der Kern und bleibt: ein Lebensmittel ohne
    Ballaststoff-Angabe macht die Summe UNVOLLSTAENDIG, nicht niedriger. Der
    Unterschied zwischen "du hast wenig gegessen" und "wir wissen es nicht"
    ist der Grund, warum dieses Modul ueberhaupt Luecken ausweist.
    """
    summe = {m: 0.0 for m in MAKROS}
    fehlt = set()
    for eintrag in eintraege:
        for makro in MAKROS:
            wert = _zahl(eintrag.get(makro))
            if wert is None:
                fehlt.add(makro)
            else:
                summe[makro] += wert

    mass = massstab(ziele)
    raus = {}
    for makro in MAKROS:
        richt = mass[makro]["wert"]
        wert = summe[makro]
        raus[makro] = {
            "label": MAKRO_LABEL[makro],
            "value": round(wert),
            "incomplete": makro in fehlt,
            "reference": round(richt),
            "own_target": mass[makro]["eigen"],
            # Ungedeckelt: das Deckeln macht der Ring, nicht die Rechnung.
            # Wer hier deckelt, kann spaeter nicht mehr sagen, wie weit
            # darueber es war.
            "share": round(wert / richt, 3) if richt else 0,
            # Ueberschritten heisst 0 und nicht negativ; wie weit darueber,
            # sagt ``over``.
            "remaining": max(0, round(richt - wert)),
            "over": max(0, round(wert - richt)),
        }
    return raus
