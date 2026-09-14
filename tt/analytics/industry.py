"""Sector analytics - the same questions asked per industry.

Which industries are hiring early-career engineers, which are growing, what
they pay, and which skills each one actually wants. A backend engineer aiming
at healthcare needs a different list from one aiming at AI infrastructure, and
this is where that difference shows up.
"""
from __future__ import annotations

from datetime import date, timedelta

DAY = "substr(first_published,1,10)"
MONTH = "substr(first_published,1,7)"
# Sector figures lean on the description too, so they use the same filter
# as the ticker.
ELIGIBLE = "eligible=1 AND has_content=1 AND first_published IS NOT NULL"


def _window(days: int) -> tuple[str, str]:
    today = date.today()
    return (today - timedelta(days=days)).isoformat(), today.isoformat()


def board(conn, window_days: int = 30) -> list[dict]:
    """One row per sector: volume, share, movement and pay."""
    start, end = _window(window_days)
    prev_start = (date.fromisoformat(start) - timedelta(days=window_days)).isoformat()
    prev_end = (date.fromisoformat(start) - timedelta(days=1)).isoformat()

    def counts(a: str, b: str) -> dict[str, int]:
        rows = conn.execute(
            f"""SELECT COALESCE(NULLIF(sector,''),'Unclassified') s, COUNT(*) n
                FROM postings WHERE {ELIGIBLE} AND {DAY} >= ? AND {DAY} <= ?
                GROUP BY s""",
            (a, b),
        ).fetchall()
        return {r["s"]: r["n"] for r in rows}

    now, prev = counts(start, end), counts(prev_start, prev_end)
    now_total = sum(now.values()) or 1
    prev_total = sum(prev.values()) or 1

    pay = {
        r["s"]: r
        for r in conn.execute(
            f"""SELECT COALESCE(NULLIF(sector,''),'Unclassified') s, COUNT(*) n,
                       AVG(salary_min) lo, AVG(salary_max) hi
                FROM postings
                WHERE eligible=1 AND has_content=1 AND salary_min IS NOT NULL
                  AND {DAY} >= ? GROUP BY s""",
            ((date.today() - timedelta(days=180)).isoformat(),),
        ).fetchall()
    }

    companies = {
        r["s"]: r["n"]
        for r in conn.execute(
            f"""SELECT COALESCE(NULLIF(sector,''),'Unclassified') s,
                       COUNT(DISTINCT company_name) n
                FROM postings WHERE {ELIGIBLE} AND {DAY} >= ? GROUP BY s""",
            (start,),
        ).fetchall()
    }

    out = []
    for sector, count in now.items():
        before = prev.get(sector, 0)
        share = count / now_total * 100
        prev_share = before / prev_total * 100
        # Movement on share, not raw count - older postings have been filled and
        # no longer appear on the boards we read, which inflates raw growth.
        change = ((share - prev_share) / prev_share * 100) if prev_share else (
            100.0 if count else 0.0
        )
        money = pay.get(sector)
        out.append({
            "sector": sector,
            "postings": count,
            "prev_postings": before,
            "companies": companies.get(sector, 0),
            "share": round(share, 1),
            "share_change": round(share - prev_share, 1),
            "change": round(change, 1),
            "pay_low": int(money["lo"]) if money and money["lo"] else None,
            "pay_high": int(money["hi"]) if money and money["hi"] else None,
            "pay_samples": money["n"] if money else 0,
        })
    out.sort(key=lambda r: r["postings"], reverse=True)
    return out


def series(conn, sector: str, months: int = 12) -> list[dict]:
    """Monthly share of the market for one sector."""
    start = (date.today() - timedelta(days=months * 31)).isoformat()[:7]
    totals = {
        r["m"]: r["n"]
        for r in conn.execute(
            f"SELECT {MONTH} m, COUNT(*) n FROM postings WHERE {ELIGIBLE} "
            f"AND {MONTH} >= ? GROUP BY m",
            (start,),
        ).fetchall()
    }
    hits = {
        r["m"]: r["n"]
        for r in conn.execute(
            f"""SELECT {MONTH} m, COUNT(*) n FROM postings
                WHERE {ELIGIBLE} AND sector = ? AND {MONTH} >= ? GROUP BY m""",
            (sector, start),
        ).fetchall()
    }
    return [
        {
            "month": m,
            "postings": hits.get(m, 0),
            "share": round(hits.get(m, 0) / totals[m] * 100, 2) if totals[m] else 0.0,
        }
        for m in sorted(totals)
    ]


