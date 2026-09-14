"""Strip the parts of a posting that are not about the job.

Every description ends with the same few hundred words about benefits, equal
opportunity and pay transparency. Left in, they wreck the numbers: "medical,
dental and vision" made Healthcare look like the third most in-demand skill on
the board, and "compliance with applicable law" did the same for Compliance.

This module removes those passages before any counting happens.
"""
from __future__ import annotations

import re

# A paragraph matching one of these is boilerplate, not a description of work.
DROP_PARAGRAPH = re.compile(
    r"(equal\s+(?:employment\s+)?opportunit|"
    r"without\s+regard\s+to\s+race|regardless\s+of\s+race|"
    r"sexual\s+orientation|gender\s+identity|protected\s+veteran|"
    r"reasonable\s+accommodation|americans\s+with\s+disabilities|"
    r"e-?verify|background\s+check|drug\s+screen|"
    r"pay\s+transparency|salary\s+range|compensation\s+range|"
    r"base\s+pay\s+range|total\s+compensation|expected\s+salary|"
    r"medical,?\s+dental|dental,?\s+(?:and\s+)?vision|health\s+insurance|"
    r"401\s*\(?k\)?|paid\s+time\s+off|parental\s+leave|"
    r"commuter\s+benefit|wellness\s+stipend|flexible\s+spending|"
    r"life\s+insurance|disability\s+insurance|employee\s+stock|"
    r"privacy\s+(?:policy|notice)|applicant\s+privacy|"
    r"we\s+are\s+an\s+equal|fair\s+chance|ban\s+the\s+box|"
    r"recruitment\s+(?:agenc|fraud)|unsolicited\s+resum|"
    r"visa\s+sponsorship|export\s+control|"
    r"our\s+(?:benefits|perks)|perks\s+(?:and|&)\s+benefits|"
    r"benefits\s+(?:and|&)\s+perks|what\s+we\s+offer\s*:?\s*$)",
    re.I,
)

# Once we hit one of these headings, everything after it is boilerplate.
#
# Written loosely on purpose. Companies do not use a fixed set of headings -
# "Benefits", "Benefits and Growth:", "What We Offer You", "Perks & Culture"
# are all the same section, and an exact-match list missed most of them.
TAIL_MARKER = re.compile(
    r"^\s*[^\n]{0,70}?\b("
    r"benefits?|perks?|compensation|salary|total rewards|"
    r"equal opportunit|eeo|legal|disclaimer|"
    r"diversity|inclusion|pay transparency|e-?verify|privacy|"
    r"what we offer|why (?:join|work)|life at"
    r")\b[^\n]{0,40}:?\s*$",
    re.I,
)

# Sentences about benefits that sit inside an otherwise useful paragraph -
# typically the "about us" blurb - rather than under their own heading.
DROP_SENTENCE = re.compile(
    r"competitive (?:benefits|compensation|salary|pay)|"
    r"comprehensive benefits|benefits package|generous (?:pto|vacation|leave)|"
    r"invest heavily in our (?:teammates|people|employees)|"
    r"physical,? emotional,? and financial well-?being|"
    r"paid (?:holidays?|sick|time off|parental)",
    re.I,
)


def strip_boilerplate(content: str) -> str:
    """Remove benefits, legal and pay sections from a job description."""
    if not content:
        return ""
    paragraphs = re.split(r"\n\s*\n", content)
    kept: list[str] = []
    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            continue
        # A short line that is only a heading ends the useful part.
        if len(stripped) < 70 and TAIL_MARKER.match(stripped):
            break
        # Benefits wording inside a longer "about us" paragraph: drop just
        # those sentences and keep whatever the paragraph says about the work.
        if DROP_SENTENCE.search(stripped):
            sentences = re.split(r"(?<=[.!?])\s+", stripped)
            keep = [s for s in sentences if not DROP_SENTENCE.search(s)]
            stripped = " ".join(keep).strip()
            if not stripped:
                continue
        if DROP_PARAGRAPH.search(stripped):
            # Short paragraphs are pure boilerplate; long ones may still have
            # real content around the offending sentence, so drop by sentence.
            if len(stripped) < 600:
                continue
            sentences = re.split(r"(?<=[.!?])\s+", stripped)
            keep = [s for s in sentences if not DROP_PARAGRAPH.search(s)]
            if keep:
                kept.append(" ".join(keep))
            continue
        kept.append(stripped)
    return "\n\n".join(kept)


_WORD_SPLIT = re.compile(r"[^a-z0-9]+")


def company_terms(company_name: str) -> set[str]:
    """Words that are just the employer's own name.

    Cloudflare's postings say "Cloudflare" thirty times, which would otherwise
    make Cloudflare the most in-demand skill in the market.
    """
    if not company_name:
        return set()
    name = company_name.lower()
    terms = {name}
    for part in _WORD_SPLIT.split(name):
        if len(part) > 2 and part not in {"the", "inc", "llc", "labs", "ai", "com"}:
            terms.add(part)
    return terms


def prepare(content: str, company_name: str = "") -> str:
    """Description text ready for skill counting."""
    return strip_boilerplate(content)
