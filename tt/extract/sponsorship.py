"""Does this employer sponsor a work visa?

For anyone on OPT or an F-1 this is the first question, not the last, and it
decides whether the rest of the posting is worth reading at all. Companies
almost always say - the trouble is they say it in one sentence buried near the
legal boilerplate.

Four answers:

  no         the posting says it will not sponsor, or requires citizenship
  clearance  a US security clearance is required, which rules out most
             non-citizens in practice even when sponsorship is never mentioned
  yes        the posting says it will sponsor or help with a visa
  unknown    nothing was said, which is the most common case

The hardest part is not the wording, it is the equal-opportunity paragraph.
Nearly every posting contains "regardless of race, colour, religion ...
citizenship", and a naive search for "citizenship" marks the entire market as
closed. Those sentences are excluded before anything else runs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Sentences that are equal-opportunity boilerplate. They mention citizenship
# and national origin but say nothing about whether this job sponsors.
EEO = re.compile(
    r"regardless of|without regard to|equal (employment )?opportunit|"
    r"discriminat|protected (class|status|veteran)|affirmative action|"
    r"diversity|we celebrate|all qualified applicants will receive",
    re.I,
)

WILL_NOT_SPONSOR = re.compile(
    r"(not|unable|cannot|can't|does not|do not|will not|won't|no)\s+"
    r"(be\s+)?(able\s+to\s+)?(currently\s+)?"
    r"(provide|offer|support|consider|sponsor)\w*\s*"
    r"(future\s+)?(employment\s+)?(work\s+)?(visa\s+)?(sponsorship|sponsoring|visas?)"
    r"|"
    r"(sponsorship|visa[s]?)\s+(is\s+)?(not|unavailable)\s*(available|offered|provided)?"
    r"|"
    r"no\s+(visa\s+)?sponsorship"
    r"|"
    r"may not be able to employ candidates.{0,220}sponsorship"
    r"|"
    r"without (the need for )?(current or future )?(visa )?sponsorship"
    r"|"
    r"does not (provide|offer) sponsorship",
    re.I,
)

CITIZEN_ONLY = re.compile(
    r"(must be|require[sd]?|only)\s+(a\s+)?(us|u\.s\.|united states)\s+"
    r"(citizen|person)"
    r"|"
    r"(us|u\.s\.)\s+citizenship\s+(is\s+)?(required|mandatory)"
    r"|"
    r"citizenship,?\s+lawful permanent residency,?\s+or\s+refugee"
    r"|"
    r"must be authorized to work.{0,60}without.{0,30}sponsorship"
    r"|"
    r"green card holder.{0,40}(only|required)",
    re.I,
)

CLEARANCE = re.compile(
    r"(active|current|existing|obtain(ing)?|eligib\w+ for)\s+"
    r"(a\s+)?(us|u\.s\.)?\s*(ts/sci|top secret|secret|security)\s+clearance"
    r"|"
    r"security clearance\s+(is\s+)?(required|necessary)"
    r"|"
    r"\bts/sci\b|\bpolygraph\b",
    re.I,
)

WILL_SPONSOR = re.compile(
    r"(will|do|does|can|happy to|willing to|able to|open to)\s+"
    r"(consider\s+)?(provide|offer|support)?\s*(visa\s+)?sponsor\w*"
    r"|"
    r"sponsorship\s+(is\s+)?(available|offered|provided|possible)"
    r"|"
    r"we sponsor|visa sponsorship available|"
    r"every reasonable effort to get you a visa|"
    r"(assist|help)\s+with\s+(your\s+)?(visa|immigration|relocation and visa)|"
    r"h-?1b\s+(sponsorship|transfer)s?\s+(available|offered|supported)|"
    r"immigration support",
    re.I,
)

# Export-control wording is deliberately NOT treated as a restriction.
#
# Almost every US software company includes a paragraph about export laws and
# sanctioned countries. It is boilerplate that applies to a handful of
# nationalities, not a statement about sponsorship, and reading it as one
# labelled ordinary jobs at ordinary companies "clearance required". Where an
# employer really does require citizenship or permanent residency, CITIZEN_ONLY
# already catches it from the plain wording.
EXPORT_CONTROL = re.compile(
    r"export (control|administration|licen[sc])\w*|itar|deemed export", re.I
)

# Abbreviations whose full stop must not be treated as the end of a sentence.
# Without this, "related to certain U.S. visa categories, or support future
# H-1B sponsorship" gets cut in half and the policy is missed entirely - which
# is exactly how a posting that plainly says it will not sponsor ends up
# recorded as "not stated".
ABBREVIATIONS = [
    "U.S.A.", "U.S.", "U.K.", "e.g.", "i.e.", "etc.", "vs.", "approx.",
    "Inc.", "Ltd.", "Co.", "Corp.", "Mr.", "Ms.", "Mrs.", "Dr.", "Ph.D.",
    "B.S.", "M.S.", "St.", "No.", "Jr.", "Sr.",
]
_PROTECT = "␟"  # a character no job description will contain

SPLIT = re.compile(r"(?<=[.!?])\s+|\n")


def _sentences(text: str) -> list[str]:
    guarded = text
    for abbreviation in ABBREVIATIONS:
        guarded = guarded.replace(abbreviation, abbreviation.replace(".", _PROTECT))
    for part in SPLIT.split(guarded):
        yield part.replace(_PROTECT, ".")


@dataclass
class Verdict:
    status: str  # "yes" | "no" | "clearance" | "unknown"
    note: str    # the sentence it was decided on, trimmed


ORDER = {"no": 0, "clearance": 1, "yes": 2, "unknown": 3}


def classify(text: str) -> Verdict:
    """Read the posting and decide. Returns the sentence behind the call."""
    if not text:
        return Verdict("unknown", "")

    findings: list[tuple[str, str]] = []
    for raw in _sentences(text):
        sentence = re.sub(r"\s+", " ", raw).strip()
        if len(sentence) < 12 or len(sentence) > 600:
            continue
        if EEO.search(sentence):
            continue  # equal-opportunity boilerplate, not a sponsorship policy

        if WILL_NOT_SPONSOR.search(sentence) or CITIZEN_ONLY.search(sentence):
            findings.append(("no", sentence))
        elif CLEARANCE.search(sentence):
            findings.append(("clearance", sentence))
        elif WILL_SPONSOR.search(sentence):
            findings.append(("yes", sentence))

    if not findings:
        return Verdict("unknown", "")

    # A "no" anywhere outranks a "yes" elsewhere: if a posting says it will not
    # sponsor, a friendly sentence about relocation does not cancel that out.
    findings.sort(key=lambda pair: ORDER[pair[0]])
    status, sentence = findings[0]
    return Verdict(status, sentence[:300])


LABELS = {
    "yes": "Sponsors",
    "no": "No sponsorship",
    "clearance": "Clearance required",
    "unknown": "Not stated",
}
