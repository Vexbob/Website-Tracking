-- CS2-Modul — Bestand an Spielgegenstaenden und sein Zeitwert
--
-- Was dieses Modul fuehrt, ist ein BESTAND, kein Handelsbuch: es gibt keinen
-- Kaufpreis, keine Kaeufe und keine Verkaeufe. Eine Zeile sagt, was da ist und
-- was es heute wert waere -- nicht, was es gekostet hat.
--
-- Das ist eine Entscheidung und keine Luecke, und der Grund steht im
-- Tabellenschnitt selbst: eine Position ist eine MENGE, die ueber Jahre
-- gewachsen ist -- 1.223 Kisten, in unterschiedlichen Stueckzahlen, zu
-- verschiedenen Zeiten, bei verschiedenen Anbietern gekauft. Es gibt fuer so
-- eine Zeile keinen Einstandspreis, den man nachtragen koennte; es gaebe nur
-- eine erfundene Zahl, die danach wie eine gemessene aussieht. Wer Gewinn
-- rechnen will, braucht ein anderes Modell (eine Zeile je Kauf), nicht eine
-- Spalte mehr an diesem.
--
-- Preise kommen VON HAND. Es gibt keine Marktschnittstelle, und deshalb ist
-- nicht der Preis die heikle Angabe, sondern sein ALTER: ``priced_at`` sagt,
-- wann die Zahl zuletzt bestaetigt wurde, und die Oberflaeche fuehrt die
-- aeltesten zuerst vor. Ein Preis von gestern und einer von vor acht Monaten
-- sehen sonst gleich aus, und eine Gesamtsumme aus beidem behauptet eine
-- Genauigkeit, die sie nicht hat.
--
-- Drei Entscheidungen zum Schnitt der Tabellen:
--
-- 1. **Was eine Kategorie zulaesst, steht an der Kategorie.** Die
--    Vorgaengerfassung hatte "Wear und StatTrak nur bei Skin, Playskin bei
--    Skin und Agent" als zwei Funktionen im Quelltext. Damit war jede neue
--    Kategorie ein Codeeingriff. Hier sind es drei Spalten.
--
-- 2. **Ein Item ist eine eigene Zeile, keine Zeichenkette.** Bisher war der
--    Name der Schluessel und stand in jeder Position noch einmal; eine
--    Umbenennung musste durch den ganzen Bestand laufen. Jetzt zeigt die
--    Position auf ``cs2_items``, und Umbenennen ist ein UPDATE an einer Stelle.
--
-- 3. **Dasselbe Item in zwei Lagern sind zwei Positionen.** Der eindeutige
--    Index ``idx_cs2_positions_signatur`` traegt genau die Signatur, mit der
--    die Vorgaengerfassung Zeilen zusammenfuehrte (Kategorie, Name, Wear,
--    StatTrak, Playskin, Lager) -- nur dass die Datenbank sie jetzt
--    durchsetzt, statt einer Funktion beim Einfuegen. Warum ein Index und
--    kein UNIQUE an der Tabelle, steht unten bei ``cs2_positions``.
--
-- Brutto und Netto stehen NICHT in der Tabelle. Sie sind Menge x Preis und
-- davon 15 % Gebuehr -- beides jederzeit ausrechenbar, und als gespeicherte
-- Spalte waeren sie die dritte Stelle, die dieselbe Zahl behauptet.

-- ---------- Kategorien: was fuer eine Art Gegenstand ----------
CREATE TABLE IF NOT EXISTS cs2_categories (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    -- Was diese Art zulaesst. Frueher drei Bedingungen im Quelltext.
    supports_wear       BOOLEAN NOT NULL DEFAULT FALSE,
    supports_stattrak   BOOLEAN NOT NULL DEFAULT FALSE,
    supports_playskin   BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

-- ---------- Lager: wo der Gegenstand liegt ----------
CREATE TABLE IF NOT EXISTS cs2_storages (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    -- Das Auffanglager. Wird ein Lager geloescht, ziehen seine Positionen
    -- hierher -- deshalb darf es selbst nicht geloescht werden.
    is_default  BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, name)
);

-- Nur ein Auffanglager je Nutzer.
CREATE UNIQUE INDEX IF NOT EXISTS idx_cs2_storages_default
    ON cs2_storages(user_id) WHERE is_default;

-- ---------- Items: der Gegenstand selbst, einmal ----------
CREATE TABLE IF NOT EXISTS cs2_items (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES cs2_categories(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, category_id, name)
);

CREATE INDEX IF NOT EXISTS idx_cs2_items_suche
    ON cs2_items(user_id, category_id, name);

