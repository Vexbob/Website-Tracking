-- Blog-Modul (v1.18.0)
CREATE TABLE IF NOT EXISTS blog_posts (
    id            SERIAL PRIMARY KEY,
    slug          TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    subtitle      TEXT,
    content_html  TEXT NOT NULL DEFAULT '',
    author_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    author_name   TEXT,
    cover_url     TEXT,
    tags          TEXT[] NOT NULL DEFAULT '{}',
    published_at  TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    view_count    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_blog_posts_pub  ON blog_posts(published_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_blog_posts_slug ON blog_posts(slug);
