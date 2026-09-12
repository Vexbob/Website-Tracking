#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aus dem grossen Open-Food-Facts-Abzug einen kleinen, eigenen Katalog machen.

Open Food Facts veroeffentlicht taeglich seinen gesamten Bestand als eine
Datei: rund 1,2 GB gepackt, knapp 10 GB als Text, gut vier Millionen
Produkte, 211 Spalten. Davon ist fuer dieses Modul fast nichts brauchbar --
Fotos, Zusatzstoff-Listen, Verpackungscodes, Produkte aus aller Welt, und
sehr viele Zeilen ganz ohne Naehrwerte.

Dieses Skript liest den Abzug **stroemend** (nie mehr als eine Zeile im
Speicher, die 10 GB werden nirgends ausgepackt) und schreibt eine kleine
Datei mit genau den Spalten, die der Katalog braucht -- und nur den
Produkten, die hier auch im Laden stehen.

    # 1. Filtern (dauert ein paar Minuten, laeuft auf dem eigenen Rechner)
    python off_katalog.py en.openfoodfacts.org.products.csv.gz -z katalog.csv.gz

    # 2. Nur nachsehen, was uebrig bliebe, ohne etwas zu schreiben
    python off_katalog.py en.openfoodfacts.org.products.csv.gz --nur-zaehlen

    # 3. Einspielen. Fragt nach der Verbindungsadresse, wenn weder --db
    #    noch DATABASE_URL gesetzt ist.
    python off_katalog.py katalog.csv.gz --einspielen

