"""What companies are trying to solve, written in plain English by Claude.

Job descriptions state the problem outright - "you will build X because Y does
not scale" - but nobody reads four hundred of them. This module gathers the
relevant passages, asks Claude to name the recurring problems, and stores the
answer with links back to the postings it came from.

Two rules keep it honest:
  - every theme has to cite the postings it came from, so nothing is invented
  - results are cached against a hash of the input, so the same question is
    never paid for twice
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone

from .. import config
from ..extract import clean

log = logging.getLogger("tt.themes")

SYSTEM = """You read software job postings and work out what a company is \
actually trying to build or fix.

You are looking at postings for early-career software engineers, so the themes \
should be the kind of thing a new graduate would find useful when deciding what \
to learn or who to apply to.

Rules:
- Base every theme on what the postings actually say. Never guess or use \
outside knowledge about the company.
- Each theme must cite the posting ids it came from.
- Write plainly. No buzzwords, no marketing language, no filler. A theme titled \
"Leveraging synergistic AI transformation" is useless; "Moving payment fraud \
checks from batch jobs to real time" is useful.
- If the postings do not support a clear theme, return fewer themes. Three \
solid ones beat eight vague ones.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Two or three sentences on what this group is working on overall.",
        },
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short, concrete, under 10 words."},
                    "problem": {
                        "type": "string",
                        "description": "Two or three sentences on the problem being solved and why it matters now.",
                    },
                    "skills": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Skills the postings ask for in service of this theme.",
                    },
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ids of postings supporting this theme.",
                    },
                    "momentum": {"type": "string", "enum": ["new", "rising", "steady"]},
                },
                "required": ["title", "problem", "skills", "evidence_ids", "momentum"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "themes"],
    "additionalProperties": False,
}

# The parts of a posting that describe the work, rather than the benefits.
INTERESTING = re.compile(
    r"(what you(?:'| wi)ll (?:do|build|own)|about the (?:role|team|job)|"
    r"the (?:role|opportunity|team)|responsibilities|in this role|"
    r"you will|your impact|what you'll be doing|the challenge|why this)",
    re.I,
)
BORING = re.compile(
    r"(equal opportunity|benefits|compensation|salary range|"
    r"we offer|perks|accommodation|e-verify|privacy policy|"
    r"pay transparency|applicants with)",
    re.I,
)


def _relevant_excerpt(content: str, budget: int = 1400) -> str:
    """Keep the part of a posting that describes the work."""
    if not content:
        return ""
    # Drop benefits, legal and export-control passages before choosing what to
    # send, so none of the token budget is spent on text about nothing.
    content = clean.strip_boilerplate(content)
    chunks = [c.strip() for c in re.split(r"\n\s*\n", content) if c.strip()]
    scored: list[tuple[int, str]] = []
    for index, chunk in enumerate(chunks):
        if BORING.search(chunk):
            continue
        score = 0
        if INTERESTING.search(chunk):
            score += 3
        if index < 4:
            score += 1
        if len(chunk) > 200:
            score += 1
        scored.append((score, chunk))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    out, used = [], 0
    for _score, chunk in scored:
        if used >= budget:
            break
        take = chunk[: budget - used]
        out.append(take)
        used += len(take)
    return "\n".join(out)


COLUMNS = "id, title, company_name, team, department, metro, content, first_published"


def _gather(conn, scope: str, subject: str, window_days: int, limit: int) -> list[dict]:
    """The postings this write-up should be based on."""
    start = (date.today() - timedelta(days=window_days)).isoformat()
    where = "eligible=1 AND has_content=1 AND substr(first_published,1,10) >= ?"
    args: list = [start]

    if scope == "company":
        where += " AND company_slug = ?"
        args.append(subject)
    elif scope == "skill":
        where += " AND id IN (SELECT posting_id FROM posting_skills WHERE skill = ?)"
        args.append(subject)
    elif scope == "metro":
        where += " AND metro = ?"
        args.append(subject)

    args.append(limit)
    sql = (
        f"SELECT {COLUMNS} FROM postings WHERE {where} "
        f"ORDER BY first_published DESC LIMIT ?"
    )
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _build_prompt(rows: list[dict], label: str) -> str:
    parts = [f"Job postings for early-career software engineers at {label}.", ""]
    for row in rows:
        excerpt = _relevant_excerpt(row["content"] or "")
        if not excerpt:
            continue
        parts.append(f"--- posting id: {row['id']}")
        parts.append(f"title: {row['title']}")
        parts.append(f"company: {row['company_name']}")
        if row.get("team") or row.get("department"):
            parts.append(f"team: {row.get('team') or row.get('department')}")
        if row.get("metro"):
            parts.append(f"location: {row['metro']}")
        parts.append(f"posted: {(row.get('first_published') or '')[:10]}")
        parts.append(excerpt)
        parts.append("")
    parts.append(
        "Identify the recurring problems these postings are hiring to solve. "
        "Return between 3 and 6 themes, most significant first."
    )
    return "\n".join(parts)


