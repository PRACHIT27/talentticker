"""Work out which industry a posting belongs to.

Two ways, in order of trust:

  1. The company's own entry in companies.yml. A job at Stripe is fintech
     whatever the description happens to say, so this is used whenever it is
     available.
  2. Keywords in the description, for companies nobody has mapped yet. Less
     reliable, so it needs several matching words before it commits.
"""
from __future__ import annotations

import re

# Sector -> words that suggest it. Written to be specific: "patient" and
# "clinical" mean healthcare, while "health" on its own means the benefits
# paragraph.
SECTOR_TERMS: dict[str, list[str]] = {
    "AI": [
        "large language model", "foundation model", "generative ai",
        "machine learning platform", "inference", "model training",
        "fine-tuning", "ai research", "agentic", "ai agent", "llm",
        "neural network", "transformer model", "prompt",
    ],
    "Fintech": [
        "payments", "payment processing", "banking", "lending", "credit",
        "underwriting", "fraud detection", "trading", "brokerage",
        "financial services", "ledger", "settlement", "cryptocurrency",
        "blockchain", "money movement", "compliance and risk", "kyc",
        "anti-money laundering", "card issuing", "treasury",
    ],
    "Healthcare": [
        "patient", "clinical", "electronic health record", "ehr", "provider network",
        "payer", "claims processing", "hipaa", "diagnosis", "therapeutic",
        "life sciences", "drug discovery", "genomic", "medical device",
        "care delivery", "health system", "telehealth",
    ],
    "Security": [
        "threat detection", "vulnerability", "penetration testing", "malware",
        "security operations", "zero trust", "identity provider",
        "endpoint security", "intrusion", "incident response", "soc 2",
        "cloud security posture", "application security",
    ],
    "Data Infrastructure": [
        "data warehouse", "query engine", "distributed database", "columnar",
        "data pipeline", "stream processing", "data lake", "storage engine",
        "etl", "orchestration", "catalog", "lakehouse",
    ],
    "Developer Tools": [
        "developer experience", "developer tools", "ci/cd", "build system",
        "observability platform", "code editor", "sdk", "api platform",
        "internal tooling", "deployment platform", "monitoring platform",
    ],
    "Gaming": [
        "game engine", "gameplay", "player experience", "multiplayer",
        "game development", "unreal", "matchmaking", "live ops",
    ],
    "Mobility & Robotics": [
        "autonomous vehicle", "self-driving", "robotics", "perception",
        "motion planning", "lidar", "fleet", "battery", "drivetrain",
        "electric vehicle", "drone",
    ],
    "Aerospace & Defense": [
        "spacecraft", "satellite", "aerospace", "defense", "mission systems",
        "orbital", "launch vehicle", "national security", "classified",
        "avionics", "radar",
    ],
    # "catalog", "inventory" and "order management" were removed: they are
    # ordinary software words and were dropping banks and hardware firms into
    # Marketplace.
    "Marketplace": [
        "marketplace", "e-commerce", "ecommerce", "checkout experience",
        "merchant", "seller experience", "buyer", "fulfillment center",
        "online store", "shopping experience", "storefront",
    ],
    "Cloud Infrastructure": [
        "cloud platform", "public cloud", "compute service", "virtualization",
        "kubernetes platform", "container platform", "cloud native",
        "multi-tenant", "control plane", "region launch",
    ],
    "Education": [
        "learner", "curriculum", "coursework", "student", "edtech",
        "learning platform", "instructor",
    ],
    "Consumer": [
        "social network", "creator", "streaming", "content moderation",
        "feed ranking", "subscriber", "media playback", "recommendation feed",
    ],
    "Productivity": [
        "collaboration", "workflow automation", "crm", "hr platform",
        "payroll", "document editing", "project management", "workspace",
        "customer engagement", "marketing automation",
    ],
    "Logistics": [
        "supply chain", "freight", "shipment", "warehouse management",
        "route optimization", "carrier", "customs",
    ],
}

_PATTERNS: dict[str, re.Pattern[str]] = {
    sector: re.compile("|".join(rf"\b{re.escape(t)}\b" for t in terms), re.I)
    for sector, terms in SECTOR_TERMS.items()
}

UNKNOWN = "Unclassified"


def from_content(text: str, min_hits: int = 3) -> str:
    """Guess a sector from the job description.

    Only used when the company has no sector in companies.yml. The threshold
    keeps a single passing mention of "payments" from labelling a whole company
    as fintech.
    """
    if not text:
        return UNKNOWN
    scores: dict[str, int] = {}
    for sector, pattern in _PATTERNS.items():
        hits = len(pattern.findall(text))
        if hits:
            scores[sector] = hits
    if not scores:
        return UNKNOWN
    best, count = max(scores.items(), key=lambda kv: kv[1])
    return best if count >= min_hits else UNKNOWN


# Business units inside conglomerates.
#
# A single label per company breaks down at the big ones. Amazon was filed
# under Marketplace, but 572 of its 1,042 early-career roles are AWS - cloud
# infrastructure, not shopping - so "Marketplace" was really just "Amazon", and
# anyone reading the sector page got a wrong answer about both. Where a posting
# names its business unit, that wins over the company default.
TEAM_SECTORS: dict[str, str] = {
    "aws": "Cloud Infrastructure",
    "amazon web services": "Cloud Infrastructure",
    "azure": "Cloud Infrastructure",
    "google cloud": "Cloud Infrastructure",
    "alexa": "Consumer",
    "amazon devices": "Consumer",
    "entertainment": "Consumer",
    "prime video": "Consumer",
    "advertising": "Advertising",
    "ads": "Advertising",
    "security": "Security",
    "trust and safety": "Security",
    "health": "Healthcare",
    "payments": "Fintech",
    "lending": "Fintech",
    "robotics": "Mobility & Robotics",
    "autonomous": "Mobility & Robotics",
    "space": "Aerospace & Defense",
    "defense": "Aerospace & Defense",
    "gaming": "Gaming",
    "games": "Gaming",
}


def from_team(team: str) -> str:
    """Sector implied by the business unit a posting belongs to."""
    if not team:
        return ""
    lowered = team.lower().replace("-", " ").replace("_", " ")
    for needle, sector in TEAM_SECTORS.items():
        if re.search(rf"(^|\W){re.escape(needle)}(\W|$)", lowered):
            return sector
    return ""


def resolve(
    company_sector: str | None,
    content: str,
    team: str = "",
    department: str = "",
) -> str:
    """The sector for one posting.

    Order of trust: the business unit named on the posting, then the company's
    entry in companies.yml, then a guess from the description.
    """
    unit = from_team(team) or from_team(department)
    if unit:
        return unit
    if company_sector and company_sector.strip():
        return company_sector.strip()
    return from_content(content)