-- ---------- Positionen: der eigentliche Bestand ----------
CREATE TABLE IF NOT EXISTS cs2_positions (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_id     INTEGER NOT NULL REFERENCES cs2_items(id) ON DELETE CASCADE,
    storage_id  INTEGER NOT NULL REFERENCES cs2_storages(id) ON DELETE CASCADE,
    -- Abnutzung. Leer ist erlaubt und heisst "hat keine", nicht "unbekannt" --
    -- welche Kategorien eine haben, steht an der Kategorie.
    wear        TEXT CHECK (wear IS NULL OR wear IN ('FN', 'MW', 'FT', 'WW', 'BS')),
    stattrak    BOOLEAN NOT NULL DEFAULT FALSE,
    -- Wird selbst gespielt und ist nicht zum Verkauf gedacht. Zaehlt im
    -- Gesamtwert mit, wird aber getrennt ausgewiesen.
    playskin    BOOLEAN NOT NULL DEFAULT FALSE,
    -- Menge und Preis duerfen fehlen: eine angefangene Zeile ist ein
    -- regulaerer Zustand. Sie zaehlt dann nirgends mit und wird als
    -- unvollstaendig ausgewiesen -- nicht als Null.
    quantity    INTEGER CHECK (quantity IS NULL OR quantity >= 0),
    price_eur   NUMERIC(12, 2) CHECK (price_eur IS NULL OR price_eur >= 0),
    -- Wann der Preis zuletzt bestaetigt wurde. Die zentrale Angabe dieses
    -- Moduls, weil Preise von Hand kommen.
    priced_at   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Die Signatur einer Position -- und der Grund, warum sie ein Ausdrucks-Index
-- ist und kein UNIQUE an der Tabelle:
--
-- **Postgres haelt zwei NULL fuer verschieden.** Ein
-- ``UNIQUE (user_id, item_id, wear, stattrak, playskin, storage_id)`` laesst
-- deshalb beliebig viele gleiche Zeilen zu, sobald ``wear`` leer ist -- und
-- leer ist es bei jeder Kategorie ausser Skin, also bei Cases, Stickern und
-- Kapseln. Genau das ist passiert: ein zweiter Lauf der Uebernahme hat 57
-- Zeilen gedoppelt, waehrend die 59 Skins mit Abnutzung sauber blieben. Und
-- weil ``ON CONFLICT`` an dieselbe Regel gebunden ist, griff dort auch das
-- Zusammenfuehren beim Nachkauf nie.
--
-- ``COALESCE(wear, '')`` macht aus "hat keine Abnutzung" einen Wert statt
-- einer Leerstelle. ``NULLS NOT DISTINCT`` waere kuerzer, gibt es aber erst
-- ab Postgres 15 -- und eine Migration, die auf dem Zielserver nicht laeuft,
-- haelt die ganze App an. 043 loest das an anderer Stelle ebenso.
--
-- Jedes ``ON CONFLICT`` auf diese Tabelle muss den Ausdruck WOERTLICH so
-- nennen, samt ``::text`` -- Postgres legt den Typ im Index mit ab und findet
-- ihn sonst nicht (InvalidColumnReferenceError: there is no unique or
-- exclusion constraint matching the ON CONFLICT specification).
CREATE UNIQUE INDEX IF NOT EXISTS idx_cs2_positions_signatur
    ON cs2_positions (user_id, item_id, COALESCE(wear, ''::text), stattrak, playskin, storage_id);

CREATE INDEX IF NOT EXISTS idx_cs2_positions_user
    ON cs2_positions(user_id, item_id);
-- Die Pflegeansicht fragt genau so: aelteste zuerst, NULL zuerst.
CREATE INDEX IF NOT EXISTS idx_cs2_positions_alter
    ON cs2_positions(user_id, priced_at NULLS FIRST);

-- ---------- Snapshots: der Bestand an einem Tag ----------
-- Ein Tag, eine Zeile. Wer zweimal am selben Tag festhaelt, ersetzt die Zeile
-- (ON CONFLICT DO UPDATE) -- zwei Staende desselben Tages waeren nicht zu
-- trennen, und das Tagesdatum ist die Aufloesung, die dieses Modul hergibt.
CREATE TABLE IF NOT EXISTS cs2_snapshots (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    taken_on        DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_gross     NUMERIC(14, 2) NOT NULL DEFAULT 0,
    total_net       NUMERIC(14, 2) NOT NULL DEFAULT 0,
    playskin_gross  NUMERIC(14, 2) NOT NULL DEFAULT 0,
    playskin_net    NUMERIC(14, 2) NOT NULL DEFAULT 0,
    rows_valid      INTEGER NOT NULL DEFAULT 0,
    rows_incomplete INTEGER NOT NULL DEFAULT 0,
    -- Wie aktuell der Bestand war, als der Stand festgehalten wurde. Ohne das
    -- sieht ein Snapshot aus acht Monate alten Preisen aus wie ein frischer.
    stale_rows      INTEGER NOT NULL DEFAULT 0,
    note            TEXT,
    UNIQUE (user_id, taken_on)
);

CREATE INDEX IF NOT EXISTS idx_cs2_snapshots_verlauf
    ON cs2_snapshots(user_id, taken_on);

-- ---------- Die Aufteilung eines Snapshots ----------
-- Zwei Tabellen statt einer mit einer Art-Spalte: so traegt jede ihren echten
-- Fremdschluessel, und eine geloeschte Kategorie nimmt ihre Zeilen mit.
CREATE TABLE IF NOT EXISTS cs2_snapshot_categories (
    id          SERIAL PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES cs2_snapshots(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES cs2_categories(id) ON DELETE CASCADE,
    gross       NUMERIC(14, 2) NOT NULL DEFAULT 0,
    UNIQUE (snapshot_id, category_id)
);

CREATE TABLE IF NOT EXISTS cs2_snapshot_storages (
    id          SERIAL PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES cs2_snapshots(id) ON DELETE CASCADE,
    storage_id  INTEGER NOT NULL REFERENCES cs2_storages(id) ON DELETE CASCADE,
    gross       NUMERIC(14, 2) NOT NULL DEFAULT 0,
    UNIQUE (snapshot_id, storage_id)
);
