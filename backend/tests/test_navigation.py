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


# --------------------------------------------------------------------------
# Gesamt-Export
# --------------------------------------------------------------------------
# Eine Sektion braucht ZWEI Eintraege: einen in EXPORT_SECTIONS und einen
# Zweig in _build_sections. Fehlt der zweite, steht die Sektion im Dialog zur
# Wahl und die Datei bleibt an dieser Stelle leer -- ein Fehler, den niemand
# bemerkt, bis er die Datei aufmacht.
def test_jede_export_sektion_wird_auch_gebaut():
    from services import full_export as fe
    quelle = (WURZEL / "backend" / "services" / "full_export.py").read_text(
        encoding="utf-8")
    bau = quelle[quelle.index("async def _build_sections"):]
    fehlt = [s["key"] for s in fe.EXPORT_SECTIONS
             if f'"{s["key"]}" in want' not in bau]
    assert not fehlt, (
        "Diese Sektionen stehen in EXPORT_SECTIONS, werden aber in "
        "_build_sections nie gebaut: " + ", ".join(fehlt))


def test_jede_export_sektion_gehoert_zu_einer_gruppe():
    from services import full_export as fe
    gruppen = {g["key"] for g in fe.EXPORT_GROUPS}
    fehlt = sorted({s["group"] for s in fe.EXPORT_SECTIONS} - gruppen)
    assert not fehlt, "Gruppen ohne Eintrag in EXPORT_GROUPS: " + ", ".join(fehlt)


# --------------------------------------------------------------------------
# Geteilte Frontend-Bausteine (v2.1.0)
# --------------------------------------------------------------------------
# Ein Modul, das ``VexModal`` benutzt, muss /js/modal.js auch laden. Diese
# Verknuepfung steht in zwei Dateien und bricht lautlos: das Skript wirft
# ``VexModal is not defined`` erst in dem Moment, in dem jemand den Dialog
# oeffnet -- nicht beim Laden der Seite. Bis dahin sieht alles richtig aus.
#
# Ein Waechter fuer alle Bausteine, weil jeder naechste dieselbe Falle
# mitbringt. ``VexIkon`` (v2.4.0) ist der schlimmste Fall davon: es wird beim
# ZEICHNEN aufgerufen, nicht erst beim Klicken -- fehlt das Skript, stirbt das
# Modul mitten im Aufbau der Seite und uebrig bleibt der Seitenhintergrund.
def test_wer_einen_geteilten_baustein_benutzt_laedt_ihn_auch():
    bausteine = {"VexModal": "/js/modal.js",
                 "VexRing": "/js/ring.js",
                 "VexBild": "/js/bild.js",
                 "VexIkon": "/js/ikon.js"}
    front = WURZEL / "frontend"
    seiten = [(h, h.read_text(encoding="utf-8")) for h in front.rglob("*.html")]
    fehler = []

    for js in sorted(front.rglob("*.js")):
        if js.parent.name == "js":          # die Bausteine selbst
            continue
        quelle = js.read_text(encoding="utf-8")
        gebraucht = sorted(n for n in bausteine if (n + ".") in quelle)
        if not gebraucht:
            continue
        pfad = "/" + js.relative_to(front).as_posix()
        for seite, html in seiten:
            if pfad not in html:
                continue
            for name in gebraucht:
                if bausteine[name] in html:
                    continue
                fehler.append(
                    "%s benutzt %s, aber %s bindet %s nicht ein"
                    % (pfad, name,
                       "/" + seite.relative_to(front).as_posix(),
                       bausteine[name]))

    assert not fehler, "\n".join(fehler)


