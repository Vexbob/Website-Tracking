"""CS2 — die beiden Export-Sektionen.

Sie stehen hier und nicht in ``full_export.py``, obwohl die uebrigen Module
ihre Bauer dort inline halten. Der Grund ist der Umzug: so ist das Modul eine
Datei mehr im eigenen Ordner statt hundertzwanzig Zeilen mitten in einer
fremden, und ``full_export.py`` bekommt zwei Importzeilen und sechs Zeilen im
Verteiler. Wer das spaeter angleichen will, verschiebt den Inhalt -- die
Funktionen halten denselben Vertrag wie ``_sec_chess_*``: sie geben
``list[str]`` zurueck, erste Zeile ``# SEKTION: …``, dann die Kopfzeile, dann
die Datenzeilen, am Ende eine leere.

Zwei Sektionen, weil es zwei verschiedene Dinge sind:

* **Bestand** ist ein Stand von jetzt. Er traegt deshalb KEINEN Zeitraum:
  "was lag im Maerz im Lager" beantwortet dieses Modul nicht, und eine
  Sektion, die sich filtern laesst, ohne dass der Filter etwas bedeutet,
  liefert stillschweigend die immer gleiche Liste.
* **Staende** sind die Historie und tragen ihn.

Beide sind ``aggregatable: False``. Ein Monatsmittel ueber Portfoliowerte
waere weder der Stand am Monatsende noch der Durchschnittsbesitz, sondern
eine dritte Zahl, die niemand bestellt hat.
"""
from __future__ import annotations

from helpers import _export_csv_field as _f
from services import cs2_rechnung as rechnung


def _euro(v) -> str:
    """Betrag mit PUNKT als Dezimalzeichen -- wie jede andere Zahl der Datei.

    Dieselbe Regel wie ``_euro_de`` in ``full_export.py``, nur ohne dessen
    Namen: eine Datei, ein Dezimalzeichen. Komma neben Semikolon macht aus der
    Haelfte der Zahlen Text fuer jedes Programm, das die Datei liest.
    """
    if v is None:
        return ""
    return f"{float(v):.2f}"


def _ganz(v) -> str:
    return "" if v is None else str(int(v))


async def _sec_cs2_positions(db, user_id: int) -> list[str]:
    """Der Bestand, eine Zeile je Position.

    Brutto und Netto stehen mit drin, obwohl sie in der Datenbank nicht
    existieren: eine Exportdatei wird ausgewertet und nicht nachgerechnet.
    Der Preisstand steht daneben -- ohne ihn sieht ein acht Monate alter Preis
    aus wie ein heutiger, und genau das ist bei Handpflege die Angabe, auf die
    es ankommt.
    """
    rows = await db.fetch(
        "SELECT c.name AS kategorie, i.name AS gegenstand, p.wear, p.stattrak, "
        "       p.playskin, s.name AS lager, p.quantity, p.price_eur, p.priced_at "
        "  FROM cs2_positions p "
        "  JOIN cs2_items i      ON i.id = p.item_id "
        "  JOIN cs2_categories c ON c.id = i.category_id "
        "  JOIN cs2_storages s   ON s.id = p.storage_id "
        " WHERE p.user_id=$1 "
        " ORDER BY (p.quantity * p.price_eur) DESC NULLS LAST, i.name", user_id)
    out = ["# SEKTION: CS2 - Bestand",
           "Kategorie;Gegenstand;Abnutzung;StatTrak;Selbst gespielt;Lager;"
           "Stueckzahl;Preis je Stueck;Brutto;Nach Gebuehr;Preisstand"]
    for r in rows:
        # Dieselbe Rechnung wie ueberall sonst. Die Gebuehr hier noch einmal
        # hinzuschreiben waere die zweite Stelle, an der sie steht -- und die
        # erste, die beim naechsten Mal vergessen wird.
        brutto = rechnung.brutto(r["quantity"], r["price_eur"])
        netto = rechnung.netto(brutto)
        out.append(
            f'{_f(r["kategorie"] or "")};{_f(r["gegenstand"] or "")};'
            f'{_f(r["wear"] or "")};'
            f'{_f("ja" if r["stattrak"] else "nein")};'
            f'{_f("ja" if r["playskin"] else "nein")};'
            f'{_f(r["lager"] or "")};{_ganz(r["quantity"])};'
            f'{_euro(r["price_eur"])};{_euro(brutto)};{_euro(netto)};'
            f'{"" if r["priced_at"] is None else r["priced_at"].isoformat()}')
    out.append("")
    return out


async def _sec_cs2_snapshots(db, user_id: int, date_from, date_to) -> list[str]:
    """Die festgehaltenen Staende, ein Tag je Zeile.

    ``Ueberfaellige Preise`` steht mit in der Zeile, weil ein Stand aus acht
    Monate alten Preisen sonst aussieht wie ein frischer. Die Zahl sagt, wie
    weit man dem Wert an diesem Tag trauen konnte.
    """
    werte = [user_id]
    bed = ""
    if date_from:
        werte.append(date_from)
        bed += f" AND taken_on >= ${len(werte)}"
    if date_to:
        werte.append(date_to)
        bed += f" AND taken_on <= ${len(werte)}"
    rows = await db.fetch(
        "SELECT taken_on, total_gross, total_net, playskin_gross, playskin_net, "
        "       rows_valid, rows_incomplete, stale_rows, note "
        "  FROM cs2_snapshots "
        f" WHERE user_id=$1{bed} ORDER BY taken_on", *werte)
    out = ["# SEKTION: CS2 - Festgehaltene Staende",
           "Datum;Brutto;Nach Gebuehr;Davon selbst gespielt (brutto);"
           "Davon selbst gespielt (netto);Positionen;Unvollstaendig;"
           "Ueberfaellige Preise;Anmerkung"]
    for r in rows:
        out.append(
            f'{r["taken_on"].isoformat()};{_euro(r["total_gross"])};'
            f'{_euro(r["total_net"])};{_euro(r["playskin_gross"])};'
            f'{_euro(r["playskin_net"])};{_ganz(r["rows_valid"])};'
            f'{_ganz(r["rows_incomplete"])};{_ganz(r["stale_rows"])};'
            f'{_f(r["note"] or "")}')
    out.append("")
    return out
