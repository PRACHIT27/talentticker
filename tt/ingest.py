"""Pull job boards, work out what each posting means, and store it.

Two modes:

  refresh()  - full pull with descriptions. Slow, run nightly. Also notices
               jobs that vanished from a board and marks them closed.
  poll()     - cheap check for job IDs we have not seen. Fast, run every few
               minutes. Only the genuinely new jobs get their description
               fetched, which is what makes 5-minute alerts affordable.
"""
from __future__ import annotations

import concurrent.futures as futures
import logging
import re
from datetime import datetime, timezone
from typing import Iterable

import yaml

import os

from . import config, db, rawstore
from .extract import (
    clean, locations, salary, sectors, seniority, skills, sponsorship,
)
from .sources import BoardError, RawPosting, get_source, make_client, resolve

log = logging.getLogger("tt.ingest")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# company registry
# --------------------------------------------------------------------------


def load_companies() -> list[dict]:
    if not config.COMPANIES_FILE.exists():
        return []
    data = yaml.safe_load(config.COMPANIES_FILE.read_text(encoding="utf-8")) or {}
    return data.get("companies", [])


def sync_companies() -> int:
    """Copy the YAML registry into the database, keeping existing state."""
    rows = load_companies()
    with db.session() as conn:
        for entry in rows:
            ats = str(entry.get("ats", "")).strip()
            token = str(entry.get("token", "")).strip()
            if not ats or not token:
                continue
            slug = f"{ats}:{token}"
            conn.execute(
                """
                INSERT INTO companies (slug, ats, board_token, name, sector, tier, active)
                VALUES (?,?,?,?,?,?,1)
                ON CONFLICT(slug) DO UPDATE SET
                    name = COALESCE(excluded.name, companies.name),
                    sector = excluded.sector,
                    tier = excluded.tier
                """,
                (slug, ats, token, entry.get("name") or token,
                 entry.get("sector") or "", int(entry.get("tier", 2))),
            )
    return len(rows)


def companies(conn, tier: int | None = None, include_inactive: bool = False) -> list[dict]:
    sql = "SELECT * FROM companies WHERE 1=1"
    args: list = []
    if not include_inactive:
        sql += " AND active=1"
    if tier is not None:
        sql += " AND tier<=?"
        args.append(tier)
    sql += " ORDER BY tier, slug"
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    # Skip readers the active profile has no use for.
    skip = set(config.PROFILE.exclude_sources)
    if skip:
        rows = [r for r in rows if r["ats"] not in skip]
    # A profile may need a different board token - see Profile.source_tokens.
    overrides = config.PROFILE.source_tokens
    if overrides:
        for row in rows:
            if row["ats"] in overrides:
                row["board_token"] = overrides[row["ats"]]
    return rows


# --------------------------------------------------------------------------
# interpreting one posting
# --------------------------------------------------------------------------


def analyse(post: RawPosting) -> dict:
    """Work out whether we care about this job, and everything we can read off it."""
    place = locations.parse_with_fallback(post.location_raw, post.content, post.remote)

    lo, hi = post.salary_min, post.salary_max
    if lo is None:
        lo, hi = salary.parse(post.content)

    # Pay is read first so it can act as a seniority signal for postings that
    # state no years of experience at all.
    verdict = seniority.classify(
        post.title, post.content, post.department, config.MAX_YEARS, salary_min=lo
    )

    # Only US roles count for this product.
    eligible = verdict.eligible and locations.is_us(place)
    reason = verdict.reason
    if verdict.eligible and not locations.is_us(place):
        reason = f"{verdict.reason}; outside the US"

    return {
        "is_swe": int(verdict.is_swe),
        "eligible": int(eligible),
        "yoe_min": verdict.yoe_min,
        "yoe_max": verdict.yoe_max,
        "level": verdict.level,
        "reason": reason,
        "metro": place.metro,
        "state": place.state,
        "country": place.country,
        "remote": int(place.remote),
        "salary_min": lo,
        "salary_max": hi,
    }


