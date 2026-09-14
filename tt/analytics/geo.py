"""Where early-career software demand is moving.

A note on what this does and does not measure. Tracking individual people
moving between companies would mean scraping profile data, which this project
does not do. What it measures instead is where the jobs are: how many
early-career software roles each US metro opened, month over month. For someone
deciding which city to aim at, that is the more useful number anyway.
"""
from __future__ import annotations

from datetime import date, timedelta

DAY = "substr(first_published,1,10)"
MONTH = "substr(first_published,1,7)"
ELIGIBLE = "eligible=1 AND has_content=1 AND first_published IS NOT NULL"


def _window(days: int) -> tuple[str, str]:
    today = date.today()
    return (today - timedelta(days=days)).isoformat(), today.isoformat()


def metros(conn, window_days: int = 30, limit: int = 25) -> list[dict]:
    """Metro leaderboard with movement against the previous period."""
    start, end = _window(window_days)
    prev_start = (date.fromisoformat(start) - timedelta(days=window_days)).isoformat()
    prev_end = (date.fromisoformat(start) - timedelta(days=1)).isoformat()

    def counts(a: str, b: str) -> dict[str, int]:
        rows = conn.execute(
            f"""SELECT COALESCE(NULLIF(metro,''),'Unspecified') m, COUNT(*) n
                FROM postings WHERE {ELIGIBLE} AND {DAY} >= ? AND {DAY} <= ?
                GROUP BY m""",
            (a, b),
        ).fetchall()
        return {r["m"]: r["n"] for r in rows}

    now, prev = counts(start, end), counts(prev_start, prev_end)
    now_total = sum(now.values()) or 1
    prev_total = sum(prev.values()) or 1

    out = []
    for metro, count in now.items():
        before = prev.get(metro, 0)
        share = count / now_total * 100
        prev_share = before / prev_total * 100
        # Headline movement is measured on share, not raw count. Raw counts
        # drift upward on their own because older postings have been filled and
        # no longer appear on the boards we read.
        if prev_share:
            change = (share - prev_share) / prev_share * 100
        else:
            change = 100.0 if count else 0.0
        out.append({
            "metro": metro,
            "postings": count,
            "prev_postings": before,
            "share": round(share, 1),
            "share_change": round(share - prev_share, 1),
            "change": round(change, 1),
            "count_change": round((count - before) / before * 100, 1) if before else None,
        })
    out.sort(key=lambda r: r["postings"], reverse=True)
    return out[:limit]


def metro_series(conn, metro: str | None = None, months: int = 12) -> list[dict]:
    start = (date.today() - timedelta(days=months * 31)).isoformat()[:7]
    if metro:
        rows = conn.execute(
            f"""SELECT {MONTH} m, COUNT(*) n FROM postings
                WHERE {ELIGIBLE} AND metro = ? AND {MONTH} >= ?
                GROUP BY m ORDER BY m""",
            (metro, start),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""SELECT {MONTH} m, COUNT(*) n FROM postings
                WHERE {ELIGIBLE} AND {MONTH} >= ? GROUP BY m ORDER BY m""",
            (start,),
        ).fetchall()
    return [{"month": r["m"], "postings": r["n"]} for r in rows]


def states(conn, window_days: int = 90) -> list[dict]:
    start, end = _window(window_days)
    rows = conn.execute(
        f"""SELECT state, COUNT(*) n FROM postings
            WHERE {ELIGIBLE} AND state != '' AND {DAY} >= ? AND {DAY} <= ?
            GROUP BY state ORDER BY n DESC""",
        (start, end),
    ).fetchall()
    return [{"state": r["state"], "postings": r["n"]} for r in rows]


def remote_trend(conn, months: int = 12) -> list[dict]:
    """Share of early-career software roles that are remote, by month."""
    start = (date.today() - timedelta(days=months * 31)).isoformat()[:7]
    rows = conn.execute(
        f"""SELECT {MONTH} m, COUNT(*) total, SUM(remote) remote
            FROM postings WHERE {ELIGIBLE} AND {MONTH} >= ?
            GROUP BY m ORDER BY m""",
        (start,),
    ).fetchall()
    return [
        {
            "month": r["m"],
            "total": r["total"],
            "remote": r["remote"] or 0,
            "share": round((r["remote"] or 0) / r["total"] * 100, 1) if r["total"] else 0,
        }
        for r in rows
    ]


def company_flow(conn, window_days: int = 30, limit: int = 20) -> dict:
    """Which companies are opening more early-career roles, and which fewer.

    This is the closest honest read on "where talent is heading": a company
    that tripled its junior openings is building a team, and one that stopped
    posting has pulled back.
    """
    start, end = _window(window_days)
    prev_start = (date.fromisoformat(start) - timedelta(days=window_days)).isoformat()
    prev_end = (date.fromisoformat(start) - timedelta(days=1)).isoformat()

    def counts(a: str, b: str) -> dict[str, int]:
        rows = conn.execute(
            f"""SELECT company_name c, COUNT(*) n FROM postings
                WHERE {ELIGIBLE} AND {DAY} >= ? AND {DAY} <= ? GROUP BY c""",
            (a, b),
        ).fetchall()
        return {r["c"]: r["n"] for r in rows}

    now, prev = counts(start, end), counts(prev_start, prev_end)
    rows = []
    for company in set(now) | set(prev):
        a, b = now.get(company, 0), prev.get(company, 0)
        rows.append({
            "company": company,
            "postings": a,
            "prev_postings": b,
            "delta": a - b,
            "change": round((a - b) / b * 100, 1) if b else (100.0 if a else 0.0),
        })

    growing = sorted(rows, key=lambda r: r["delta"], reverse=True)[:limit]
    shrinking = sorted([r for r in rows if r["delta"] < 0], key=lambda r: r["delta"])[:limit]
    return {"growing": growing, "shrinking": shrinking}


def pay_by_metro(conn, window_days: int = 180, min_samples: int = 3) -> list[dict]:
    start, end = _window(window_days)
    rows = conn.execute(
        f"""SELECT metro, COUNT(*) n, AVG(salary_min) lo, AVG(salary_max) hi
            FROM postings
            WHERE {ELIGIBLE} AND salary_min IS NOT NULL AND metro != ''
              AND {DAY} >= ? AND {DAY} <= ?
            GROUP BY metro HAVING n >= ? ORDER BY hi DESC""",
        (start, end, min_samples),
    ).fetchall()
    return [
        {
            "metro": r["metro"],
            "samples": r["n"],
            "low": int(r["lo"]),
            "high": int(r["hi"]),
            "mid": int((r["lo"] + r["hi"]) / 2),
        }
        for r in rows
    ]
