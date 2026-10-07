"""Depot — Tagesschlusskurse in Euro holen (v2.39.0).

Der Kontoauszug kennt Geld, keine Kurse. Ohne Kurs gibt es keinen
Depotwert, und ohne Depotwert sagt die Seite nicht, was das Depot heute ist.

Die Quelle ist onvista: die Abfragen gehen ueber die ISIN (Yahoo kennt viele
der Fonds nur unter Dollar- oder Pfund-Kuerzeln oder gar nicht), und
onvista fuehrt den LS Exchange, den Handelsplatz von Trade Republic. Es ist
eine oeffentliche, aber nicht dokumentierte Schnittstelle -- sie kann sich
aendern. Deshalb steht hier alles, was ihre Form kennt, an EINER Stelle,
und die drei Leser (``instrument_waehlen``, ``markt_waehlen``,
``schlusskurse``) sind reine Funktionen mit eigenen Tests.

Je ISIN sind es drei Abfragen beim ersten Mal (Suche, Uebersicht, Verlauf),
danach eine am Tag. Abgefragt wird nur die ISIN -- nichts ueber das Konto.

Bewusst mit ``urllib`` aus der Standardbibliothek (wie
``services/chess_platforms.py``), aufgerufen ueber ``asyncio.to_thread``.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

BASIS = "https://api.onvista.de/api/v1"
USER_AGENT = "Vexbob/1.0 (persoenlicher Tracker, Einzelnutzer)"
ZEITLIMIT = 15

# Der Pfad der Uebersicht haengt an der Art des Instruments.
TYP_PFAD = {"FUND": "funds", "STOCK": "stocks", "DERIVATIVE": "derivatives",
            "BOND": "bonds", "INDEX": "indices"}

# Reihenfolge der Boersenplaetze: zuerst der von Trade Republic, dann die
# mit langem, dichtem Verlauf. Gefuehrt wird nur in Euro.
MAERKTE = ("LS Exchange", "Lang & Schwarz", "Tradegate BSX", "gettex", "Xetra",
           "Frankfurt", "Stuttgart", "Muenchen", "München")


class KursFehler(Exception):
    """Die Quelle antwortete nicht oder nicht so, wie erwartet."""


def _holen(pfad: str, **parameter) -> dict:
    url = BASIS + pfad + ("?" + urllib.parse.urlencode(parameter) if parameter else "")
    anfrage = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT) as antwort:
            return json.loads(antwort.read())
    except urllib.error.HTTPError as e:
        raise KursFehler(f"onvista antwortet mit {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise KursFehler("onvista ist nicht erreichbar") from e
    except ValueError as e:
        raise KursFehler("onvista antwortet unlesbar") from e


# ---------------------------------------------------------------- Leser

def instrument_waehlen(antwort: dict, isin: str):
    """Aus der Suche das Instrument mit genau dieser ISIN -- (Typ, Kennung)
    oder ``None``. Die Suche liefert auch Aehnliches; ein Treffer mit
    anderer ISIN waere ein anderes Wertpapier mit anderem Kurs."""
    for x in (antwort or {}).get("list") or []:
        if x.get("isin") == isin and x.get("entityType") and x.get("entityValue"):
            return x["entityType"], str(x["entityValue"]), x.get("name")
    return None


def markt_waehlen(uebersicht: dict):
    """(Notierung, Boersenname) des besten Euro-Platzes oder ``None``."""
    plaetze = []
    for q in ((uebersicht or {}).get("quoteList") or {}).get("list") or []:
        markt = q.get("market") or {}
        notierung = markt.get("idNotation") or q.get("idNotation")
        if q.get("isoCurrency") != "EUR" or not notierung:
            continue
        name = markt.get("name") or ""
        rang = MAERKTE.index(name) if name in MAERKTE else len(MAERKTE)
        plaetze.append((rang, str(notierung), name))
    if not plaetze:
        return None
    plaetze.sort(key=lambda p: p[0])
    return plaetze[0][1], plaetze[0][2]


def schlusskurse(antwort: dict) -> list:
    """[(Tag, Kurs)] aus dem Tagesverlauf. Die Zeitstempel stehen auf 12 Uhr
    UTC des Handelstags; ein Kurs in anderer Waehrung wird abgelehnt statt
    stillschweigend als Euro gelesen."""
    if not antwort:
        return []
    if antwort.get("isoCurrency") not in (None, "EUR"):
        raise KursFehler(f"Kurse in {antwort.get('isoCurrency')} statt Euro")
    raus = {}
    for ts, kurs in zip(antwort.get("datetimeLast") or [], antwort.get("last") or []):
        if ts is None or kurs is None:
            continue
        try:
            wert = Decimal(str(kurs))
        except InvalidOperation:
            continue
        if wert <= 0:
            continue
        raus[datetime.fromtimestamp(int(ts), timezone.utc).date()] = wert
    return sorted(raus.items())


# ---------------------------------------------------------------- Abruf

def quelle_finden(isin: str) -> dict:
    """Instrument und Boersenplatz zu einer ISIN. ``gefunden: False``, wenn
    die Quelle sie nicht kennt (ausgelaufene Optionsscheine, Krypto)."""
    treffer = instrument_waehlen(_holen("/instruments/query", searchValue=isin), isin)
    if not treffer:
        return {"gefunden": False, "fehler": "Die Kursquelle kennt diese ISIN nicht."}
    typ, instrument, name = treffer
    pfad = TYP_PFAD.get(typ)
    if not pfad:
        return {"gefunden": False, "fehler": f"Instrumentart {typ} wird nicht gefuehrt."}
    markt = markt_waehlen(_holen(f"/{pfad}/{instrument}/snapshot"))
    if not markt:
        return {"gefunden": False, "fehler": "Kein Handelsplatz in Euro."}
    return {"gefunden": True, "typ": typ, "instrument": instrument,
            "notierung": markt[0], "markt": markt[1], "name": name}


def verlauf_holen(quelle: dict, ab: date, bis: date = None) -> list:
    """Schlusskurse ab ``ab`` bis heute.

    Eine Abfrage reicht hoechstens fuenf Jahre ab ihrem Startdatum -- fuer
    einen Auszug ab 2019 endeten die Kurse sonst 2024 und der Depotwert
    stuende danach still. Deshalb in Stuecken, jeweils ab dem letzten Tag."""
    bis = bis or date.today()
    raus, start = {}, ab
    for _ in range(6):                       # 30 Jahre sind genug
        stueck = schlusskurse(_holen(
            f"/instruments/{quelle['typ']}/{quelle['instrument']}/eod_history",
            idNotation=quelle["notierung"], range="Y5", startDate=start.isoformat()))
        raus.update(stueck)
        if not stueck:
            break
        letzter = stueck[-1][0]
        if letzter >= bis - timedelta(days=7) or letzter <= start:
            break
        start = letzter + timedelta(days=1)
    return sorted(raus.items())
