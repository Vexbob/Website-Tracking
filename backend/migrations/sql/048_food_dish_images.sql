-- Ein Foto je Gericht (v1.99.0)
--
-- Nur fuer eigene Rezepte, nicht fuer Lebensmittel aus Open Food Facts: ein
-- fremdes Produktfoto waere weder mein Essen noch meine Daten, und bei
-- 400.000 Katalogeintraegen erkennt man ein Produkt am Namen und an der
-- Marke. Ein selbst gekochtes Gericht erkennt man am Bild.
--
-- Eigene Tabelle statt einer Spalte an ``food_dishes``: ``_gerichte()``
-- liest die Liste mit SELECT ueber alle Spalten, und ein BYTEA wuerde bei
-- jedem Listenaufruf mitgeschleift. Hier steht es daneben und wird nur
-- geholt, wenn es angezeigt wird.
--
-- UNIQUE (dish_id) heisst: ein erneuter Upload ERSETZT. Eine Bildergalerie
-- je Rezept waere eine zweite Sache -- hier geht es um das eine Foto, an dem
-- man das Gericht in der Liste wiedererkennt.

CREATE TABLE IF NOT EXISTS food_dish_images (
    id             SERIAL PRIMARY KEY,
    dish_id        INTEGER NOT NULL UNIQUE
                   REFERENCES food_dishes(id) ON DELETE CASCADE,
    mime_type      TEXT NOT NULL DEFAULT 'image/jpeg',
    size_bytes     INTEGER NOT NULL DEFAULT 0,
    image_data     BYTEA NOT NULL,
    thumbnail_data BYTEA,
    uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
