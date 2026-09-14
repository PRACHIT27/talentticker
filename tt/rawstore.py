"""A fetch cache shared by every profile.

Four of the six readers - Greenhouse, Ashby, Lever and Amazon - list an entire
board and filter locally. That means two profiles running against the same
registry issue byte-identical requests: measured across the engineering and
product runs, 237 boards were pulled twice and 31,230 postings fetched twice for
no benefit to anyone, least of all the companies serving them.

Workday and Eightfold are different. They will not list everything, so the
search terms come from the profile and the responses genuinely differ. Those
are not cached.

The cache is deliberately dumb. It stores a posting exactly as the board
returned it, with no interpretation: no eligibility, no skills, no seniority.
All of that is profile-specific and stays in each profile's own database. This
file only answers "have we already asked this board today, and what did it
say".
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from . import config
from .sources import RawPosting

# Readers whose response does not depend on the profile.
CACHEABLE = {"greenhouse", "ashby", "lever", "amazon", "jobboard"}

PATH = Path(config.ROOT) / "var" / "fetchcache.db"

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS fetches (
    company_slug TEXT PRIMARY KEY,
    fetched_at   TEXT NOT NULL,
    payload      TEXT NOT NULL,   -- JSON list of postings as the board sent them
    count        INTEGER
);
"""


@contextmanager
def _session() -> Iterator[sqlite3.Connection]:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def is_cacheable(ats: str) -> bool:
    """Workday and Eightfold answer differently per profile, so they are not."""
    return ats in CACHEABLE


def key(company_slug: str, board_token: str) -> str:
    """Cache key.

    It has to include the board token, not just the company. A profile can
    override the token - Amazon's is a job category - and keying on the company
    alone served the product profile the engineering profile's cached software
    postings, silently and with no error.
    """
    digest = hashlib.sha1(board_token.encode("utf-8")).hexdigest()[:12]
    return f"{company_slug}#{digest}"


def load(company_slug: str, board_token: str, max_age_minutes: int) -> list[RawPosting] | None:
    """Postings from a recent fetch, or None if there is nothing fresh enough."""
    if max_age_minutes <= 0:
        return None
    with _session() as conn:
        row = conn.execute(
            "SELECT fetched_at, payload FROM fetches WHERE company_slug=?",
            (key(company_slug, board_token),),
        ).fetchone()
    if not row:
        return None
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
    except ValueError:
        return None
    if datetime.now(timezone.utc) - fetched > timedelta(minutes=max_age_minutes):
        return None
    try:
        raw = json.loads(row["payload"])
    except json.JSONDecodeError:
        return None
    return [RawPosting(**item) for item in raw]


def save(company_slug: str, board_token: str, postings: list[RawPosting]) -> None:
    payload = json.dumps([
        {
            "ats": p.ats, "board_token": p.board_token, "external_id": p.external_id,
            "title": p.title, "url": p.url, "location_raw": p.location_raw,
            "content": p.content, "department": p.department, "team": p.team,
            "first_published": p.first_published, "updated_at": p.updated_at,
            "salary_min": p.salary_min, "salary_max": p.salary_max,
            "remote": p.remote, "company_name": p.company_name,
        }
        for p in postings
    ])
    with _session() as conn:
        conn.execute(
            "INSERT INTO fetches (company_slug, fetched_at, payload, count) "
            "VALUES (?,?,?,?) ON CONFLICT(company_slug) DO UPDATE SET "
            "fetched_at=excluded.fetched_at, payload=excluded.payload, "
            "count=excluded.count",
            (key(company_slug, board_token),
             datetime.now(timezone.utc).isoformat(timespec="seconds"),
             payload, len(postings)),
        )


def stats() -> dict:
    if not PATH.exists():
        return {"boards": 0, "postings": 0, "size_mb": 0.0}
    with _session() as conn:
        row = conn.execute("SELECT COUNT(*) b, COALESCE(SUM(count),0) n FROM fetches").fetchone()
    return {
        "boards": row["b"],
        "postings": row["n"],
        "size_mb": round(PATH.stat().st_size / 1_048_576, 1),
    }


def clear() -> None:
    with _session() as conn:
        conn.execute("DELETE FROM fetches")
