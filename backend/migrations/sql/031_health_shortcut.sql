-- Beta-Strecke: Apple-Health-Import per iPhone-Kurzbefehl (v1.47.0)
--
-- Motivation: Die bestehende Anbindung ueber die App "Health Auto Export"
-- laeuft unzuverlaessig. Als zweiter, unabhaengiger Weg schickt ein Kurzbefehl
-- auf dem iPhone einmal taeglich die letzten drei Tage an
-- ``POST /api/health/shortcut/import``. Drei Tage statt einem, damit ein
-- ausgefallener Lauf vom naechsten nachgeholt wird -- derselbe Tag kommt also
-- mehrfach an und darf keine Dubletten erzeugen.
--
-- Bewusst EIGENE Tabelle statt ``health_metric_samples``: die Strecke ist ein
-- Versuch mit noch unbekanntem Datenformat und darf die produktiven Werte
-- weder ueberschreiben noch verunreinigen. Sie fliesst in keine Auswertung ein
-- und ist nur im Beta-Reiter des Gesundheits-Moduls roh sichtbar. Die
-- Spaltennamen sind trotzdem absichtlich an ``health_metric_samples``
-- angelehnt, damit ein spaeteres Umschalten ein Copy-Job zwischen zwei
-- Tabellen bleibt und kein Umbau.
--
-- Der Roh-Payload jedes Aufrufs landet NICHT hier, sondern im vorhandenen
-- ``health_import_log`` mit ``kind='shortcut'`` -- inklusive der schon
-- gebauten Aufbewahrungsgrenze und des Download-Endpoints.

CREATE TABLE IF NOT EXISTS health_shortcut_samples (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Freies Textfeld ohne Enum/FK: eine neue Metrik funktioniert an dem Tag,
    -- an dem der Kurzbefehl sie zum ersten Mal schickt. Die Registry im
    -- Service (SHORTCUT_METRICS) liefert nur Label und Default-Einheit, sie
    -- ist ausdruecklich kein Tuersteher.
    metric_key    TEXT NOT NULL,
    -- 'day'   = Tagesaggregat (Schritte); bucket_start ist Mitternacht lokal.
    -- 'point' = Einzelmessung (spaeter z.B. Puls); bucket_start ist der echte
    --           Zeitstempel.
    -- Beides im selben Unique-Index, damit spaetere Metriken mit mehreren
    -- Werten pro Tag OHNE Schema-Aenderung dazukommen koennen. Ein
    -- UNIQUE (user_id, metric_key, sample_date) haette dafuer eine Migration
    -- am Index erzwungen.
    bucket        TEXT NOT NULL DEFAULT 'day',
    bucket_start  TIMESTAMPTZ NOT NULL,
    sample_date   DATE NOT NULL,
    value         NUMERIC,
    unit          TEXT,
    -- Der Zeitstempel EXAKT so, wie der Kurzbefehl ihn geliefert hat. Landet
    -- ein Wert am falschen Tag, ist damit unterscheidbar, ob der Kurzbefehl
    -- Unsinn geschickt oder der Parser ihn falsch interpretiert hat.
    raw_date      TEXT,
    source        TEXT NOT NULL DEFAULT 'ios_shortcut',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Wiederholte Lieferung desselben Tages ueberschreibt (ON CONFLICT DO
    -- UPDATE im Ingest), statt eine zweite Zeile anzulegen.
    UNIQUE (user_id, metric_key, bucket, bucket_start)
);

CREATE INDEX IF NOT EXISTS idx_health_shortcut_user_date
    ON health_shortcut_samples(user_id, sample_date DESC);
