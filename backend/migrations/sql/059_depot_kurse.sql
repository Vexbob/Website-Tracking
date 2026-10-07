-- Depot: Kurse und Stueck aus der App (v2.39.0)
--
-- Der Kontoauszug kennt Geld, keine Kurse. Fuer den Depotwert holt der
-- Server Tagesschlusskurse in Euro (``services/depot_kurse.py``, onvista,
-- bevorzugt LS Exchange -- der Handelsplatz von Trade Republic).
--
-- 1) ``depot_kursquellen``: je ISIN, wo ihr Kurs herkommt (Instrument und
--    Boersenplatz) und wann zuletzt geholt wurde. ``gefunden = FALSE`` haelt
--    fest, dass die Quelle die ISIN nicht kennt -- sonst fragte jeder Aufruf
--    erneut nach einem laengst ausgelaufenen Optionsschein.
-- 2) ``depot_kurse``: ein Schlusskurs je ISIN und Tag. Kurse sind oeffentlich
--    und fuer alle Konten dieselben, deshalb ohne ``user_id``; sie sind ein
--    Zwischenspeicher, kein Bestand, und kommen nicht ins Backup -- nach
--    einem Zurueckspielen holt der Server sie neu.
-- 3) ``depot_stueck``: die Stueckzahl laut App, von Hand eingetragen. Die
--    aelteren Zeilen des Auszugs (vor Juni 2024) nennen keine Stueckzahl;
--    fuer eine Position, die damals schon bestand, laesst sich der Bestand
--    deshalb nicht aus dem Auszug allein zusammenzaehlen. Eine Zahl je
--    Wertpapier mit ihrem Datum genuegt: alles danach rechnet der Auszug
--    weiter, alles davor zurueck.

CREATE TABLE IF NOT EXISTS depot_kursquellen (
    isin         TEXT PRIMARY KEY,
    quelle       TEXT NOT NULL DEFAULT 'onvista',
    gefunden     BOOLEAN NOT NULL DEFAULT TRUE,
    typ          TEXT,
    instrument   TEXT,
    notierung    TEXT,
    markt        TEXT,
    name         TEXT,
    fehler       TEXT,
    -- Ab welchem Tag der Verlauf schon geholt ist. Ein Fonds, den es erst
    -- seit 2025 gibt, hat keine Kurse davor -- am ersten Kurs laesst sich
    -- deshalb nicht ablesen, ob schon vollstaendig geholt wurde.
    geholt_ab    DATE,
    geholt_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS depot_kurse (
    isin   TEXT NOT NULL,
    datum  DATE NOT NULL,
    kurs   NUMERIC NOT NULL,
    PRIMARY KEY (isin, datum)
);

CREATE TABLE IF NOT EXISTS depot_stueck (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    isin         TEXT NOT NULL,
    stueck       NUMERIC NOT NULL,
    datum        DATE NOT NULL,
    geaendert_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, isin)
);
