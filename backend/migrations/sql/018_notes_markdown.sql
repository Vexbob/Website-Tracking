-- Paket 18: Notizen-Format (v1.17.0)
--
-- Wechsel von contenteditable-HTML zu Markdown als Speicherformat.
-- ``format`` markiert pro Notiz, wie ``content`` interpretiert werden soll:
--   * 'html'     — Legacy-Notizen (v1.14 - v1.16), contenteditable-Output
--   * 'markdown' — neue Notizen ab v1.17.0
--
-- Bestandsdaten bleiben unangetastet — der Frontend-Client konvertiert
-- HTML beim ersten Laden zu Markdown und schreibt beim naechsten Save mit
-- ``format='markdown'`` zurueck (transparente Client-side-Migration).

ALTER TABLE notes
    ADD COLUMN IF NOT EXISTS format TEXT NOT NULL DEFAULT 'markdown';

-- Bestehende Notizen: als 'html' markieren, damit der Client sie migriert.
-- Neue Notizen bekommen dank DEFAULT bereits 'markdown'.
UPDATE notes SET format = 'html'
 WHERE format = 'markdown' AND created_at < NOW();
