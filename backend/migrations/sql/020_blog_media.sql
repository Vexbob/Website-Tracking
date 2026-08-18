-- Blog-Media (v1.18.1) — Bilder für Blog-Posts
CREATE TABLE IF NOT EXISTS blog_media (
    id           SERIAL PRIMARY KEY,
    post_id      INTEGER REFERENCES blog_posts(id) ON DELETE SET NULL,
    filename     TEXT NOT NULL DEFAULT '',
    mime_type    TEXT NOT NULL DEFAULT 'image/jpeg',
    size_bytes   INTEGER NOT NULL DEFAULT 0,
    width        INTEGER,
    height       INTEGER,
    image_data   BYTEA NOT NULL,
    thumbnail_data BYTEA,
    uploaded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_blog_media_post ON blog_media(post_id);