Warum ueberhaupt ein eigener Katalog? Die Suche laeuft heute gegen
search.openfoodfacts.org -- ein ehrenamtlich betriebener Dienst, der unter
Last mit 503 antwortet (genau das war der Fehler aus v1.86.0). Ein eigener
Katalog ist schnell, immer da und hoeflich. Der Preis: er altert. Deshalb
steht an jeder Zeile, wann Open Food Facts sie zuletzt geaendert hat, und
der Abzug wird gelegentlich neu eingespielt -- nicht taeglich, das waere
1,2 GB fuer ein paar hundert geaenderte Produkte.
"""
import argparse
import csv
import gzip
import os
import sys
import time

# Die Windows-Konsole steht auf cp1252. Ein Pfeil oder ein Auslassungszeichen
# in einer Meldung beendet das Skript dann mit einem UnicodeEncodeError --
# ausgerechnet die Ausgabe bringt es um. Also einmal umstellen und notfalls
# ersetzen lassen; eine Meldung mit einem Fragezeichen darin ist immer noch
# besser als keine.
for _strom in (sys.stdout, sys.stderr):
    try:
        _strom.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# Die Spalten des Abzugs, die uebernommen werden. Links der Name in der
# Quelle, rechts der in der eigenen Tabelle.
FELDER = {
    "code": "code",
    "product_name": "name",
    "brands": "brand",
    "energy-kcal_100g": "kcal",
    "proteins_100g": "protein_g",
    "carbohydrates_100g": "carbs_g",
    "sugars_100g": "sugar_g",
    "fat_100g": "fat_g",
    "saturated-fat_100g": "sat_fat_g",
    "fiber_100g": "fiber_g",
    "salt_100g": "salt_g",
    "serving_quantity": "portion_g",
}
# Reihenfolge der Ausgabe -- dieselbe wie die Spalten der Tabelle.
AUSGABE = ("code", "name", "brand", "base_unit", "kcal", "protein_g",
           "carbs_g", "sugar_g", "fat_g", "sat_fat_g", "fiber_g", "salt_g",
           "portion_g", "updated_at")

# Wo es das Produkt gibt. Open Food Facts fuehrt das als Marken-Tag
# ("en:germany"); die Liste ist eine Voreinstellung, kein Gesetz.
LAENDER_STANDARD = ("en:germany", "en:austria", "en:switzerland")

# Obergrenzen, ab denen eine Angabe nicht mehr stimmen KANN. In einem offen
# gepflegten Bestand steht regelmaessig der Kilojoule-Wert im Kalorienfeld
# oder ein Komma zu weit rechts. Solche Zeilen fliegen raus, statt spaeter
# eine Tagessumme zu verdreifachen: reines Fett hat 900 kcal je 100 g, mehr
# gibt es nicht.
GRENZE = {"kcal": 900.0, "protein_g": 100.0, "carbs_g": 100.0,
          "sugar_g": 100.0, "fat_g": 100.0, "sat_fat_g": 100.0,
          "fiber_g": 100.0, "salt_g": 100.0, "portion_g": 5000.0}

NAME_MAX = 160


def _oeffnen(pfad: str, modus: str = "rt"):
    """Oeffnet gepackt oder ungepackt — je nachdem, wie die Datei heisst.

    Open Food Facts bietet den Abzug gepackt an; ausgepackt liegt er als
    zwoelf Gigabyte Text da. Gelesen wird so oder so zeilenweise, gepackt
    ist nur die sparsamere Variante.
    """
    if "b" in modus:
        # Binaer, wo der Inhalt unveraendert weitergereicht wird (COPY):
        # asyncpg schiebt die gelesenen Bloecke roh an den Server, und im
        # Textmodus kaemen dort Zeichenketten statt Bytes an.
        return (gzip.open(pfad, modus) if pfad.lower().endswith(".gz")
                else open(pfad, modus))
    if pfad.lower().endswith(".gz"):
        return gzip.open(pfad, modus, encoding="utf-8",
                         errors="replace" if "r" in modus else None, newline="")
    return open(pfad, modus, encoding="utf-8",
                errors="replace" if "r" in modus else None, newline="")


def _zahl(roh, grenze):
    """Eine Zahl aus der Zelle ziehen — oder nichts, wenn sie nicht stimmen kann."""
    roh = (roh or "").strip().replace(",", ".")
    if not roh:
        return None
    try:
        wert = float(roh)
    except ValueError:
        return None
    if wert < 0 or wert > grenze:
        return None
    return round(wert, 2)


def _fluessig(zeile: dict) -> bool:
    """Beziehen sich die 100er-Angaben auf Milliliter?

    Open Food Facts sagt das nicht direkt; es steht in der Mengenangabe der
    Packung ("1 l", "500 ml"). Falsch geraten hiesse: Saft wird in Gramm
    eingetragen -- was am Naehrwert nichts aendert, aber an der Beschriftung.
    """
    text = ((zeile.get("quantity") or "") + " " +
            (zeile.get("serving_size") or "")).lower()
    return any(e in text for e in (" ml", "ml)", "cl", " l ", " liter", "1l", "0,5l"))


def zeile_pruefen(z: dict, laender) -> dict:
    """Aus einer Zeile des Abzugs eine Katalogzeile — oder None."""
    code = "".join(c for c in (z.get("code") or "") if c.isdigit())
    if not (8 <= len(code) <= 14):
        return None
    name = " ".join((z.get("product_name") or "").split())
    if not name or len(name) < 2:
        return None

    # Nur, was hier auch im Regal steht. Ohne diesen Schnitt waeren es vier
    # Millionen Zeilen, von denen der Alltag hier keine hundert braucht.
    tags = (z.get("countries_tags") or "").lower()
    if laender and not any(l in tags for l in laender):
        return None

    kcal = _zahl(z.get("energy-kcal_100g"), GRENZE["kcal"])
    if kcal is None:
        # Ein Eintrag ohne Kalorien traegt zu einer Naehrwerttabelle nichts
        # bei -- er waere nur ein Name, den man anschliessend selbst
        # ausfuellen muss. Dafuer gibt es "Von Hand anlegen".
        return None

    raus = {"code": code, "name": name[:NAME_MAX],
            "brand": " ".join((z.get("brands") or "").split()).split(",")[0][:80],
            "base_unit": "ml" if _fluessig(z) else "g",
            "kcal": kcal,
            "updated_at": (z.get("last_modified_t") or "").strip() or None}
    for quelle, ziel in FELDER.items():
        if ziel in ("code", "name", "brand", "kcal"):
            continue
        raus[ziel] = _zahl(z.get(quelle), GRENZE[ziel])
    return raus


def filtern(quelle: str, ziel: str, laender, grenze=None) -> dict:
    """Liest den Abzug und schreibt den Katalog. Gibt die Zaehlerstaende zurueck."""
    stand = {"gelesen": 0, "kein_code": 0, "kein_name": 0, "fremd": 0,
             "keine_kcal": 0, "doppelt": 0, "behalten": 0, "juengste": 0}
    gesehen = set()
    begonnen = time.time()
    schreiber = None
    raus = None
    if ziel:
        raus = _oeffnen(ziel, "wt")
        schreiber = csv.writer(raus, delimiter="\t", lineterminator="\n",
                               quoting=csv.QUOTE_MINIMAL)

    with _oeffnen(quelle) as f:
        leser = csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        for z in leser:
            stand["gelesen"] += 1
            if grenze and stand["gelesen"] > grenze:
                break
            if stand["gelesen"] % 250000 == 0:
                print("  … %8d gelesen, %7d behalten (%.0f s)"
                      % (stand["gelesen"], stand["behalten"],
                         time.time() - begonnen), flush=True)
            zeile = zeile_pruefen(z, laender)
            if zeile is None:
                # Grob mitzaehlen, woran es lag -- sonst weiss niemand, ob der
                # Filter zu scharf steht.
                code = "".join(c for c in (z.get("code") or "") if c.isdigit())
                if not (8 <= len(code) <= 14):
                    stand["kein_code"] += 1
                elif not (z.get("product_name") or "").strip():
                    stand["kein_name"] += 1
                elif laender and not any(
                        l in (z.get("countries_tags") or "").lower() for l in laender):
                    stand["fremd"] += 1
                else:
                    stand["keine_kcal"] += 1
                continue
            if zeile["code"] in gesehen:
                # Derselbe Strichcode steht im Abzug mehrfach. Der erste
                # Treffer gewinnt; die Datei ist nach Code sortiert, die
                # Dubletten sind Schreibfehler.
                stand["doppelt"] += 1
                continue
            gesehen.add(zeile["code"])
            stand["behalten"] += 1
            # Woher der Abzug stammt, steht nirgends in der Datei -- die
            # juengste Aenderung darin ist die beste Auskunft darueber.
            try:
                stand["juengste"] = max(stand["juengste"],
                                        int(zeile["updated_at"] or 0))
            except (TypeError, ValueError):
                pass
            if schreiber:
                schreiber.writerow(["" if zeile[s] is None else zeile[s]
                                    for s in AUSGABE])
    if raus:
        raus.close()
    stand["sekunden"] = round(time.time() - begonnen)
    return stand


def _ziel(url: str):
    """Wirt und Port aus der Adresse — ohne das Passwort.

    Beides kann fehlen: Railway setzt in DATABASE_PUBLIC_URL Platzhalter
    ein, und solange der TCP-Proxy aus ist, bleiben die leer. Dann steht
    dort woertlich "@:/railway" -- mit Passwort, aber ohne Ziel.
    """
    import urllib.parse
    try:
        teile = urllib.parse.urlsplit(url)
        return (teile.hostname or ""), teile.port
    except ValueError:
        return "", None


def _adresse(vorgabe=None) -> str:
    """Die Verbindungsadresse — aus dem Aufruf, der Umgebung oder der Frage.

    Gefragt wird, weil eine Umgebungsvariable zu setzen der Teil ist, an dem
    es haengen bleibt: drei Zeilen, von denen zwei nichts mit der Sache zu
    tun haben. Einfuegen und Enter ist derselbe Vorgang ohne das Drumherum.
    """
    url = (vorgabe or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        print("Verbindungsadresse der Datenbank einfügen und Enter drücken.")
        print("(Bei Railway: Postgres-Dienst → Variables → DATABASE_PUBLIC_URL)")
        try:
            url = input("> ").strip()
        except EOFError:
            url = ""
    # Die Adresse steht oft in Anfuehrungszeichen in der Zwischenablage.
    url = url.strip('"').strip("'")
    if not url.startswith(("postgres://", "postgresql://")):
        sys.exit("Das sieht nicht nach einer Postgres-Adresse aus — sie fängt "
                 "mit postgresql:// an.")
    wirt, port = _ziel(url)
    if not wirt or not port:
        sys.exit(
            "In der Adresse fehlt %s.\n"
            "Das passiert bei Railway genau dann, wenn der öffentliche "
            "Zugang zur Datenbank noch aus ist: DATABASE_PUBLIC_URL setzt "
            "dort Platzhalter ein, die leer bleiben.\n\n"
            "Einschalten: Postgres-Dienst → Settings → Networking → TCP "
            "Proxy (Port 5432 angeben). Danach steht unter Variables ein "
            "Wirt auf .proxy.rlwy.net mit fünfstelligem Port drin."
            % ("der Rechnername und der Port" if not wirt and not port
               else "der Rechnername" if not wirt else "der Port"))
    if wirt.endswith(".railway.internal"):
        sys.exit(
            "Das ist die INTERNE Adresse (%s) — die gilt nur zwischen den "
            "Diensten innerhalb von Railway.\n"
            "Gebraucht wird DATABASE_PUBLIC_URL: Postgres-Dienst → Variables "
            "→ DATABASE_PUBLIC_URL. Der Wirt endet dort auf .proxy.rlwy.net "
            "und der Port ist fünfstellig." % wirt)
    if "proxy.rlwy.net" in wirt and port == 5432:
        # Der Proxy hoert auf einem zufaelligen hohen Port; 5432 ist der,
        # den Postgres INNEN benutzt. Die beiden zu mischen ist der
        # haeufigste Griff daneben -- und er sieht aus wie ein Serverfehler.
        sys.exit(
            "Wirt und Port passen nicht zusammen: %s ist der öffentliche "
            "Proxy, aber 5432 ist der Port von INNEN.\n"
            "In DATABASE_PUBLIC_URL steht hinter dem Doppelpunkt ein "
            "fünfstelliger Port (z. B. :23456) — den braucht es." % wirt)
    return url


async def einspielen(datei: str, url=None) -> None:
    """Spielt den gefilterten Katalog in die Datenbank — in einem Rutsch.

    Die Tabelle wird dabei ersetzt, nicht ergaenzt: ein neuer Abzug ist ein
    neuer Stand, und zwei Staende nebeneinander waeren nicht zu trennen.
    Bis zum Ende laeuft alles in einer Transaktion -- schlaegt es fehl, steht
    der alte Katalog unveraendert da.
    """
    import asyncio

    import asyncpg

    print("Verbinde …", flush=True)
    try:
        conn = await asyncpg.connect(url, timeout=20)
    except asyncpg.InvalidPasswordError:
        sys.exit("Benutzername oder Passwort stimmt nicht. Die Adresse aus "
                 "Railway enthält beides — am besten noch einmal ganz "
                 "kopieren.")
    except (OSError, asyncio.TimeoutError) as e:
        wirt, port = _ziel(url)
        import asyncio as _a
        grund = ("Dort nimmt niemand Verbindungen an"
                 if isinstance(e, ConnectionRefusedError) else
                 "Diesen Rechner gibt es nicht"
                 if e.__class__.__name__ == "gaierror" else
                 "Keine Antwort in 20 Sekunden"
                 if isinstance(e, _a.TimeoutError) else
                 "Die Verbindung kam nicht zustande")
        sys.exit(
            "Versucht wurde: %s Port %s\n"
            "%s (%s).\n\n"
            "Bei Railway: Postgres-Dienst → Variables → DATABASE_PUBLIC_URL "
            "kopieren. Dort steht ein Wirt auf .proxy.rlwy.net mit einem "
            "fünfstelligen Port. Steht diese Variable nicht da, ist der "
            "öffentliche Zugang für den Dienst noch nicht eingeschaltet: "
            "Settings → Networking → TCP Proxy."
            % (wirt, port, grund, e.__class__.__name__))
    except Exception as e:
        sys.exit("Die Verbindung kam nicht zustande: %s" % e)
    try:
        # Ohne die Tabelle waere die Fehlermeldung von Postgres ("relation
        # does not exist") richtig, aber nicht hilfreich -- sie sagt nicht,
        # dass zuerst das Backend mit der Migration laufen muss.
        if not await conn.fetchval(
                "SELECT to_regclass('public.food_catalog') IS NOT NULL"):
            sys.exit("Die Tabelle food_catalog gibt es noch nicht — erst muss "
                     "das Backend einmal mit Migration 043 gestartet sein.")
        print("Lade %s …" % os.path.basename(datei), flush=True)
        async with conn.transaction():
            await conn.execute("TRUNCATE food_catalog")
            with _oeffnen(datei, "rb") as f:
                ergebnis = await conn.copy_to_table(
                    "food_catalog", source=f, columns=list(AUSGABE),
                    format="csv", delimiter="\t", null="")
            print(ergebnis)
        anzahl = await conn.fetchval("SELECT count(*) FROM food_catalog")
        print("Im Katalog stehen jetzt %d Produkte." % anzahl)
    finally:
        await conn.close()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("datei", help="der Abzug (.csv.gz) oder der fertige Katalog")
    p.add_argument("-z", "--ziel", help="wohin der gefilterte Katalog geschrieben wird")
    p.add_argument("--nur-zaehlen", action="store_true",
                   help="nichts schreiben, nur sagen, was übrig bliebe")
    p.add_argument("--laender", default=",".join(LAENDER_STANDARD),
                   help="Länder-Tags, kommagetrennt; leer = alle behalten")
    p.add_argument("--grenze", type=int, default=0,
                   help="nur die ersten N Zeilen lesen (zum Ausprobieren)")
    p.add_argument("--einspielen", action="store_true",
                   help="einen fertigen Katalog in die Datenbank laden")
    p.add_argument("--db", help="Verbindungsadresse der Datenbank; ohne diese "
                                "wird DATABASE_URL genommen oder danach gefragt")
    a = p.parse_args()

    if a.einspielen:
        import asyncio
        adresse = _adresse(a.db)
        asyncio.run(einspielen(a.datei, adresse))
        return

    if not a.ziel and not a.nur_zaehlen:
        sys.exit("Entweder --ziel angeben oder --nur-zaehlen.")
    laender = tuple(t.strip().lower() for t in a.laender.split(",") if t.strip())
    stand = filtern(a.datei, None if a.nur_zaehlen else a.ziel, laender,
                    a.grenze or None)

    print("\nGelesen: %(gelesen)d Zeilen in %(sekunden)d s" % stand)
    print("  ohne brauchbaren Strichcode: %(kein_code)d" % stand)
    print("  ohne Namen:                  %(kein_name)d" % stand)
    print("  nicht in %-20s%d" % (",".join(laender) + ":", stand["fremd"]))
    print("  ohne Kalorienangabe:         %(keine_kcal)d" % stand)
    print("  doppelter Strichcode:        %(doppelt)d" % stand)
    print("  BEHALTEN:                    %(behalten)d" % stand)
    if stand["juengste"]:
        print("  juengste Aenderung darin:    %s"
              % time.strftime("%d.%m.%Y", time.localtime(stand["juengste"])))
    if a.ziel and not a.nur_zaehlen:
        mb = os.path.getsize(a.ziel) / 1024 / 1024
        print("\n%s: %.1f MB gepackt" % (a.ziel, mb))


if __name__ == "__main__":
    csv.field_size_limit(10 * 1024 * 1024)
    main()
