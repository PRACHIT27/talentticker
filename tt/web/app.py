"""The dashboard and its JSON API."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import config, db, ingest, scheduler
from ..alerts import watchlist as wl
from ..analytics import emerging, geo, industry, themes, ticker

log = logging.getLogger("tt.web")

HERE = Path(__file__).parent
app = FastAPI(title="TalentTicker", docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

_scheduler = None


@app.on_event("startup")
def _startup() -> None:
    global _scheduler
    db.init()
    with db.session() as conn:
        wl.ensure_defaults(conn)
    ingest.sync_companies()
    _scheduler = scheduler.start()


@app.on_event("shutdown")
def _shutdown() -> None:
    if _scheduler:
        _scheduler.shutdown(wait=False)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """The dashboard shell.

    The stylesheet and script carry a version stamped from their own modified
    time. Without it a browser happily serves yesterday's cached JavaScript
    against today's API and the page looks broken for no visible reason.
    """
    html = (HERE / "templates" / "index.html").read_text(encoding="utf-8")
    stamp = max(
        int((HERE / "static" / name).stat().st_mtime)
        for name in ("app.js", "style.css")
    )
    return html.replace("{{asset_version}}", str(stamp))


# --------------------------------------------------------------------------
# the ticker
# --------------------------------------------------------------------------


@app.get("/api/summary")
def api_summary() -> dict:
    with db.session() as conn:
        data = ticker.summary(conn)
        data["last_refresh"] = db.get_meta(conn, "last_refresh", "")
        snapshot_days = conn.execute(
            "SELECT COUNT(DISTINCT day) n FROM snapshots"
        ).fetchone()["n"]
        data["snapshot_days"] = snapshot_days
    # The dashboard header names the active profile, so it is obvious at a
    # glance whether you are looking at engineering or product figures.
    data["profile"] = config.PROFILE.name
    data["profile_label"] = config.PROFILE.label
    return data


@app.get("/api/ticker")
def api_ticker(
    window: int = Query(30, ge=7, le=365),
    limit: int = Query(60, ge=1, le=400),
    category: str = "",
) -> dict:
    from ..extract.taxonomy import CATEGORY_LABELS, category_of

    with db.session() as conn:
        rows = ticker.board(conn, window_days=window)
        series = ticker.series_bulk(conn)
    if category:
        rows = [r for r in rows if category_of(r["skill"]) == category]
    for row in rows:
        row["category"] = category_of(row["skill"])
        # The readable name, so the UI never has to show a raw key like "ai".
        row["category_label"] = CATEGORY_LABELS.get(row["category"], row["category"])
        # Sparkline data travels with the row so the page needs one request.
        row["series"] = series.get(row["skill"], [])[-12:]
    return {"window": window, "rows": rows[:limit], "total": len(rows)}


@app.get("/api/movers")
def api_movers(window: int = Query(30, ge=7, le=365)) -> dict:
    with db.session() as conn:
        return ticker.movers(conn, window_days=window)


@app.get("/api/skill")
def api_skill(name: str, window: int = Query(90, ge=7, le=365)) -> dict:
    """Detail for one skill.

    The name arrives as a query parameter rather than a path segment because
    plenty of skills contain a slash - "CI/CD" would otherwise look like two
    path components and return a 404.
    """
    with db.session() as conn:
        detail = ticker.skill_detail(conn, name, window_days=window)
        detail["sectors"] = industry.skill_by_sector(conn, name, window_days=window)
    if not detail["series"] and not detail["companies"]:
        raise HTTPException(404, f"nothing recorded for '{name}'")
    return detail


@app.get("/api/emerging")
def api_emerging(limit: int = Query(30, ge=1, le=100)) -> dict:
    with db.session() as conn:
        return {"rows": emerging.rising(conn, limit=limit)}


# --------------------------------------------------------------------------
# geography and company flow
# --------------------------------------------------------------------------


@app.get("/api/metros")
def api_metros(window: int = Query(30, ge=7, le=365)) -> dict:
    from datetime import date, timedelta

    since = (date.today() - timedelta(days=window)).isoformat()
    with db.session() as conn:
        states = geo.states(conn, window_days=window)
        total = conn.execute(
            "SELECT COUNT(*) n FROM postings WHERE eligible=1 "
            "AND substr(first_published,1,10) >= ?",
            (since,),
        ).fetchone()["n"]
        placed = sum(s["postings"] for s in states)
        return {
            "metros": geo.metros(conn, window_days=window),
            "states": states,
            # Roles advertised only as remote or "United States" belong to no
            # single state, so the map has to say how many it is leaving out.
            "total": total,
            "placed": placed,
            "unplaced": max(0, total - placed),
            "remote": geo.remote_trend(conn),
            "pay": geo.pay_by_metro(conn),
            "trend": geo.metro_series(conn),
        }


@app.get("/api/companies")
def api_companies(window: int = Query(30, ge=7, le=365)) -> dict:
    with db.session() as conn:
        flow = geo.company_flow(conn, window_days=window)
        boards = conn.execute(
            """SELECT c.slug, c.name, c.ats, c.active, c.last_polled, c.last_error,
                      c.job_count,
                      (SELECT COUNT(*) FROM postings p
                       WHERE p.company_slug=c.slug AND p.eligible=1
                         AND p.closed_at IS NULL) early
               FROM companies c ORDER BY early DESC, c.name"""
        ).fetchall()
    flow["boards"] = [dict(r) for r in boards]
    return flow


# --------------------------------------------------------------------------
# what companies are solving
# --------------------------------------------------------------------------


@app.get("/api/themes")
def api_themes(scope: str = "market", subject: str = "", refresh: bool = False) -> dict:
    with db.session() as conn:
        if not refresh:
            cached = themes.get_cached(conn, scope, subject)
            if cached:
                cached["cached"] = True
                return cached
        try:
            return themes.build(conn, scope=scope, subject=subject, force=refresh)
        except Exception as exc:  # noqa: BLE001 - surface the reason in the UI
            raise HTTPException(503, f"could not build themes: {exc}") from exc


# --------------------------------------------------------------------------
# jobs and watchlists
# --------------------------------------------------------------------------


@app.get("/api/jobs")
def api_jobs(
    skill: str = "",
    metro: str = "",
    company: str = "",
    sector: str = "",
    sponsorship: str = "",
    days: int = Query(14, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """The job list. Unlike the analytics, this includes aggregated listings.

    `sponsorship` accepts one of yes / no / clearance / unknown, or the special
    value `open` - meaning anything not ruled out, so postings that say nothing
    are kept rather than silently discarded.
    """
    from datetime import date, timedelta

    since = (date.today() - timedelta(days=days)).isoformat()
    where = ["p.eligible=1", "p.closed_at IS NULL", "substr(p.first_published,1,10) >= ?"]
    args: list = [since]
    join = ""
    if skill:
        join = "JOIN posting_skills s ON s.posting_id = p.id"
        where.append("s.skill = ?")
        args.append(skill)
    if metro:
        where.append("p.metro = ?")
        args.append(metro)
    if company:
        where.append("p.company_name = ?")
        args.append(company)
    if sector:
        where.append("p.sector = ?")
        args.append(sector)
    if sponsorship == "open":
        where.append("COALESCE(p.sponsorship,'unknown') NOT IN ('no','clearance')")
    elif sponsorship:
        where.append("COALESCE(p.sponsorship,'unknown') = ?")
        args.append(sponsorship)
    args.append(limit)

    sql = (
        "SELECT p.id, p.title, p.company_name, p.sector, p.metro, p.state, "
        "p.remote, p.url, p.first_published, p.yoe_min, p.yoe_max, "
        "p.salary_min, p.salary_max, p.ats, p.has_content, "
        "COALESCE(p.sponsorship,'unknown') sponsorship, p.sponsorship_note "
        f"FROM postings p {join} WHERE {' AND '.join(where)} "
        "ORDER BY p.first_published DESC LIMIT ?"
    )
    with db.session() as conn:
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    return {"rows": rows}


@app.get("/api/sponsorship")
def api_sponsorship(window: int = Query(90, ge=7, le=365)) -> dict:
    """Which employers sponsor, as far as their own postings admit."""
    from datetime import date, timedelta

    since = (date.today() - timedelta(days=window)).isoformat()
    with db.session() as conn:
        totals = {
            r["s"]: r["n"]
            for r in conn.execute(
                """SELECT COALESCE(sponsorship,'unknown') s, COUNT(*) n FROM postings
                   WHERE eligible=1 AND has_content=1
                     AND substr(first_published,1,10) >= ? GROUP BY s""",
                (since,),
            ).fetchall()
        }
        companies = conn.execute(
            """SELECT company_name,
                      SUM(sponsorship='yes') yes,
                      SUM(sponsorship='no') no,
                      SUM(sponsorship='clearance') clearance,
                      COUNT(*) total
               FROM postings
               WHERE eligible=1 AND has_content=1
                 AND substr(first_published,1,10) >= ?
               GROUP BY company_name
               HAVING yes > 0 OR no > 0 OR clearance > 0
               ORDER BY yes DESC, no DESC""",
            (since,),
        ).fetchall()
    return {"totals": totals, "companies": [dict(r) for r in companies]}


@app.get("/api/sectors")
def api_sectors(window: int = Query(30, ge=7, le=365)) -> dict:
    with db.session() as conn:
        return {"rows": industry.board(conn, window_days=window)}


@app.get("/api/sector")
def api_sector(name: str, window: int = Query(120, ge=7, le=365)) -> dict:
    with db.session() as conn:
        detail = industry.detail(conn, name, window_days=window)
    if not detail["companies"] and not detail["skills"]:
        raise HTTPException(404, f"nothing recorded for sector '{name}'")
    return detail


@app.get("/api/alert-config")
def api_alert_config() -> dict:
    """Where alerts go and whether sending is actually switched on.

    Deliberately reports only whether a password is present, never its value.
    """
    configured = bool(config.SMTP_HOST and config.ALERT_TO)
    if config.SMTP_DRY_RUN:
        mode = "dry run - alerts print to the console and are not emailed"
    elif not config.ALERT_TO:
        mode = "no recipient set - add TT_ALERT_TO to your .env"
    elif not config.SMTP_HOST:
        mode = "no mail server set - add TT_SMTP_HOST to your .env"
    else:
        mode = "sending"
    return {
        "to": config.ALERT_TO or "",
        "from": config.SMTP_FROM or "",
        "smtp_host": config.SMTP_HOST or "",
        "smtp_port": config.SMTP_PORT,
        "has_password": bool(config.SMTP_PASS),
        "dry_run": config.SMTP_DRY_RUN,
        "configured": configured and not config.SMTP_DRY_RUN,
        "mode": mode,
    }


@app.get("/api/watchlists")
def api_watchlists() -> dict:
    with db.session() as conn:
        wl.ensure_defaults(conn)
        rows = [dict(r) for r in conn.execute("SELECT * FROM watchlists").fetchall()]
    return {"rows": rows}


@app.post("/api/watchlists")
def api_save_watchlist(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "a watchlist needs a name")
    entry = wl.Watchlist(
        name=name,
        query=payload.get("query", ""),
        skills=payload.get("skills", ""),
        states=payload.get("states", ""),
        remote_ok=int(payload.get("remote_ok", 1)),
        max_years=float(payload.get("max_years", 4)),
        active=int(payload.get("active", 1)),
    )
    with db.session() as conn:
        wl.save(conn, entry)
    return {"ok": True, "name": name}


@app.delete("/api/watchlists/{name}")
def api_delete_watchlist(name: str) -> dict:
    with db.session() as conn:
        conn.execute("DELETE FROM watchlists WHERE name=?", (name,))
    return {"ok": True}


@app.get("/api/alerts")
def api_recent_alerts(limit: int = Query(50, ge=1, le=200)) -> dict:
    with db.session() as conn:
        rows = conn.execute(
            """SELECT a.sent_at, a.watchlist, p.title, p.company_name, p.url, p.metro
               FROM alerts_sent a JOIN postings p ON p.id = a.posting_id
               ORDER BY a.sent_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return {"rows": [dict(r) for r in rows]}
