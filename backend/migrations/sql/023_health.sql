-- Gesundheits-Modul (v1.22.0) — Sync via Auto Health Export (iPhone)
-- Ersetzt die alte, ungenutzte generische ``health_metrics``-Tabelle durch
-- typ-spezifische Tabellen (Zeitserien, Blutdruck-Paare, Blutzucker,
-- Schlafphasen, Workouts + Workout-Detailmetriken).

DROP TABLE IF EXISTS health_metrics;

-- ---------- API-Keys fuer den automatisierten Sync ----------
-- Format des Klartext-Keys: hae_<user_id>_<random>. Nur der Hash wird
-- gespeichert (HMAC-SHA256 mit SECRET_KEY als Pepper, siehe auth.py) —
-- bewusst kein bcrypt, da der Key selbst schon hochentropisch ist und
-- der Import-Endpoint ggf. mehrmals taeglich automatisiert aufgerufen wird.
CREATE TABLE IF NOT EXISTS health_api_keys (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash      TEXT NOT NULL UNIQUE,
    label         TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    last_used_at  TIMESTAMPTZ,
    revoked_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_health_api_keys_user ON health_api_keys(user_id);

-- ---------- Einfache Zeitserien-Metriken ----------
-- aktive Energie, Herzfrequenz (mit Min/Max/Avg), Ø-Herzfrequenz beim Gehen,
-- Gewicht, HRV, Ruhepuls, kardiorespiratorische Erholung, Schritte, VO2max,
-- Schwimmdistanz.
CREATE TABLE IF NOT EXISTS health_metric_samples (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    metric_type  TEXT NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL,
    sample_date  DATE NOT NULL,
    qty          NUMERIC,
    min_value    NUMERIC,
    max_value    NUMERIC,
    avg_value    NUMERIC,
    unit         TEXT,
    source       TEXT NOT NULL DEFAULT 'auto_health_export',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, metric_type, recorded_at, source)
);
CREATE INDEX IF NOT EXISTS idx_health_samples_user_type_date
    ON health_metric_samples(user_id, metric_type, sample_date);

-- ---------- Blutdruck (Paar aus Systole/Diastole) ----------
CREATE TABLE IF NOT EXISTS health_blood_pressure (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recorded_at  TIMESTAMPTZ NOT NULL,
    systolic     NUMERIC,
    diastolic    NUMERIC,
    unit         TEXT NOT NULL DEFAULT 'mmHg',
    source       TEXT NOT NULL DEFAULT 'auto_health_export',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, recorded_at, source)
);
CREATE INDEX IF NOT EXISTS idx_health_bp_user_date ON health_blood_pressure(user_id, recorded_at);

-- ---------- Blutzucker ----------
CREATE TABLE IF NOT EXISTS health_blood_glucose (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recorded_at  TIMESTAMPTZ NOT NULL,
    value        NUMERIC,
    unit         TEXT NOT NULL DEFAULT 'mg/dL',
    source       TEXT NOT NULL DEFAULT 'auto_health_export',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, recorded_at, source)
);
CREATE INDEX IF NOT EXISTS idx_health_glucose_user_date ON health_blood_glucose(user_id, recorded_at);

-- ---------- Schlaf (ein Eintrag pro Nacht, Phasen als Spalten) ----------
CREATE TABLE IF NOT EXISTS health_sleep (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sleep_date      DATE NOT NULL,
    sleep_start     TIMESTAMPTZ,
    sleep_end       TIMESTAMPTZ,
    in_bed_minutes  NUMERIC,
    asleep_minutes  NUMERIC,
    core_minutes    NUMERIC,
    deep_minutes    NUMERIC,
    rem_minutes     NUMERIC,
    awake_minutes   NUMERIC,
    source          TEXT NOT NULL DEFAULT 'auto_health_export',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, sleep_date, source)
);
CREATE INDEX IF NOT EXISTS idx_health_sleep_user_date ON health_sleep(user_id, sleep_date);

-- ---------- Workouts (bewusst OHNE Routendaten) ----------
CREATE TABLE IF NOT EXISTS health_workouts (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    external_id         TEXT NOT NULL,
    workout_type        TEXT,
    start_at            TIMESTAMPTZ NOT NULL,
    end_at              TIMESTAMPTZ,
    duration_min        NUMERIC,
    active_energy_kcal  NUMERIC,
    total_energy_kcal   NUMERIC,
    distance_m          NUMERIC,
    avg_heart_rate      NUMERIC,
    max_heart_rate      NUMERIC,
    elevation_m         NUMERIC,
    source              TEXT NOT NULL DEFAULT 'auto_health_export',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_health_workouts_user_start ON health_workouts(user_id, start_at DESC);

-- ---------- Workout-Detailmetriken (flexibel, je Sportart unterschiedlich) ----------
CREATE TABLE IF NOT EXISTS health_workout_metrics (
    id           SERIAL PRIMARY KEY,
    workout_id   INTEGER NOT NULL REFERENCES health_workouts(id) ON DELETE CASCADE,
    metric_key   TEXT NOT NULL,
    value        NUMERIC,
    unit         TEXT,
    UNIQUE (workout_id, metric_key)
);
CREATE INDEX IF NOT EXISTS idx_health_workout_metrics_workout ON health_workout_metrics(workout_id);