MIN_REAL_DESCRIPTION = 200


def _duplicate_of_direct_source(conn, post: RawPosting) -> tuple[bool, str, str]:
    """Is this aggregated listing a second copy of a job we already read directly?

    Returns (is duplicate, referenced ats, referenced id). The aggregated boards
    are useful for reach but they lag and carry no description, so wherever we
    hold the company's own posting that copy wins.
    """
    origin = resolve(post.url)
    if not origin:
        return False, "", ""

    if origin.external_id:
        existing = conn.execute(
            "SELECT 1 FROM postings WHERE ats=? AND external_id=? LIMIT 1",
            (origin.ats, origin.external_id),
        ).fetchone()
        if existing:
            return True, origin.ats, origin.external_id

    # No id match: fall back to the same company advertising the same title.
    title = re.sub(r"[^a-z0-9]+", " ", (post.title or "").lower()).strip()
    company = re.sub(r"[^a-z0-9]+", "", (post.company_name or "").lower())
    if title and company:
        row = conn.execute(
            """SELECT 1 FROM postings
               WHERE has_content=1
                 AND replace(replace(lower(company_name),' ',''),'.','') LIKE ?
                 AND lower(title) = ? LIMIT 1""",
            (f"%{company}%", (post.title or "").lower()),
        ).fetchone()
        if row:
            return True, origin.ats, origin.external_id
    return False, origin.ats, origin.external_id


def _drop_superseded_listings(conn, post: RawPosting) -> None:
    """Remove aggregated copies now that the real posting has arrived."""
    conn.execute(
        "DELETE FROM postings WHERE ats='jobboard' AND ref_ats=? AND ref_external_id=?",
        (post.ats, post.external_id),
    )


def store(conn, post: RawPosting, company_name: str, company_sector: str = "") -> bool:
    """Save a posting. Returns True if this is the first time we have seen it."""
    is_listing = post.ats == "jobboard"
    ref_ats = ref_id = ""

    if is_listing:
        duplicate, ref_ats, ref_id = _duplicate_of_direct_source(conn, post)
        if duplicate:
            return False
    else:
        _drop_superseded_listings(conn, post)

    # An aggregated board is not itself an employer: each of its rows names a
    # different company, so the row wins over the registry entry. For a direct
    # board it is the other way round, because the registry has the tidy name
    # ("Amazon") rather than whatever the posting says ("Audible, Inc. - B13").
    if is_listing:
        company_name = post.company_name or company_name

    facts = analyse(post)
    sector = sectors.resolve(company_sector, post.content, post.team, post.department)
    has_content = int(len(post.content or "") >= MIN_REAL_DESCRIPTION)
    visa = sponsorship.classify(post.content) if has_content else sponsorship.Verdict(
        "unknown", ""
    )
    existing = conn.execute(
        "SELECT id, eligible FROM postings WHERE id=?", (post.id,)
    ).fetchone()
    stamp = now_iso()

    conn.execute(
        """
        INSERT INTO postings (
            id, company_slug, company_name, sector, ats, external_id, title, url,
            department, team, location_raw, content, first_published,
            updated_at, seen_first, seen_last, closed_at,
            is_swe, yoe_min, yoe_max, level, eligible, reason,
            metro, state, country, remote, salary_min, salary_max, processed,
            has_content, sponsorship, sponsorship_note, ref_ats, ref_external_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            company_name=excluded.company_name,
            title=excluded.title, url=excluded.url, location_raw=excluded.location_raw,
            content=excluded.content, updated_at=excluded.updated_at,
            seen_last=excluded.seen_last, closed_at=NULL, sector=excluded.sector,
            is_swe=excluded.is_swe, yoe_min=excluded.yoe_min, yoe_max=excluded.yoe_max,
            level=excluded.level, eligible=excluded.eligible, reason=excluded.reason,
            metro=excluded.metro, state=excluded.state, country=excluded.country,
            remote=excluded.remote, salary_min=excluded.salary_min,
            salary_max=excluded.salary_max, processed=1,
            has_content=excluded.has_content, sponsorship=excluded.sponsorship,
            sponsorship_note=excluded.sponsorship_note,
            ref_ats=excluded.ref_ats, ref_external_id=excluded.ref_external_id
        """,
        (
            post.id, f"{post.ats}:{post.board_token}", company_name or post.company_name,
            sector, post.ats, post.external_id, post.title, post.url,
            post.department, post.team, post.location_raw, post.content,
            post.first_published or stamp, post.updated_at, stamp, stamp,
            facts["is_swe"], facts["yoe_min"], facts["yoe_max"], facts["level"],
            facts["eligible"], facts["reason"], facts["metro"], facts["state"],
            facts["country"], facts["remote"], facts["salary_min"], facts["salary_max"],
            has_content, visa.status, visa.note, ref_ats, ref_id,
        ),
    )

    conn.execute("DELETE FROM posting_skills WHERE posting_id=?", (post.id,))
    if facts["eligible"] and has_content:
        body = clean.strip_boilerplate(post.content)
        found = skills.extract(f"{post.title}\n{body}", company_name or post.company_name)
        if found:
            conn.executemany(
                "INSERT OR REPLACE INTO posting_skills (posting_id, skill, hits) VALUES (?,?,?)",
                [(post.id, name, hits) for name, hits in found.items()],
            )
    return existing is None


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------


