from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config, db
from .analytics import building, emerging, geo, industry, themes, ticker
from .extract.taxonomy import CATEGORY_LABELS, category_of

WINDOWS = (30, 60, 90, 180)
SKILL_LIMIT = 250


def _summary(conn) -> dict:
    data = dict(ticker.summary(conn))
    data["profile"] = config.PROFILE.name
    data["profile_label"] = config.PROFILE.label
    data["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["snapshot_days"] = conn.execute(
        "SELECT COUNT(DISTINCT day) n FROM snapshots"
    ).fetchone()["n"]
    return data


def _ticker(conn) -> dict:
    series = ticker.series_bulk(conn)
    out = {}
    for window in WINDOWS:
        rows = ticker.board(conn, window_days=window)
        for row in rows:
            row["category"] = category_of(row["skill"])
            row["category_label"] = CATEGORY_LABELS.get(row["category"], row["category"])
            row["series"] = series.get(row["skill"], [])[-12:]
        out[str(window)] = rows[:SKILL_LIMIT]
    return out


def _skills(conn, names: list[str]) -> dict:
    out = {}
    for name in names:
        detail = ticker.skill_detail(conn, name, window_days=90)
        detail["sectors"] = industry.skill_by_sector(conn, name, window_days=90)
        detail.pop("openings", None)
        out[name] = detail
    return out


def _sectors(conn) -> dict:
    out = {"board": {}, "detail": {}}
    for window in WINDOWS:
        out["board"][str(window)] = industry.board(conn, window_days=window)
    for row in out["board"]["90"]:
        name = row["sector"]
        detail = industry.detail(conn, name, window_days=120)
        detail.pop("openings", None)
        out["detail"][name] = detail
    return out


def _geo(conn) -> dict:
    out = {}
    for window in WINDOWS:
        since = (date.today() - timedelta(days=window)).isoformat()
        states = geo.states(conn, window_days=window)
        total = conn.execute(
            "SELECT COUNT(*) n FROM postings WHERE eligible=1 "
            "AND substr(first_published,1,10) >= ?",
            (since,),
        ).fetchone()["n"]
        placed = sum(s["postings"] for s in states)
        out[str(window)] = {
            "metros": geo.metros(conn, window_days=window),
            "states": states,
            "total": total,
            "placed": placed,
            "unplaced": max(0, total - placed),
            "pay": geo.pay_by_metro(conn),
            "remote": geo.remote_trend(conn),
            "companies": geo.company_flow(conn, window_days=window),
        }
    return out


def _jobs(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT p.id, p.title, p.company_name, p.sector, p.metro, p.state,
                  p.remote, p.url, p.first_published, p.yoe_min, p.yoe_max,
                  p.salary_min, p.salary_max, p.sponsorship, p.sponsorship_note
           FROM postings p
           WHERE p.eligible=1 AND p.closed_at IS NULL
           ORDER BY p.first_published DESC"""
    ).fetchall()
    skills_by_posting: dict[str, list[str]] = {}
    for row in conn.execute(
        """SELECT s.posting_id, s.skill FROM posting_skills s
           JOIN postings p ON p.id = s.posting_id
           WHERE p.eligible=1 AND p.closed_at IS NULL"""
    ).fetchall():
        skills_by_posting.setdefault(row["posting_id"], []).append(row["skill"])

    out = []
    for row in rows:
        job = dict(row)
        job["skills"] = sorted(skills_by_posting.get(job["id"], []))
        out.append(job)
    return out


def build(conn) -> dict:
    tick = _ticker(conn)
    names = [r["skill"] for r in tick["90"]]
    return {
        "summary": _summary(conn),
        "ticker": tick,
        "movers": {str(w): ticker.movers(conn, window_days=w) for w in WINDOWS},
        "skills": _skills(conn, names),
        "emerging": emerging.rising(conn, limit=40),
        "sectors": _sectors(conn),
        "geo": _geo(conn),
        "jobs": _jobs(conn),
        "themes": themes.get_cached(conn, "market", "") or {},
        "building": {
            "summary": building.summary(conn),
            "board": building.board(conn),
            "languages": building.languages(conn),
            "repos": building.top_repos(conn, limit=60),
        },
    }


def write(destination: Path | None = None) -> dict:
    target = destination or (config.ROOT / "site" / "data" / f"{config.PROFILE.name}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    with db.session() as conn:
        payload = build(conn)
    target.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return {
        "path": str(target),
        "size_kb": round(target.stat().st_size / 1024),
        "skills": len(payload["skills"]),
        "jobs": len(payload["jobs"]),
        "sectors": len(payload["sectors"]["detail"]),
    }
