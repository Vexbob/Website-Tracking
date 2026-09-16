-- Abgelehnte Bruecken-Vorschlaege (v1.99.0)
--
-- Der Tracker bietet an, haeufige Namen aus dem Essenstagebuch als richtiges
-- Lebensmittel anzulegen ("Muesli, 43x notiert -- Naehrwerte hinterlegen?").
-- Wer das fuer einen Namen nicht will, soll nicht bei jedem Aufruf wieder
-- gefragt werden.
--
-- Dasselbe Muster wie bei den Dubletten-Vorschlaegen (024, 028, 036): der
-- abgelehnte Vorschlag bekommt eine Zeile, und die Abfrage schliesst ihn
-- danach aus. Gemerkt wird die KLEINGESCHRIEBENE Schreibweise -- sonst kaeme
-- derselbe Name beim naechsten Mal als "Muesli" statt "muesli" zurueck.

CREATE TABLE IF NOT EXISTS food_bridge_dismissed (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label_lower TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, label_lower)
);
