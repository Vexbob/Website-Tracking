-- Paket 9: Ausgaben-Modul
-- Kassenbon-Scan, Positions-Erfassung, Läden, Kategorien, mitlernende Regeln,
-- Bildspeicher, Statistiken. Idempotent.

-- Läden (Aldi, Lidl, dm, ...)
CREATE TABLE IF NOT EXISTS stores (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color TEXT DEFAULT '#6b7280',
    icon TEXT,
    sort_order INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_stores_user ON stores(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_stores_user_name
    ON stores(user_id, LOWER(name));

-- Kategorien (Lebensmittel, Drogerie, Technik, ...)
CREATE TABLE IF NOT EXISTS expense_categories (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color TEXT DEFAULT '#3b82f6',
    icon TEXT,
    sort_order INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_expense_categories_user ON expense_categories(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_expense_categories_user_name
    ON expense_categories(user_id, LOWER(name));

-- Auto-Kategorisierungs-Regeln (mitlernend: hit_count zählt Bestätigungen)
CREATE TABLE IF NOT EXISTS category_rules (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES expense_categories(id) ON DELETE CASCADE,
    store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    hit_count INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_category_rules_user ON category_rules(user_id);
CREATE INDEX IF NOT EXISTS idx_category_rules_keyword ON category_rules(user_id, LOWER(keyword));

-- Kassenbon-Bilder (BYTEA, mit Thumbnail für Galerie)
CREATE TABLE IF NOT EXISTS receipt_images (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER,
    image_data BYTEA,
    thumbnail_data BYTEA,
    ocr_provider TEXT,
    ocr_raw_text TEXT,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_receipt_images_user ON receipt_images(user_id, uploaded_at DESC);

-- Ausgaben (ein Kassenbon ODER manueller Eintrag)
CREATE TABLE IF NOT EXISTS expenses (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    receipt_image_id INTEGER REFERENCES receipt_images(id) ON DELETE SET NULL,
    store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
    purchase_date DATE NOT NULL,
    total_amount NUMERIC NOT NULL,
    vat_amount NUMERIC,
    payment_method TEXT,
    is_recurring BOOLEAN DEFAULT FALSE,
    recurring_pattern TEXT,
    note TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses(user_id, purchase_date DESC);
CREATE INDEX IF NOT EXISTS idx_expenses_user_store ON expenses(user_id, store_id);

-- Einzelpositionen (Line-Items)
CREATE TABLE IF NOT EXISTS expense_items (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    quantity NUMERIC DEFAULT 1,
    unit_price NUMERIC,
    total_price NUMERIC NOT NULL,
    category_id INTEGER REFERENCES expense_categories(id) ON DELETE SET NULL,
    sort_order INTEGER
);
CREATE INDEX IF NOT EXISTS idx_expense_items_expense ON expense_items(expense_id);
CREATE INDEX IF NOT EXISTS idx_expense_items_desc ON expense_items(user_id, LOWER(description));
CREATE INDEX IF NOT EXISTS idx_expense_items_category ON expense_items(user_id, category_id);