# How long a cached board response stays usable. Long enough that a second
# profile run in the same session reuses it, short enough that a nightly
# refresh always goes out to the board for real.
CACHE_MINUTES = int(os.getenv("TT_FETCH_CACHE_MINUTES", "180"))


def _fetch_company(
    company: dict, client, use_cache: bool = True
) -> tuple[dict, list[RawPosting] | None, str]:
    """Fetch one board, reusing a recent response when there is one.

    Greenhouse, Ashby, Lever and Amazon list the whole board and we filter
    locally, so their response does not depend on the profile - two profiles
    would otherwise send identical requests and download the same tens of
    thousands of postings twice. Workday and Eightfold search by title, so
    their answers really do differ and they always go out to the network.
    """
    slug = company["slug"]
    if use_cache and rawstore.is_cacheable(company["ats"]):
        cached = rawstore.load(slug, company["board_token"], CACHE_MINUTES)
        if cached is not None:
            return company, cached, ""

    try:
        source = get_source(company["ats"], client)
        postings = source.fetch(company["board_token"])
    except (BoardError, ValueError) as exc:
        return company, None, str(exc)

    if rawstore.is_cacheable(company["ats"]):
        rawstore.save(slug, company["board_token"], postings)
    return company, postings, ""


def refresh(tier: int | None = None, limit: int | None = None,
            use_cache: bool = True) -> dict:
    """Full pull across every active company. Run nightly."""
    with db.session() as conn:
        targets = companies(conn, tier=tier)
    if limit:
        targets = targets[:limit]

    stats = {"companies": 0, "failed": 0, "postings": 0, "new": 0, "eligible": 0}
    client = make_client()

    with futures.ThreadPoolExecutor(config.FETCH_CONCURRENCY) as pool:
        results = pool.map(lambda c: _fetch_company(c, client, use_cache), targets)

        # One transaction per company, not one for the whole run. Workday has
        # to fetch a description per job, so a single board can take minutes -
        # long enough that holding one write transaction open would block the
        # dashboard and lose everything if the run were interrupted.
        for company, posts, error in results:
            with db.session() as conn:
                if posts is None:
                    stats["failed"] += 1
                    conn.execute(
                        "UPDATE companies SET last_error=?, last_polled=?, "
                        "active=CASE WHEN ?='board not found (404)' THEN 0 ELSE active END "
                        "WHERE slug=?",
                        (error, now_iso(), error, company["slug"]),
                    )
                    log.warning("%s: %s", company["slug"], error)
                    continue

                stats["companies"] += 1
                seen_ids = set()
                for post in posts:
                    seen_ids.add(post.id)
                    if store(conn, post, company.get("name", ""), company.get("sector", "")):
                        stats["new"] += 1
                    stats["postings"] += 1

                # Anything we knew about that is no longer on the board is closed.
                known = conn.execute(
                    "SELECT id FROM postings WHERE company_slug=? AND closed_at IS NULL",
                    (company["slug"],),
                ).fetchall()
                gone = [r["id"] for r in known if r["id"] not in seen_ids]
                if gone:
                    conn.executemany(
                        "UPDATE postings SET closed_at=? WHERE id=?",
                        [(now_iso(), pid) for pid in gone],
                    )

                conn.execute(
                    "UPDATE companies SET last_polled=?, last_error=NULL, job_count=? WHERE slug=?",
                    (now_iso(), len(posts), company["slug"]),
                )

                log.info(
                    "%s: %d posting(s)", company["slug"], len(posts)
                )

    with db.session() as conn:
        stats["eligible"] = conn.execute(
            "SELECT COUNT(*) c FROM postings WHERE eligible=1"
        ).fetchone()["c"]

    client.close()
    return stats


