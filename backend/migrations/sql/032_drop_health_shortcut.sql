-- Ruecknahme der Beta-Strecke "Apple Health per iPhone-Kurzbefehl" (v1.49.0)
--
-- Die Strecke war ein Versuch, weil der Sync ueber Auto Health Export
-- unzuverlaessig schien. Die eigentliche Ursache lag woanders: die App
-- exportiert die Zusatzmetriken nicht, wenn mehrere Workout-Typen zusammen
-- exportiert werden. Mit einem Workout-Typ je Export laeuft der bestehende
-- Sync -- der Kurzbefehl-Weg wird damit nicht mehr gebraucht und faellt
-- vollstaendig weg, statt als ungenutzte Tabelle liegen zu bleiben.
--
-- Migration 031 wird bewusst NICHT geloescht oder editiert: sie ist auf allen
-- Umgebungen bereits angewendet, und der Runner prueft ihren SHA256. Die
-- Ruecknahme gehoert deshalb in eine eigene, nachfolgende Migration.
--
-- Die Tabelle enthielt ausschliesslich Testdaten aus dem Einrichten des
-- Kurzbefehls; es geht nichts verloren, was nicht auch ueber den regulaeren
-- Sync vorliegt. Die Gesundheitsdaten der Auto-Health-Export-Strecke liegen in
-- anderen Tabellen und sind hiervon nicht beruehrt.

DROP TABLE IF EXISTS health_shortcut_samples;

-- Die Testaufrufe im gemeinsamen Import-Protokoll ebenfalls entfernen. Sie
-- wurden mit ``kind`` = 'shortcut-<format>' abgelegt; die Eintraege der
-- Auto-Health-Export-Strecke (json / csv / multipart / empty) bleiben stehen.
DELETE FROM health_import_log WHERE kind LIKE 'shortcut%';
