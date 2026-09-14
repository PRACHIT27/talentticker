"""Find terms that are rising fast but are not in the skill dictionary yet.

The curated taxonomy only knows what we already thought to list. The whole
point of watching the market early is spotting the thing that was not on
anybody's list last quarter, so this module works the other way round: it
counts every phrase in recent postings, compares against an older baseline,
and surfaces whatever climbed.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta

from ..extract import clean, locations
from ..extract.taxonomy import SKILLS

WORD = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")

STOPWORDS = {
    "a", "about", "above", "across", "after", "all", "also", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "could", "did", "do",
    "does", "doing", "down", "during", "each", "few", "for", "from", "further",
    "had", "has", "have", "having", "he", "her", "here", "hers", "him", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "just", "me", "more",
    "most", "my", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
    "other", "our", "ours", "out", "over", "own", "same", "she", "should",
    "so", "some", "such", "than", "that", "the", "their", "theirs", "them",
    "then", "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "we", "were", "what", "when",
    "where", "which", "while", "who", "whom", "why", "will", "with", "would",
    "you", "your", "yours", "us", "shall", "may", "might", "must", "upon",
}

# Wording that appears in almost every posting and tells us nothing.
BOILERPLATE = {
    "equal opportunity", "opportunity employer", "regardless of race",
    "sexual orientation", "gender identity", "reasonable accommodation",
    "background check", "visa sponsorship", "full time", "years experience",
    "years of experience", "computer science", "bachelor degree",
    "bachelors degree", "master degree", "strong communication",
    "communication skills", "problem solving", "team player", "fast paced",
    "cross functional", "health insurance", "paid time", "time off",
    "stock options", "compensation package", "san francisco", "new york",
    "united states", "work closely", "we are looking", "you will",
    "the role", "our team", "the team", "this role", "job description",
    "apply now", "learn more", "click here", "base salary", "salary range",
    "total compensation", "life insurance", "parental leave", "401 k",
    "dental vision", "medical dental", "please note", "we believe",
    "our mission", "the company", "and more", "among others", "such as",
    "ability to", "experience with", "experience in", "familiarity with",
    "working with", "work with", "knowledge of", "understanding of",
    "proficiency in", "expertise in", "hands on", "nice to", "to have",
    "plus years", "or equivalent", "related field", "degree in",
}

GENERIC = {
    "experience", "team", "teams", "work", "working", "role", "company",
    "candidate", "candidates", "opportunity", "skills", "skill", "ability",
    "strong", "great", "good", "new", "help", "build", "building", "develop",
    "development", "design", "designing", "support", "make", "making", "use",
    "using", "including", "across", "within", "well", "like", "want", "need",
    "looking", "join", "please", "years", "year", "months", "month", "day",
    "days", "time", "people", "person", "business", "customer", "customers",
    "user", "users", "product", "products", "project", "projects", "process",
    "processes", "system", "systems", "solution", "solutions", "technology",
    "technologies", "technical", "software", "engineer", "engineering",
    "engineers", "developer", "developers", "code", "codebase", "quality",
    "best", "practices", "environment", "world", "global", "high", "level",
    "based", "full", "part", "one", "two", "three", "four", "five", "first",
    "second", "next", "every", "many", "much", "well", "even", "still", "yet",
    "office", "remote", "hybrid", "benefits", "salary", "equity", "bonus",
    "apply", "application", "applications", "resume", "interview", "hiring",
    "candidate", "employment", "employee", "employees", "position", "job",
    "jobs", "career", "careers", "responsibilities", "requirements",
    "qualifications", "preferred", "required", "must", "plus", "bonus",
    # Markup that survives a badly encoded description.
    "div", "span", "strong", "br", "li", "ul", "ol", "href", "nbsp", "amp",
    "https", "http", "www", "com", "font", "style", "class", "align", "img",
}

KNOWN_TERMS: set[str] = set()
for _canonical, (_cat, _aliases) in SKILLS.items():
    KNOWN_TERMS.add(_canonical.lower())
    for _alias in _aliases:
        if "\\" not in _alias:
            KNOWN_TERMS.add(_alias.lower())

# Capitalised words that are not technologies. Place names come straight from
# the location gazetteer, since "Dublin" and "Tokyo" pass the capitalisation
# test just as easily as "Terraform" does.
PLACES: set[str] = set(locations.CITIES) | set(locations.FOREIGN)
PLACES |= set(locations.FOREIGN_COUNTRIES) | set(locations.STATES)
PLACES |= {abbr.lower() for abbr in locations.STATE_ABBRS}

NOT_TECHNOLOGY = {
    "media", "revenue", "future", "operational", "programming", "law", "legal",
    "acquisition", "video", "grad", "finance", "accounting", "marketing",
    "sales", "operations", "strategy", "growth", "partner", "partners",
    "community", "culture", "values", "mission", "vision", "impact", "scale",
    "innovation", "excellence", "leadership", "management", "organization",
    "department", "division", "headquarters", "office", "campus", "america",
    "american", "english", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday", "january", "february", "march", "april",
    "may", "june", "july", "august", "september", "october", "november",
    "december", "bachelor", "bachelors", "master", "masters", "phd", "bs",
    "ms", "ba", "science", "computer", "engineering", "technology", "internet",
    "cloud", "data", "platform", "infrastructure", "security", "software",
    # HR, legal and recruiting vocabulary. These arrive capitalised in headings
    # and bullet lists, so the capitalisation test alone lets them through, and
    # they then dominate the list purely by being common. Adding new job
    # sources brought a fresh wave of it, which is what this block answers.
    "statement", "policy", "policies", "offer", "offers", "posting", "postings",
    "drug", "care", "schedule", "usage", "regulations", "regulation", "rules",
    "graduate", "graduates", "junior", "senior", "staff", "principal", "intern",
    "operate", "inclusion", "diversity", "equity", "belonging", "rewards",
    "holidays", "holiday", "sick", "discounts", "discount", "workplace",
    "eligible", "eligibility", "hire", "hiring", "notice", "applicant",
    "applicants", "disability", "veteran", "veterans", "accommodation",
    "accommodations", "reasonable", "harassment", "retaliation", "gender",
    "orientation", "religion", "ancestry", "citizenship", "immigration",
    "sponsorship", "visa", "relocation", "stipend", "bonus", "equity",
    "insurance", "wellness", "retirement", "pension", "leave", "pto",
    "onboarding", "referral", "referrals", "recruiter", "recruiting",
    "total rewards", "base", "range", "minimum", "maximum", "annual",
    "vacation", "flexible", "hybrid", "onsite", "background", "screening",
    # Corporate and process nouns. Same story: capitalised in headings, common
    # everywhere, and never the name of a technology.
    "administration", "maintenance", "responsible", "plan", "plans",
    "readiness", "corporate", "governance", "equipment", "integrity",
    "demands", "abilities", "details", "matter", "matters", "zero", "total",
    "type", "types", "stand", "search", "standards", "standard", "procedures",
    "procedure", "requirement", "controls", "control", "activities",
    "objectives", "initiatives", "stakeholders", "deliverables", "milestones",
    "priorities", "assignments", "duties", "tasks", "functions", "efforts",
    "conditions", "criteria", "guidelines", "specifications", "reports",
    "reporting", "coordination", "communications", "presentations",
}


TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#./-]*")
SENTENCE_END = re.compile(r"[.!?:;)\]]\s*$|^\s*$|[\n\-•]\s*$")


def _looks_named(token: str, at_sentence_start: bool) -> bool:
    """Is this word the name of a technology rather than ordinary English?

    Three shapes give a name away, and none of them describes a normal word:
      - all capitals, like MCP, SRE, AWS
      - a capital letter inside the word, like PyTorch, ClickHouse, gRPC
      - a plain capitalised word appearing mid-sentence, like Terraform

    That last rule is why sentence position matters. "Understands the system"
    starts a sentence with a capital and means nothing; "we use Terraform"
    capitalises mid-sentence and means everything.
    """
    if len(token) < 2:
        return False
    body = token.rstrip(".,")
    if not body:
        return False
    if body.isupper() and len(body) >= 2 and not body.isdigit():
        return True
    if any(c.isupper() for c in body[1:]):
        return True
    if body[0].isupper() and not at_sentence_start:
        return True
    return False


def _phrases(text: str, max_n: int = 3) -> set[str]:
    """Named technologies mentioned in one posting.

    Runs over the original text rather than a lowercased copy, because
    capitalisation is the strongest available clue that a word is a product
    name and not a verb.
    """
    if not text:
        return set()

    tokens: list[tuple[str, bool]] = []  # (token, qualifies as a name)
    for match in TOKEN.finditer(text):
        token = match.group(0)
        before = text[max(0, match.start() - 3) : match.start()]
        at_start = not before.strip() or bool(SENTENCE_END.search(before))
        tokens.append((token, _looks_named(token, at_start)))

    out: set[str] = set()
    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            window = tokens[i : i + n]
            if not all(named for _tok, named in window):
                continue
            words = [tok.strip(".,").lower() for tok, _ in window]
            if any(
                not w or w in STOPWORDS or w in GENERIC
                or w in PLACES or w in NOT_TECHNOLOGY
                for w in words
            ):
                continue
            phrase = " ".join(words)
            if phrase in BOILERPLATE or phrase in KNOWN_TERMS:
                continue
            if len(phrase) < 3 or phrase.replace(".", "").replace("-", "").isdigit():
                continue
            out.add(phrase)
    return out


def _document_frequency(
    conn, start: str, end: str, cap: int = 4000
) -> tuple[Counter, Counter, int]:
    """Count phrases by posting and by company.

    The company count is the one that matters. A single employer with a
    distinctive turn of phrase across twenty postings would otherwise look
    exactly like a genuine market-wide trend.
    """
    rows = conn.execute(
        """SELECT title, content, company_name FROM postings
           WHERE eligible=1 AND has_content=1 AND substr(first_published,1,10) >= ?
             AND substr(first_published,1,10) <= ?
           LIMIT ?""",
        (start, end, cap),
    ).fetchall()

    by_posting: Counter = Counter()
    seen_by_company: dict[str, set[str]] = {}
    for row in rows:
        body = clean.strip_boilerplate(row["content"] or "")
        found = _phrases(f"{row['title'] or ''}\n{body}")
        by_posting.update(found)
        company = row["company_name"] or "?"
        seen_by_company.setdefault(company, set()).update(found)

    by_company: Counter = Counter()
    for phrases in seen_by_company.values():
        by_company.update(phrases)
    return by_posting, by_company, len(rows)


def rising(
    conn,
    recent_days: int = 60,
    baseline_days: int = 240,
    min_recent: int = 4,
    min_companies: int = 3,
    limit: int = 40,
) -> list[dict]:
    """Phrases appearing far more often now than they used to.

    A phrase has to clear four bars: it must show up in a handful of recent
    postings, at several different companies, meaningfully more often than in
    the baseline period, and it must not already be a skill we track by name.

    The multiple-companies rule does most of the work. Without it the list
    fills up with one employer's house style repeated across every opening.
    """
    today = date.today()
    recent_start = (today - timedelta(days=recent_days)).isoformat()
    base_end = (today - timedelta(days=recent_days + 1)).isoformat()
    base_start = (today - timedelta(days=recent_days + baseline_days)).isoformat()

    recent, recent_companies, recent_docs = _document_frequency(
        conn, recent_start, today.isoformat()
    )
    base, _base_companies, base_docs = _document_frequency(conn, base_start, base_end)
    if not recent_docs:
        return []

    results = []
    for phrase, count in recent.items():
        if count < min_recent:
            continue
        if recent_companies.get(phrase, 0) < min_companies:
            continue
        recent_share = count / recent_docs
        # Appearing in nearly every posting means it is boilerplate we missed.
        if recent_share > 0.4:
            continue
        base_share = (base.get(phrase, 0) / base_docs) if base_docs else 0.0
        # Smoothing keeps a phrase with one historical mention from scoring
        # as an infinite increase.
        lift = (recent_share + 0.002) / (base_share + 0.002)
        if lift < 1.6:
            continue
        results.append({
            "phrase": phrase,
            "recent": count,
            "companies": recent_companies.get(phrase, 0),
            "recent_share": round(recent_share * 100, 2),
            "baseline": base.get(phrase, 0),
            "baseline_share": round(base_share * 100, 2),
            "lift": round(lift, 2),
            "is_new": base.get(phrase, 0) == 0,
        })

    results.sort(key=lambda r: (r["lift"], r["companies"], r["recent"]), reverse=True)
    return _dedupe(results)[:limit]


def _dedupe(rows: list[dict]) -> list[dict]:
    """Drop phrases that are contained in a stronger phrase already kept.

    Without this the list fills up with "context protocol", "model context"
    and "model context protocol" as three separate findings.
    """
    kept: list[dict] = []
    for row in rows:
        phrase = row["phrase"]
        if any(
            phrase != other["phrase"]
            and phrase in other["phrase"]
            and other["recent"] >= row["recent"] * 0.7
            for other in kept
        ):
            continue
        kept.append(row)
    return kept
