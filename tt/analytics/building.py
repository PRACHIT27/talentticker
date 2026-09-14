from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ..extract import skills
from ..extract.taxonomy import CATEGORY_LABELS, category_of
from ..sources import github

MIN_REPOS = 4


def refresh(conn, months: int = 6, min_stars: int = 25, pages: int = 6) -> dict:
    repos = github.trending(months=months, min_stars=min_stars, pages=pages)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for repo in repos:
        conn.execute(
            """INSERT INTO repos
               (full_name, description, language, topics, stars, created_at,
                pushed_at, url, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(full_name) DO UPDATE SET
                 description=excluded.description, language=excluded.language,
                 topics=excluded.topics, stars=excluded.stars,
                 pushed_at=excluded.pushed_at, fetched_at=excluded.fetched_at""",
            (repo["full_name"], repo["description"], repo["language"],
             repo["topics"], repo["stars"], repo["created_at"],
             repo["pushed_at"], repo["url"], stamp),
        )
        text = " ".join([
            repo["description"],
            repo["topics"].replace(",", " "),
            repo["language"],
        ])
        found = skills.extract(text)
        conn.execute("DELETE FROM repo_skills WHERE full_name=?", (repo["full_name"],))
        if found:
            conn.executemany(
                "INSERT OR REPLACE INTO repo_skills (full_name, skill) VALUES (?,?)",
                [(repo["full_name"], name) for name in found],
            )
    return {"repos": len(repos)}


def board(conn, months: int = 6, job_window: int = 90) -> list[dict]:
    since = (date.today() - timedelta(days=months * 30)).isoformat()
    job_since = (date.today() - timedelta(days=job_window)).isoformat()

    repo_total = conn.execute(
        "SELECT COUNT(*) n FROM repos WHERE created_at >= ?", (since,)
    ).fetchone()["n"] or 1
    job_total = conn.execute(
        """SELECT COUNT(*) n FROM postings
           WHERE eligible=1 AND has_content=1
             AND substr(first_published,1,10) >= ?""",
        (job_since,),
    ).fetchone()["n"] or 1

    repo_counts = {
        r["skill"]: r["n"]
        for r in conn.execute(
            """SELECT s.skill, COUNT(DISTINCT s.full_name) n
               FROM repo_skills s JOIN repos r ON r.full_name = s.full_name
               WHERE r.created_at >= ? GROUP BY s.skill""",
            (since,),
        ).fetchall()
    }
    job_counts = {
        r["skill"]: r["n"]
        for r in conn.execute(
            """SELECT s.skill, COUNT(DISTINCT p.id) n
               FROM posting_skills s JOIN postings p ON p.id = s.posting_id
               WHERE p.eligible=1 AND p.has_content=1
                 AND substr(p.first_published,1,10) >= ?
               GROUP BY s.skill""",
            (job_since,),
        ).fetchall()
    }

    rows = []
    for skill, count in repo_counts.items():
        if count < MIN_REPOS:
            continue
        repo_share = count / repo_total * 100
        job_share = job_counts.get(skill, 0) / job_total * 100
        rows.append({
            "skill": skill,
            "category": category_of(skill),
            "category_label": CATEGORY_LABELS.get(category_of(skill), "other"),
            "repos": count,
            "repo_share": round(repo_share, 1),
            "jobs": job_counts.get(skill, 0),
            "job_share": round(job_share, 1),
            "gap": round(repo_share - job_share, 1),
            "ratio": round(repo_share / job_share, 2) if job_share else None,
        })
    rows.sort(key=lambda r: r["gap"], reverse=True)
    return rows


def top_repos(conn, months: int = 6, limit: int = 40, skill: str = "") -> list[dict]:
    since = (date.today() - timedelta(days=months * 30)).isoformat()
    if skill:
        rows = conn.execute(
            """SELECT r.* FROM repos r JOIN repo_skills s ON s.full_name = r.full_name
               WHERE r.created_at >= ? AND s.skill = ?
               ORDER BY r.stars DESC LIMIT ?""",
            (since, skill, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM repos WHERE created_at >= ? ORDER BY stars DESC LIMIT ?",
            (since, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def languages(conn, months: int = 6) -> list[dict]:
    since = (date.today() - timedelta(days=months * 30)).isoformat()
    rows = conn.execute(
        """SELECT language, COUNT(*) n, SUM(stars) stars FROM repos
           WHERE created_at >= ? AND language != '' GROUP BY language
           ORDER BY n DESC LIMIT 15""",
        (since,),
    ).fetchall()
    total = sum(r["n"] for r in rows) or 1
    return [
        {
            "language": r["language"],
            "repos": r["n"],
            "stars": r["stars"],
            "share": round(r["n"] / total * 100, 1),
        }
        for r in rows
    ]


def summary(conn, months: int = 6) -> dict:
    since = (date.today() - timedelta(days=months * 30)).isoformat()
    row = conn.execute(
        """SELECT COUNT(*) n, COALESCE(SUM(stars),0) stars, MAX(fetched_at) fetched
           FROM repos WHERE created_at >= ?""",
        (since,),
    ).fetchone()
    return {
        "repos": row["n"],
        "stars": row["stars"],
        "fetched_at": row["fetched"] or "",
        "months": months,
    }