def poll(tier: int = 1) -> list[str]:
    """Look for jobs we have not seen yet. Returns the new posting IDs.

    The cheap listing endpoint is checked first, and a full description is only
    pulled when an unfamiliar ID shows up.
    """
    with db.session() as conn:
        targets = companies(conn, tier=tier)
        known: set[str] = {
            r["id"] for r in conn.execute("SELECT id FROM postings").fetchall()
        }

    client = make_client()
    new_ids: list[str] = []

    def check(company: dict) -> tuple[dict, list[RawPosting]]:
        try:
            source = get_source(company["ats"], client)
            light = source.fetch_light(company["board_token"])
            unseen = [
                ext for ext, _ in light
                if f"{company['ats']}:{company['board_token']}:{ext}" not in known
            ]
            if not unseen:
                return company, []
            # Boards are cheap to re-read in full; filter down to the new ones.
            wanted = set(unseen)
            return company, [p for p in source.fetch(company["board_token"])
                             if p.external_id in wanted]
        except (BoardError, ValueError) as exc:
            log.warning("%s: %s", company["slug"], exc)
            return company, []

    with futures.ThreadPoolExecutor(config.FETCH_CONCURRENCY) as pool:
        results = list(pool.map(check, targets))

    with db.session() as conn:
        for company, posts in results:
            for post in posts:
                if store(conn, post, company.get("name", ""), company.get("sector", "")):
                    new_ids.append(post.id)
            conn.execute(
                "UPDATE companies SET last_polled=? WHERE slug=?",
                (now_iso(), company["slug"]),
            )

    client.close()
    return new_ids


