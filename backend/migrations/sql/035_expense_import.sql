-- CSV-Import fuer Ausgaben (v1.80.0) — der Backlog aus der C24-App
--
-- Bis August 2026 wurden Ausgaben nicht in Vexbob erfasst. Der Rueckblick
-- kommt deshalb aus dem CSV-Export der Bank-App und sieht anders aus als ein
-- gescannter Kassenbon:
--
--     Buchungsdatum  Betrag    Zahlungsempfaenger  Kategorie  Unterkategorie
--     31.07.2026     -35,50 €  Amazon              Shopping   Online-Shopping
--
-- Es gibt KEINE Einzelpositionen — nur den Gesamtbetrag. Genau das ist der
-- Unterschied, den die Daten selbst tragen muessen: eine Buchung ohne
-- Positionen ist sonst spaeter nicht von einem Bon zu unterscheiden, bei dem
-- das Abtippen der Positionen vergessen wurde.
--
-- Drei Dinge bekommt die Buchung deshalb mit:
--
--   * ``source``          woher sie stammt ('receipt' | 'manual' | 'import')
--   * ``src_*``           was in der CSV stand, unveraendert
--   * ``import_id``       welcher Upload sie angelegt hat
--
-- Die ``src_``-Spalten sind kein Ballast, sondern die Voraussetzung fuer den
-- zweiten Schritt: die Kategorien der Bank-App ("Weitere Ausgaben") sind
-- nicht die dieser Website. Ein KI-Lauf soll sie spaeter einmalig zuordnen —
-- und der braucht das Original. Wer es beim Import wegwirft, kann die
-- Zuordnung nur noch durch einen erneuten Import nachholen.

-- ---------- Ein Upload ----------
-- Wie bei den Musik-Uploads: jeder Import wird protokolliert, damit
-- nachvollziehbar bleibt, woher eine Buchung stammt, und damit ein
-- versehentlicher Import als Ganzes wieder verschwinden kann.
CREATE TABLE IF NOT EXISTS expense_imports (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename       TEXT,
    size_bytes     INTEGER NOT NULL DEFAULT 0,
    uploaded_at    TIMESTAMPTZ DEFAULT NOW(),
    date_from      DATE,                          -- Zeitraum, den die Datei abdeckt
    date_to        DATE,
    rows_read      INTEGER NOT NULL DEFAULT 0,    -- Datenzeilen in der Datei
    rows_written   INTEGER NOT NULL DEFAULT 0,    -- davon uebernommen
    rows_skipped   INTEGER NOT NULL DEFAULT 0,    -- Gutschriften, kaputte Zeilen
    rows_replaced  INTEGER NOT NULL DEFAULT 0,    -- vorher geloescht (Zeitraum-Ersatz)
    stores_created INTEGER NOT NULL DEFAULT 0,    -- neu angelegte Laeden
    -- Was uebersprungen wurde und warum, je Grund eine Zahl plus Beispiele.
    -- Als JSONB, weil die Gruende wachsen duerfen und niemand danach filtert.
    notes          JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_expense_imports_user
    ON expense_imports(user_id, uploaded_at DESC);

-- ---------- Herkunft an der Buchung ----------
-- 'receipt' ist der Bestand: alles, was vor dieser Migration existierte,
-- kam ueber Foto/OCR oder von Hand. Der Default haelt das so.
ALTER TABLE expenses
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'receipt';
ALTER TABLE expenses
    ADD COLUMN IF NOT EXISTS src_payee TEXT;
ALTER TABLE expenses
    ADD COLUMN IF NOT EXISTS src_category TEXT;
ALTER TABLE expenses
    ADD COLUMN IF NOT EXISTS src_subcategory TEXT;
ALTER TABLE expenses
    ADD COLUMN IF NOT EXISTS import_id INTEGER
        REFERENCES expense_imports(id) ON DELETE SET NULL;

-- Der Zeitraum-Ersatz beim erneuten Import fragt genau danach: welche
-- importierten Buchungen liegen in diesem Zeitraum?
CREATE INDEX IF NOT EXISTS idx_expenses_user_source_date
    ON expenses(user_id, source, purchase_date);
CREATE INDEX IF NOT EXISTS idx_expenses_import
    ON expenses(import_id);

-- Fuer den zweiten Schritt (Kategorien zuordnen): "zeig mir alle Buchungen,
-- deren Bank-Kategorie X ist und die noch keine eigene Kategorie haben".
CREATE INDEX IF NOT EXISTS idx_expenses_src_category
    ON expenses(user_id, src_category)
    WHERE src_category IS NOT NULL;
