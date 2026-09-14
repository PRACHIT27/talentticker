"""SQLite storage. One file, no server, easy to move to Postgres later."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS companies (
    slug          TEXT PRIMARY KEY,   -- ats:board_token, e.g. "greenhouse:stripe"
    ats           TEXT NOT NULL,
    board_token   TEXT NOT NULL,
    name          TEXT,
    sector        TEXT,               -- from companies.yml, else guessed
    tier          INTEGER DEFAULT 2,  -- 1 = poll every few minutes, 2 = hourly
    active        INTEGER DEFAULT 1,
    last_polled   TEXT,
    last_error    TEXT,
    job_count     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS postings (
    id             TEXT PRIMARY KEY,  -- "<ats>:<board_token>:<external_id>"
    company_slug   TEXT NOT NULL,
    company_name   TEXT,
    sector         TEXT,              -- copied here so sector queries stay simple
    ats            TEXT,
    external_id    TEXT,
    title          TEXT,
    url            TEXT,
    department     TEXT,
    team           TEXT,
    location_raw   TEXT,
    content        TEXT,              -- description as plain text
    first_published TEXT,             -- ISO8601, when the company first posted it
    updated_at     TEXT,
    seen_first     TEXT,              -- when we first saw it
    seen_last      TEXT,
    closed_at      TEXT,              -- set when it disappears from the board

    -- derived by the extractors
    is_swe         INTEGER DEFAULT 0,
    yoe_min        REAL,
    yoe_max        REAL,
    level          TEXT,
    eligible       INTEGER DEFAULT 0, -- SWE and 0-4 years: what this product is about
    reason         TEXT,              -- why it was kept or dropped, for debugging
    metro          TEXT,
    state          TEXT,
    country        TEXT,
    remote         INTEGER DEFAULT 0,
    salary_min     INTEGER,
    salary_max     INTEGER,
    processed      INTEGER DEFAULT 0,
    alerted        INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_postings_pub      ON postings(first_published);
CREATE INDEX IF NOT EXISTS idx_postings_eligible ON postings(eligible, first_published);
CREATE INDEX IF NOT EXISTS idx_postings_company  ON postings(company_slug);
CREATE INDEX IF NOT EXISTS idx_postings_metro    ON postings(metro);
CREATE INDEX IF NOT EXISTS idx_postings_unproc   ON postings(processed);

CREATE TABLE IF NOT EXISTS posting_skills (
    posting_id  TEXT NOT NULL,
    skill       TEXT NOT NULL,
    hits        INTEGER DEFAULT 1,
    PRIMARY KEY (posting_id, skill)
);
CREATE INDEX IF NOT EXISTS idx_ps_skill ON posting_skills(skill);

CREATE TABLE IF NOT EXISTS watchlists (
    name        TEXT PRIMARY KEY,
    query       TEXT,      -- words that must appear in title or description
    skills      TEXT,      -- comma separated, any match counts
    states      TEXT,      -- comma separated, empty means anywhere in the US
    remote_ok   INTEGER DEFAULT 1,
    max_years   REAL DEFAULT 4,
    sponsorship TEXT DEFAULT '',   -- '' any | 'open' not ruled out | yes/no/clearance
    active      INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS alerts_sent (
    posting_id  TEXT NOT NULL,
    watchlist   TEXT NOT NULL,
    sent_at     TEXT,
    PRIMARY KEY (posting_id, watchlist)
);

-- Cached Claude output so we never pay twice for the same question.
CREATE TABLE IF NOT EXISTS themes (
    key         TEXT PRIMARY KEY,   -- e.g. "company:greenhouse:stripe:2026-09"
    kind        TEXT,
    subject     TEXT,
    payload     TEXT,               -- JSON
    built_at    TEXT,
    input_hash  TEXT
);

-- A daily record of what was actually open.
--
-- The backfill from `first_published` only ever sees jobs that are still live,
-- so older months look artificially thin: a role posted in March and filled in
-- April has vanished from the board. These snapshots are the fix. They start
-- empty and build a true history from the first day the scheduler runs.
CREATE TABLE IF NOT EXISTS snapshots (
    day         TEXT NOT NULL,
    kind        TEXT NOT NULL,    -- 'skill' | 'metro' | 'company' | 'all'
    name        TEXT NOT NULL,
    open_count  INTEGER,
    total_open  INTEGER,
    PRIMARY KEY (day, kind, name)
);
CREATE INDEX IF NOT EXISTS idx_snap ON snapshots(kind, name, day);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Columns added after the first release. SQLite's CREATE TABLE IF NOT EXISTS
# leaves an existing table alone, so new columns have to be added by hand.
MIGRATIONS: list[tuple[str, str, str]] = [
    ("companies", "sector", "TEXT"),
    ("postings", "sector", "TEXT"),
    # 1 when we hold the real job description. Aggregated listings (the GitHub
    # new-grad boards) carry a title and a link but no description, so they can
    # be alerted on and listed but must stay out of the skill and sector maths.
    ("postings", "has_content", "INTEGER DEFAULT 0"),
    # "yes" | "no" | "clearance" | "unknown", plus the sentence behind the call.
    ("postings", "sponsorship", "TEXT"),
    ("postings", "sponsorship_note", "TEXT"),
    # Where a listing points when it links to an applicant system we also read
    # directly, so the two copies can be collapsed into one.
    ("postings", "ref_ats", "TEXT"),
    ("postings", "ref_external_id", "TEXT"),
    # "" = any, "open" = anything not explicitly ruled out, or an exact status.
    ("watchlists", "sponsorship", "TEXT DEFAULT ''"),
]


# Indexes that depend on a migrated column, so they run after the migration
# rather than inside SCHEMA - on an existing database the column is not there
# yet when the schema script executes.
POST_MIGRATION = """
CREATE INDEX IF NOT EXISTS idx_postings_sector  ON postings(sector, first_published);
CREATE INDEX IF NOT EXISTS idx_postings_content ON postings(has_content, eligible, first_published);
CREATE INDEX IF NOT EXISTS idx_postings_ref     ON postings(ref_ats, ref_external_id);
CREATE INDEX IF NOT EXISTS idx_postings_extid   ON postings(ats, external_id);
CREATE INDEX IF NOT EXISTS idx_postings_sponsor ON postings(sponsorship);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, coltype in MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # table not created yet; SCHEMA will include the column
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.executescript(POST_MIGRATION)


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
