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
import io
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


# ------------------------------------------------------- Die Datei als Datei
# v2.10.2: Der Inhalt des Archivs war nie das Problem -- der NAME war es. Der
# Browser reicht ``Content-Disposition`` aus einer Antwort von einer fremden
# Domain nur weiter, wenn der Server sie ausdruecklich freigibt. Ohne die
# Freigabe griff der Dialog zu seinem Rueckfallnamen, und der hiess fest
# ".csv" -- ein vollstaendiges Archiv mit einer Endung, die es nicht oeffnet.
import re
import zipfile as _zip

from routers import export_router as er                       # noqa: E402


class _Anfrage:
    """Nur das, was ``export_all`` von einem Request liest."""

    def __init__(self, query=None, headers=None):
        self.query_params = query or {}
        self.headers = headers or {}


def test_zip_antwort_ist_ein_zip_und_heisst_auch_so():
    antwort = asyncio.run(er.export_all(
        _Anfrage(), date_from=None, date_to=None,
        aggregate="none", sections=None, format="zip",
        db=LeereDB(), user=NUTZER))
    assert antwort.media_type == "application/zip"
    # Kein gzip darueber: ein Archiv ist bereits gepackt, und ein zweites
    # Mal verpackt kaeme es als .zip.gz an.
    assert "Content-Encoding" not in antwort.headers
    name = re.search(r'filename="([^"]+)"',
                     antwort.headers["Content-Disposition"]).group(1)
    assert name.endswith(".zip"), name
    # Und der Rumpf ist wirklich eines -- inklusive der LIESMICH.
    archiv = _zip.ZipFile(io.BytesIO(antwort.body))
    assert "LIESMICH.txt" in archiv.namelist()


def test_csv_antwort_bleibt_eine_csv():
    antwort = asyncio.run(er.export_all(
        _Anfrage(), date_from=None, date_to=None,
        aggregate="none", sections=None, format="csv", db=LeereDB(), user=NUTZER))
    assert antwort.media_type.startswith("text/csv")
    assert '.csv"' in antwort.headers["Content-Disposition"]


def test_der_browser_darf_den_dateinamen_lesen():
    """Sonst ist der Name des Servers fuer das Skript unsichtbar.

    Frontend und Backend liegen auf verschiedenen Domains. Ohne
    ``expose_headers`` liefert ``res.headers.get('content-disposition')``
    im Browser ``null``, egal was der Server sendet.
    """
    quelle = open(os.path.join(os.path.dirname(__file__), "..", "main.py"),
                  encoding="utf-8").read()
    kopf = quelle[quelle.index("CORSMiddleware,"):][:400]
    assert "expose_headers" in kopf
    assert "Content-Disposition" in kopf


def test_rueckfallname_im_dialog_kennt_beide_formen():
    """Der Dialog darf nicht fest .csv annehmen, wenn ZIP gewaehlt ist."""
    pfad = os.path.join(os.path.dirname(__file__), "..", "..",
                        "frontend", "js", "export-dialog.js")
    js = open(pfad, encoding="utf-8").read()
    stelle = js[js.index("let filename ="):][:200]
    assert "state.format === 'zip'" in stelle
    assert "'.zip'" in stelle
