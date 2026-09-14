"""Job board readers, one per applicant tracking system.

Two kinds of source, and the difference matters:

  direct    Greenhouse, Ashby, Lever, Workday, Amazon. We read the company's
            own board and get the full description and the real publish date.
            These are authoritative.

  listing   The community new-grad boards on GitHub. Second-hand, no
            description, and the date is approximate, so they only fill gaps
            where a company's own system has no usable feed. Any row that
            points back at a direct source is discarded in favour of it.
"""
from __future__ import annotations

from .amazon import Amazon
from .ashby import Ashby
from .base import BoardError, RawPosting, Source, html_to_text, make_client
from .eightfold import Eightfold
from .greenhouse import Greenhouse
from .jobboard import JobBoard
from .lever import Lever
from .resolve import Origin, resolve
from .workday import Workday

SOURCES: dict[str, type[Source]] = {
    "greenhouse": Greenhouse,
    "ashby": Ashby,
    "lever": Lever,
    "workday": Workday,
    "amazon": Amazon,
    "eightfold": Eightfold,
    "jobboard": JobBoard,
}

# Sources that give us the real description. Everything else is a pointer.
DIRECT = {"greenhouse", "ashby", "lever", "workday", "amazon", "eightfold"}


def get_source(ats: str, client=None) -> Source:
    try:
        return SOURCES[ats](client)
    except KeyError:
        raise ValueError(f"unknown job board type: {ats}") from None


def is_direct(ats: str) -> bool:
    return ats in DIRECT


__all__ = [
    "SOURCES",
    "DIRECT",
    "get_source",
    "is_direct",
    "resolve",
    "Origin",
    "Source",
    "RawPosting",
    "BoardError",
    "html_to_text",
    "make_client",
    "Greenhouse",
    "Ashby",
    "Lever",
    "Workday",
    "Amazon",
    "Eightfold",
    "JobBoard",
]
