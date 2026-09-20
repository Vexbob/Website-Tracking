"""Waechter fuer die FORM des Gesamtexports (v2.10.0).

Bis v2.9.0 hatte die Datei drei Eigenschaften, die sie schwer benutzbar
machten, und alle drei standen als Absicht im Kopf der Datei selbst:

1. Zwei Dezimaltrennzeichen. ``_num`` schrieb Punkt, ``_euro_de`` Komma --
   in derselben Datei, getrennt durch Semikolon. Fuer jedes Programm, das die
   Datei liest, war damit die Haelfte der Zahlen Text.
2. Leere Sektionen wurden trotzdem abgedruckt. In einem frisch benutzten
   Konto standen zwei Dutzend Ueberschriften ueber nichts.
3. Zwanzig Tabellen mit verschiedener Spaltenzahl lagen in EINER Datei. Kein
   Tabellenprogramm kann das oeffnen -- dafuer gibt es jetzt das Archiv.

Die Tests kommen ohne Datenbank aus: ein Doppel, das auf jede Abfrage nichts
liefert, reicht fuer die Form. Was IN den Zeilen steht, prueft
``test_export_aggregation.py``.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from services import full_export as fx


class LeereDB:
    """Antwortet auf jede Abfrage mit nichts -- wie ein frisches Konto."""

    async def fetch(self, *a, **k):
        return []

    async def fetchrow(self, *a, **k):
        return None

    async def fetchval(self, *a, **k):
        return 0


NUTZER = {"id": 1, "username": "etienne"}


def _bauen(**kw):
    return asyncio.run(fx.build_full_export_csv(LeereDB(), NUTZER, **kw))


# ---------------------------------------------------------------- Zahlen
def test_euro_und_zahl_nutzen_dasselbe_trennzeichen():
    """Sonst ist die Haelfte der Spalten fuer jede Auswertung Text."""
    assert fx._euro_de(1465.5) == "1465.50"
    assert fx._num(1465.5) == "1465.50"
    assert "," not in fx._euro_de(-12.30)
    # Und der Kopf behauptet nichts anderes mehr.
    text = _bauen()
    kopf = [z for z in text.split("\n") if z.startswith("# Konventionen")]
    assert kopf, "Die Datei sagt nicht mehr, wie ihre Zahlen aussehen"
    assert "Punkt-Dezimal" in kopf[0]
    assert "Komma-Dezimal" not in kopf[0]


def test_leeres_feld_bleibt_leer_und_wird_nicht_null():
    """Eine 0 waere eine Behauptung ueber etwas, das niemand weiss."""
    assert fx._num(None) == ""
    assert fx._euro_de(None) == ""


# ------------------------------------------------------------- Leere Bloecke
def test_leere_bloecke_stehen_im_kopf_statt_in_der_datei():
    text = _bauen()
    zeilen = text.split("\n")
    ueberschriften = [z for z in zeilen if z.startswith("# SEKTION:")]
    # Genau eine Sektion hat bei leerer Datenbank Inhalt: die
    # Gesundheits-Zusammenfassung, die ihre Nullen ausdruecklich benennt.
    assert len(ueberschriften) == 1, ueberschriften
    assert "Zusammenfassung" in ueberschriften[0]

    gemeldet = [z for z in zeilen if z.startswith("# GEWAEHLT, ABER LEER")]
    assert gemeldet, "Weggelassene Bloecke muessen genannt werden"
    # Namentlich, nicht als Sektionsschluessel: ein Block ist feiner als eine
    # Sektion (``sparziel_meta`` allein bringt sechs).
    assert "Sparziele" in gemeldet[0]
    assert "Blutzucker" in gemeldet[0]


def test_bloecke_werden_einzeln_gezaehlt_nicht_je_sektion():
    """``sparziel_meta`` ist EINE Sektion mit SECHS Bloecken.

    Die erste Fassung von ``_hat_daten`` hielt die zweite Ueberschrift fuer
    eine Datenzeile und erklaerte damit jede mehrteilige Sektion fuer
    gefuellt -- genau die Sektionen, die am haeufigsten leer sind.
    """
    zeilen = [
        "# SEKTION: Sparziele",
        "id;name",
        "",
        "# SEKTION: Achievements",
        "id;title",
        "",
    ]
    assert fx._hat_daten(zeilen) is False
    behalten, leer = fx._leere_bloecke_aussortieren(zeilen)
    assert behalten == []
    assert leer == ["Sparziele", "Achievements"]

    zeilen[4:5] = ["id;title", "7;Abnehmen"]
    behalten, leer = fx._leere_bloecke_aussortieren(zeilen)
    assert leer == ["Sparziele"]
    assert "7;Abnehmen" in behalten


# -------------------------------------------------------------- Das Archiv
def test_archiv_hat_eine_datei_je_block_und_eine_liesmich():
    dateien = asyncio.run(fx.build_export_archive(LeereDB(), NUTZER))
    assert "LIESMICH.txt" in dateien
    csvs = [n for n in dateien if n.endswith(".csv")]
    assert csvs == ["01-gesundheit-zusammenfassung.csv"], csvs
    # In der einzelnen Datei steht KEINE Kommentarzeile: jede davon waere
    # eine Zeile vor dem Spaltenkopf, an der ein Tabellenprogramm die
    # Spalten falsch zaehlt.
    inhalt = dateien[csvs[0]]
    assert not any(z.startswith("#") for z in inhalt.split("\n"))
    assert inhalt.split("\n")[0] == "Kennzahl;Wert"
    # Die LIESMICH traegt den Vorspann, sonst waere der Ordner eine
    # Sammlung ohne Herkunft.
    liesmich = dateien["LIESMICH.txt"]
    assert "Vexbob Gesamt-Export" in liesmich
    assert "01-gesundheit-zusammenfassung.csv" in liesmich


def test_dateiname_bleibt_sortierbar_und_ohne_umlaute():
    assert fx._dateiname("Gesundheit - Blutdruck", 6) == "06-gesundheit-blutdruck.csv"
    # Die Nummer steht vorn, damit die Dateien im Archiv in der Reihenfolge
    # der Bloecke liegen -- alphabetisch stuende Ausgaben vor Sparziel.
    assert fx._dateiname("Ernährung - Nährwerte", 2).startswith("02-")
    assert fx._dateiname("Ernährung - Nährwerte", 2) == "02-ernaehrung-naehrwerte.csv"
    # Ein Block ohne Ueberschrift bekommt trotzdem einen Namen. Der Aufrufer
    # haengt zusaetzlich die Nummer an, damit zwei namenlose sich nicht
    # gegenseitig ueberschreiben.
    assert fx._dateiname("", 1) == "01-sektion.csv"
    assert fx._dateiname("sektion-4", 4) == "04-sektion-4.csv"


# ------------------------------------------------------- Auswertbare Auswahl
def test_rohdaten_sind_als_solche_gekennzeichnet():
    """Der Knopf „Zum Auswerten“ liest dieses Kennzeichen aus dem Register.

    Stuende die Liste im Frontend, waere eine neue Rohdaten-Sektion zwei
    Aenderungen an zwei Orten -- und die zweite vergisst man.
    """
    roh = {s["key"] for s in fx.EXPORT_SECTIONS if s.get("bulk")}
    assert roh == {"chess_pgn", "expense_imports", "music_imports"}
    assert set(fx.AUSWERTBARE_SECTION_KEYS) == set(fx.ALL_SECTION_KEYS) - roh
    # Jede Sektion muss entscheidbar sein: ein fehlendes Kennzeichen heisst
    # "gehoert in die Auswertung", und das ist die richtige Voreinstellung.
    assert len(fx.AUSWERTBARE_SECTION_KEYS) == len(fx.ALL_SECTION_KEYS) - 3
