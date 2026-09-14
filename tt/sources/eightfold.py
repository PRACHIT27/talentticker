"""Eightfold-hosted career sites.

Eightfold runs the careers site for Netflix and a number of other large
employers who do not use any of the usual applicant systems. Without it Netflix
simply does not appear.

A board token looks like `host:domain`, both taken from the careers URL. For
https://explore.jobs.netflix.net (which reports itself as netflix.com) that is
`explore.jobs.netflix.net:netflix.com`.

Like Workday, the search result carries no description, so each job needs a
second request. The same limits apply: search for software titles, skip the
obviously senior ones, and fetch details newest-first up to a cap.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from .base import BoardError, RawPosting, Source, html_to_text

PAGE_SIZE = 50
MAX_PAGES = 6
DETAIL_DELAY = 0.15
MAX_DETAILS = 40
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



def parse_token(board_token: str) -> tuple[str, str]:
    parts = board_token.split(":")
    if len(parts) != 2:
        raise BoardError(
            f"eightfold token must look like host:domain, got {board_token!r}"
        )
    return parts[0], parts[1]


def _epoch_to_iso(value) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).date().isoformat()
    except (ValueError, OSError, OverflowError, TypeError):
        return ""


class Eightfold(Source):
    name = "eightfold"

    def _listing(self, board_token: str) -> list[dict]:
        host, domain = parse_token(board_token)
        base = f"https://{host}/api/apply/v2/jobs"
        found: dict[str, dict] = {}

        for term in _search_terms():
            for page in range(MAX_PAGES):
                url = (
                    f"{base}?domain={domain}&start={page * PAGE_SIZE}"
                    f"&num={PAGE_SIZE}&query={term.replace(' ', '%20')}"
                    f"&location=United%20States"
                )
                data = self._get(url)
                positions = data.get("positions", [])
                if not positions:
                    break
                for position in positions:
                    if position.get("id"):
                        found.setdefault(str(position["id"]), position)
                if len(positions) < PAGE_SIZE:
                    break
        return list(found.values())

    def fetch_light(self, board_token: str) -> list[tuple[str, str]]:
        return [
            (str(p.get("id")), _epoch_to_iso(p.get("t_create")))
            for p in self._listing(board_token)
        ]

    def fetch(self, board_token: str) -> list[RawPosting]:
        host, domain = parse_token(board_token)
        base = f"https://{host}/api/apply/v2/jobs"

        likely, senior = _title_filters()
        wanted = [
            p
            for p in self._listing(board_token)
            if likely.search(p.get("name") or "")
            and not senior.search(p.get("name") or "")
        ]
        wanted.sort(key=lambda p: p.get("t_create") or 0, reverse=True)
        wanted = wanted[:MAX_DETAILS]

        out: list[RawPosting] = []
        for position in wanted:
            job_id = str(position["id"])
            try:
                detail = self._get(f"{base}/{job_id}?domain={domain}")
            except BoardError:
                continue
            time.sleep(DETAIL_DELAY)

            info = detail.get("position") or detail
            posted = _epoch_to_iso(info.get("t_create") or position.get("t_create"))
            locations = info.get("locations") or [info.get("location") or ""]
            out.append(
                RawPosting(
                    ats="eightfold",
                    board_token=board_token,
                    external_id=job_id,
                    title=info.get("name") or position.get("name") or "",
                    url=info.get("canonicalPositionUrl")
                    or f"https://{host}/careers/job/{job_id}",
                    location_raw="; ".join(x for x in locations if x),
                    content=html_to_text(info.get("job_description")),
                    department=info.get("department") or "",
                    team=info.get("business_unit") or "",
                    company_name=domain.split(".")[0],
                    first_published=posted,
                    updated_at=_epoch_to_iso(info.get("t_update")) or posted,
                )
            )
        return out
