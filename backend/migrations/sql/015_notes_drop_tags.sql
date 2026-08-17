-- Paket 15: Tags aus Notizen entfernt (UI wird auf Master-Detail umgestellt).
-- 014 ist in derselben Session neu angelegt worden, es gibt noch keine
-- Nutzdaten in `tags` — die Spalte kann gefahrlos wegfallen.

DROP INDEX IF EXISTS idx_notes_tags;
ALTER TABLE notes DROP COLUMN IF EXISTS tags;
