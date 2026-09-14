"""The numbers behind the skills ticker.

A skill's "price" is the share of early-career software postings that mention
it. Share rather than raw count, so that a quiet hiring month does not look
like every skill suddenly falling out of favour.

Everything is measured against `first_published`, the date the company actually
put the job up. Greenhouse gives us that going back more than a year, which is
why the charts have history from the very first run.
"""
from __future__ import annotations

from datetime import date, timedelta

# Dates are stored as ISO strings; the first ten characters are the day.
DAY = "substr(p.first_published,1,10)"
MONTH = "substr(p.first_published,1,7)"

# has_content keeps aggregated listings (title + link, no description) out of
# the share maths. Counting them would inflate every denominator while never
# contributing a skill, quietly dragging every percentage down.
BASE = ("FROM postings p WHERE p.eligible=1 AND p.has_content=1 "
        "AND p.first_published IS NOT NULL")


def _window(days: int) -> tuple[str, str]:
    today = date.today()
    return (today - timedelta(days=days)).isoformat(), today.isoformat()


def total_postings(conn, start: str, end: str) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) n {BASE} AND {DAY} >= ? AND {DAY} <= ?", (start, end)
    ).fetchone()
    return row["n"] or 0


def _counts(conn, start: str, end: str) -> dict[str, int]:
    rows = conn.execute(
        f"""
        SELECT s.skill, COUNT(DISTINCT p.id) n
        FROM posting_skills s JOIN postings p ON p.id = s.posting_id
        WHERE p.eligible=1 AND p.has_content=1 AND p.first_published IS NOT NULL
          AND {DAY} >= ? AND {DAY} <= ?
        GROUP BY s.skill
        """,
        (start, end),
    ).fetchall()
    return {r["skill"]: r["n"] for r in rows}


def board(conn, window_days: int = 30, min_postings: int = 3) -> list[dict]:
    """One row per skill: where it stands now and how it has moved.

    The comparison period is the window immediately before this one, so a
    30-day view compares the last 30 days against the 30 before that.
    """
    start, end = _window(window_days)
    prev_start = (date.fromisoformat(start) - timedelta(days=window_days)).isoformat()
    prev_end = (date.fromisoformat(start) - timedelta(days=1)).isoformat()

    now_counts = _counts(conn, start, end)
    prev_counts = _counts(conn, prev_start, prev_end)
    now_total = total_postings(conn, start, end)
    prev_total = total_postings(conn, prev_start, prev_end)

    rows: list[dict] = []
    for skill, count in now_counts.items():
        if count < min_postings:
            continue
        share = count / now_total if now_total else 0.0
        prev_count = prev_counts.get(skill, 0)
        prev_share = prev_count / prev_total if prev_total else 0.0

        if prev_share > 0:
            change = (share - prev_share) / prev_share * 100
        elif share > 0:
            change = 100.0  # brand new; treat as a full point of growth
        else:
            change = 0.0

        rows.append({
            "skill": skill,
            "postings": count,
            "share": round(share * 100, 2),
            "prev_postings": prev_count,
            "prev_share": round(prev_share * 100, 2),
            "change": round(change, 1),
            "is_new": prev_count == 0,
        })

    rows.sort(key=lambda r: r["postings"], reverse=True)
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank

    # Where each skill sat last period, so the dashboard can show rank moves.
    prev_sorted = sorted(prev_counts.items(), key=lambda kv: kv[1], reverse=True)
    prev_rank = {skill: i for i, (skill, _) in enumerate(prev_sorted, 1)}
    for row in rows:
        old = prev_rank.get(row["skill"])
        row["rank_change"] = (old - row["rank"]) if old else None
    return rows


