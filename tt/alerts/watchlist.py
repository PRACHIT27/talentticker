"""Deciding which new jobs are worth interrupting you for.

There are thousands of open roles. Sending all of them is the same as sending
none, so nothing leaves the building unless it matches a watchlist you wrote.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULTS = [
    {
        "name": "new-grad-swe",
        "query": "",
        "skills": "",
        "states": "",
        "remote_ok": 1,
        "max_years": 2,
        "sponsorship": "",
    },
]


@dataclass
class Watchlist:
    name: str
    query: str = ""
    skills: str = ""
    states: str = ""
    remote_ok: int = 1
    max_years: float = 4.0
    sponsorship: str = ""
    active: int = 1

    @property
    def skill_list(self) -> list[str]:
        return [s.strip() for s in (self.skills or "").split(",") if s.strip()]

    @property
    def state_list(self) -> list[str]:
        return [s.strip().upper() for s in (self.states or "").split(",") if s.strip()]

    @property
    def terms(self) -> list[str]:
        return [t.strip().lower() for t in (self.query or "").split(",") if t.strip()]


def load(conn) -> list[Watchlist]:
    rows = conn.execute("SELECT * FROM watchlists WHERE active=1").fetchall()
    return [Watchlist(**dict(r)) for r in rows]


def ensure_defaults(conn) -> None:
    from .. import config

    configured = config.PROFILE.watchlists
    if configured:
        for entry in configured:
            save(conn, Watchlist(
                name=entry["name"],
                query=entry.get("query", ""),
                skills=entry.get("skills", ""),
                states=entry.get("states", ""),
                remote_ok=int(entry.get("remote_ok", 1)),
                max_years=float(entry.get("max_years", 4)),
                sponsorship=entry.get("sponsorship", ""),
                active=int(entry.get("active", 1)),
            ))
        return

    existing = conn.execute("SELECT COUNT(*) n FROM watchlists").fetchone()["n"]
    if existing:
        return
    for entry in DEFAULTS:
        conn.execute(
            "INSERT INTO watchlists (name, query, skills, states, remote_ok, "
            "max_years, sponsorship, active) VALUES (?,?,?,?,?,?,?,1)",
            (entry["name"], entry["query"], entry["skills"], entry["states"],
             entry["remote_ok"], entry["max_years"], entry.get("sponsorship", "")),
        )


def save(conn, watchlist: Watchlist) -> None:
    conn.execute(
        """INSERT INTO watchlists (name, query, skills, states, remote_ok,
                                   max_years, sponsorship, active)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(name) DO UPDATE SET
             query=excluded.query, skills=excluded.skills, states=excluded.states,
             remote_ok=excluded.remote_ok, max_years=excluded.max_years,
             sponsorship=excluded.sponsorship, active=excluded.active""",
        (watchlist.name, watchlist.query, watchlist.skills, watchlist.states,
         watchlist.remote_ok, watchlist.max_years, watchlist.sponsorship,
         watchlist.active),
    )


def matches(watchlist: Watchlist, posting: dict, posting_skills: set[str]) -> bool:
    """Does this job clear the bar for this watchlist?"""
    if not posting.get("eligible"):
        return False

    years = posting.get("yoe_min")
    if years is not None and years > watchlist.max_years:
        return False

    # Visa sponsorship. "open" keeps anything not explicitly ruled out, which
    # includes the many postings that simply never mention it.
    want = (watchlist.sponsorship or "").strip()
    if want:
        status = posting.get("sponsorship") or "unknown"
        if want == "open":
            if status in ("no", "clearance"):
                return False
        elif status != want:
            return False

    states = watchlist.state_list
    if states:
        state = (posting.get("state") or "").upper()
        remote = bool(posting.get("remote"))
        if state not in states and not (remote and watchlist.remote_ok):
            return False
    elif not watchlist.remote_ok and posting.get("remote"):
        return False

    wanted = watchlist.skill_list
    if wanted and not any(s in posting_skills for s in wanted):
        return False

    terms = watchlist.terms
    if terms:
        haystack = f"{posting.get('title','')} {posting.get('content','')}".lower()
        if not any(re.search(rf"\b{re.escape(t)}\b", haystack) for t in terms):
            return False

    return True


def pending(conn, posting_ids: list[str]) -> dict[str, list[dict]]:
    """Group new postings by the watchlist that wants them.

    Anything already sent for that watchlist is skipped, so a restart or an
    overlapping poll never sends the same job twice.
    """
    if not posting_ids:
        return {}
    lists = load(conn)
    if not lists:
        return {}

    placeholders = ",".join("?" * len(posting_ids))
    rows = conn.execute(
        f"SELECT * FROM postings WHERE id IN ({placeholders}) AND eligible=1",
        posting_ids,
    ).fetchall()
    if not rows:
        return {}

    skills_by_posting: dict[str, set[str]] = {}
    for row in conn.execute(
        f"SELECT posting_id, skill FROM posting_skills WHERE posting_id IN ({placeholders})",
        posting_ids,
    ).fetchall():
        skills_by_posting.setdefault(row["posting_id"], set()).add(row["skill"])

    already = {
        (r["posting_id"], r["watchlist"])
        for r in conn.execute(
            f"SELECT posting_id, watchlist FROM alerts_sent WHERE posting_id IN ({placeholders})",
            posting_ids,
        ).fetchall()
    }

    out: dict[str, list[dict]] = {}
    for watchlist in lists:
        for row in rows:
            posting = dict(row)
            if (posting["id"], watchlist.name) in already:
                continue
            if matches(watchlist, posting, skills_by_posting.get(posting["id"], set())):
                posting["skills"] = sorted(skills_by_posting.get(posting["id"], set()))
                out.setdefault(watchlist.name, []).append(posting)
    return out


def mark_sent(conn, watchlist_name: str, posting_ids: list[str], when: str) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO alerts_sent (posting_id, watchlist, sent_at) VALUES (?,?,?)",
        [(pid, watchlist_name, when) for pid in posting_ids],
    )
