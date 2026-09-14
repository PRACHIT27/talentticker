"""Community-maintained new-grad job boards on GitHub.

Repositories like speedyapply/2027-SWE-College-Jobs and
SimplifyJobs/New-Grad-Positions are markdown tables of new-graduate software
roles in the US, updated constantly by people doing exactly the same search.
They are worth reading for two reasons.

First, coverage. They list roles at Google, TikTok, SpaceX and everyone else
whose applicant system has no usable feed, so they fill the gap that a
board-by-board approach leaves.

Second, discovery. Every row links to an apply page, and that URL names the
applicant system: `job-boards.greenhouse.io/twitch/...` tells us Twitch has a
Greenhouse board we could be reading directly, with full descriptions. See
`discover.py`, which mines exactly that.

What these rows do not carry is a job description. Without one there are no
skills to count, so these postings are marked `has_content = 0` and left out of
the ticker and the sector figures. They still appear in the job list and still
fire alerts, which is what they are good for.
"""
from __future__ import annotations

import html
import re
from datetime import date, timedelta

from .base import BoardError, RawPosting, Source

RAW = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"

# A row looks like:
# | <a href="COMPANY"><strong>Name</strong></a> | Title | City, ST | $186k/yr |
#   <a href="APPLY"><img .../></a> | 8d |
ROW = re.compile(r"^\|(.+)\|\s*$")
LINK_TEXT = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
TAGS = re.compile(r"<[^>]+>")
AGE = re.compile(r"^(\d+)\s*([dhmo])", re.I)
SALARY = re.compile(r"\$\s*([\d.]+)\s*([kK])?")
CLOSED = re.compile(r"\bclosed\b|🔒", re.I)


def _text(cell: str) -> str:
    return html.unescape(TAGS.sub("", cell)).strip()


def _age_to_date(cell: str) -> str:
    """"8d" means posted eight days ago. Turn that into a real date."""
    match = AGE.search(cell.strip())
    if not match:
        return ""
    amount, unit = int(match.group(1)), match.group(2).lower()
    days = {"h": 0, "d": 1, "m": 30, "o": 30}.get(unit, 1) * amount
    if unit == "h":
        days = 0
    return (date.today() - timedelta(days=days)).isoformat()


def _salary(cell: str) -> tuple[int | None, int | None]:
    match = SALARY.search(cell)
    if not match:
        return None, None
    value = float(match.group(1))
    if match.group(2):
        value *= 1000
    if value < 30_000 or value > 1_500_000:
        return None, None
    return int(value), int(value)


class JobBoard(Source):
    """Reads one markdown table from a GitHub repository.

    Token format: `owner/repo:branch:path/to/FILE.md`
    """

    name = "jobboard"

    def fetch(self, board_token: str) -> list[RawPosting]:
        parts = board_token.split(":")
        if len(parts) != 3:
            raise BoardError(
                "jobboard token must look like owner/repo:branch:PATH.md, "
                f"got {board_token!r}"
            )
        repo, branch, path = parts
        url = RAW.format(repo=repo, branch=branch, path=path)
        try:
            response = self.client.get(url)
        except Exception as exc:  # noqa: BLE001
            raise BoardError(str(exc)) from exc
        if response.status_code == 404:
            raise BoardError("board not found (404)")
        if response.status_code >= 400:
            raise BoardError(f"http {response.status_code}")

        out: list[RawPosting] = []
        seen: set[str] = set()
        for line in response.text.split("\n"):
            posting = _parse_row(line, board_token)
            if posting and posting.external_id not in seen:
                seen.add(posting.external_id)
                out.append(posting)
        return out


def _parse_row(line: str, board_token: str) -> RawPosting | None:
    line = line.strip()
    if not line.startswith("|") or "<a href" not in line:
        return None
    cells = [c.strip() for c in line.strip("|").split("|")]
    if len(cells) < 5:
        return None

    company_cell, title_cell, location_cell = cells[0], cells[1], cells[2]
    company = _text(company_cell)
    title = _text(title_cell)
    if not company or not title or title.lower() in {"position", "role"}:
        return None

    # The apply link is whichever link is not the company's home page.
    links = LINK_TEXT.findall(line)
    apply_url = ""
    for href, _label in links:
        if href.startswith("http") and href != (links[0][0] if links else ""):
            apply_url = href
            break
    if not apply_url and links:
        apply_url = links[-1][0]
    if not apply_url or CLOSED.search(title_cell):
        return None

    # Some boards put salary in column 4, others go straight to the link.
    salary_cell = cells[3] if len(cells) >= 6 else ""
    low, high = _salary(salary_cell)
    posted = _age_to_date(cells[-1])

    return RawPosting(
        ats="jobboard",
        board_token=board_token,
        # The apply URL is the only stable identifier these tables offer.
        external_id=re.sub(r"[^A-Za-z0-9]+", "-", apply_url)[-90:],
        title=title,
        url=apply_url,
        location_raw=_text(location_cell),
        content="",  # no description in these tables - see the module docstring
        company_name=company,
        first_published=posted,
        updated_at=posted,
        salary_min=low,
        salary_max=high,
    )
