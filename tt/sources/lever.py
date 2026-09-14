"""Lever job boards.

Lever splits a posting into an opening blurb, a body, and named sections such
as "What We Require". Those sections hold the experience requirements, so we
stitch all of them back together before handing the text to the extractors.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .base import RawPosting, Source, html_to_text

API = "https://api.lever.co/v0/postings/{token}?mode=json"


def _epoch_ms_to_iso(value) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError, TypeError):
        return ""


def _full_text(job: dict) -> str:
    parts = [
        job.get("openingPlain") or html_to_text(job.get("opening")),
        job.get("descriptionBodyPlain")
        or job.get("descriptionPlain")
        or html_to_text(job.get("description")),
    ]
    for section in job.get("lists") or []:
        parts.append(section.get("text") or "")
        parts.append(html_to_text(section.get("content")))
    parts.append(job.get("additionalPlain") or html_to_text(job.get("additional")))
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


class Lever(Source):
    name = "lever"

    def fetch(self, board_token: str) -> list[RawPosting]:
        data = self._get(API.format(token=board_token))
        if not isinstance(data, list):
            return []
        out: list[RawPosting] = []
        for j in data:
            cats = j.get("categories") or {}
            locations = cats.get("allLocations") or [cats.get("location") or ""]
            created = _epoch_ms_to_iso(j.get("createdAt"))
            out.append(
                RawPosting(
                    ats=self.name,
                    board_token=board_token,
                    external_id=str(j.get("id")),
                    title=(j.get("text") or "").strip(),
                    url=j.get("hostedUrl") or j.get("applyUrl") or "",
                    location_raw="; ".join(x for x in locations if x),
                    content=_full_text(j),
                    department=cats.get("department") or "",
                    team=cats.get("team") or "",
                    company_name=board_token,
                    first_published=created,
                    updated_at=created,
                    remote=(j.get("workplaceType") or "").lower() == "remote",
                )
            )
        return out
