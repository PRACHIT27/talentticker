"""Role profiles - what "a job I care about" means.

Everything in this project except two things is role-agnostic. Reading job
boards, parsing locations and pay, detecting sponsorship, grouping by sector,
alerting, the map, the charts - none of that knows or cares whether a posting
is for an engineer.

The two parts that do are:

  1. which titles count, and what experience range is in scope
  2. which skills to look for

So those move into a profile, and the rest stays exactly as it is. A profile is
a YAML file in `data/profiles/`. Pick one with `TT_PROFILE=product`.

Each profile gets its own database. That is deliberate: `eligible` means
something different per profile, and sharing one table would mean every query
carrying a profile filter and one wrong join quietly mixing product roles into
the engineering figures. Separate files cost a little repeated fetching and
remove a whole class of bug.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "data" / "profiles"
DEFAULT = "swe"


@dataclass
class Profile:
    name: str
    label: str                      # shown in the dashboard header
    description: str = ""
    max_years: float = 4.0
    title_terms: list[str] = field(default_factory=list)
    exclude_titles: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    # What to type into the search box on boards that will not list everything
    # (Workday, Eightfold). Wrong terms here mean whole boards return nothing.
    search_terms: list[str] = field(default_factory=list)
    # Skill dictionaries to load, as file names under data/skills/.
    skill_sets: list[str] = field(default_factory=list)
    # Set when the profile uses the software dictionary written in taxonomy.py.
    include_builtin_skills: bool = True
    # Readers this profile should not bother with. The community new-grad
    # lists on GitHub are software-engineering lists, so a product run fetches
    # 446 rows from them and keeps none of it.
    exclude_sources: list[str] = field(default_factory=list)
    # Override a reader's board token per profile. Amazon's token is a job
    # category, and it was pinned to "Software Development" - so the product
    # profile was asking Amazon for software jobs and, unsurprisingly, finding
    # one product role in 2,601 postings. Several categories can be given,
    # separated by a pipe.
    source_tokens: dict = field(default_factory=dict)
    # Who gets the alerts for this profile. Falls back to TT_ALERT_TO.
    # Needed as soon as two people share one installation.
    alert_to: str = ""

    @property
    def db_name(self) -> str:
        return "talentticker.db" if self.name == DEFAULT else f"talentticker-{self.name}.db"


def available() -> list[str]:
    if not PROFILE_DIR.exists():
        return [DEFAULT]
    return sorted(p.stem for p in PROFILE_DIR.glob("*.yml"))


@lru_cache(maxsize=8)
def load(name: str | None = None) -> Profile:
    name = (name or os.getenv("TT_PROFILE") or DEFAULT).strip().lower()
    path = PROFILE_DIR / f"{name}.yml"
    if not path.exists():
        known = ", ".join(available())
        raise SystemExit(
            f"unknown profile {name!r}. Available: {known}\n"
            f"Profiles live in {PROFILE_DIR}"
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Profile(
        name=name,
        label=data.get("label") or name,
        description=data.get("description", ""),
        max_years=float(data.get("max_years", 4)),
        title_terms=[t.lower() for t in data.get("title_terms") or []],
        exclude_titles=[t.lower() for t in data.get("exclude_titles") or []],
        departments=[t.lower() for t in data.get("departments") or []],
        search_terms=data.get("search_terms") or [],
        skill_sets=data.get("skill_sets") or [],
        include_builtin_skills=bool(data.get("include_builtin_skills", True)),
        exclude_sources=[a.lower() for a in data.get("exclude_sources") or []],
        source_tokens=dict(data.get("source_tokens") or {}),
        alert_to=(data.get("alert_to") or "").strip(),
    )


def active() -> Profile:
    return load()


# --------------------------------------------------------------------------
# Title pre-filtering for boards that charge us a request per description
# --------------------------------------------------------------------------

import re  # noqa: E402


def title_filters(profile: Profile | None = None) -> tuple[re.Pattern, re.Pattern]:
    """(worth fetching, obviously too senior) for the active profile.

    Workday and Eightfold need a separate request per job description, so the
    listing is filtered on the title first. Hardcoding that filter to software
    wording broke the moment a second profile existed: "Product Manager" matches
    nothing in the software list, and worse, the seniority pattern excluded
    "manager" - which is the job title itself, so every product role would have
    been thrown away before its description was ever read.
    """
    profile = profile or active()
    words: set[str] = set()
    for term in profile.title_terms:
        words.update(w for w in re.split(r"[^a-z0-9+#]+", term) if len(w) > 2)
    likely = re.compile(
        r"\b(" + "|".join(sorted(re.escape(w) for w in words)) + r")\b", re.I
    ) if words else re.compile(r".")

    senior = ["senior", r"sr\.?", "staff", "principal", "director", "vp", "head",
              "architect", "distinguished", "fellow", "intern", "internship"]
    # Only treat "manager" and "lead" as seniority when the role is not itself
    # a management job.
    if not any("manager" in t or "management" in t for t in profile.title_terms):
        senior += ["manager", "lead"]
    return likely, re.compile(r"\b(" + "|".join(senior) + r")\b", re.I)