def movers(conn, window_days: int = 30, limit: int = 10, min_postings: int = 5) -> dict:
    """Biggest risers and fallers, plus the emerging list.

    "Emerging" deliberately uses a lower floor: a skill going from 2 postings
    to 14 is the signal worth catching early, and a raw-count ranking would
    bury it under the languages everybody lists.
    """
    rows = board(conn, window_days, min_postings=1)
    solid = [r for r in rows if r["postings"] >= min_postings]

    gainers = sorted(
        [r for r in solid if r["change"] > 0], key=lambda r: r["change"], reverse=True
    )[:limit]
    losers = sorted(
        [r for r in solid if r["change"] < 0], key=lambda r: r["change"]
    )[:limit]

    emerging = sorted(
        [
            r for r in rows
            if r["postings"] >= 3
            and r["share"] < 12
            and (r["is_new"] or r["change"] >= 40)
        ],
        key=lambda r: (r["change"], r["postings"]),
        reverse=True,
    )[:limit]

    return {"gainers": gainers, "losers": losers, "emerging": emerging}


def series(conn, skill: str, months: int = 12) -> list[dict]:
    """Monthly share for one skill, for the sparkline and detail chart."""
    start = (date.today() - timedelta(days=months * 31)).isoformat()[:7]
    totals = {
        r["m"]: r["n"]
        for r in conn.execute(
            f"SELECT {MONTH} m, COUNT(*) n {BASE} AND {MONTH} >= ? GROUP BY m",
            (start,),
        ).fetchall()
    }
    hits = {
        r["m"]: r["n"]
        for r in conn.execute(
            f"""
            SELECT {MONTH} m, COUNT(DISTINCT p.id) n
            FROM posting_skills s JOIN postings p ON p.id = s.posting_id
            WHERE p.eligible=1 AND p.has_content=1 AND s.skill = ? AND {MONTH} >= ?
            GROUP BY m
            """,
            (skill, start),
        ).fetchall()
    }
    out = []
    for month in sorted(totals):
        total = totals[month]
        count = hits.get(month, 0)
        out.append({
            "month": month,
            "postings": count,
            "total": total,
            "share": round(count / total * 100, 2) if total else 0.0,
        })
    return out


def series_bulk(conn, months: int = 12) -> dict[str, list[dict]]:
    """Monthly share for every skill at once.

    The dashboard draws a sparkline on each row. Fetching those one at a time
    meant forty round trips and a page that visibly stalled, so this does the
    whole grid in two queries.
    """
    start = (date.today() - timedelta(days=months * 31)).isoformat()[:7]
    totals = {
        r["m"]: r["n"]
        for r in conn.execute(
            f"SELECT {MONTH} m, COUNT(*) n {BASE} AND {MONTH} >= ? GROUP BY m",
            (start,),
        ).fetchall()
    }
    rows = conn.execute(
        f"""
        SELECT s.skill, {MONTH} m, COUNT(DISTINCT p.id) n
        FROM posting_skills s JOIN postings p ON p.id = s.posting_id
        WHERE p.eligible=1 AND p.has_content=1 AND {MONTH} >= ?
        GROUP BY s.skill, m
        """,
        (start,),
    ).fetchall()

    hits: dict[str, dict[str, int]] = {}
    for row in rows:
        hits.setdefault(row["skill"], {})[row["m"]] = row["n"]

    months_sorted = sorted(totals)
    out: dict[str, list[dict]] = {}
    for skill, by_month in hits.items():
        out[skill] = [
            {
                "month": m,
                "share": round(by_month.get(m, 0) / totals[m] * 100, 2) if totals[m] else 0.0,
            }
            for m in months_sorted
        ]
    return out


