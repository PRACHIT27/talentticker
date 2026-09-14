"""Greenhouse job boards.

The big win here is `first_published`: Greenhouse stamps every posting with the
date the company originally put it up, so a first run gives us a year of real
history instead of a flat line.
"""
from __future__ import annotations

from .base import RawPosting, Source, html_to_text

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


class Greenhouse(Source):
    name = "greenhouse"

    def fetch_light(self, board_token: str) -> list[tuple[str, str]]:
        data = self._get(API.format(token=board_token))
        return [
            (str(j.get("id")), j.get("updated_at") or "")
            for j in data.get("jobs", [])
        ]

    def fetch(self, board_token: str) -> list[RawPosting]:
        data = self._get(API.format(token=board_token) + "?content=true")
        out: list[RawPosting] = []
        for j in data.get("jobs", []):
            offices = j.get("offices") or []
            departments = j.get("departments") or []
            location = (j.get("location") or {}).get("name") or ""
            if not location and offices:
                location = offices[0].get("name") or ""
            out.append(
                RawPosting(
                    ats=self.name,
                    board_token=board_token,
                    external_id=str(j.get("id")),
                    title=(j.get("title") or "").strip(),
                    url=j.get("absolute_url") or "",
                    location_raw=location,
                    content=html_to_text(j.get("content")),
                    department=(departments[0].get("name") if departments else "") or "",
                    company_name=j.get("company_name") or board_token,
                    first_published=j.get("first_published") or j.get("updated_at") or "",
                    updated_at=j.get("updated_at") or "",
                )
            )
        return out
