"""Amazon's own job platform.

Amazon does not use Greenhouse, Ashby or Lever - it runs amazon.jobs on its own
stack, which is why none of its roles appeared until this reader existed. The
same is true of most of the very large employers, and it is the main reason a
board-by-board approach misses them.

The search endpoint powering amazon.jobs returns JSON, including the full
description and the "basic qualifications" block, which is where the years of
experience are stated. `board_token` selects the job category, so one entry in
companies.yml covers everything Amazon has open in that category.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlencode

from .base import RawPosting, Source, html_to_text

BASE = "https://www.amazon.jobs"
SEARCH = BASE + "/en/search.json"
PAGE_SIZE = 100
MAX_PAGES = 30  # 3,000 roles per category is well past what we need


class Amazon(Source):
    name = "amazon"

    @staticmethod
    def categories(board_token: str) -> list[str]:
        """A token may name several categories, separated by a pipe."""
        return [c.strip() for c in (board_token or "").split("|") if c.strip()] or ["all"]

    def _page(self, category: str, offset: int) -> dict:
        query = [
            ("result_limit", str(PAGE_SIZE)),
            ("offset", str(offset)),
            ("sort", "recent"),
            ("country[]", "USA"),
        ]
        if category and category != "all":
            query.append(("category[]", category))
        return self._get(f"{SEARCH}?{urlencode(query)}")

    def fetch_light(self, board_token: str) -> list[tuple[str, str]]:
        """Just the ids and dates, for spotting new postings cheaply."""
        out: list[tuple[str, str]] = []
        for category in self.categories(board_token):
            for page in range(MAX_PAGES):
                data = self._page(category, page * PAGE_SIZE)
                jobs = data.get("jobs", [])
                if not jobs:
                    break
                out += [(str(j.get("id_icims")), _iso_date(j.get("posted_date")))
                        for j in jobs]
                if len(jobs) < PAGE_SIZE:
                    break
        return out

    def fetch(self, board_token: str) -> list[RawPosting]:
        out: list[RawPosting] = []
        seen: set[str] = set()
        for category in self.categories(board_token):
            for page in range(MAX_PAGES):
                data = self._page(category, page * PAGE_SIZE)
                jobs = data.get("jobs", [])
                if not jobs:
                    break
                for job in jobs:
                    external_id = str(job.get("id_icims") or job.get("id") or "")
                    if not external_id or external_id in seen:
                        continue
                    seen.add(external_id)
                    out.append(_to_posting(job, board_token))
                if len(jobs) < PAGE_SIZE:
                    break
        return out


def _iso_date(value: str | None) -> str:
    """Amazon prints dates as "September  4, 2026", sometimes double-spaced."""
    if not value:
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _to_posting(job: dict, category: str) -> RawPosting:
    # The qualifications blocks are where experience requirements live, so they
    # matter more to us than the marketing copy at the top.
    body = "\n\n".join(
        html_to_text(job.get(field) or "")
        for field in ("description", "basic_qualifications", "preferred_qualifications")
        if job.get(field)
    )
    path = job.get("job_path") or ""
    posted = _iso_date(job.get("posted_date"))
    return RawPosting(
        ats="amazon",
        board_token=category,
        external_id=str(job.get("id_icims") or job.get("id")),
        title=(job.get("title") or "").strip(),
        url=BASE + path if path.startswith("/") else path,
        location_raw=job.get("normalized_location") or job.get("location") or "",
        content=body,
        department=job.get("job_category") or "",
        team=job.get("business_category") or "",
        # Subsidiaries post under their own name ("Audible, Inc. - B13"), but
        # for market analysis they are all Amazon.
        company_name="Amazon",
        first_published=posted,
        updated_at=posted,
    )
