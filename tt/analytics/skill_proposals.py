"""Propose new dictionary entries without calling any model.

Claude Code and chat subscriptions do not include API credit - they are billed
separately - so anything that depends on an API key has to be optional. This
module does the same job as skill_discovery.py for nothing.

It reuses the phrase miner from emerging.py, which already does most of the
work: it strips boilerplate, keeps only capitalised technology names, ignores
places and generic words, and requires a term to appear at several different
companies before it counts. What this adds is the last step - turning the
survivors into dictionary entries, with the counts measured across the whole
corpus rather than just the recent window.

The trade against the Claude version is honest: this finds *named things*
(Karpenter, CrowdStrike, Jamf) reliably, because capitalisation gives them
away. It will not spot an unnamed concept written in lower case, like "canary
analysis" or "blue-green deploys". Claude catches those. For the price
difference - free against $0.81 a run - this is the sensible default, and
`--ai` is there when there is credit to spend.
"""
from __future__ import annotations

import re
from ..extract.taxonomy import SKILLS
from . import emerging

# Rough category guesses from the shape of the term. Deliberately crude - the
# category only groups rows in a dropdown, and a wrong guess is easy to fix by
# hand in the YAML file.
CATEGORY_HINTS: list[tuple[str, str]] = [
    (r"agent|llm|model|prompt|embedding|inference|rag|eval|token|fine.?tun|"
     r"gpu|cuda|tensor|neural|vector", "ai"),
    (r"kubernetes|docker|terraform|ansible|helm|cluster|deploy|ci|pipeline|"
     r"observab|telemetry|grafana|prometheus|karpenter|istio", "infra"),
    (r"aws|azure|gcp|cloud|lambda|s3|ec2|serverless", "cloud"),
    (r"sql|database|warehouse|kafka|spark|airflow|etl|snowflake|postgres|"
     r"clickhouse|redis|mongo", "data"),
    (r"react|vue|angular|svelte|css|tailwind|frontend|browser|ui", "frontend"),
    (r"security|auth|oauth|saml|oidc|siem|crowdstrike|jamf|kandji|entra|"
     r"vault|encrypt|threat|vulnerab|mdm|okta|zero.?trust", "security"),
    (r"api|rest|grpc|graphql|microservice|queue|cache|scal|latency|"
     r"availability|shard|replica", "design"),
    (r"test|agile|scrum|review|document|mentor|incident|oncall", "practice"),
]


def _guess_category(phrase: str) -> str:
    for pattern, category in CATEGORY_HINTS:
        if re.search(pattern, phrase, re.I):
            return category
    return "practice"


def run(conn, limit: int = 40, min_companies: int = 4, min_postings: int = 8) -> dict:
    """Candidate dictionary entries, found statistically and free of charge.

    The counts come straight from the miner. An earlier version re-counted each
    candidate across the whole corpus case-insensitively, which quietly undid
    the capitalisation test that makes the miner work: "Matter" then matched
    every lower-case "matter" and the list filled with ordinary English ranked
    by sheer frequency. The miner's own numbers are the ones to trust.
    """
    known = {name.lower() for name in SKILLS}
    for _category, aliases in SKILLS.values():
        for alias in aliases:
            if "\\" not in alias:
                known.add(alias.lower())

    rising = emerging.rising(conn, limit=200, min_companies=min_companies)

    proposals = []
    for row in rising:
        phrase = row["phrase"]
        if phrase.lower() in known or len(phrase) < 3:
            continue
        if row["recent"] < min_postings or row["companies"] < min_companies:
            continue
        proposals.append({
            # Acronyms stay upper case; everything else gets title case, which
            # is how these read on the dashboard.
            "name": phrase.upper() if len(phrase) <= 4 and " " not in phrase
                    else phrase.title(),
            "category": _guess_category(phrase),
            "aliases": [phrase],
            "postings": row["recent"],
            "companies": row["companies"],
            "lift": row["lift"],
        })

    # Rank by how many different employers use the term. One company saying it
    # twenty times is house style; eight companies saying it is a trend.
    proposals.sort(key=lambda p: (p["companies"], p["lift"]), reverse=True)
    return {"proposals": proposals[:limit], "considered": len(rising)}
