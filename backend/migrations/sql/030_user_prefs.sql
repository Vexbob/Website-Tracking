-- Kleiner Key/Value-Speicher fuer Oberflaechen-Einstellungen (v1.46.1)
--
-- Erster Nutzer: die Reihenfolge der Vitalwerte-Diagramme im Gesundheits-Modul.
-- Die Metriken sind -- anders als Achievements oder Wochenziele -- keine
-- Datenbankzeilen, sondern eine feste Liste im Frontend. Es gibt also keine
-- Tabelle mit einer sort_order-Spalte, an die sich eine Reihenfolge haengen
-- liesse. Statt dafuer eine eigene Tabelle anzulegen, bekommt der Nutzer hier
-- einen generischen Ablageplatz, den kuenftige Einstellungen mitbenutzen
-- koennen.
--
-- Bewusst NICHT im localStorage: die Reihenfolge soll -- wie die der
-- Wochenziele, an der sich der Wunsch orientiert -- auf allen Geraeten
-- dieselbe sein.
--
-- ``value`` ist TEXT und enthaelt JSON. TEXT statt JSONB, weil asyncpg JSONB
-- ohne registrierten Codec ohnehin als String liefert -- so bleibt das
-- Serialisieren an einer Stelle (im Router) statt halb in der DB.

CREATE TABLE IF NOT EXISTS user_prefs (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, key)
);
