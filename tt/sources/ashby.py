"""Ashby job boards.

Ashby hands back everything in one call, including a plain-text description and
a published date. It is also the only one of the three that regularly publishes
salary ranges, which we keep.
"""
from __future__ import annotations

import re

from .base import RawPosting, Source, html_to_text

API = "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"

_MONEY = re.compile(r"\$\s*([\d,.]+)\s*([KkMm])?")


def _parse_salary(comp: dict | None) -> tuple[int | None, int | None]:
    """Pull a low and high number out of Ashby's pay summary string.

    The summary looks like "$120K - $160K - Offers Equity", so we read the
    dollar amounts and expand any K or M suffix.
    """
    if not comp:
        return None, None
    text = comp.get("scrapeableCompensationSalarySummary") or comp.get(
        "compensationTierSummary"
    )
    if not text:
        return None, None
    values: list[int] = []
    for amount, suffix in _MONEY.findall(text):
        try:
            n = float(amount.replace(",", ""))
        except ValueError:
            continue
        if suffix and suffix.lower() == "k":
            n *= 1_000
        elif suffix and suffix.lower() == "m":
            n *= 1_000_000
        # Ignore equity percentages and other small numbers that are not salary.
        if n >= 10_000:
            values.append(int(n))
    if not values:
        return None, None
    return min(values), max(values)


class Ashby(Source):
    name = "ashby"

    def fetch(self, board_token: str) -> list[RawPosting]:
        data = self._get(API.format(token=board_token))
        out: list[RawPosting] = []
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            lo, hi = _parse_salary(j.get("compensation"))
            content = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml"))
            locations = [j.get("location") or ""]
            locations += [s for s in (j.get("secondaryLocations") or []) if isinstance(s, str)]
            locations += [
                s.get("location", "")
                for s in (j.get("secondaryLocations") or [])
                if isinstance(s, dict)
            ]
            out.append(
                RawPosting(
                    ats=self.name,
                    board_token=board_token,
                    external_id=str(j.get("id")),
                    title=(j.get("title") or "").strip(),
                    url=j.get("jobUrl") or j.get("applyUrl") or "",
                    location_raw="; ".join(x for x in locations if x),
                    content=content,
                    department=j.get("department") or "",
                    team=j.get("team") or "",
                    company_name=board_token,
                    first_published=j.get("publishedAt") or "",
                    updated_at=j.get("publishedAt") or "",
                    salary_min=lo,
                    salary_max=hi,
                    remote=bool(j.get("isRemote"))
                    or (j.get("workplaceType") or "").lower() == "remote",
                )
            )
        return out
