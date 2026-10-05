-- Depot: der Trade-Republic-Kontoauszug (v2.38.0, Modul im Bau)
--
-- Trade Republic gibt den Verlauf als PDF heraus: den Kontoauszug des
-- Cashkontos mit jeder Buchung -- Einzahlung, Kauf, Sparplan, Verkauf,
-- Ertrag, Zinsen. ``services/depot_import.py`` liest ihn und prueft jede
-- Zeile gegen den Saldo und die Summen der Kontouebersicht.
--
-- 1) ``depot_imports``: welcher Auszug wann kam, fuer welchen Zeitraum, mit
--    Pruefsumme -- derselbe Auszug zweimal faellt auf.
-- 2) ``depot_import_dateien``: das PDF selbst, in einer eigenen Tabelle
--    (eine Bytes-Spalte am Protokoll wuerde bei jedem Listenaufruf
--    mitgeschleift). Aufbewahrt, damit ein spaeter verbesserter Leser alte
--    Auszuege neu lesen kann, ohne dass jemand sie noch einmal hochlaedt.
-- 3) ``depot_buchungen``: je Zeile des Auszugs eine Buchung. ``betrag`` mit
--    Vorzeichen (Eingang positiv), ``saldo`` wie im Auszug, ``stueck`` nur,
--    wo der Auszug es nennt -- die aelteren deutschen Zeilen tun es nicht,
--    und eine Stueckzahl aus Betrag und Kurs zu raten waere die falsche
--    Genauigkeit. ``reihe`` haelt die Reihenfolge innerhalb eines Tages.
--
-- Ein neuer Auszug ERSETZT die Buchungen seines Zeitraums (Trade Republic
-- stellt ihn meist ueber die ganze Laufzeit aus) -- zwei Auszuege
-- nebeneinander zaehlten jede Buchung doppelt.

CREATE TABLE IF NOT EXISTS depot_imports (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dateiname       TEXT,
    hochgeladen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    groesse         INTEGER NOT NULL DEFAULT 0,
    pruefsumme      TEXT NOT NULL,
    zeitraum_von    DATE NOT NULL,
    zeitraum_bis    DATE NOT NULL,
    buchungen       INTEGER NOT NULL DEFAULT 0,
    endsaldo        NUMERIC,
    ersetzt         INTEGER NOT NULL DEFAULT 0,
    UNIQUE (user_id, pruefsumme)
);
CREATE INDEX IF NOT EXISTS idx_depot_imports_user ON depot_imports(user_id, hochgeladen_at DESC);

CREATE TABLE IF NOT EXISTS depot_import_dateien (
    import_id   INTEGER PRIMARY KEY REFERENCES depot_imports(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    daten       BYTEA NOT NULL
);

CREATE TABLE IF NOT EXISTS depot_buchungen (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    import_id    INTEGER REFERENCES depot_imports(id) ON DELETE CASCADE,
    datum        DATE NOT NULL,
    reihe        INTEGER NOT NULL DEFAULT 0,
    art          TEXT NOT NULL,
    typ          TEXT,
    beschreibung TEXT,
    isin         TEXT,
    name         TEXT,
    stueck       NUMERIC,
    betrag       NUMERIC NOT NULL,
    saldo        NUMERIC
);
CREATE INDEX IF NOT EXISTS idx_depot_buchungen_user ON depot_buchungen(user_id, datum, reihe);
CREATE INDEX IF NOT EXISTS idx_depot_buchungen_isin ON depot_buchungen(user_id, isin);
