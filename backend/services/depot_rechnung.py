"""Depot rechnen — Stueck, Einstand, Wert und Ergebnis (v2.39.0).

Reine Funktionen ueber Buchungen (Zeilen von ``depot_buchungen``, nach
Datum und Reihe) und Kurse (``{isin: [(tag, kurs)]}``, aufsteigend).

**Das Gesamtergebnis braucht keine Annahme:**

    Ergebnis = Depotwert + Cash − (Einzahlungen − Auszahlungen)

Was das Depot wert ist und was auf dem Konto liegt, minus was netto
hineingeflossen ist. Darin steckt alles: Kursgewinne, Verkaeufe, Zinsen,
Ertraege, Gebuehren, Steuern. Bis v2.38.0 stand an dieser Stelle eine Kurve
aus Ein- und Ausgaengen; wer mehr entnommen als eingezahlt hatte, sah dort
einen negativen Bestand.

**Stueckzahlen.** Die Zeilen ab Juni 2024 nennen sie, die aelteren nicht.
Je Wertpapier gibt es deshalb eine Grenze -- seine letzte Zeile ohne
Stueckzahl. Was danach kommt, zaehlt der Auszug; den Stand AN der Grenze
liefert eines von dreien:

- nichts: nennt jede Zeile die Stueckzahl, beginnt der Bestand bei 0;
- die Stueckzahl laut App (``anker``), von der aus zurueckgerechnet wird;
- der Verkauf: eine Position, deren letzte Zeile ein Verkauf ist, endet bei 0;
- die Kurse: Stueck = Betrag ÷ Schlusskurs am Tag jeder alten Zeile.

Das Letzte ist eine Rechnung, keine Angabe des Auszugs -- und sie ist genau
genug: bei den Zeilen MIT Stueckzahl liegt der Ausfuehrungskurs im Median
bei 1,0007 des Schlusskurses (Streuung 1,4 %), ueber viele Zeilen mittelt
sich das weg. Die erste Fassung rechnete hier nicht und schrieb „Stueck
unbekannt“; der Nutzer fragte zu Recht, warum der ganze Auszug die
Stueckzahl nicht hergibt. Die Zahl laut App geht weiterhin vor, und ``quelle = "kurse"`` sagt, woher sie
kommt. Fehlt auch ein Kurs, ist der Bestand unbekannt und die Position steht
zum Einstand im Wert.

**Einstand und Realisiert** nach gleitendem Durchschnitt, wie die App den
Kaufkurs zeigt: ein Verkauf realisiert Erloes − anteiligen Einstand. Vor der
Grenze gibt es keine Stueckzahl und damit keinen Durchschnitt; dort ist der
Einstand das eingesetzte Geld (Kaeufe − Verkaeufe). Wurde damals mehr
verkauft als gekauft, gilt der Ueberschuss an der Grenze als realisiert. Fuer
eine ganz verkaufte Position stimmt die Summe immer: Erloese − Kaeufe.
"""
from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

HANDEL = ("kauf", "sparplan", "verkauf")
# Geld, das von aussen kommt oder hinausgeht -- alles andere ist Ergebnis.
EXTERN = ("einzahlung", "auszahlung", "karte")
NULL = Decimal(0)
EPS = Decimal("0.000001")
# Wie weit vor dem ersten noetigen Tag Kurse geholt werden: ein Kauf am
# Montag braucht den Schlusskurs vom Freitag.
VORLAUF = timedelta(days=7)
# Wie alt ein Schlusskurs hoechstens sein darf, um eine alte Zeile in Stueck
# umzurechnen: ueber Feiertage hinweg, nicht ueber eine Kursluecke.
KURS_HOECHSTENS_ALT = timedelta(days=10)