def test_wer_auf_window_prueft_findet_den_baustein_auch_dort():
    """``window.VexPrefs ? ... : Standard`` ergab immer den Standard.

    Ein ``const`` auf oberster Ebene eines klassischen Skripts wird KEINE
    Eigenschaft von ``window``. ``VexPrefs`` war der einzige geteilte
    Baustein ohne ``window.X = X``, und die beiden Stellen, die defensiv auf
    sein Vorhandensein prueften, liefen deshalb IMMER in den Ersatzzweig:
    der Export-Dialog machte trotz gespeicherter Stufen mit "Einzeln" auf,
    und der Standard-Zeitraum aus den Einstellungen galt nie. Beide Werte
    waren am Konto gespeichert und wurden nur nie gelesen -- ein Fehler, den
    man der Oberflaeche nicht ansieht, weil sie nicht kaputt aussieht,
    sondern nur etwas anderes tut.

    Der Test dreht das um: wer irgendwo ``window.Xyz`` LIEST, muss ein
    ``window.Xyz =`` irgendwo im Frontend gegenueberstehen haben.
    """
    front = WURZEL / "frontend"
    quellen = {js: js.read_text(encoding="utf-8")
               for js in sorted(front.rglob("*.js"))}
    # Ein nachlaufendes ``(?!...)`` reicht hier NICHT: ``\w+`` gibt beim
    # Zuruecksetzen ein Zeichen her, und aus "VexPrefs =" wird dann der
    # gefundene Name "VexPref" mit passendem Lookahead. Deshalb wird der
    # Name ganz gelesen und erst danach geschaut, was dahinter steht.
    muster = re.compile(r"window\.(Vex\w+|Toast)")
    zuweisung = re.compile(r"\s*=[^=]")

    gesetzt = set()
    for text in quellen.values():
        for treffer in muster.finditer(text):
            if zuweisung.match(text[treffer.end():]):
                gesetzt.add(treffer.group(1))

    fehler = []
    for js, text in quellen.items():
        gelesen = {t.group(1) for t in muster.finditer(text)
                   if not zuweisung.match(text[t.end():])}
        for name in sorted(gelesen - gesetzt):
            fehler.append("%s prueft auf window.%s, aber nichts setzt es"
                          % ("/" + js.relative_to(front).as_posix(), name))
    assert not fehler, "\n".join(fehler)


def test_app_version_ist_der_oberste_changelog_eintrag():
    """``APP_VERSION`` und die oberste Zeile des Zeitstrahls sind dieselbe Zahl.

    Sie stehen in zwei Dateien und laufen deshalb auseinander. Am Tag, an dem
    dieser Test entstand, war das zweimal passiert: ein Rueckbau bekam eine
    neue Minor-Nummer (v2.11.0), obwohl die Konvention dafuer die Patch-Zahl
    des bestehenden Eintrags vorsieht -- gemerkt hat es niemand, weil die
    Fussleiste einfach die Zahl zeigt, die in version.js steht.
    """
    front = WURZEL / "frontend"
    version = (front / "js" / "version.js").read_text(encoding="utf-8")
    log = (front / "js" / "changelog.js").read_text(encoding="utf-8")

    gesetzt = re.search(r"APP_VERSION\s*=\s*'([^']+)'", version)
    assert gesetzt, "version.js setzt kein APP_VERSION"

    eintraege = re.findall(r"\{ v: '([^']+)'", log)
    assert eintraege, "changelog.js hat keine Eintraege"
    assert gesetzt.group(1) == eintraege[0], (
        "APP_VERSION ist %s, oberster Changelog-Eintrag ist %s"
        % (gesetzt.group(1), eintraege[0]))

    # Und der Zeitstrahl laeuft abwaerts -- eine Version, die zwischen zwei
    # aelteren steht, findet niemand wieder. Der aelteste Eintrag heisst
    # "v0.x" und fasst die Vorgeschichte zusammen; er hat absichtlich keine
    # Nummer und bleibt deshalb aussen vor.
    zaehlbar = [v for v in eintraege if re.fullmatch(r"v\d+\.\d+\.\d+", v)]

    def teile(v):
        return tuple(int(x) for x in v[1:].split("."))

    sortiert = sorted(zaehlbar, key=teile, reverse=True)
    assert zaehlbar == sortiert, (
        "Der Zeitstrahl ist nicht absteigend: %s"
        % [v for v, w in zip(zaehlbar, sortiert) if v != w][:4])