def skills_for(conn, sector: str, window_days: int = 120, limit: int = 18) -> list[dict]:
    """What this sector asks for, and how that differs from the market.

    The interesting column is `lift`: Terraform being common everywhere is not
    news, but Terraform being twice as common in one sector is.
    """
    start, end = _window(window_days)

    total = conn.execute(
        f"SELECT COUNT(*) n FROM postings WHERE {ELIGIBLE} AND sector=? "
        f"AND {DAY} >= ? AND {DAY} <= ?",
        (sector, start, end),
    ).fetchone()["n"] or 1
    market_total = conn.execute(
        f"SELECT COUNT(*) n FROM postings WHERE {ELIGIBLE} AND {DAY} >= ? AND {DAY} <= ?",
        (start, end),
    ).fetchone()["n"] or 1

    rows = conn.execute(
        f"""SELECT s.skill, COUNT(DISTINCT p.id) n
            FROM posting_skills s JOIN postings p ON p.id=s.posting_id
            WHERE p.eligible=1 AND p.has_content=1 AND p.sector=?
              AND substr(p.first_published,1,10) >= ?
              AND substr(p.first_published,1,10) <= ?
            GROUP BY s.skill ORDER BY n DESC LIMIT ?""",
        (sector, start, end, limit),
    ).fetchall()

    market = {
        r["skill"]: r["n"]
        for r in conn.execute(
            f"""SELECT s.skill, COUNT(DISTINCT p.id) n
                FROM posting_skills s JOIN postings p ON p.id=s.posting_id
                WHERE p.eligible=1 AND p.has_content=1 AND substr(p.first_published,1,10) >= ?
                  AND substr(p.first_published,1,10) <= ?
                GROUP BY s.skill""",
            (start, end),
        ).fetchall()
    }

    out = []
    for row in rows:
        share = row["n"] / total * 100
        market_share = market.get(row["skill"], 0) / market_total * 100
        out.append({
            "skill": row["skill"],
            "postings": row["n"],
            "share": round(share, 1),
            "market_share": round(market_share, 1),
            "lift": round(share / market_share, 2) if market_share else None,
        })
    return out


def detail(conn, sector: str, window_days: int = 120) -> dict:
    start, end = _window(window_days)
    companies = conn.execute(
        f"""SELECT company_name name, COUNT(*) n FROM postings
            WHERE {ELIGIBLE} AND sector=? AND {DAY} >= ? AND {DAY} <= ?
            GROUP BY name ORDER BY n DESC LIMIT 12""",
        (sector, start, end),
    ).fetchall()
    metros = conn.execute(
        f"""SELECT COALESCE(NULLIF(metro,''),'Unspecified') metro, COUNT(*) n
            FROM postings WHERE {ELIGIBLE} AND sector=? AND {DAY} >= ? AND {DAY} <= ?
            GROUP BY metro ORDER BY n DESC LIMIT 10""",
        (sector, start, end),
    ).fetchall()
    openings = conn.execute(
        f"""SELECT id, title, company_name, metro, url, first_published,
                   salary_min, salary_max, yoe_min, remote
            FROM postings
            WHERE {ELIGIBLE} AND sector=? AND closed_at IS NULL
              AND {DAY} >= ? AND {DAY} <= ?
            ORDER BY first_published DESC LIMIT 40""",
        (sector, start, end),
    ).fetchall()
    return {
        "sector": sector,
        "series": series(conn, sector),
        "skills": skills_for(conn, sector),
        "companies": [dict(r) for r in companies],
        "metros": [dict(r) for r in metros],
        "openings": [dict(r) for r in openings],
    }


def skill_by_sector(conn, skill: str, window_days: int = 120) -> list[dict]:
    """Which sectors want a given skill. Powers the skill drawer."""
    start, end = _window(window_days)
    totals = {
        r["s"]: r["n"]
        for r in conn.execute(
            f"""SELECT COALESCE(NULLIF(sector,''),'Unclassified') s, COUNT(*) n
                FROM postings WHERE {ELIGIBLE} AND {DAY} >= ? AND {DAY} <= ?
                GROUP BY s""",
            (start, end),
        ).fetchall()
    }
    rows = conn.execute(
        f"""SELECT COALESCE(NULLIF(p.sector,''),'Unclassified') s, COUNT(DISTINCT p.id) n
            FROM posting_skills ps JOIN postings p ON p.id=ps.posting_id
            WHERE ps.skill=? AND p.eligible=1 AND p.has_content=1
              AND substr(p.first_published,1,10) >= ?
              AND substr(p.first_published,1,10) <= ?
            GROUP BY s ORDER BY n DESC""",
        (skill, start, end),
    ).fetchall()
    return [
        {
            "sector": r["s"],
            "postings": r["n"],
            "share": round(r["n"] / totals[r["s"]] * 100, 1) if totals.get(r["s"]) else 0.0,
        }
        for r in rows
    ]