def _client():
    """Build the Anthropic client, pinned to the real API by default.

    The SDK picks up ANTHROPIC_BASE_URL from the environment automatically, and
    some tooling sets that variable to its own local proxy. Inheriting it here
    sends these requests somewhere unexpected and fails in a way that looks like
    a bad key, so the endpoint is set explicitly unless TT_ANTHROPIC_BASE_URL
    says otherwise.
    """
    import anthropic

    if not config.ANTHROPIC_API_KEY:
        # The SDK also reads an `ant auth login` profile, so an unset key is
        # not necessarily an error - let it try.
        log.info("ANTHROPIC_API_KEY not set; relying on a stored credential profile")

    kwargs = {"base_url": config.ANTHROPIC_BASE_URL}
    if config.ANTHROPIC_API_KEY:
        kwargs["api_key"] = config.ANTHROPIC_API_KEY
    return anthropic.Anthropic(**kwargs)


def estimate(conn, scope: str = "market", subject: str = "",
             window_days: int = 45, limit: int = 40) -> dict:
    """Show what would be sent to Claude, and roughly what it would cost.

    Worth running before the first real call so there are no surprises on the
    bill. Opus 5 input is $5 per million tokens, output $25 per million.
    """
    rows = _gather(conn, scope, subject, window_days, limit)
    prompt = _build_prompt(rows, subject or "the US market")
    # Four characters per token is close enough for a cost estimate.
    input_tokens = (len(prompt) + len(SYSTEM)) // 4
    output_tokens = 2000
    cost = input_tokens / 1_000_000 * 5 + output_tokens / 1_000_000 * 25
    return {
        "postings": len(rows),
        "prompt_chars": len(prompt),
        "approx_input_tokens": input_tokens,
        "approx_cost_usd": round(cost, 4),
        "prompt": prompt,
    }


def build(
    conn,
    scope: str = "market",
    subject: str = "",
    window_days: int = 45,
    limit: int = 40,
    force: bool = False,
) -> dict:
    """Produce (or reuse) the theme write-up for one scope.

    scope is "market" for everything, "company" for one employer, or "skill"
    to ask what people are building with a particular technology.
    """
    label = subject or "companies across the US market"
    rows = _gather(conn, scope, subject, window_days, limit)
    if len(rows) < 3:
        return {
            "summary": "Not enough postings yet to say anything reliable.",
            "themes": [],
            "posting_count": len(rows),
            "cached": False,
        }

    key = f"{scope}:{subject}:{date.today().isoformat()[:7]}"
    fingerprint = hashlib.sha256(
        "|".join(sorted(r["id"] for r in rows)).encode()
    ).hexdigest()[:32]

    if not force:
        cached = conn.execute(
            "SELECT payload, input_hash, built_at FROM themes WHERE key=?", (key,)
        ).fetchone()
        if cached and cached["input_hash"] == fingerprint:
            payload = json.loads(cached["payload"])
            payload["cached"] = True
            payload["built_at"] = cached["built_at"]
            return payload

    prompt = _build_prompt(rows, label)
    client = _client()
    response = client.messages.create(
        model=config.MODEL,
        max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        thinking={"type": "adaptive"},
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        raise RuntimeError(f"Claude declined this request: {getattr(detail, 'explanation', '')}")

    text = next((b.text for b in response.content if b.type == "text"), "")
    payload = json.loads(text)

    # Attach readable evidence so the dashboard can link straight to the jobs.
    by_id = {r["id"]: r for r in rows}
    for theme in payload.get("themes", []):
        theme["evidence"] = [
            {
                "id": pid,
                "title": by_id[pid]["title"],
                "company": by_id[pid]["company_name"],
            }
            for pid in theme.get("evidence_ids", [])
            if pid in by_id
        ]

    payload["posting_count"] = len(rows)
    payload["cached"] = False
    payload["built_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["usage"] = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }

    conn.execute(
        "INSERT INTO themes (key, kind, subject, payload, built_at, input_hash) "
        "VALUES (?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
        "payload=excluded.payload, built_at=excluded.built_at, input_hash=excluded.input_hash",
        (key, scope, subject, json.dumps(payload), payload["built_at"], fingerprint),
    )
    return payload


def get_cached(conn, scope: str, subject: str = "") -> dict | None:
    key = f"{scope}:{subject}:{date.today().isoformat()[:7]}"
    row = conn.execute("SELECT payload FROM themes WHERE key=?", (key,)).fetchone()
    if not row:
        row = conn.execute(
            "SELECT payload FROM themes WHERE kind=? AND subject=? "
            "ORDER BY built_at DESC LIMIT 1",
            (scope, subject),
        ).fetchone()
    return json.loads(row["payload"]) if row else None
