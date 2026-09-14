"""Find company job boards we are not reading yet.

Hand-maintaining a list of applicant-system tokens does not scale - there are
thousands of companies and every one picked its own vendor. So instead of
guessing, this reads the aggregated new-grad boards, looks at where each apply
link actually points, and works backwards to the board behind it.

A row linking to `job-boards.greenhouse.io/twitch/jobs/8748321` says Twitch has
a Greenhouse board with token `twitch`. We then fetch that board to check it is
real before adding it, so a mangled URL never becomes a permanently failing
entry in the registry.

    python -m tt discover              # report what is missing
    python -m tt discover --add        # add the ones that respond
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict

import yaml

from . import config, db
from .sources import BoardError, get_source, make_client
from .sources.resolve import resolve

log = logging.getLogger("tt.discover")

# The boards we mine for links. These are community lists of new-grad software
# roles - exactly the scope of this project.
SOURCES = [
    "speedyapply/2027-SWE-College-Jobs:main:NEW_GRAD_USA.md",
    "speedyapply/2026-SWE-College-Jobs:main:NEW_GRAD_USA.md",
    "SimplifyJobs/New-Grad-Positions:dev:README.md",
]

# Workday needs a site name as well as a tenant, and only the URL knows it, so
# these arrive fully formed as tenant:pod:site.
SUPPORTED = {"greenhouse", "ashby", "lever", "workday"}


def candidates(board_tokens: list[str] | None = None) -> dict[tuple[str, str], dict]:
    """Every (ats, token) referenced by the aggregated boards."""
    client = make_client()
    found: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "companies": Counter()}
    )
    source = get_source("jobboard", client)

    for token in board_tokens or SOURCES:
        try:
            postings = source.fetch(token)
        except BoardError as exc:
            log.warning("could not read %s: %s", token, exc)
            continue
        log.info("%s: %d rows", token, len(postings))
        for posting in postings:
            origin = resolve(posting.url)
            if not origin or origin.ats not in SUPPORTED or not origin.token:
                continue
            entry = found[(origin.ats, origin.token)]
            entry["count"] += 1
            entry["companies"][posting.company_name] += 1

    client.close()
    return dict(found)


def known() -> set[tuple[str, str]]:
    with db.session() as conn:
        rows = conn.execute("SELECT ats, board_token FROM companies").fetchall()
    return {(r["ats"], r["board_token"]) for r in rows}


def verify(ats: str, token: str) -> int:
    """Fetch a candidate board. Returns how many jobs it has, or -1 if dead."""
    client = make_client()
    try:
        source = get_source(ats, client)
        # The light listing is enough to prove the board exists, and for Workday
        # it avoids pulling hundreds of descriptions just to answer the question.
        return len(source.fetch_light(token))
    except (BoardError, ValueError):
        return -1
    finally:
        client.close()


def run(add: bool = False, min_rows: int = 1, verify_all: bool = True) -> dict:
    """Report - and optionally add - boards we are missing."""
    already = known()
    everything = candidates()
    missing = {
        key: value
        for key, value in everything.items()
        if key not in already and value["count"] >= min_rows
    }

    report = {"seen": len(everything), "already_known": 0, "new": [], "dead": []}
    report["already_known"] = len(everything) - len(missing)

    for (ats, token), value in sorted(
        missing.items(), key=lambda kv: -kv[1]["count"]
    ):
        name = value["companies"].most_common(1)[0][0] if value["companies"] else token
        jobs = verify(ats, token) if verify_all else 0
        entry = {
            "ats": ats,
            "token": token,
            "name": name,
            "rows_on_board": value["count"],
            "jobs": jobs,
        }
        if jobs < 0:
            report["dead"].append(entry)
        else:
            report["new"].append(entry)

    if add and report["new"]:
        _append_to_registry(report["new"])
    return report


def _append_to_registry(entries: list[dict]) -> None:
    """Write new companies into companies.yml, keeping the file readable."""
    path = config.COMPANIES_FILE
    existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    have = {(c.get("ats"), c.get("token")) for c in existing.get("companies", [])}

    lines = ["", "  # ---- added by `python -m tt discover --add` ----"]
    added = 0
    for entry in entries:
        if (entry["ats"], entry["token"]) in have:
            continue
        name = str(entry["name"]).replace('"', "'")
        lines.append(
            f"  - {{ats: {entry['ats']}, token: {entry['token']}, "
            f'name: "{name}", sector: ""}}'
        )
        added += 1

    if added:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    log.info("added %d company board(s) to %s", added, path)
