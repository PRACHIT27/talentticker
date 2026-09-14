"""Shared pieces for every job board reader."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from .. import config


@dataclass
class RawPosting:
    """One job as the company published it, before we interpret anything."""

    ats: str
    board_token: str
    external_id: str
    title: str
    url: str
    location_raw: str = ""
    content: str = ""
    department: str = ""
    team: str = ""
    first_published: str = ""
    updated_at: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    remote: bool = False
    company_name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.ats}:{self.board_token}:{self.external_id}"


_TAG = re.compile(r"<[^>]+>")
_BREAKS = re.compile(r"</(p|div|li|h[1-6]|tr)>|<br\s*/?>", re.I)
_BULLET = re.compile(r"<li[^>]*>", re.I)
_SPACE = re.compile(r"[ \t ]+")
_BLANK = re.compile(r"\n{3,}")


def html_to_text(raw: str | None) -> str:
    """Turn a job description into readable plain text.

    Job boards return HTML with wildly inconsistent markup, and the skill
    matcher needs clean word boundaries. A full HTML parser is overkill here -
    we only care about keeping line breaks where lists and paragraphs were.

    Order matters. Several boards return tags that are themselves escaped
    (`&lt;div&gt;`), so the text has to be unescaped before tags are removed.
    Doing it the other way round leaves literal "div" and "br" scattered
    through the output, which then shows up as fake trending vocabulary.
    """
    if not raw:
        return ""
    # Unescape until it stops changing. Some boards double-encode, so the raw
    # text holds `&amp;nbsp;`: one pass leaves a literal `&nbsp;` behind, which
    # then survives into the description and shows up as vocabulary. Two passes
    # is enough in practice; the cap only guards against a pathological input.
    text = raw
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    text = _BULLET.sub("\n- ", text)
    text = _BREAKS.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = _SPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _BLANK.sub("\n\n", text).strip()


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=config.HTTP_TIMEOUT,
        headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )


class BoardError(Exception):
    """The board could not be read. Recorded against the company, not fatal."""


class Source:
    """Base class. Subclasses read one applicant tracking system."""

    name: str = ""

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or make_client()

    def fetch(self, board_token: str) -> list[RawPosting]:
        """Every open posting on the board, with full descriptions."""
        raise NotImplementedError

    def fetch_light(self, board_token: str) -> list[tuple[str, str]]:
        """Cheap listing used to spot new jobs: (external_id, updated_at).

        Defaults to a full fetch for boards that only offer one endpoint.
        """
        return [(p.external_id, p.updated_at) for p in self.fetch(board_token)]

    def _get(self, url: str) -> Any:
        try:
            resp = self.client.get(url)
        except httpx.HTTPError as exc:
            raise BoardError(str(exc)) from exc
        if resp.status_code == 404:
            raise BoardError("board not found (404)")
        if resp.status_code == 429:
            raise BoardError("rate limited (429)")
        if resp.status_code >= 400:
            raise BoardError(f"http {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise BoardError("response was not JSON") from exc
