"""Tests for source parsing, deduplication and sponsorship.

Nothing here touches the network - the point is the parsing rules, which are
where the bugs live.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tt.extract import sponsorship  # noqa: E402
from tt.sources import jobboard, resolve, workday  # noqa: E402
from tt.sources.base import html_to_text  # noqa: E402


# --------------------------------------------------------------------------
# sponsorship
# --------------------------------------------------------------------------


def test_will_not_sponsor_is_detected():
    text = "Veeva does not provide sponsorship for employment visa status."
    assert sponsorship.classify(text).status == "no"


def test_the_abbreviation_trap():
    """A full stop inside "U.S." must not end the sentence.

    This exact wording is used across many postings. Splitting on the stop in
    "U.S." cut it in half and lost the policy entirely.
    """
    text = (
        "For US based roles only, please note the Company may not be able to "
        "employ candidates for this role who have United States work "
        "authorization related to certain U.S. visa categories, or support "
        "future H-1B sponsorship at this time."
    )
    assert sponsorship.classify(text).status == "no"


def test_equal_opportunity_boilerplate_is_ignored():
    """Nearly every posting lists citizenship in its EEO paragraph.

    Reading that as a hiring restriction would mark the whole market closed.
    """
    text = (
        "We are an equal opportunity employer and consider all applicants "
        "regardless of race, colour, religion, national origin, citizenship, "
        "age, or veteran status."
    )
    assert sponsorship.classify(text).status == "unknown"


def test_citizenship_requirement_counts_as_no():
    text = "Citizenship, Lawful Permanent Residency, or Refugee/Asylee Status Required."
    assert sponsorship.classify(text).status == "no"


def test_clearance_is_its_own_answer():
    text = "- Active US Security clearance, or eligibility to obtain one."
    assert sponsorship.classify(text).status == "clearance"


def test_willingness_to_sponsor_is_detected():
    text = "We do sponsor and take over sponsorship of employment visas for this role."
    assert sponsorship.classify(text).status == "yes"


def test_a_refusal_outranks_a_friendly_sentence():
    text = (
        "We help with relocation and will assist with your visa where we can. "
        "This role does not provide sponsorship."
    )
    assert sponsorship.classify(text).status == "no"


def test_silence_is_reported_as_unknown():
    assert sponsorship.classify("Build great software with Python.").status == "unknown"


# --------------------------------------------------------------------------
# resolving an apply link back to its applicant system
# --------------------------------------------------------------------------


def test_greenhouse_link_resolves():
    origin = resolve("https://job-boards.greenhouse.io/twitch/jobs/8748321")
    assert origin.ats == "greenhouse"
    assert origin.token == "twitch"
    assert origin.external_id == "8748321"


def test_company_hosted_page_with_an_embedded_id():
    origin = resolve("https://stripe.com/jobs/search?gh_jid=8128744")
    assert origin.ats == "greenhouse"
    assert origin.external_id == "8128744"


def test_amazon_link_resolves():
    origin = resolve("https://www.amazon.jobs/jobs/10530257/apply")
    assert origin.ats == "amazon"
    assert origin.external_id == "10530257"


def test_workday_link_carries_tenant_pod_and_site():
    origin = resolve(
        "https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced"
        "/job/San-Jose/Software-Engineer_R171183"
    )
    assert origin.ats == "workday"
    assert origin.token == "adobe:wd5:external_experienced"
    assert origin.external_id == "R171183"


def test_an_unknown_careers_page_resolves_to_nothing():
    assert resolve("https://careers.example.com/roles/12345") is None


# --------------------------------------------------------------------------
# the aggregated board parser
# --------------------------------------------------------------------------


ROW = (
    '| <a href="https://www.amazon.com"><strong>Amazon</strong></a> '
    "| Software Development Engineer - Early Career | Cambridge, MA | $186k/yr "
    '| <a href="https://www.amazon.jobs/jobs/10530257/apply">'
    '<img src="https://i.imgur.com/JpkfjIq.png" alt="Apply" width="70"/></a> | 8d |'
)


def test_a_board_row_is_parsed():
    posting = jobboard._parse_row(ROW, "owner/repo:main:FILE.md")
    assert posting is not None
    assert posting.company_name == "Amazon"
    assert posting.title == "Software Development Engineer - Early Career"
    assert posting.location_raw == "Cambridge, MA"
    assert posting.url == "https://www.amazon.jobs/jobs/10530257/apply"
    assert posting.salary_min == 186_000
    # These rows carry no description, which is why they stay out of the
    # skill and sector figures.
    assert posting.content == ""


def test_the_age_column_becomes_a_date():
    posting = jobboard._parse_row(ROW, "owner/repo:main:FILE.md")
    from datetime import date, timedelta

    assert posting.first_published == (date.today() - timedelta(days=8)).isoformat()


def test_header_rows_are_skipped():
    assert jobboard._parse_row("| Company | Position | Location |", "x:y:z") is None
    assert jobboard._parse_row("|---|---|---|", "x:y:z") is None
    assert jobboard._parse_row("just some prose", "x:y:z") is None


# --------------------------------------------------------------------------
# workday helpers
# --------------------------------------------------------------------------


def test_workday_token_must_have_three_parts():
    assert workday.parse_token("nvidia:wd5:Site") == ("nvidia", "wd5", "Site")
    try:
        workday.parse_token("nvidia")
    except Exception as exc:
        assert "tenant:pod:site" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("a malformed token should be rejected")


def test_requisition_id_is_read_from_the_path():
    path = "/job/US-Remote/Software-Engineer--OpenShell_JR2015623"
    assert workday._id_from_path(path) == "JR2015623"


# --------------------------------------------------------------------------
# html handling
# --------------------------------------------------------------------------


def test_escaped_markup_does_not_leak_tag_names():
    """Some boards return tags that are themselves escaped.

    Stripping tags before unescaping left literal "div" and "br" in the text,
    which then showed up as trending vocabulary.
    """
    text = html_to_text("&lt;p&gt;We use &lt;strong&gt;Kubernetes&lt;/strong&gt;.&lt;/p&gt;")
    assert "Kubernetes" in text
    assert "div" not in text and "strong" not in text and "&lt;" not in text


def test_export_control_boilerplate_is_not_a_restriction():
    """Nearly every US software posting carries an export-law paragraph.

    It applies to nationals of a few sanctioned countries and says nothing
    about sponsorship. Treating it as one labelled ordinary jobs at ordinary
    companies "clearance required".
    """
    text = (
        "Elasticsearch develops and distributes technology subject to U.S. "
        "export controls and licensing requirements for individuals who are "
        "nationals of the following sanctioned countries and regions."
    )
    assert sponsorship.classify(text).status == "unknown"
