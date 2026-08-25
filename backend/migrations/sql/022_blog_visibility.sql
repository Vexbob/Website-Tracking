-- Blog-Sichtbarkeit (v1.19.0)
-- is_public: Post ist öffentlich lesbar (ohne Login)
-- show_on_login: Post wird auf der Login-Seite als Teaser angezeigt
ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE blog_posts ADD COLUMN IF NOT EXISTS show_on_login BOOLEAN NOT NULL DEFAULT false;

-- Bestehende veröffentlichte Posts als öffentlich markieren (Migration)
UPDATE blog_posts SET is_public = true WHERE published_at IS NOT NULL;
