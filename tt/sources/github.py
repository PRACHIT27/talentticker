from __future__ import annotations

import os
import time
from datetime import date, timedelta

from .base import BoardError, make_client

SEARCH = "https://api.github.com/search/repositories"
PER_PAGE = 100
MAX_PAGES = 10
PAUSE = 2.5


def _headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def rate_limit() -> dict:
    client = make_client()
    try:
        response = client.get("https://api.github.com/rate_limit", headers=_headers())
        data = response.json()["resources"]["search"]
        return {"limit": data["limit"], "remaining": data["remaining"]}
    finally:
        client.close()


def _search(client, query: str, pages: int) -> list[dict]:
    out: list[dict] = []
    for page in range(1, pages + 1):
        url = (
            f"{SEARCH}?q={query}&sort=stars&order=desc"
            f"&per_page={PER_PAGE}&page={page}"
        )
        response = client.get(url, headers=_headers())
        if response.status_code == 403:
            raise BoardError("github rate limit reached")
        if response.status_code >= 400:
            raise BoardError(f"http {response.status_code}")
        items = response.json().get("items", [])
        if not items:
            break
        out += items
        if len(items) < PER_PAGE:
            break
        time.sleep(PAUSE)
    return out


def trending(months: int = 6, min_stars: int = 25, pages: int = MAX_PAGES) -> list[dict]:
    since = (date.today() - timedelta(days=months * 30)).isoformat()
    client = make_client()
    try:
        raw = _search(client, f"created:>{since}+stars:>{min_stars}", pages)
    finally:
        client.close()

    seen: set[str] = set()
    out: list[dict] = []
    for item in raw:
        name = item.get("full_name")
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({
            "full_name": name,
            "description": (item.get("description") or "").strip(),
            "language": item.get("language") or "",
            "topics": ",".join(item.get("topics") or []),
            "stars": int(item.get("stargazers_count") or 0),
            "created_at": (item.get("created_at") or "")[:10],
            "pushed_at": (item.get("pushed_at") or "")[:10],
            "url": item.get("html_url") or "",
        })
    return out
