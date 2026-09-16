"""Zwei Waechter gegen Listen, die auseinanderlaufen (v1.95.1).

Beide Tests gibt es, weil genau der Fehler, den sie pruefen, im Bestand
stand -- nicht als Vorsichtsmassnahme gegen etwas Gedachtes:

1. ``ALLOWED_NAV_TABS`` im Backend kannte weder ``/schach/`` noch
   ``/ernaehrung/``. Die Einstellungsseite schickt beim Speichern aber ALLE
   Module, und ``_href_list`` weist die ganze Liste ab, sobald ein Pfad
   unbekannt ist. Der Knopf "Leiste speichern" antwortete deshalb bei jedem
   Konto mit einem Fehler -- und weil derselbe Pruefer fuer Reihenfolge,
   Ausgeblendetes und Ruhendes gilt, betraf das alle drei Einstellungen.

2. ``backup.TABLES_ORDERED`` enthielt keine einzige Tabelle der Module
   Ernaehrung, Schach, Notizen und Marken. Ein Wiederherstellen haette sie
   lautlos verloren: fehlt eine Tabelle in der Liste, wird sie weder
   gesichert noch vermisst.

Beide Listen lassen sich nicht aus einer gemeinsamen Quelle erzeugen -- die
eine steht in JavaScript, die andere in Python, und die Tabellen stehen in
SQL. Ein Vergleich im Test ist der naechstbeste Weg.
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from routers import ui_router                      # noqa: E402
from services import backup                        # noqa: E402

WURZEL = pathlib.Path(__file__).resolve().parents[2]
NAV_SWITCHER = WURZEL / "frontend" / "js" / "nav-switcher.js"
MIGRATIONEN = WURZEL / "backend" / "migrations" / "sql"


def _module_pfade() -> set:
    """Die href-Werte aus der MODULES-Registry des Frontends."""
    quelle = NAV_SWITCHER.read_text(encoding="utf-8")
    block = re.search(r"const MODULES = \[(.*?)\n    \];", quelle, re.S)
    assert block, "MODULES-Registry in nav-switcher.js nicht gefunden"
    pfade = set(re.findall(r"href:\s*'([^']+)'", block.group(1)))
    assert len(pfade) >= 8, f"nur {len(pfade)} Module gefunden -- Regex kaputt?"
    return pfade


def test_jedes_modul_darf_in_der_navigation_stehen():
    fehlt = sorted(_module_pfade() - set(ui_router.ALLOWED_NAV_TABS))
    assert not fehlt, (
        "Diese Module stehen in nav-switcher.js, aber nicht in "
        "ALLOWED_NAV_TABS (ui_router.py). Solange das so ist, antwortet JEDES "
        "Speichern auf /einstellungen/ mit HTTP 400: " + ", ".join(fehlt))


def test_keine_karteileichen_in_der_erlaubnisliste():
    """Umgekehrt: ein Pfad, den es nicht mehr gibt, faellt auch auf.

    Nicht kritisch, aber eine Liste, die Pfade zu geloeschten Modulen fuehrt,
    ist eine Liste, der man beim naechsten Mal weniger glaubt. Ausgenommen ist
    ``VERALTETE_NAV_TABS``: diese Pfade stehen dort mit Absicht, weil sie noch
    in gespeicherten Einstellungen vorkommen koennen.
    """
    uebrig = sorted(set(ui_router.ALLOWED_NAV_TABS) - _module_pfade()
                    - set(ui_router.VERALTETE_NAV_TABS))
    assert not uebrig, (
        "ALLOWED_NAV_TABS kennt Pfade, die in MODULES fehlen: "
        + ", ".join(uebrig))


# --------------------------------------------------------------------------
# Backup
# --------------------------------------------------------------------------
# Was bewusst NICHT gesichert wird -- jede Zeile mit dem Grund, warum nicht.
# Ohne Begruendung gehoert hier nichts hinein: die Ausnahmeliste ist sonst
# der bequemste Weg, einen Datenverlust festzuschreiben.
NICHT_GESICHERT = {
    # Das Rohpaket jedes Health-Imports, als BYTEA. Es ist ein Protokoll,
    # kein Bestand -- die daraus gelesenen Werte stehen in health_*.
    "health_import_log":
        "Rohdaten-Protokoll, die Messwerte selbst stehen in health_*",
    # In Migration 032 wieder entfernt; die Tabelle gibt es nicht mehr.
    "health_shortcut_samples":
        "in Migration 032 gedroppt",
    # Einladungen sind Verwaltung, kein persoenlicher Bestand; ein
    # zurueckgespielter Einladungscode waere sogar unerwuenscht.
    "invite_tokens":
        "Verwaltung, kein Bestand -- und ein alter Code soll nicht wieder gelten",
    # Die Sicherungen selbst. Eine Sicherung der Sicherungen waere bei jedem
    # Lauf doppelt so gross wie die vorige.
    "backup_snapshots":
        "die Sicherungen selbst",
}


def _tabellen_mit_user_id() -> dict:
    """Jede per Migration angelegte Tabelle, die eine user_id traegt.

    Zwei Wege fuehren dahin: die Spalte steht im CREATE TABLE, oder sie kam
    spaeter per ALTER TABLE dazu (Migration 005 hat so den Mehrbenutzerbetrieb
    nachgeruestet). Nur den ersten zu pruefen, haelt die halbe Sparziel-Welt
    faelschlich fuer nutzerlos.
    """
    gefunden = {}
    for datei in sorted(MIGRATIONEN.glob("*.sql")):
        text = datei.read_text(encoding="utf-8")
        for treffer in re.finditer(
                r"CREATE TABLE (?:IF NOT EXISTS )?([a-z_]+)\s*\((.*?)\n\);",
                text, re.S):
            name, koerper = treffer.group(1), treffer.group(2)
            if re.search(r"\buser_id\b", koerper):
                gefunden.setdefault(name, datei.name)
        for treffer in re.finditer(
                r"ALTER TABLE\s+([a-z_]+)\s+ADD COLUMN[^;]*?\buser_id\b",
                text, re.S):
            gefunden.setdefault(treffer.group(1), datei.name)
    assert len(gefunden) > 20, "Migrationen nicht gelesen -- Regex kaputt?"
    return gefunden


def test_jede_nutzertabelle_wird_gesichert():
    tabellen = _tabellen_mit_user_id()
    fehlt = sorted(n for n in tabellen
                   if n not in backup.TABLES_ORDERED and n not in NICHT_GESICHERT)
    assert not fehlt, (
        "Diese Tabellen tragen eine user_id, stehen aber nicht in "
        "backup.TABLES_ORDERED. Ein Restore verliert sie lautlos: "
        + ", ".join(f"{n} ({tabellen[n]})" for n in fehlt))


def test_tabellen_ohne_user_id_haengen_an_einer_mit():
    """Eine Tabelle ohne user_id braucht einen Eintrag in PARENT_SCOPE.

    Sonst faellt die Abfrage in den "alles lesen"-Zweig -- und im Backup EINES
    Kontos landen die Zeilen ALLER Konten (gefunden in v1.65.0).
    """
    mit_user = set(_tabellen_mit_user_id())
    ohne = [t for t in backup.TABLES_ORDERED
            if t != "users" and t not in mit_user]
    fehlt = sorted(t for t in ohne if t not in backup.PARENT_SCOPE)
    assert not fehlt, (
        "Diese Tabellen haben keine user_id und keinen PARENT_SCOPE-Eintrag — "
        "ihr Backup enthielte fremde Zeilen: " + ", ".join(fehlt))
