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

    # 3. Einspielen (dort, wo die Datenbank erreichbar ist -- z. B. im
    #    Backend-Container, der DATABASE_URL ohnehin kennt)
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
             "keine_kcal": 0, "doppelt": 0, "behalten": 0}
    gesehen = set()
    begonnen = time.time()
    schreiber = None
    raus = None
    if ziel:
        raus = gzip.open(ziel, "wt", encoding="utf-8", newline="")
        schreiber = csv.writer(raus, delimiter="\t", lineterminator="\n",
                               quoting=csv.QUOTE_MINIMAL)

    with gzip.open(quelle, "rt", encoding="utf-8", errors="replace",
                   newline="") as f:
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
            if schreiber:
                schreiber.writerow(["" if zeile[s] is None else zeile[s]
                                    for s in AUSGABE])
    if raus:
        raus.close()
    stand["sekunden"] = round(time.time() - begonnen)
    return stand


async def einspielen(datei: str) -> None:
    """Spielt den gefilterten Katalog in die Datenbank — in einem Rutsch.

    Die Tabelle wird dabei ersetzt, nicht ergaenzt: ein neuer Abzug ist ein
    neuer Stand, und zwei Staende nebeneinander waeren nicht zu trennen.
    Bis zum Ende laeuft alles in einer Transaktion -- schlaegt es fehl, steht
    der alte Katalog unveraendert da.
    """
    import asyncpg

    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL ist nicht gesetzt — ohne die weiß ich nicht, wohin.")
    conn = await asyncpg.connect(url)
    try:
        async with conn.transaction():
            await conn.execute("TRUNCATE food_catalog")
            with gzip.open(datei, "rt", encoding="utf-8", newline="") as f:
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
    a = p.parse_args()

    if a.einspielen:
        import asyncio
        asyncio.run(einspielen(a.datei))
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
    if a.ziel and not a.nur_zaehlen:
        mb = os.path.getsize(a.ziel) / 1024 / 1024
        print("\n%s: %.1f MB gepackt" % (a.ziel, mb))


if __name__ == "__main__":
    csv.field_size_limit(10 * 1024 * 1024)
    main()
