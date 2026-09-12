"""Aus Stufen werden Spannen — die Rechnung des Ernaehrungs-Moduls.

Eingetragen wird eine Stufe ("normal" oder "uebermaessig"), keine Gramm.
Daraus eine einzelne Zahl zu machen, waere die Genauigkeit, die es nie gab:
"2.147 kcal" aus zwei Grobstufen ist erfunden. Deshalb rechnet dieses Modul
grundsaetzlich mit **Spannen** -- von bis.

Die Faktoren stehen bewusst hier und nicht in der Datenbank: sie sind eine
Aussage darueber, was "normal" und "uebermaessig" heissen soll, und die
gehoert an eine Stelle, an der sie jemand liest.

    normal        0,85 bis 1,15 mal die Portion
                  Wer eine uebliche Portion isst, trifft sie ungefaehr --
                  ein Spielraum von gut einem Zehntel nach beiden Seiten.
    uebermaessig  1,4 bis 2,0 mal die Portion
                  "Deutlich mehr" heisst irgendetwas zwischen anderthalb und
                  doppelt. Breiter als die normale Stufe, weil die Erinnerung
                  daran auch unschaerfer ist.

Fehlende Naehrwerte bleiben fehlend. Wenn eine Zutat keine Ballaststoffe
angibt, ist die Ballaststoff-Summe des Tages **unvollstaendig** -- nicht
niedriger. Der Unterschied ist der zwischen "du hast wenig gegessen" und
"wir wissen es nicht".
"""

STUFEN = {
    "normal": (0.85, 1.15),
    "viel": (1.4, 2.0),
}
STUFEN_LABEL = {"normal": "normal", "viel": "übermäßig"}

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
EINHEITEN = ("g", "ml", "portion", "packung")
EINHEIT_LABEL = {"g": "g", "ml": "ml", "portion": "Portion", "packung": "Packung"}


def einheiten_fuer(lebensmittel: dict) -> list:
    """Welche Einheiten dieses Lebensmittel anbietet — mit Beschriftung.

    Eine Einheit ohne hinterlegte Groesse wird gar nicht erst angeboten: ein
    Auswahlfeld mit "Packung", das dann 100 g rechnet, waere geraten.
    """
    basis = lebensmittel.get("base_unit") or "g"
    raus = [{"key": basis, "label": EINHEIT_LABEL[basis], "grams": 1.0}]
    portion = _zahl(lebensmittel.get("portion_g"))
    if portion:
        raus.append({
            "key": "portion",
            "label": (lebensmittel.get("portion_label") or "Portion"),
            "grams": portion,
        })
    packung = _zahl(lebensmittel.get("package_g"))
    if packung:
        raus.append({"key": "packung", "label": "Packung", "grams": packung})
    return raus


def in_basis(menge, einheit: str, lebensmittel: dict):
    """Rechnet eine Eingabe in Gramm bzw. Milliliter um.

    Rueckgabe: (wert, hinweis) -- der Hinweis ist gesetzt, wenn geraten
    werden musste (Einheit ohne hinterlegte Groesse).
    """
    menge = float(menge or 0)
    if menge <= 0:
        return 0.0, "Eine Menge von null ergibt keine Portion."
    basis = lebensmittel.get("base_unit") or "g"
    if einheit in ("g", "ml"):
        return menge, None
    if einheit == "portion":
        gramm = _zahl(lebensmittel.get("portion_g"))
        if not gramm:
            return menge * PORTION_FALLBACK, (
                "Für dieses Lebensmittel ist keine Portionsgröße hinterlegt — "
                f"gerechnet wird mit {PORTION_FALLBACK:.0f} {basis}.")
        return menge * gramm, None
    if einheit == "packung":
        gramm = _zahl(lebensmittel.get("package_g"))
        if not gramm:
            return menge * PORTION_FALLBACK, (
                "Für dieses Lebensmittel ist keine Packungsgröße hinterlegt — "
                f"gerechnet wird mit {PORTION_FALLBACK:.0f} {basis}.")
        return menge * gramm, None
    return menge, None


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


def eintrag_spanne(basis: dict, stufe: str) -> dict:
    """Aus einer Portion und einer Stufe die Spanne je Makro."""
    unten, oben = STUFEN.get(stufe, STUFEN["normal"])
    raus = {}
    for makro in MAKROS:
        wert = _zahl(basis.get(makro))
        if wert is None:
            raus[makro] = None
        else:
            raus[makro] = (round(wert * unten, 1), round(wert * oben, 1))
    return raus


def tages_summe(eintraege) -> dict:
    """Die Spanne des Tages.

    ``eintraege``: Folge von Spannen aus ``eintrag_spanne``.
    Rueckgabe je Makro: {min, max, incomplete, reference, share_min, share_max}
    """
    unten = {m: 0.0 for m in MAKROS}
    oben = {m: 0.0 for m in MAKROS}
    fehlt = set()
    for spanne in eintraege:
        for makro in MAKROS:
            wert = spanne.get(makro)
            if wert is None:
                fehlt.add(makro)
            else:
                unten[makro] += wert[0]
                oben[makro] += wert[1]

    raus = {}
    for makro in MAKROS:
        richt = RICHTWERT[makro]
        raus[makro] = {
            "label": MAKRO_LABEL[makro],
            "min": round(unten[makro]),
            "max": round(oben[makro]),
            "incomplete": makro in fehlt,
            "reference": richt,
            # Anteil am Richtwert, gedeckelt bei 150 %: ein Balken, der
            # weiterlaeuft, sagt nichts mehr -- ab da steht die Zahl daneben.
            "share_min": min(1.5, round(unten[makro] / richt, 3)),
            "share_max": min(1.5, round(oben[makro] / richt, 3)),
        }
    return raus
