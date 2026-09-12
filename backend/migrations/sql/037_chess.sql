-- Schach-Modul (v1.83.0) — Wertungszahlen und Partien von Lichess und Chess.com
--
-- Die Daten kommen von den beiden Plattformen selbst. Beide geben oeffentlich
-- heraus, was dieses Modul braucht -- ohne Anmeldung, ohne Schluessel:
--
--     Lichess    https://lichess.org/api/user/<name>          Wertungszahlen
--                https://lichess.org/api/games/user/<name>    Partien (ndjson)
--     Chess.com  https://api.chess.com/pub/player/<name>/stats
--                https://api.chess.com/pub/player/<name>/games/archives
--
-- Hinterlegt wird deshalb nur ein Benutzername je Plattform. Ein Passwort
-- oder ein Token waere ein Geheimnis, das dieses Modul gar nicht braucht.

-- ---------- Ein verbundenes Konto ----------
CREATE TABLE IF NOT EXISTS chess_accounts (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- 'lichess' oder 'chesscom'. Die Schreibweise der Plattform steht in
    -- ``username`` so, wie sie sie selbst zurueckgibt (Gross-/Kleinschreibung).
    platform        TEXT NOT NULL CHECK (platform IN ('lichess', 'chesscom')),
    username        TEXT NOT NULL,
    profile_url     TEXT,
    linked_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Wann zuletzt Wertungszahlen bzw. Partien geholt wurden, und wie weit der
    -- Partien-Import gekommen ist. ``games_through`` ist der Zeitpunkt der
    -- juengsten gespeicherten Partie -- daran setzt der naechste Lauf an,
    -- statt jedes Mal die ganze Historie erneut abzufragen.
    ratings_at      TIMESTAMPTZ,
    games_at        TIMESTAMPTZ,
    games_through   TIMESTAMPTZ,
    -- Ein Konto je Plattform und Nutzer: zwei Lichess-Konten nebeneinander
    -- waeren zwei Verlaeufe in einer Kurve, die sich nicht vergleichen lassen.
    UNIQUE (user_id, platform)
);

-- ---------- Wertungszahl, taeglich festgehalten ----------
-- Beide Plattformen geben nur den AKTUELLEN Stand heraus, keinen Verlauf.
-- Der Verlauf entsteht deshalb hier: ein Abruf schreibt je Disziplin eine
-- Zeile fuer den heutigen Tag, ein zweiter Abruf am selben Tag ueberschreibt
-- sie. So wird aus taeglichem Nachsehen von selbst eine Kurve, und mehrfaches
-- Aktualisieren erzeugt keine Treppe aus Doppelwerten.
CREATE TABLE IF NOT EXISTS chess_ratings (
    id          SERIAL PRIMARY KEY,
    account_id  INTEGER NOT NULL REFERENCES chess_accounts(id) ON DELETE CASCADE,
    -- bullet | blitz | rapid | classical | daily | puzzle
    perf        TEXT NOT NULL,
    rating      INTEGER NOT NULL,
    rd          INTEGER,
    games       INTEGER,
    -- Chess.com gibt zur Raetsel-Wertung nur Hoechst- und Tiefstwert heraus,
    -- nicht den aktuellen Stand. Eine Zeile mit is_best sagt: das ist ein
    -- Bestwert, keine Tagesform. Ohne dieses Feld stuende in derselben Spalte
    -- einmal "heute" und einmal "jemals" -- und niemand koennte es sehen.
    is_best     BOOLEAN NOT NULL DEFAULT FALSE,
    taken_on    DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE (account_id, perf, taken_on)
);

CREATE INDEX IF NOT EXISTS idx_chess_ratings_verlauf
    ON chess_ratings(account_id, perf, taken_on);

-- ---------- Partien ----------
-- ``ext_id`` ist die ID der Plattform (Lichess-ID bzw. Chess.com-UUID).
-- Zusammen mit dem Konto ist sie eindeutig -- daran haengt, dass derselbe
-- Import zweimal hintereinander folgenlos bleibt.
CREATE TABLE IF NOT EXISTS chess_games (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id      INTEGER NOT NULL REFERENCES chess_accounts(id) ON DELETE CASCADE,
    platform        TEXT NOT NULL,
    ext_id          TEXT NOT NULL,
    played_at       TIMESTAMPTZ NOT NULL,
    perf            TEXT,
    variant         TEXT,
    rated           BOOLEAN,
    -- 'weiss' | 'schwarz'
    color           TEXT,
    -- 'sieg' | 'remis' | 'niederlage'
    result          TEXT,
    -- Wie die Partie endete (matt, aufgegeben, zeit, remis, abgebrochen …).
    end_reason      TEXT,
    own_rating      INTEGER,
    rating_diff     INTEGER,
    opponent        TEXT,
    opponent_rating INTEGER,
    opening         TEXT,
    eco             TEXT,
    moves           INTEGER,
    url             TEXT,
    -- Die Zugfolge als PGN. Chess.com liefert sie mit, Lichess auf Wunsch;
    -- sie ist der einzige Teil, den man nicht aus den Spalten daneben wieder
    -- herstellen kann, und ohne sie ist eine gespeicherte Partie nicht mehr
    -- als eine Zeile in einer Statistik.
    pgn             TEXT,
    UNIQUE (account_id, ext_id)
);

CREATE INDEX IF NOT EXISTS idx_chess_games_user_zeit
    ON chess_games(user_id, played_at DESC);

CREATE INDEX IF NOT EXISTS idx_chess_games_konto_zeit
    ON chess_games(account_id, played_at DESC);

-- ---------- Protokoll der Importlaeufe ----------
-- Ein Lauf holt hoechstens ein Stueck der Historie (der Router deckelt das),
-- der naechste setzt fort. Das Protokoll sagt hinterher, was wirklich
-- ankam -- und bei einem Abbruch, wie weit es kam.
CREATE TABLE IF NOT EXISTS chess_imports (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id  INTEGER REFERENCES chess_accounts(id) ON DELETE SET NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    games_seen  INTEGER NOT NULL DEFAULT 0,
    games_new   INTEGER NOT NULL DEFAULT 0,
    ok          BOOLEAN NOT NULL DEFAULT TRUE,
    note        TEXT
);

CREATE INDEX IF NOT EXISTS idx_chess_imports_user
    ON chess_imports(user_id, started_at DESC);
