"""Workday career sites.

Workday is the applicant system behind a very large share of big US employers -
NVIDIA, Salesforce, Adobe, Snap, General Motors, and most of the defence and
Fortune 500 world. Adding it roughly triples the reach of everything else here.

A board token looks like `tenant:pod:site`, the three parts of a Workday career
URL. For https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite that is
`nvidia:wd5:NVIDIAExternalCareerSite`.

Unlike the other readers, Workday splits its data in two: a search returns
titles and paths, and the description needs a second request per job. With a
hundred and fifty Workday boards in the registry, fetching everything would run
for hours, so this reader is deliberately bounded:

  - it searches for software titles rather than listing every opening
  - it skips descriptions for titles that are obviously out of range
  - it only pulls details for the newest matches, since a product about
    applying early cares most about what went up this week

Anything it does not reach on one run is picked up by later runs.
"""
from __future__ import annotations

import re
import time

from .base import BoardError, RawPosting, Source, html_to_text

PAGE_SIZE = 20
MAX_PAGES = 10
DETAIL_DELAY = 0.15  # be a polite guest on someone else's careers site
def _search_terms() -> list[str]:
    """What to type into the board's search box.

    These boards will not list everything, so the terms decide what we ever
    see. They come from the role profile - searching "software engineer" on a
    product-management run would return an empty board.
    """
    from ..profiles import active

    return active().search_terms or ["software engineer"]


def _title_filters():
    from ..profiles import title_filters

    return title_filters()
MAX_DETAILS = 40

# "Posted Today", "Posted 5 Days Ago", "Posted 30+ Days Ago"
POSTED_AGE = re.compile(r"(\d+)\s*\+?\s*day", re.I)

# Only fetch descriptions for titles that could plausibly be in scope. This is
# a coarse pre-filter; the real decision is still made by extract/seniority.py
# once the description is in hand.


def parse_token(board_token: str) -> tuple[str, str, str]:
    parts = board_token.split(":")
    if len(parts) != 3:
        raise BoardError(
            f"workday token must look like tenant:pod:site, got {board_token!r}"
        )
    return parts[0], parts[1], parts[2]


def posted_age_days(posted_on: str) -> int:
    """Roughly how old a listing is, from Workday's human-readable label."""
    if not posted_on:
        return 999
    lowered = posted_on.lower()
    if "today" in lowered:
        return 0
    if "yesterday" in lowered:
        return 1
    match = POSTED_AGE.search(lowered)
    return int(match.group(1)) if match else 999


class Workday(Source):
    name = "workday"

    def _search_url(self, tenant: str, pod: str, site: str) -> str:
        return f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"

    def _post(self, url: str, payload: dict):
        try:
            response = self.client.post(url, json=payload)
        except Exception as exc:  # noqa: BLE001 - httpx raises several types
            raise BoardError(str(exc)) from exc
        if response.status_code == 404:
            raise BoardError("board not found (404)")
        if response.status_code >= 400:
            raise BoardError(f"http {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise BoardError("response was not JSON") from exc

    def _listing(self, board_token: str) -> list[dict]:
        """Search results across the software terms, de-duplicated by path."""
        tenant, pod, site = parse_token(board_token)
        url = self._search_url(tenant, pod, site)
        found: dict[str, dict] = {}

        for term in _search_terms():
            for page in range(MAX_PAGES):
                data = self._post(
                    url,
                    {"appliedFacets": {}, "limit": PAGE_SIZE,
                     "offset": page * PAGE_SIZE, "searchText": term},
                )
                postings = data.get("jobPostings", [])
                if not postings:
                    break
                for posting in postings:
                    path = posting.get("externalPath")
                    if path:
                        found.setdefault(path, posting)
                if len(postings) < PAGE_SIZE:
                    break
        return list(found.values())

    def fetch_light(self, board_token: str) -> list[tuple[str, str]]:
        return [
            (_id_from_path(p.get("externalPath") or ""), p.get("postedOn") or "")
            for p in self._listing(board_token)
        ]

    def fetch(self, board_token: str) -> list[RawPosting]:
        tenant, pod, site = parse_token(board_token)
        prefix = f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
        public = f"https://{tenant}.{pod}.myworkdayjobs.com/{site}"

        likely, senior = _title_filters()
        wanted = [
            posting
            for posting in self._listing(board_token)
            if posting.get("externalPath")
            and likely.search(posting.get("title") or "")
            and not senior.search(posting.get("title") or "")
        ]
        # Newest first, then capped - one enormous board must not starve the
        # other hundred and forty.
        wanted.sort(key=lambda p: posted_age_days(p.get("postedOn") or ""))
        wanted = wanted[:MAX_DETAILS]

        out: list[RawPosting] = []
        for posting in wanted:
            path = posting["externalPath"]
            try:
                detail = self._get(prefix + path)
            except BoardError:
                continue
            time.sleep(DETAIL_DELAY)

            info = detail.get("jobPostingInfo") or {}
            started = (info.get("startDate") or "")[:10]
            out.append(
                RawPosting(
                    ats="workday",
                    board_token=board_token,
                    external_id=_id_from_path(path),
                    title=info.get("title") or posting.get("title") or "",
                    url=info.get("externalUrl") or (public + path),
                    location_raw=info.get("location")
                    or posting.get("locationsText")
                    or "",
                    content=html_to_text(info.get("jobDescription")),
                    company_name=tenant,
                    first_published=started,
                    updated_at=started,
                )
            )
        return out


def _id_from_path(path: str) -> str:
    """Workday paths end in the requisition id, which is stable."""
    tail = path.rstrip("/").rsplit("/", 1)[-1]
    match = re.search(r"_([A-Za-z0-9\-]+)$", tail)
    return match.group(1) if match else tail
