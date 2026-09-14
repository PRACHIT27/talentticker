"""Work out which applicant system an apply link points at.

The aggregated new-grad boards are a useful safety net, but they are second-hand
and can lag: a role shows up there days after the company published it, and the
row carries no description. Where we read the company's board directly we
already have the better copy - earlier, with the full text.

So every aggregated row is resolved back to its origin. If the link is a
Greenhouse, Ashby, Lever, Workday or Amazon posting we already hold, the
aggregated duplicate is dropped. Direct sources always win.

It doubles as company discovery: a link to `job-boards.greenhouse.io/twitch/...`
tells us Twitch has a Greenhouse board worth adding to companies.yml.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("greenhouse", re.compile(
        r"(?:job-boards|boards)\.greenhouse\.io/(?:embed/job_app\?for=)?"
        r"(?P<token>[A-Za-z0-9_-]+)/jobs/(?P<id>\d+)", re.I)),
    ("ashby", re.compile(
        r"jobs\.ashbyhq\.com/(?P<token>[A-Za-z0-9._-]+)/(?P<id>[0-9a-f-]{16,})", re.I)),
    ("lever", re.compile(
        r"jobs\.lever\.co/(?P<token>[A-Za-z0-9._-]+)/(?P<id>[0-9a-f-]{16,})", re.I)),
    ("amazon", re.compile(
        r"amazon\.jobs/(?:[a-z-]{2,5}/)?jobs/(?P<id>\d+)", re.I)),
    ("workday", re.compile(
        r"(?P<tenant>[A-Za-z0-9-]+)\.(?P<pod>wd\d+)\.myworkdayjobs\.com/"
        r"(?:[a-z]{2}-[A-Z]{2}/)?(?P<site>[A-Za-z0-9_-]+)/job/[^/]+/[^/]*?"
        r"_(?P<id>[A-Za-z0-9-]+)", re.I)),
    ("workable", re.compile(
        r"(?:apply\.workable\.com|[a-z0-9-]+\.workable\.com)/(?:j/)?"
        r"(?P<token>[A-Za-z0-9_-]+)(?:/j/(?P<id>[A-Z0-9]+))?", re.I)),
    ("smartrecruiters", re.compile(
        r"jobs\.smartrecruiters\.com/(?P<token>[A-Za-z0-9_-]+)/(?P<id>\d+)", re.I)),
]

# Some companies wrap a Greenhouse posting in their own careers page and keep
# the real id in the query string.
QUERY_IDS = {"gh_jid": "greenhouse", "lever-id": "lever", "ashby_jid": "ashby"}


class Origin:
    __slots__ = ("ats", "token", "external_id")

    def __init__(self, ats: str, token: str = "", external_id: str = ""):
        self.ats = ats
        self.token = token
        self.external_id = external_id

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Origin({self.ats}, {self.token!r}, {self.external_id!r})"


def resolve(url: str) -> Origin | None:
    """Identify the applicant system behind an apply link, if we know it."""
    if not url:
        return None

    for ats, pattern in PATTERNS:
        match = pattern.search(url)
        if not match:
            continue
        groups = match.groupdict()
        if ats == "workday":
            token = f"{groups['tenant']}:{groups['pod']}:{groups['site']}"
        else:
            token = groups.get("token") or ""
        return Origin(ats, token, groups.get("id") or "")

    # A company-hosted page that still carries the underlying job id.
    try:
        query = parse_qs(urlparse(url).query)
    except ValueError:
        return None
    for key, ats in QUERY_IDS.items():
        if key in query and query[key]:
            return Origin(ats, "", query[key][0])
    return None


def board_url(origin: Origin) -> str:
    """A link to the whole board, for the discovery report."""
    if origin.ats == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{origin.token}/jobs"
    if origin.ats == "ashby":
        return f"https://api.ashbyhq.com/posting-api/job-board/{origin.token}"
    if origin.ats == "lever":
        return f"https://api.lever.co/v0/postings/{origin.token}?mode=json"
    if origin.ats == "workday":
        tenant, pod, site = origin.token.split(":")
        return f"https://{tenant}.{pod}.myworkdayjobs.com/{site}"
    return ""
