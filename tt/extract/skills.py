"""Find known skills in a job description."""
from __future__ import annotations

import re
from functools import lru_cache

from . import clean
from .taxonomy import SKILLS


def _alias_to_pattern(alias: str) -> str:
    """Turn one alias into a safe regex fragment.

    Aliases written with a backslash are already regular expressions and are
    used as-is. Plain words get escaped and fenced with lookarounds so that
    "react" does not fire inside "preact" and "java" does not fire inside
    "javascript".
    """
    if "\\" in alias:
        return alias
    # Allow a trailing plural. Job descriptions say "guardrails", "embeddings"
    # and "agent harnesses" far more often than the singular, and without this
    # the closing boundary rejects every one of them - "guardrail" was matching
    # 3 postings where the real figure is over a hundred.
    plural = r"(?:e?s)?" if alias[-1:].isalpha() else ""
    return r"(?<![\w+#.])" + re.escape(alias) + plural + r"(?![\w+#])"


@lru_cache(maxsize=1)
def _compiled() -> list[tuple[str, re.Pattern[str]]]:
    out = []
    for skill, (_category, aliases) in SKILLS.items():
        joined = "|".join(f"(?:{_alias_to_pattern(a)})" for a in aliases)
        out.append((skill, re.compile(joined, re.I)))
    return out


def extract(text: str, company_name: str = "") -> dict[str, int]:
    """Skills mentioned in the text, with how many times each appeared.

    The count is a weak signal of emphasis: a posting that says "Kubernetes"
    six times means it more than one that mentions it once.

    Pass `company_name` so that an employer's own name is not counted as a
    skill in its own postings - otherwise every Cloudflare job makes Cloudflare
    look like a soaring market-wide requirement.
    """
    if not text:
        return {}
    own = clean.company_terms(company_name)
    found: dict[str, int] = {}
    for skill, pattern in _compiled():
        if skill.lower() in own:
            continue
        hits = len(pattern.findall(text))
        if hits:
            found[skill] = hits
    return found


def skills_in_title(title: str) -> set[str]:
    """Skills named in the job title itself, which carry extra weight."""
    return set(extract(title or ""))
