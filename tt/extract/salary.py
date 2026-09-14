"""Pull a pay range out of a job description.

Several US states require the range to be printed in the posting, so this works
often enough to be useful even when the job board gives us no structured field.
"""
from __future__ import annotations

import re

# "$120,000 - $160,000", "$120K-$160K", "$120,000 to $160,000 USD"
#
# The amount is matched as one pattern with an optional K or M suffix. Written
# as an alternation the digits branch wins first, swallows "130" and leaves the
# "K" behind, so "$130K to $180K" silently fails to parse.
AMOUNT = r"\d[\d,]*(?:\.\d+)?\s*[KkMm]?"
RANGE = re.compile(
    rf"\$\s*({AMOUNT})\s*(?:-|–|—|to)\s*\$?\s*({AMOUNT})"
)
CONTEXT = re.compile(
    r"salary|compensation|pay|base|range|annual|\bocm\b|total target", re.I
)


def _to_number(token: str) -> int | None:
    token = token.strip().replace(",", "")
    multiplier = 1
    if token[-1:].lower() == "k":
        token = token[:-1].strip()
        multiplier = 1_000
    try:
        value = float(token) * multiplier
    except ValueError:
        return None
    return int(value)


def parse(text: str) -> tuple[int | None, int | None]:
    """Lowest and highest yearly figure that looks like a salary range."""
    if not text:
        return None, None
    best: tuple[int, int] | None = None
    for match in RANGE.finditer(text):
        window = text[max(0, match.start() - 200) : match.end() + 100]
        if not CONTEXT.search(window):
            continue
        low, high = _to_number(match.group(1)), _to_number(match.group(2))
        if low is None or high is None or low > high:
            continue
        # Filter out hourly rates and equity percentages.
        if low < 30_000 or high > 1_500_000:
            continue
        if best is None or high > best[1]:
            best = (low, high)
    return best if best else (None, None)
