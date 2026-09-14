"""Tests for the parts that decide what counts as an early-career software job.

These are the rules everything else depends on, so they get the most coverage.
Run with:  .venv/Scripts/python -m pytest tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tt.extract import clean, locations, salary, sectors, seniority, skills  # noqa: E402


# --------------------------------------------------------------------------
# the 0-4 years filter
# --------------------------------------------------------------------------


def keep(title, content="", dept="Engineering", pay=None):
    return seniority.classify(title, content, dept, salary_min=pay).eligible


def test_new_grad_titles_are_kept():
    assert keep("Software Engineer, New Grad")
    assert keep("Entry Level Software Developer")
    assert keep("Junior Backend Engineer")
    assert keep("Associate Software Engineer")
    assert keep("Software Engineer I")


def test_senior_titles_are_dropped():
    assert not keep("Senior Software Engineer", "8+ years of experience")
    assert not keep("Staff Engineer", "10 years experience required")
    assert not keep("Principal Engineer", "12 years of relevant experience")
    assert not keep("Distinguished Engineer")


def test_management_titles_are_always_dropped():
    # Even when the description mentions a small number of years.
    assert not keep("Engineering Manager", "2+ years of experience")
    assert not keep("Manager, Applied AI Engineering", "2 years of experience")
    assert not keep("Director of Platform Engineering", "3 years experience")


def test_stated_years_decide_borderline_cases():
    assert keep("Backend Engineer", "Requires 3-5 years of industry experience")
    assert not keep("Backend Engineer", "Requires 7+ years of industry experience")
    # A senior title asking only three years is still worth surfacing.
    assert keep("Senior Backend Engineer", "3+ years of professional experience")


def test_non_software_roles_are_dropped():
    assert not keep("Sales Engineer", "2 years experience", "Sales")
    assert not keep("Product Manager", "3 years experience", "Product")
    assert not keep("Mechanical Engineer", "2 years experience", "Hardware")
    assert not keep("Technical Recruiter", "1 year experience", "People")


def test_internships_are_separated_out():
    verdict = seniority.classify("Software Engineer Intern", "currently enrolled")
    assert verdict.is_swe and not verdict.eligible
    assert verdict.level == "intern"


def test_high_pay_flags_a_senior_role_with_no_stated_years():
    assert not keep("Research Engineer, Systems", "Build things.", pay=380_000)
    assert keep("Software Engineer, Platform", "Build things.", pay=150_000)


def test_doctorate_requirement_is_not_early_career():
    assert not keep("Research Engineer", "A PhD in machine learning is required.")
    # "preferred" is a different matter and should not disqualify.
    assert keep("Research Engineer", "A PhD is preferred but not required.")


def test_benefits_numbers_are_not_read_as_experience():
    low, _high = seniority.parse_years("We offer 401k and 5 weeks of vacation.")
    assert low is None


def test_written_out_numbers_are_understood():
    low, _ = seniority.parse_years("Minimum of two years of hands-on experience.")
    assert low == 2


def test_smallest_stated_requirement_wins():
    low, _ = seniority.parse_years(
        "3+ years of experience required. 6+ years of experience preferred."
    )
    assert low == 3


# --------------------------------------------------------------------------
# locations
# --------------------------------------------------------------------------


def test_us_cities_map_to_metros():
    assert locations.parse("Palo Alto, CA").metro == "SF Bay Area"
    assert locations.parse("Cambridge, MA").metro == "Boston"
    assert locations.parse("Arlington, VA").metro == "Washington DC"
    assert locations.parse("Brooklyn, NY").metro == "New York"


def test_foreign_locations_are_excluded():
    for place in ["Tokyo, Japan", "London, England", "Bengaluru", "Toronto, Canada"]:
        assert not locations.is_us(locations.parse(place)), place


def test_multi_location_strings_pick_the_first_us_office():
    place = locations.parse("San Francisco, CA • New York, NY • United States")
    assert place.metro == "SF Bay Area"


def test_remote_is_detected():
    assert locations.parse("Remote - USA").remote
    assert locations.parse("Seattle, WA or Remote").remote


def test_useless_location_falls_back_to_the_description():
    place = locations.parse_with_fallback(
        "Hybrid", "This role is based in Austin, TX and requires two days onsite."
    )
    assert place.metro == "Austin"
    assert place.state == "TX"


# --------------------------------------------------------------------------
# skills
# --------------------------------------------------------------------------


def test_word_boundaries_prevent_false_matches():
    found = skills.extract("We use Java and Preact here.")
    assert "Java" in found
    assert "JavaScript" not in found
    assert "React" not in found


def test_aliases_roll_up_to_one_skill():
    found = skills.extract("Experience with K8s, Kubernetes and EKS.")
    assert found.get("Kubernetes", 0) >= 3


def test_symbols_in_names_are_handled():
    found = skills.extract("Strong C++ and C# background, plus .NET experience.")
    assert "C++" in found and "C#" in found and ".NET" in found


def test_a_company_is_not_a_skill_in_its_own_posting():
    text = "Cloudflare is hiring. At Cloudflare you will use Cloudflare Workers."
    assert "Cloudflare" not in skills.extract(text, company_name="Cloudflare")
    # At a different company, naming Cloudflare is a genuine signal.
    assert "Cloudflare" in skills.extract(text, company_name="Stripe")


# --------------------------------------------------------------------------
# boilerplate removal
# --------------------------------------------------------------------------


def test_benefits_block_is_removed():
    text = (
        "You will build payment systems in Go.\n\n"
        "We offer medical, dental and vision coverage, a 401(k) match, "
        "and generous paid time off.\n\n"
        "Acme is an equal opportunity employer."
    )
    cleaned = clean.strip_boilerplate(text)
    assert "payment systems" in cleaned
    assert "dental" not in cleaned
    assert "equal opportunity" not in cleaned


def test_healthcare_is_not_inferred_from_the_benefits_line():
    posting = "Build APIs in Python.\n\nBenefits include medical, dental and vision."
    found = skills.extract(clean.strip_boilerplate(posting))
    assert "Healthcare" not in found
    assert "Python" in found


# --------------------------------------------------------------------------
# salary
# --------------------------------------------------------------------------


def test_salary_range_is_read():
    low, high = salary.parse("The base salary range for this role is $120,000 - $160,000.")
    assert (low, high) == (120_000, 160_000)


def test_k_suffix_is_expanded():
    low, high = salary.parse("Compensation: $130K to $180K plus equity.")
    assert (low, high) == (130_000, 180_000)


def test_unrelated_numbers_are_ignored():
    assert salary.parse("We serve 10,000 - 20,000 requests per second.") == (None, None)


# --------------------------------------------------------------------------
# sectors
# --------------------------------------------------------------------------


def test_curated_company_sector_wins():
    # Even when the text sounds like something else, the mapping is trusted.
    assert sectors.resolve("Fintech", "Build clinical patient dashboards") == "Fintech"


def test_sector_is_guessed_when_the_company_is_unmapped():
    text = (
        "You will build payment processing and fraud detection for our "
        "lending product, working on underwriting and settlement flows."
    )
    assert sectors.resolve("", text) == "Fintech"


def test_a_single_passing_mention_does_not_set_a_sector():
    assert sectors.from_content("We also handle payments occasionally.") == sectors.UNKNOWN


def test_healthcare_needs_clinical_words_not_benefits_words():
    benefits = "Great health insurance and medical coverage for your family."
    assert sectors.from_content(benefits) == sectors.UNKNOWN
    real = (
        "Work on the electronic health record, patient scheduling and "
        "clinical decision support used by every provider network we serve."
    )
    assert sectors.from_content(real) == "Healthcare"


def test_an_age_requirement_is_not_years_of_experience():
    """Amazon opens every posting with "Are 18 years of age or older".

    The word "Experience" sits in the next bullet, close enough that a plain
    context check read it as eighteen years of experience and discarded the
    role - including genuine "Early Career" postings.
    """
    text = (
        "- Are 18 years of age or older\n"
        "- Experience with at least one modern language such as Java or Python"
    )
    assert seniority.parse_years(text)[0] is None
    assert seniority.classify("Software Development Engineer, Early Career", text).eligible


def test_an_age_line_does_not_hide_a_real_requirement():
    text = "Are 18 years of age or older. 2+ years of professional development experience."
    assert seniority.parse_years(text)[0] == 2


def test_a_business_unit_beats_the_company_label():
    """One label per company breaks down at conglomerates.

    Amazon was filed under Marketplace, but most of its early-career roles are
    AWS - cloud infrastructure, not shopping. The sector page was really just
    reporting "Amazon" and gave a wrong answer about both categories.
    """
    assert sectors.resolve("Marketplace", "", team="aws") == "Cloud Infrastructure"
    assert sectors.resolve("Marketplace", "", team="alexa-and-amazon-devices") == "Consumer"
    assert sectors.resolve("Marketplace", "", team="amazon-security") == "Security"
    # With no business unit named, the company label still applies.
    assert sectors.resolve("Marketplace", "", team="retail") == "Marketplace"


def test_ordinary_software_words_do_not_imply_a_marketplace():
    """"catalog" and "inventory" are ordinary words.

    They were dropping banks and hardware firms into Marketplace.
    """
    text = "Maintain the service catalog and inventory of internal APIs."
    assert sectors.from_content(text) == sectors.UNKNOWN


def test_plural_skill_names_are_matched():
    """Descriptions say "guardrails", not "guardrail".

    Without plural handling the closing word boundary rejected every plural,
    and Guardrails showed 3 postings where the real figure was over a hundred.
    """
    found = skills.extract("We build guardrails, embeddings and eval harnesses.")
    assert "Guardrails" in found
    assert "Embeddings" in found
    assert "Agent Harness" in found


def test_plurals_do_not_create_false_matches():
    # "Javas" is not a word, and Java must still not fire inside JavaScript.
    found = skills.extract("We use JavaScript on the frontend.")
    assert "Java" not in found


# --------------------------------------------------------------------------
# role profiles
# --------------------------------------------------------------------------


def _classify_as(profile_name, title, content="", dept=""):
    """Run the classifier under a named profile."""
    import os
    from tt import profiles

    previous = os.environ.get("TT_PROFILE")
    os.environ["TT_PROFILE"] = profile_name
    profiles.load.cache_clear()
    try:
        return seniority.classify(title, content, dept)
    finally:
        if previous is None:
            os.environ.pop("TT_PROFILE", None)
        else:
            os.environ["TT_PROFILE"] = previous
        profiles.load.cache_clear()


def test_product_profile_keeps_product_roles():
    assert _classify_as("product", "Associate Product Manager", "new grad").eligible
    assert _classify_as("product", "Product Manager", "2+ years of product experience").eligible
    assert _classify_as("product", "Technical Product Manager", "1-3 years in a product role").eligible


def test_manager_is_the_job_not_a_seniority_signal_for_product():
    """Engineering treats "Manager" as out of range. Product cannot.

    The whole title is "Product Manager", so the rule that protects the
    engineering profile would otherwise reject every single product role.
    """
    assert not _classify_as("swe", "Product Manager", "2 years").eligible
    assert _classify_as("product", "Product Manager", "2 years of product experience").eligible


def test_executives_are_excluded_under_every_profile():
    # Allowing "manager" for product must not also let directors through.
    assert not _classify_as("product", "Director of Product Management", "").eligible
    assert not _classify_as("product", "VP of Product", "").eligible
    assert not _classify_as("product", "Group Product Manager", "7+ years leading product").eligible


def test_profiles_do_not_overlap():
    assert not _classify_as("product", "Software Engineer", "2 years experience").eligible
    assert not _classify_as("swe", "Associate Product Manager", "new grad").eligible


def test_each_profile_uses_its_own_database():
    from tt import profiles

    assert profiles.load("swe").db_name != profiles.load("product").db_name


# --------------------------------------------------------------------------
# the shared fetch cache
# --------------------------------------------------------------------------


def test_only_profile_independent_readers_are_cached():
    """Workday and Eightfold search by title, so their answers differ per role.

    Caching them would serve a product run the results of a software search.
    """
    from tt import rawstore

    for ats in ("greenhouse", "ashby", "lever", "amazon"):
        assert rawstore.is_cacheable(ats), ats
    for ats in ("workday", "eightfold"):
        assert not rawstore.is_cacheable(ats), ats


def test_a_profile_can_skip_readers_it_has_no_use_for():
    from tt import profiles

    assert "jobboard" in profiles.load("product").exclude_sources
    assert "jobboard" not in profiles.load("swe").exclude_sources