def snapshot() -> int:
    """Record what is open today, so real history builds up over time.

    Worth understanding why this exists: reading a job board only ever shows
    jobs that are still live. Backfilling from the original publish date gives
    us a useful head start, but it systematically undercounts older months,
    because anything that got filled has disappeared. These daily rows are
    unaffected by that, and after a few weeks of running they become the
    trustworthy series.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    rows: list[tuple] = []
    with db.session() as conn:
        total = conn.execute(
            "SELECT COUNT(*) n FROM postings WHERE eligible=1 AND closed_at IS NULL"
        ).fetchone()["n"]
        rows.append((today, "all", "all", total, total))

        for kind, sql in (
            (
                "skill",
                """SELECT s.skill name, COUNT(DISTINCT p.id) n
                   FROM posting_skills s JOIN postings p ON p.id=s.posting_id
                   WHERE p.eligible=1 AND p.closed_at IS NULL GROUP BY s.skill""",
            ),
            (
                "metro",
                """SELECT COALESCE(NULLIF(metro,''),'Unspecified') name, COUNT(*) n
                   FROM postings WHERE eligible=1 AND closed_at IS NULL GROUP BY name""",
            ),
            (
                "company",
                """SELECT company_name name, COUNT(*) n FROM postings
                   WHERE eligible=1 AND closed_at IS NULL GROUP BY name""",
            ),
        ):
            for row in conn.execute(sql).fetchall():
                rows.append((today, kind, row["name"], row["n"], total))

        conn.executemany(
            "INSERT INTO snapshots (day, kind, name, open_count, total_open) "
            "VALUES (?,?,?,?,?) ON CONFLICT(day, kind, name) DO UPDATE SET "
            "open_count=excluded.open_count, total_open=excluded.total_open",
            rows,
        )
    return len(rows)


def reprocess() -> int:
    """Re-run the extractors over stored postings.

    Needed whenever the taxonomy or the 0-4 filter changes, so old rows get the
    benefit of the new rules without re-fetching anything.
    """
    count = 0
    with db.session() as conn:
        company_sectors = {
            r["slug"]: (r["sector"] or "")
            for r in conn.execute("SELECT slug, sector FROM companies").fetchall()
        }
        rows = conn.execute("SELECT * FROM postings").fetchall()
        for row in rows:
            post = RawPosting(
                ats=row["ats"] or "",
                board_token=(row["company_slug"] or ":").split(":", 1)[-1],
                external_id=row["external_id"] or "",
                title=row["title"] or "",
                url=row["url"] or "",
                location_raw=row["location_raw"] or "",
                content=row["content"] or "",
                department=row["department"] or "",
                team=row["team"] or "",
                first_published=row["first_published"] or "",
                updated_at=row["updated_at"] or "",
                salary_min=row["salary_min"],
                salary_max=row["salary_max"],
                remote=bool(row["remote"]),
            )
            facts = analyse(post)
            sector = sectors.resolve(
                company_sectors.get(row["company_slug"], ""),
                row["content"] or "",
                row["team"] or "",
                row["department"] or "",
            )
            has_content = int(len(row["content"] or "") >= MIN_REAL_DESCRIPTION)
            visa = (
                sponsorship.classify(row["content"] or "")
                if has_content
                else sponsorship.Verdict("unknown", "")
            )
            conn.execute(
                """UPDATE postings SET is_swe=?, eligible=?, yoe_min=?, yoe_max=?,
                   level=?, reason=?, metro=?, state=?, country=?, remote=?,
                   salary_min=?, salary_max=?, sector=?, has_content=?,
                   sponsorship=?, sponsorship_note=? WHERE id=?""",
                (
                    facts["is_swe"], facts["eligible"], facts["yoe_min"],
                    facts["yoe_max"], facts["level"], facts["reason"],
                    facts["metro"], facts["state"], facts["country"],
                    facts["remote"], facts["salary_min"], facts["salary_max"],
                    sector, has_content, visa.status, visa.note, row["id"],
                ),
            )
            conn.execute("DELETE FROM posting_skills WHERE posting_id=?", (row["id"],))
            if facts["eligible"] and has_content:
                body = clean.strip_boilerplate(row["content"] or "")
                found = skills.extract(f"{row['title']}\n{body}", row["company_name"] or "")
                if found:
                    conn.executemany(
                        "INSERT OR REPLACE INTO posting_skills (posting_id, skill, hits) "
                        "VALUES (?,?,?)",
                        [(row["id"], n, h) for n, h in found.items()],
                    )
            count += 1
    return count


def vacuum() -> dict:
    with db.session() as conn:
        before = conn.execute(
            "SELECT SUM(LENGTH(COALESCE(content,''))) n FROM postings"
        ).fetchone()["n"] or 0
        conn.execute(
            "UPDATE postings SET content='' "
            "WHERE content != '' AND (eligible=0 OR closed_at IS NOT NULL)"
        )
        after = conn.execute(
            "SELECT SUM(LENGTH(COALESCE(content,''))) n FROM postings"
        ).fetchone()["n"] or 0
    with db.connect() as conn:
        conn.execute("VACUUM")
    return {
        "freed_mb": round((before - after) / 1_000_000, 1),
        "remaining_mb": round(after / 1_000_000, 1),
        "db_mb": round(config.DB_PATH.stat().st_size / 1_048_576, 1),
    }