def co_occurring(conn, skill: str, window_days: int = 90, limit: int = 12) -> list[dict]:
    """Skills that show up alongside this one - "also asked for"."""
    start, end = _window(window_days)
    rows = conn.execute(
        f"""
        SELECT other.skill, COUNT(*) n
        FROM posting_skills mine
        JOIN posting_skills other ON other.posting_id = mine.posting_id
        JOIN postings p ON p.id = mine.posting_id
        WHERE mine.skill = ? AND other.skill != ?
          AND p.eligible=1 AND {DAY} >= ? AND {DAY} <= ?
        GROUP BY other.skill ORDER BY n DESC LIMIT ?
        """,
        (skill, skill, start, end, limit),
    ).fetchall()
    base = conn.execute(
        f"""
        SELECT COUNT(*) n FROM posting_skills s JOIN postings p ON p.id=s.posting_id
        WHERE s.skill=? AND p.eligible=1 AND {DAY} >= ? AND {DAY} <= ?
        """,
        (skill, start, end),
    ).fetchone()["n"] or 1
    return [
        {"skill": r["skill"], "postings": r["n"], "share": round(r["n"] / base * 100, 1)}
        for r in rows
    ]


def skill_detail(conn, skill: str, window_days: int = 90) -> dict:
    """Everything the detail page needs about one skill."""
    start, end = _window(window_days)
    args = (skill, start, end)

    companies = conn.execute(
        f"""
        SELECT p.company_name name, COUNT(*) n
        FROM posting_skills s JOIN postings p ON p.id=s.posting_id
        WHERE s.skill=? AND p.eligible=1 AND {DAY} >= ? AND {DAY} <= ?
        GROUP BY p.company_name ORDER BY n DESC LIMIT 12
        """,
        args,
    ).fetchall()

    metros = conn.execute(
        f"""
        SELECT COALESCE(NULLIF(p.metro,''),'Unspecified') metro, COUNT(*) n
        FROM posting_skills s JOIN postings p ON p.id=s.posting_id
        WHERE s.skill=? AND p.eligible=1 AND {DAY} >= ? AND {DAY} <= ?
        GROUP BY metro ORDER BY n DESC LIMIT 10
        """,
        args,
    ).fetchall()

    pay = conn.execute(
        f"""
        SELECT COUNT(*) n, AVG(p.salary_min) lo, AVG(p.salary_max) hi
        FROM posting_skills s JOIN postings p ON p.id=s.posting_id
        WHERE s.skill=? AND p.eligible=1 AND p.salary_min IS NOT NULL
          AND {DAY} >= ? AND {DAY} <= ?
        """,
        args,
    ).fetchone()

    openings = conn.execute(
        f"""
        SELECT p.id, p.title, p.company_name, p.metro, p.url, p.first_published,
               p.salary_min, p.salary_max, p.yoe_min
        FROM posting_skills s JOIN postings p ON p.id=s.posting_id
        WHERE s.skill=? AND p.eligible=1 AND p.closed_at IS NULL
          AND {DAY} >= ? AND {DAY} <= ?
        ORDER BY p.first_published DESC LIMIT 40
        """,
        args,
    ).fetchall()

    return {
        "skill": skill,
        "series": series(conn, skill),
        "companies": [dict(r) for r in companies],
        "metros": [dict(r) for r in metros],
        "co_occurring": co_occurring(conn, skill, window_days),
        "pay": {
            "samples": pay["n"] or 0,
            "low": int(pay["lo"]) if pay["lo"] else None,
            "high": int(pay["hi"]) if pay["hi"] else None,
        },
        "openings": [dict(r) for r in openings],
    }


def summary(conn) -> dict:
    """Headline numbers for the top of the dashboard."""
    start30, end = _window(30)
    start7, _ = _window(7)
    row = conn.execute(
        f"""
        SELECT
          (SELECT COUNT(*) FROM postings WHERE eligible=1) total,
          (SELECT COUNT(*) FROM postings WHERE eligible=1 AND closed_at IS NULL) open,
          (SELECT COUNT(*) FROM postings WHERE eligible=1 AND has_content=1) analysed,
          (SELECT COUNT(*) {BASE} AND {DAY} >= '{start30}') last30,
          (SELECT COUNT(*) {BASE} AND {DAY} >= '{start7}') last7,
          (SELECT COUNT(*) FROM postings) scanned,
          (SELECT COUNT(*) FROM companies WHERE active=1) companies
        """
    ).fetchone()
    return dict(row)
