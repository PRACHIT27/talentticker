"""Background jobs.

Runs inside the web process so that `python -m tt serve` gives you the
dashboard and the polling in one command. On a server you can turn it off with
TT_SCHEDULER=0 and drive the same work from cron instead - every job here is
also a CLI command.
"""
from __future__ import annotations

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

from . import alerts, config, db, ingest, state
from .analytics import themes

log = logging.getLogger("tt.scheduler")


def _alert(new_ids: list[str], label: str) -> None:
    """Send the alerts for these postings, then checkpoint what went out.

    The checkpoint matters. `alerts_sent` is the only thing stopping a posting
    being mailed twice, and on any host where the database does not survive a
    restart it is gone. `state.save` was wired to the CLI and nothing else, so
    in practice the table was always empty and every poll re-sent everything.
    """
    log.info("%s found %d new posting(s)", label, len(new_ids))
    result = alerts.dispatch(new_ids)
    log.info("alerts: %s", result)
    if result.get("delivered"):
        try:
            log.info("state saved: %s", state.save())
        except OSError as exc:
            log.error("could not save alert state: %s", exc)


def job_poll_hot() -> None:
    """Every few minutes: look for brand-new jobs at priority companies."""
    new_ids = ingest.poll(tier=1)
    if new_ids:
        _alert(new_ids, "poll_hot")


def job_poll_all() -> None:
    """Hourly: the same check across every company."""
    new_ids = ingest.poll(tier=2)
    if new_ids:
        _alert(new_ids, "poll_all")


def job_refresh() -> None:
    """Nightly: full re-read, close jobs that vanished, record a snapshot."""
    stats = ingest.refresh()
    log.info("refresh: %s", stats)
    ingest.snapshot()


# Each theme build is one Claude call over about forty postings - roughly
# 21k input and 2.7k output tokens, so about $0.17 on Opus. That is cheap once
# and expensive on a loop: the market summary plus eight companies every night
# comes to around $46 a month. So the market view refreshes daily and the
# per-company write-ups weekly, which lands nearer $10. Set TT_THEME_COMPANIES
# to change how many companies are covered, or 0 to skip them entirely.
THEME_COMPANIES = int(os.getenv("TT_THEME_COMPANIES", "8"))


def job_themes_market() -> None:
    """Daily: what the market as a whole is hiring to solve."""
    with db.session() as conn:
        try:
            themes.build(conn, scope="market")
        except Exception as exc:  # noqa: BLE001 - a bad API call must not kill the app
            log.error("market themes failed: %s", exc)


def job_themes_companies() -> None:
    """Weekly: the same question for the biggest individual employers."""
    if THEME_COMPANIES <= 0:
        return
    with db.session() as conn:
        top = conn.execute(
            """SELECT company_slug, COUNT(*) n FROM postings
               WHERE eligible=1 AND closed_at IS NULL AND has_content=1
               GROUP BY company_slug ORDER BY n DESC LIMIT ?""",
            (THEME_COMPANIES,),
        ).fetchall()
    for row in top:
        with db.session() as conn:
            try:
                themes.build(conn, scope="company", subject=row["company_slug"])
            except Exception as exc:  # noqa: BLE001
                log.error("themes for %s failed: %s", row["company_slug"], exc)


def job_discover() -> None:
    """Weekly: retry boards that failed, in case a token has come back."""
    with db.session() as conn:
        conn.execute(
            "UPDATE companies SET active=1 WHERE active=0 AND last_error IS NOT NULL"
        )
    stats = ingest.refresh()
    log.info("discover: %s", stats)


def start() -> BackgroundScheduler | None:
    if os.getenv("TT_SCHEDULER", "1") != "1":
        log.info("scheduler disabled (TT_SCHEDULER=0)")
        return None

    scheduler = BackgroundScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    )
    scheduler.add_job(job_poll_hot, "interval", minutes=5, id="poll_hot")
    scheduler.add_job(job_poll_all, "interval", minutes=60, id="poll_all")
    scheduler.add_job(job_refresh, "cron", hour=8, minute=0, id="refresh")
    # The Claude write-ups need API credit, which is billed separately from a
    # Claude Code or chat subscription. With no key configured they would fail
    # every night and fill the log with noise, so they are simply not
    # scheduled. Everything else runs regardless.
    if config.ANTHROPIC_API_KEY and config.CLAUDE_ENABLED:
        scheduler.add_job(job_themes_market, "cron", hour=9, minute=0,
                          id="themes_market")
        scheduler.add_job(job_themes_companies, "cron", day_of_week="mon",
                          hour=9, minute=30, id="themes_companies")
    else:
        log.info("Claude write-ups disabled (no key, or TT_CLAUDE_ENABLED=0)")
    scheduler.add_job(job_discover, "cron", day_of_week="sun", hour=10, id="discover")
    scheduler.start()
    log.info("scheduler started: %s", [j.id for j in scheduler.get_jobs()])
    return scheduler
