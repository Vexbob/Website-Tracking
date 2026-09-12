"""Open Food Facts abfragen — Naehrwerte zu einem Strichcode.

Offene Datenbank unter ODbL: keine Anmeldung, kein Schluessel, keine Kosten.
Gefragt wird nach dem Strichcode (``hole_produkt``) oder nach Text
(``suche``); beide liefern dieselbe Form, damit der Router nur eine kennt.

Drei Dinge, die diese Quelle ausmachen:

1. **Fehlende Angaben sind haeufig und bleiben None.** Gerade Ballaststoffe
   fehlen bei vielen Produkten. Eine 0 an dieser Stelle waere eine Zahl, die
   in jeder Tagessumme mitlaeuft, ohne zu stimmen -- und niemand koennte sie
   spaeter von einer echten 0 unterscheiden.
2. **Die Daten sind von Freiwilligen erfasst.** Sie koennen falsch sein. Was
   von hier kommt, ist deshalb ein Vorschlag zum Nachbessern, keine Wahrheit.
3. **Ein aussagekraeftiger User-Agent ist Pflicht** (steht so in ihrer
   Dokumentation); ohne ihn sperren sie Abfragen aus.

Bewusst mit ``urllib`` aus der Standardbibliothek -- wie beim Schach-Modul,
aufgerufen ueber ``asyncio.to_thread``.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "Vexbob/1.0 (persoenlicher Ernaehrungstracker, Einzelnutzer)"
BASIS = "https://world.openfoodfacts.org"
# Die Textsuche laeuft ueber den eigenen Suchdienst von Open Food Facts.
# Der alte Weg (``/cgi/search.pl``) ist dieselbe Maschine, die auch die
# Webseite ausliefert, und antwortet unter Last regelmaessig mit 503 -- als
# einziger Weg ist er zu wacklig. Er bleibt als Rueckfall stehen, weil er
# manchmal Treffer hat, die der Suchdienst nicht kennt.
SUCHDIENST = "https://search.openfoodfacts.org"
ZEITLIMIT = 20

# Nur die Felder holen, die gebraucht werden. Ein volles Produkt sind einige
# hundert Felder -- bei einer Suche mit 20 Treffern ist das ein Vielfaches an
# Daten fuer nichts.
FELDER = ("code,product_name,product_name_de,brands,quantity,serving_size,"
          "serving_quantity,nutriments")

# Unsere Spalten und ihre Namen in den ``nutriments``.
NAEHRWERTE = {
    "kcal": "energy-kcal_100g",
    "protein_g": "proteins_100g",
    "carbs_g": "carbohydrates_100g",
    "sugar_g": "sugars_100g",
    "fat_g": "fat_100g",
    "sat_fat_g": "saturated-fat_100g",
    "fiber_g": "fiber_100g",
    "salt_g": "salt_100g",
}


class QuellenFehler(Exception):
    """Die Datenbank hat nicht geliefert — mit einem Satz, der sagt warum."""


def _hole(url: str) -> dict:
    anfrage = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT) as antwort:
            return json.loads(antwort.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise QuellenFehler("Zu diesem Strichcode gibt es dort keinen Eintrag.")
        if e.code in (429, 502, 503, 504):
            # Kein Fehler an unserer Seite: die Datenbank wird ehrenamtlich
            # betrieben und ist zeitweise ueberlastet. Der Satz sagt das --
            # und dass der Strichcode meist trotzdem geht.
            raise QuellenFehler(
                "Open Food Facts ist gerade überlastet und antwortet nicht "
                "(Fehler %d). Der Strichcode funktioniert meist trotzdem; "
                "sonst in ein paar Minuten noch einmal." % e.code)
        raise QuellenFehler(f"Open Food Facts antwortete mit Fehler {e.code}.")
    except urllib.error.URLError as e:
        raise QuellenFehler(f"Open Food Facts war nicht erreichbar: {e.reason}")
    except json.JSONDecodeError:
        raise QuellenFehler("Die Antwort war nicht lesbar.")


def _zahl(wert):
    """Macht aus dem, was dort steht, eine Zahl -- oder None.

    Die Werte kommen mal als Zahl, mal als Zeichenkette, mal als leerer Text.
    ``None`` heisst durchgehend "keine Angabe".
    """
    if wert is None or wert == "":
        return None
    try:
        zahl = float(wert)
    except (TypeError, ValueError):
        return None
    # Negative Naehrwerte gibt es nicht; sie kommen aus Tippfehlern in der
    # Datenbank und werden wie eine fehlende Angabe behandelt.
    return zahl if zahl >= 0 else None


def _portion(produkt: dict):
    """Die uebliche Portion in Gramm, wenn die Datenbank eine kennt."""
    menge = _zahl(produkt.get("serving_quantity"))
    if menge:
        return menge
    text = (produkt.get("serving_size") or "").replace(",", ".")
    zahl = ""
    for zeichen in text:
        if zeichen.isdigit() or zeichen == ".":
            zahl += zeichen
        elif zahl:
            break
    return _zahl(zahl)


def _text(wert) -> str:
    """Aus dem, was dort steht, einen Text machen.

    Dieselbe Angabe kommt je nach Weg anders an: der Suchdienst liefert
    ``brands`` als Liste, die Produktabfrage als Text mit Komma, und ein
    Name kann als Sprach-Woerterbuch kommen. Wer das nicht abfaengt, bekommt
    im Frontend "['Crownfield']" zu lesen.
    """
    if wert is None:
        return ""
    if isinstance(wert, list):
        return str(wert[0]).strip() if wert else ""
    if isinstance(wert, dict):
        for schluessel in ("de", "en", "main"):
            if wert.get(schluessel):
                return str(wert[schluessel]).strip()
        return next((str(v).strip() for v in wert.values() if v), "")
    return str(wert).strip()


def _umbauen(produkt: dict) -> dict:
    """Ein OFF-Produkt in die Form, die dieses Projekt speichert."""
    n = produkt.get("nutriments") or {}
    daten = {
        "barcode": str(produkt.get("code") or "").strip() or None,
        # Der deutsche Name zuerst: das Modul ist auf Deutsch, und viele
        # Produkte tragen beides.
        "name": _text(produkt.get("product_name_de")) or _text(produkt.get("product_name")),
        "brand": _text(produkt.get("brands")).split(",")[0].strip() or None,
        "quantity": _text(produkt.get("quantity")) or None,
        "portion_g": _portion(produkt),
        "source": "off",
    }
    for spalte, feld in NAEHRWERTE.items():
        daten[spalte] = _zahl(n.get(feld))
    # Was ohne Naehrwerte und ohne Namen ankommt, ist kein brauchbarer
    # Treffer -- das sagt der Aufrufer dem Nutzer lieber, als eine leere
    # Zeile anzulegen.
    daten["usable"] = bool(daten["name"]) and daten["kcal"] is not None
    fehlend = [s for s in NAEHRWERTE if daten[s] is None]
    daten["missing"] = fehlend
    return daten


def hole_produkt(barcode: str) -> dict:
    code = "".join(z for z in str(barcode or "") if z.isdigit())
    if not code:
        raise QuellenFehler("Das ist kein Strichcode.")
    antwort = _hole(f"{BASIS}/api/v2/product/{code}.json?fields={FELDER}")
    # status 0 heisst: Code gueltig, aber kein Eintrag vorhanden.
    if not antwort.get("status") or not antwort.get("product"):
        raise QuellenFehler(
            "Zu diesem Strichcode gibt es bei Open Food Facts noch keinen "
            "Eintrag. Du kannst das Lebensmittel von Hand anlegen.")
    return _umbauen(antwort["product"])


def _brauchbare(produkte: list) -> list:
    treffer = []
    for produkt in produkte:
        daten = _umbauen(produkt)
        if daten["usable"]:
            treffer.append(daten)
    return treffer


def suche(text: str, hoechstens: int = 12) -> list:
    """Textsuche — fuer alles ohne Strichcode (Obst, Selbstgekochtes).

    Zwei Wege, in dieser Reihenfolge: der Suchdienst von Open Food Facts und,
    wenn der nicht antwortet, die alte Suche der Webseite. Sie hat unter Last
    regelmaessig 503 geliefert -- deshalb ist sie nur noch der Rueckfall und
    nicht mehr der einzige Weg.
    """
    begriff = (text or "").strip()
    if len(begriff) < 2:
        return []

    try:
        antwort = _hole(f"{SUCHDIENST}/search?q={urllib.parse.quote(begriff)}"
                        f"&page_size={int(hoechstens)}&fields={FELDER}")
        treffer = _brauchbare(antwort.get("hits") or [])
        if treffer:
            return treffer
    except QuellenFehler:
        treffer = []

    antwort = _hole(f"{BASIS}/cgi/search.pl?search_terms="
                    f"{urllib.parse.quote(begriff)}&search_simple=1"
                    f"&action=process&json=1&page_size={int(hoechstens)}"
                    f"&fields={FELDER}")
    return _brauchbare(antwort.get("products") or [])