def _d(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def _menge(b) -> Decimal:
    q = _d(b["stueck"])
    return -q if b["art"] == "verkauf" else q


def _f(x, stellen=2):
    return None if x is None else round(float(x), stellen)


# ------------------------------------------------------------ Positionen

def _kurs_am(liste, tag):
    """Der letzte Schlusskurs an oder vor ``tag`` -- ``None``, wenn keiner da
    oder er zu alt ist."""
    i = bisect_right([t for t, _ in liste], tag)
    if i == 0 or tag - liste[i - 1][0] > KURS_HOECHSTENS_ALT:
        return None
    return liste[i - 1][1]


def _aus_kursen(handel, g, liste):
    """Stand nach den alten Zeilen, je Zeile Betrag ÷ Schlusskurs -- oder
    ``None``, wenn fuer eine davon kein Kurs da ist."""
    menge = NULL
    for b in handel[:g + 1]:
        if b["stueck"] is not None:
            menge += _menge(b)
            continue
        k = _kurs_am(liste, b["datum"])
        if not k:
            return None
        q = abs(_d(b["betrag"])) / k
        menge += -q if b["art"] == "verkauf" else q
    return menge


def positionen(rows, anker=None, kurse=None) -> dict:
    """Je ISIN: Grenze, Stand an der Grenze und woher er kommt.

    ``anker``: ``{isin: (stueck, tag)}`` -- die Stueckzahl laut App.
    ``kurse``: ``{isin: [(tag, kurs)]}`` -- fuer die Rechnung aus Kursen.
    Rueckgabe ``{isin: {grenze, ab, start, quelle, fehler, geschaetzt, handel}}``;
    ``start`` ist ``None``, wenn sich der Bestand nicht rechnen laesst.
    """
    anker = anker or {}
    je = defaultdict(list)
    for b in rows:
        if b["isin"] and b["art"] in HANDEL:
            je[b["isin"]].append(b)
    raus = {}
    for isin, handel in je.items():
        ohne = [i for i, b in enumerate(handel) if b["stueck"] is None]
        g = ohne[-1] if ohne else -1
        nachher = handel[g + 1:]
        fehler = None
        if g < 0:
            start, quelle = NULL, "auszug"
        elif isin in anker and anker[isin][1] >= handel[g]["datum"]:
            stueck, tag = anker[isin]
            start = _d(stueck) - sum((_menge(b) for b in nachher if b["datum"] <= tag), NULL)
            quelle = "app"
        elif handel[-1]["art"] == "verkauf":
            start, quelle = -sum((_menge(b) for b in nachher), NULL), "verkauft"
        else:
            start = _aus_kursen(handel, g, (kurse or {}).get(isin) or [])
            quelle = "kurse" if start is not None else None
        # Ein Bestand unter null heisst: die Zahl passt nicht zum Auszug
        # (vertippt, oder der Auszug beginnt nach dem ersten Kauf).
        if start is not None:
            q = start
            for b in [None] + nachher:
                if b is not None:
                    q += _menge(b)
                if q < -EPS:
                    fehler = {"app": "Die Stückzahl aus der App passt nicht zum Auszug.",
                              "kurse": "Aus den Kursen ergibt sich kein stimmiger Bestand."
                              }.get(quelle, "Der Auszug beginnt nach dem ersten Kauf.")
                    start, quelle = None, None
                    break
        raus[isin] = {"grenze": g, "ab": handel[g]["datum"] if g >= 0 else None,
                      "start": start, "quelle": quelle, "fehler": fehler,
                      "geschaetzt": len(ohne) if quelle == "kurse" else 0, "handel": handel}
    return raus


def gehen(p) -> dict:
    """Die Handelszeilen einer Position der Reihe nach.

    -> ``{"schritte": [(tag, menge|None, einstand)], "realisiert": [(tag, betrag)],
    "menge", "einstand"}``. ``menge`` ist ``None``, solange sie unbekannt ist.
    """
    g, start = p["grenze"], p["start"]
    einstand = NULL
    menge = NULL if g < 0 else None
    schritte, realisiert = [], []
    for i, b in enumerate(p["handel"]):
        betrag = _d(b["betrag"])
        if menge is None:
            einstand -= betrag                    # Kauf negativ: Einstand steigt
            if i == g and start is not None:
                menge = start
                if menge <= EPS:
                    # An der Grenze ist nichts mehr da: alles ist realisiert.
                    realisiert.append((b["datum"], -einstand))
                    einstand, menge = NULL, NULL
                elif einstand < 0:
                    realisiert.append((b["datum"], -einstand))
                    einstand = NULL
        elif b["art"] == "verkauf":
            q = _d(b["stueck"])
            abgang = einstand * min(q / menge, Decimal(1)) if menge > EPS else einstand
            realisiert.append((b["datum"], betrag - abgang))
            einstand -= abgang
            menge -= q
            if menge <= EPS:
                einstand, menge = NULL, NULL
        else:
            einstand -= betrag
            menge += _d(b["stueck"])
        schritte.append((b["datum"], menge, einstand))
    return {"schritte": schritte, "realisiert": realisiert, "menge": menge, "einstand": einstand}


# ------------------------------------------------------------ Auswertung

def _beginn(pos, rows) -> date:
    """Der erste Tag, an dem jeder rechenbare Bestand bekannt ist."""
    grenzen = [p["ab"] for p in pos.values() if p["ab"] and p["start"] is not None]
    return max(grenzen) if grenzen else rows[0]["datum"]


def kursbedarf(rows, anker=None) -> dict:
    """``{isin: ab}`` -- welche Kurse ab wann noetig sind: fuer jedes
    Wertpapier, das ab dem Beginn des Verlaufs irgendwann gehalten wurde.
    Laesst sich ein Bestand nur aus Kursen rechnen, ab seiner ersten Zeile.

    Gerechnet OHNE Kurse, damit der Bedarf nicht davon abhaengt, was schon
    geholt ist -- sonst verschoebe jeder Abruf den naechsten."""
    if not rows:
        return {}
    pos = positionen(rows, anker)
    aus_kursen = {i for i, p in pos.items() if p["start"] is None and not p["fehler"]}
    grenzen = [p["ab"] for i, p in pos.items() if p["ab"] and (p["start"] is not None or i in aus_kursen)]
    beginn = max(grenzen) if grenzen else rows[0]["datum"]
    raus = {}
    for isin, p in pos.items():
        w = gehen(p)
        stand = [s for s in w["schritte"] if s[0] <= beginn]
        gehalten = bool(stand) and (stand[-1][1] is None or stand[-1][1] > EPS)
        spaeter = any(b["datum"] > beginn for b in p["handel"])
        if isin in aus_kursen:
            raus[isin] = p["handel"][0]["datum"] - VORLAUF
        elif gehalten or spaeter:
            erster = max(beginn, p["handel"][0]["datum"])
            raus[isin] = erster - VORLAUF
    return raus


def auswerten(rows, kurse, anker=None, heute=None) -> dict:
    """Alles fuer Ueberblick und Statistik aus EINER Rechnung.

    -> ``{"beginn", "ende", "verlauf": [{datum, wert, einstand, ergebnis}],
    "positionen": {isin: {...}}, "realisiert": [(tag, isin, betrag)],
    "jetzt": {...}}``
    """
    pos = positionen(rows, anker, kurse)
    gang = {isin: gehen(p) for isin, p in pos.items()}
    beginn = _beginn(pos, rows)
    ende = max(heute or rows[-1]["datum"], rows[-1]["datum"])

    # Tage des Verlaufs: Beginn, jeder Handelstag mit Kurs, jeder Buchungstag, Ende.
    tage = {beginn, ende}
    for isin, liste in kurse.items():
        if isin in pos:
            tage.update(t for t, _ in liste if beginn <= t <= ende)
    tage.update(b["datum"] for b in rows if beginn <= b["datum"] <= ende)
    tage = sorted(tage)

    zeiger_s = {isin: 0 for isin in gang}
    zeiger_k = {isin: 0 for isin in gang}
    zustand = {isin: (None, NULL, False) for isin in gang}    # menge, einstand, begonnen
    kurs_jetzt = {}
    i_row, cash, netto = 0, NULL, NULL
    verlauf = []
    for tag in tage:
        while i_row < len(rows) and rows[i_row]["datum"] <= tag:
            b = rows[i_row]
            if b["saldo"] is not None:
                cash = _d(b["saldo"])
            if b["art"] in EXTERN:
                netto += _d(b["betrag"])
            i_row += 1
        wert = einstand_summe = NULL
        for isin, w in gang.items():
            s = w["schritte"]
            while zeiger_s[isin] < len(s) and s[zeiger_s[isin]][0] <= tag:
                _, m, e = s[zeiger_s[isin]]
                zustand[isin] = (m, e, True)
                zeiger_s[isin] += 1
            m, e, begonnen = zustand[isin]
            if not begonnen:
                continue
            liste = kurse.get(isin) or []
            while zeiger_k[isin] < len(liste) and liste[zeiger_k[isin]][0] <= tag:
                kurs_jetzt[isin] = liste[zeiger_k[isin]]
                zeiger_k[isin] += 1
            if m is not None and m <= EPS:
                continue
            einstand_summe += max(e, NULL)
            if m is not None and isin in kurs_jetzt:
                wert += m * kurs_jetzt[isin][1]
            else:
                # Ohne Stueck oder ohne Kurs: zum Einstand, nicht geschaetzt.
                wert += max(e, NULL)
        verlauf.append({"datum": tag.isoformat(), "wert": _f(wert), "einstand": _f(einstand_summe),
                        "ergebnis": _f(wert + cash - netto), "cash": _f(cash), "netto": _f(netto)})

    # Stand je Wertpapier am Ende.
    raus_pos = {}
    for isin, p in pos.items():
        w = gang[isin]
        m, e = w["menge"], w["einstand"]
        gehalten = (m > EPS) if m is not None else p["handel"][-1]["art"] != "verkauf"
        k = kurs_jetzt.get(isin)
        wert = (m * k[1]) if (gehalten and m is not None and k) else None
        raus_pos[isin] = {
            "im_bestand": bool(gehalten),
            "stueck": _f(m, 6) if (m is not None and gehalten) else None,
            "stueck_quelle": p["quelle"], "stueck_fehler": p["fehler"],
            "stueck_geschaetzt": p["geschaetzt"],
            "stueck_ab": p["ab"].isoformat() if p["ab"] else None,
            "kurs": _f(k[1], 4) if k else None, "kurs_datum": k[0].isoformat() if k else None,
            "einstand": _f(max(e, NULL)) if gehalten else 0.0,
            "kaufkurs": _f(e / m, 4) if (gehalten and m is not None and m > EPS) else None,
            "wert": _f(wert),
            "unrealisiert": _f(wert - e) if wert is not None else None,
            "realisiert": _f(sum((x[1] for x in w["realisiert"]), NULL)),
        }
    realisiert = sorted(((t, isin, b) for isin, w in gang.items() for t, b in w["realisiert"]),
                        key=lambda x: x[0])
    letzt = verlauf[-1]
    bestand = [x for x in raus_pos.values() if x["im_bestand"]]
    jetzt = {
        "wert": letzt["wert"], "einstand": letzt["einstand"], "cash": letzt["cash"],
        "netto_eingezahlt": letzt["netto"], "ergebnis": letzt["ergebnis"],
        "unrealisiert": _f(sum((Decimal(str(x["unrealisiert"])) for x in bestand
                                if x["unrealisiert"] is not None), NULL)),
        "realisiert": _f(sum((x[2] for x in realisiert), NULL)),
        "kurse_stand": max((x["kurs_datum"] for x in bestand if x["kurs_datum"]), default=None),
    }
    return {"beginn": beginn, "ende": ende, "verlauf": verlauf, "positionen": raus_pos,
            "realisiert": realisiert, "jetzt": jetzt}


def _stand_bis(verlauf, tag_iso):
    """Der letzte Punkt des Verlaufs an oder vor einem Tag."""
    stand = None
    for p in verlauf:
        if p["datum"] > tag_iso:
            break
        stand = p
    return stand


def ergebnis_monate(verlauf, monate) -> list:
    """Ergebnis je Monat: Gesamtergebnis am Monatsende minus am Ende des
    Vormonats. Monate vor dem Beginn des Verlaufs bleiben leer (``None``)."""
    if not verlauf:
        return [{"monat": m, "ergebnis": None} for m in monate]
    erster = verlauf[0]["datum"][:7]
    raus = []
    for m in monate:
        j, mm = int(m[:4]), int(m[5:7])
        ende = date(j + (mm == 12), mm % 12 + 1, 1) - timedelta(days=1)
        vor = date(j, mm, 1) - timedelta(days=1)
        if m < erster:
            raus.append({"monat": m, "ergebnis": None})
            continue
        a = _stand_bis(verlauf, vor.isoformat()) or verlauf[0]
        b = _stand_bis(verlauf, ende.isoformat())
        raus.append({"monat": m, "ergebnis": _f(b["ergebnis"] - a["ergebnis"]) if b else None})
    return raus


def ergebnis_zeitraum(verlauf, von: date, bis: date):
    """Gesamtergebnis am Ende minus am Tag vor dem Anfang -- ``None``, wenn
    der Zeitraum ganz vor dem Verlauf liegt. Beginnt er davor, zaehlt ab dem
    Beginn des Verlaufs (``ab`` sagt das)."""
    if not verlauf or bis.isoformat() < verlauf[0]["datum"]:
        return None, None
    a = _stand_bis(verlauf, (von - timedelta(days=1)).isoformat()) or verlauf[0]
    b = _stand_bis(verlauf, bis.isoformat())
    return _f(b["ergebnis"] - a["ergebnis"]), a["datum"]


def realisiert_jahre(realisiert, erstes: int, letztes: int) -> list:
    """Realisiert je Kalenderjahr, lueckenlos."""
    summe = defaultdict(Decimal)
    for t, _, b in realisiert:
        summe[t.year] += b
    return [{"jahr": j, "realisiert": _f(summe.get(j, NULL))} for j in range(erstes, letztes + 1)]
