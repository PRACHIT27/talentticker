"""Let Claude find skills the dictionary does not know about yet.

Why Claude proposes entries rather than doing the counting
---------------------------------------------------------

The obvious design is to hand every posting to a model and ask "what skills are
in here". It reads well and it is affordable - about $9 for a full pass on
Haiku. It is still the wrong shape for this product, for one reason.

A ticker measures *change*. That only means something if the measurement is
identical every time it runs. A model asked the same question twice can answer
"Kubernetes" once and "container orchestration" the next, and that shows up as
a skill collapsing by 100% when nothing in the market moved. Reprocessing - done
half a dozen times while building this - would give a different answer each run,
and month-over-month comparison quietly stops meaning anything.

So the work is split:

  Claude discovers.  It reads a sample of recent postings, is shown the names
                     already tracked, and proposes what is missing.
  The dictionary counts.  Deterministic, free, identical on every run.

The second benefit is the one that settles it. When a new skill is added to the
dictionary, `tt reprocess` applies it to all 34,000 stored postings at once, so
a newly discovered term arrives with twelve months of history already attached.
Per-posting extraction cannot do that without paying to re-read the whole
corpus every time the vocabulary changes.
"""
from __future__ import annotations

import json
import logging
import random
from datetime import date, timedelta

from .. import config
from ..extract import clean
from ..extract.taxonomy import SKILLS

log = logging.getLogger("tt.skill_discovery")

BATCH = 8          # postings per request
DEFAULT_SAMPLE = 120
MIN_COMPANIES = 3  # a term at one employer is house style, not a market trend

SYSTEM = """You identify technical skills in software job postings.

You will be given several postings and a list of skills that are already \
tracked. Your job is to find concrete technical skills in the postings that are \
NOT already on that list.

What counts:
- technologies, tools, frameworks, protocols, platforms
- specific engineering practices with a name ("chaos engineering", "trunk-based \
development")
- named techniques ("speculative decoding", "vector quantisation")

What does not count:
- anything already on the tracked list, including obvious synonyms of it
- soft skills, seniority words, benefits, company names, locations
- generic phrases that are not a skill ("fast-paced environment", \
"strong communicator", "cross-functional")
- a whole job family ("backend development") rather than a skill

For each skill you find, give the canonical name and the exact surface forms \
you saw in the text, so the phrase can be matched again later. Be strict: a \
short list of real findings is far more useful than a long list padded with \
generic wording."""

SCHEMA = {
    "type": "object",
    "properties": {
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Canonical name, as a person would write it.",
                    },
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exact lowercase surface forms seen in the text.",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["language", "frontend", "backend", "cloud", "infra",
                                 "data", "ai", "security", "design", "practice", "domain"],
                    },
                    "seen_in": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ids of the postings it appeared in.",
                    },
                },
                "required": ["name", "aliases", "category", "seen_in"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["skills"],
    "additionalProperties": False,
}


def _sample(conn, size: int, days: int) -> list[dict]:
    """Recent postings, spread across employers rather than clustered.

    A straight "newest N" would be most of one big employer's weekly batch, and
    the proposals would be that company's house vocabulary.
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = [
        dict(r)
        for r in conn.execute(
            """SELECT id, title, company_name, content FROM postings
               WHERE eligible=1 AND has_content=1
                 AND substr(first_published,1,10) >= ?""",
            (since,),
        ).fetchall()
    ]
    by_company: dict[str, list[dict]] = {}
    for row in rows:
        by_company.setdefault(row["company_name"], []).append(row)

    picked: list[dict] = []
    rng = random.Random(0)  # fixed seed so a dry run and the real run agree
    companies = sorted(by_company)
    rng.shuffle(companies)
    while len(picked) < size and companies:
        for company in list(companies):
            bucket = by_company[company]
            if not bucket:
                companies.remove(company)
                continue
            picked.append(bucket.pop(rng.randrange(len(bucket))))
            if len(picked) >= size:
                break
    return picked


def _prompt(batch: list[dict]) -> str:
    known = sorted(SKILLS)
    parts = [
        "Skills already tracked (do not repeat these or their synonyms):",
        ", ".join(known),
        "",
        "Postings:",
        "",
    ]
    for row in batch:
        body = clean.strip_boilerplate(row["content"] or "")[:3500]
        parts += [f"--- posting id: {row['id']}", f"title: {row['title']}", body, ""]
    return "\n".join(parts)


def _client():
    import anthropic

    kwargs = {"base_url": config.ANTHROPIC_BASE_URL}
    if config.ANTHROPIC_API_KEY:
        kwargs["api_key"] = config.ANTHROPIC_API_KEY
    return anthropic.Anthropic(**kwargs)


def estimate(conn, sample: int = DEFAULT_SAMPLE, days: int = 60) -> dict:
    rows = _sample(conn, sample, days)
    batches = [rows[i : i + BATCH] for i in range(0, len(rows), BATCH)]
    chars = sum(len(_prompt(b)) for b in batches)
    tokens = chars // 4
    return {
        "postings": len(rows),
        "requests": len(batches),
        "approx_input_tokens": tokens,
        "approx_cost_usd": round(tokens / 1e6 * 5 + len(batches) * 700 / 1e6 * 25, 3),
    }


def run(conn, sample: int = DEFAULT_SAMPLE, days: int = 60,
        min_companies: int = MIN_COMPANIES) -> dict:
    """Ask Claude what is missing from the dictionary."""
    rows = _sample(conn, sample, days)
    if not rows:
        return {"proposals": [], "postings": 0, "requests": 0, "usage": {}}

    company_of = {r["id"]: r["company_name"] for r in rows}
    batches = [rows[i : i + BATCH] for i in range(0, len(rows), BATCH)]
    client = _client()

    found: dict[str, dict] = {}
    tokens_in = tokens_out = 0

    for index, batch in enumerate(batches, 1):
        log.info("skill discovery: batch %d of %d", index, len(batches))
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=8000,
            system=[{"type": "text", "text": SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            thinking={"type": "adaptive"},
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": _prompt(batch)}],
        )
        tokens_in += response.usage.input_tokens
        tokens_out += response.usage.output_tokens
        if response.stop_reason == "refusal":
            continue

        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            log.warning("batch %d returned unparseable JSON", index)
            continue

        for item in payload.get("skills", []):
            name = (item.get("name") or "").strip()
            if not name or name.lower() in {s.lower() for s in SKILLS}:
                continue
            entry = found.setdefault(
                name,
                {"name": name, "category": item.get("category", "practice"),
                 "aliases": set(), "postings": set(), "companies": set()},
            )
            for alias in item.get("aliases", []):
                cleaned = (alias or "").strip().lower()
                if 2 < len(cleaned) < 40:
                    entry["aliases"].add(cleaned)
            for posting_id in item.get("seen_in", []):
                entry["postings"].add(posting_id)
                if posting_id in company_of:
                    entry["companies"].add(company_of[posting_id])

    proposals = [
        {
            "name": e["name"],
            "category": e["category"],
            "aliases": sorted(e["aliases"]),
            "postings": len(e["postings"]),
            "companies": len(e["companies"]),
        }
        for e in found.values()
        if len(e["companies"]) >= min_companies and e["aliases"]
    ]
    proposals.sort(key=lambda p: (p["companies"], p["postings"]), reverse=True)

    return {
        "proposals": proposals,
        "rejected": len(found) - len(proposals),
        "postings": len(rows),
        "requests": len(batches),
        "usage": {
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "cost_usd": round(tokens_in / 1e6 * 5 + tokens_out / 1e6 * 25, 3),
        },
    }
