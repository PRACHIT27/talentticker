"""Decide whether a posting is a software job aimed at 0-4 years of experience.

Everything else in the product sits on top of this filter, so it is written to
be explainable: every decision comes back with a short reason string you can
read in the database when a result looks wrong.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --- Is this a software engineering role? ------------------------------------

def _profile():
    from ..profiles import active
    return active()


# The lists below are the software-engineering defaults. A profile overrides
# them, which is what lets the same machinery run for product management or any
# other role without touching this file.
SWE_TITLE_TERMS = [
    "software engineer", "software developer", "software development engineer",
    "backend engineer", "back end engineer", "back-end engineer",
    "frontend engineer", "front end engineer", "front-end engineer",
    "full stack", "fullstack", "full-stack",
    "web engineer", "web developer", "application engineer", "applications engineer",
    "mobile engineer", "ios engineer", "android engineer", "ios developer",
    "android developer", "mobile developer",
    "platform engineer", "infrastructure engineer", "systems engineer",
    "site reliability", "devops engineer", "cloud engineer", "network engineer",
    "security engineer", "product security", "application security",
    "data engineer", "analytics engineer", "machine learning engineer",
    "ml engineer", "ai engineer", "mlops", "research engineer",
    "embedded engineer", "embedded software", "firmware engineer",
    "qa engineer", "test engineer", "engineer in test", "automation engineer",
    "developer", "programmer", "engineer i", "engineer ii",
    "computer scientist", "compiler engineer", "graphics engineer",
    "distributed systems", "database engineer", "performance engineer",
    "tools engineer", "game engineer", "blockchain engineer", "protocol engineer",
]

# Titles that contain "engineer" but are not software jobs.
NOT_SWE_TITLE_TERMS = [
    "sales engineer", "solutions engineer", "solution engineer",
    "customer engineer", "support engineer", "field engineer",
    "implementation engineer", "deployment engineer", "forward deployed",
    "mechanical engineer", "electrical engineer", "civil engineer",
    "chemical engineer", "industrial engineer", "manufacturing engineer",
    "process engineer", "hardware engineer", "rf engineer", "optical engineer",
    "materials engineer", "structural engineer", "biomedical engineer",
    "facilities", "recruiter", "recruiting", "sourcer", "account executive",
    "account manager", "sales", "marketing", "designer", "content",
    "counsel", "attorney", "paralegal", "accountant", "controller",
    "people operations", "talent", "chief of staff", "executive assistant",
    "product manager", "program manager", "project manager", "product marketing",
    "technical writer", "technical program", "customer success",
    "data scientist",  # tracked separately; not a software engineering title
    "data analyst", "business analyst", "financial analyst",
    "engineering manager", "recruiting coordinator",
]

ENGINEERING_DEPARTMENTS = [
    "engineering", "technology", "technical", "r&d", "research and development",
    "product development", "software", "infrastructure", "platform", "security",
    "data", "machine learning", "artificial intelligence", "it",
]

# --- Seniority signals --------------------------------------------------------

# Executive roles. Never early career under any profile - a Director of Product
# is not an entry point even though "product" profiles have to allow "manager".
EXECUTIVE_TITLE = re.compile(
    r"\b(director|vp|vice\s+president|chief|president|head\s+of|"
    r"distinguished|fellow|executive|partner)\b",
    re.I,
)

# People management. Out of scope for engineering, but "Product Manager" is the
# job title itself, so profiles whose own title terms contain "manager" skip
# this one and rely on EXECUTIVE_TITLE plus the seniority words instead.
PEOPLE_MANAGER_TITLE = re.compile(r"\b(manager|management)\b", re.I)

# Kept for callers that imported the old name.
MANAGEMENT_TITLE = re.compile(
    r"\b(manager|director|vp|vice\s+president|chief|president|head\s+of|"
    r"distinguished|fellow|executive)\b",
    re.I,
)

# Senior individual-contributor wording. Usually out of range, but a posting
# that asks for three years is worth keeping even if it says "Senior".
SENIOR_IC_TITLE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|leader|head|architect|"
    r"expert|advanced|founding|group|gpm)\b",
    re.I,
)

# Roman numerals and level codes that usually sit beyond four years.
TOO_SENIOR_LEVEL = re.compile(
    r"\b(iii|iv|v|3|4|5)\b(?!\s*(?:months|weeks))|"
    r"\b(l[5-9]|e[5-9]|ic[3-9]|p[4-9]|t[5-9]|sde\s*(?:iii|3))\b",
    re.I,
)

EARLY_CAREER_TITLE = re.compile(
    r"\b("
    r"new\s*grad(?:uate)?|university\s+grad(?:uate)?|college\s+grad(?:uate)?|"
    r"entry[\s-]*level|early[\s-]*career|early[\s-]*in[\s-]*career|junior|jr\.?|"
    r"associate|campus|apprentice|rotational|graduate\s+(?:program|engineer)|"
    r"l3|e3|ic1|ic2|sde\s*(?:i|1)\b|engineer\s*(?:i|1)\b|"
    r"level\s*(?:1|2|one|two)"
    r")\b",
    re.I,
)

INTERNSHIP_TITLE = re.compile(
    r"\b(intern|internship|co[\s-]?op|summer\s+(?:analyst|associate|program))\b", re.I
)

# --- Years of experience ------------------------------------------------------

WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
}
_NUM = r"(\d{1,2}|zero|one|two|three|four|five|six|seven|eight|nine|ten|twelve)"

# "3-5 years", "3 to 5 years"
RANGE_PAT = re.compile(rf"{_NUM}\s*(?:-|–|—|to)\s*{_NUM}\s*\+?\s*(?:yrs?|years?)", re.I)
# "3+ years", "at least 3 years", "minimum of 3 years", "3 years of experience"
MIN_PAT = re.compile(
    rf"(?:(?:at\s+least|minimum\s+(?:of\s+)?|min\.?\s*|over|more\s+than|"
    rf"greater\s+than)\s*)?{_NUM}\s*(?:\+|plus)?\s*(?:yrs?|years?)",
    re.I,
)
# Only trust a year count when experience is being discussed nearby.
EXPERIENCE_CONTEXT = re.compile(
    r"experience|exp\b|background|working|professional|industry|building|"
    r"development|engineering|relevant|practical|hands[\s-]?on|"
    # Wording used outside engineering. "1-3 years in a product role" contains
    # none of the words above, so the requirement went unread and a mid-level
    # product job was kept as though it had stated nothing.
    r"role|product|managing|leading|shipping|owning|track record|career|"
    r"in a similar|equivalent",
    re.I,
)

# Years that are not years of experience. Amazon opens every posting with
# "Are 18 years of age or older", and the word "Experience" sits in the very
# next bullet - close enough that a context check alone reads it as eighteen
# years of experience and throws the role out.
NOT_EXPERIENCE_YEARS = re.compile(
    r"\s*(?:years?\s*)?(?:of\s+age|old\b|or older|and older|age\s+of)"
    r"|^\s*(?:years?\s+)?(?:of\s+)?(?:vacation|pto|paid time|tenure|warranty|"
    r"history|operation|service award)",
    re.I,
)
# Phrases that mean no experience is required.
NO_EXPERIENCE = re.compile(
    r"\b(no\s+(?:prior\s+)?experience\s+(?:is\s+)?(?:required|necessary)|"
    r"0\s*(?:-|to)\s*\d\s*years|"
    r"final\s+year|graduating|expected\s+graduation|currently\s+(?:enrolled|pursuing))\b",
    re.I,
)

# A required doctorate puts a role outside early career. "PhD preferred" or
# "PhD or equivalent experience" does not, so those are excluded from the match.
PHD_REQUIRED = re.compile(
    r"\b(ph\.?d\.?|doctorate)\b(?![^.]{0,60}\b(preferred|nice to have|"
    r"a plus|or equivalent|not required|bonus)\b)"
    r"[^.]{0,60}\b(required|must have|minimum)\b|"
    r"\b(required|must have)\b[^.]{0,40}\b(ph\.?d\.?|doctorate)\b",
    re.I,
)

# Above this base salary a role is not an early-career opening, whatever the
# title says. Used only when the posting states no years of experience, as a
# backstop against senior research and staff roles that mention neither.
SENIOR_PAY_FLOOR = 250_000


def _to_int(token: str) -> int | None:
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return WORD_NUMBERS.get(token)


def parse_years(text: str) -> tuple[float | None, float | None]:
    """Smallest and largest years-of-experience figure the posting asks for.

    A description often lists several numbers ("3+ years required, 5+ years
    preferred"). The smallest one is the real bar to clear, so that is what we
    treat as the requirement.
    """
    if not text:
        return None, None

    found: list[int] = []
    highs: list[int] = []

    for match in RANGE_PAT.finditer(text):
        window = text[max(0, match.start() - 120) : match.end() + 120]
        if not EXPERIENCE_CONTEXT.search(window):
            continue
        low, high = _to_int(match.group(1)), _to_int(match.group(2))
        if low is not None and 0 <= low <= 30:
            found.append(low)
        if high is not None and 0 <= high <= 30:
            highs.append(high)

    for match in MIN_PAT.finditer(text):
        # What comes straight after decides whether this is an age, a holiday
        # allowance, or an actual experience requirement.
        if NOT_EXPERIENCE_YEARS.match(text[match.end() : match.end() + 30]):
            continue
        window = text[max(0, match.start() - 120) : match.end() + 120]
        if not EXPERIENCE_CONTEXT.search(window):
            continue
        value = _to_int(match.group(1))
        if value is None or not 0 <= value <= 30:
            continue
        found.append(value)

    if not found:
        return None, None
    return float(min(found)), float(max(highs or found))


@dataclass
class Verdict:
    is_swe: bool
    eligible: bool
    yoe_min: float | None
    yoe_max: float | None
    level: str
    reason: str
    confidence: float


def classify(
    title: str,
    content: str,
    department: str = "",
    max_years: float | None = None,
    salary_min: int | None = None,
) -> Verdict:
    """Judge one posting against the active role profile.

    Returns why, so bad calls can be traced in the database.
    """
    profile = _profile()
    wanted = profile.title_terms or SWE_TITLE_TERMS
    unwanted = profile.exclude_titles or NOT_SWE_TITLE_TERMS
    departments = profile.departments or ENGINEERING_DEPARTMENTS
    if max_years is None:
        max_years = profile.max_years

    title_l = (title or "").lower()
    dept_l = (department or "").lower()
    body = content or ""

    # 1. Rule out roles that are a different job.
    for term in unwanted:
        if term in title_l:
            return Verdict(False, False, None, None, "", f"excluded: title has '{term}'", 0.9)

    in_scope = any(term in title_l for term in wanted)
    if not in_scope and "engineer" in title_l and profile.name == "swe":
        # Generic engineering title - trust the department to break the tie.
        in_scope = any(d in dept_l for d in departments)
    if not in_scope:
        return Verdict(False, False, None, None, "", "title outside this profile", 0.7)

    # 2. Internships are a different product; flag and skip.
    if INTERNSHIP_TITLE.search(title_l):
        return Verdict(True, False, None, None, "intern", "internship", 0.95)

    yoe_min, yoe_max = parse_years(body)
    early = bool(EARLY_CAREER_TITLE.search(title_l))
    level = "early" if early else ""

    # 3a. Management and executive titles are out regardless of stated years -
    #     unless the profile is itself a management role. "Product Manager" is
    #     the job, not a sign of seniority, so the rule has to know that.
    role_is_managerial = any(
        "manager" in term or "management" in term for term in wanted
    )
    # Executives are out under every profile.
    if EXECUTIVE_TITLE.search(title_l):
        return Verdict(True, False, yoe_min, yoe_max, "executive", "executive title", 0.95)
    # People-manager titles are out unless managing is the job.
    if not role_is_managerial and PEOPLE_MANAGER_TITLE.search(title_l):
        return Verdict(True, False, yoe_min, yoe_max, "management", "management title", 0.95)

    # 3b. Senior individual-contributor wording, unless the posting itself
    #     states a requirement of four years or less.
    if SENIOR_IC_TITLE.search(title_l):
        if yoe_min is not None and yoe_min <= max_years:
            return Verdict(
                True, True, yoe_min, yoe_max, "senior-titled",
                f"senior title but asks for only {yoe_min:g} years", 0.5,
            )
        return Verdict(True, False, yoe_min, yoe_max, "senior", "senior title", 0.9)

    # 4. Level numbers past the second rung.
    tail = title_l.split("engineer")[-1] if "engineer" in title_l else title_l
    if TOO_SENIOR_LEVEL.search(tail):
        if not early:
            return Verdict(True, False, yoe_min, yoe_max, "leveled", "level above II", 0.7)

    # 5. Explicit years requirement.
    if yoe_min is not None:
        if yoe_min <= max_years:
            return Verdict(
                True, True, yoe_min, yoe_max, level or "mid",
                f"asks for {yoe_min:g} years", 0.95,
            )
        return Verdict(
            True, False, yoe_min, yoe_max, "experienced",
            f"asks for {yoe_min:g} years", 0.95,
        )

    # 6. No years stated. Early-career wording in the title is enough.
    if early:
        return Verdict(True, True, 0.0, None, "early", "early career title", 0.9)
    if NO_EXPERIENCE.search(body):
        return Verdict(True, True, 0.0, None, "early", "states no experience needed", 0.85)

    # 7. Nothing stated. Two backstops catch senior roles that name neither a
    #    seniority word nor a number of years - most often research positions.
    if PHD_REQUIRED.search(body):
        return Verdict(True, False, None, None, "advanced", "doctorate required", 0.8)
    if salary_min and salary_min >= SENIOR_PAY_FLOOR:
        return Verdict(
            True, False, None, None, "senior",
            f"pay starts at ${salary_min:,}, above early-career range", 0.8,
        )

    # 8. A plain "Software Engineer" with no stated bar is usually open to
    #    early-career candidates, so keep it but mark the lower confidence.
    return Verdict(True, True, None, None, "unspecified", "no years stated", 0.5)
