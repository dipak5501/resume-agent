"""T39: the JD deal-breaker screen. Phrasings come from 714 real postings
(2026-09-28), often trimmed to the clause under test. Web examples and
constructed scaffolding are marked."""

import pytest

from app.services import jd_screen
from app.services.jd_screen import screen


# --- minimum experience ----------------------------------------------------


@pytest.mark.parametrize("line, years", [
    ("3+ years of non-internship professional software development experience", 3),
    ("Minimum 7.5 year(s) of experience is required", 7.5),
    ("At least 4 years of experience in application development (Internship experience does not apply)", 4),
    ("0-2 years of overall experience in data engineering, building and maintaining large-scale data pipelines", 0),
    ("3–5 years of software engineering experience, with at least one year working on AI- or ML-backed systems", 3),
    ("Two (2) or more years of experience implementing solutions using cloud computing services", 2),
    ("Seven years of experience as a systems engineer supporting programs and contracts of similar scope", 7),
    ("5 or more years of demonstrated full stack development experience", 5),
    ("- over 3 years of professional software development experience", 3),
    ("What we're looking for: 8+ years in z/OS system programming", 8),  # no word "experience": it leads the line
    ("Required Experience: 5 years’ experience.", 5),
    ("12 yrs., B.S. or 10 yrs. w/ M.S., 4 yrs. of additional SWE experience may be substituted for a bachelor’s degree.", 12),
    ("Bachelor’s degree and 6+ years of experience designing software, or 10+ years of experience in lieu of a degree", 6),
    ("• Typically has 4-7 years of work experience, preferably in inkjet writing systems", 4),  # "preferably" = the field
    ("- Minimum 5 years of experience as a front-end or design engineer, ideally on a marketing site", 5),
    ("A bachelors degree plus 3 years of recent specialized experience", 3),  # "plus" is not "a plus"
    ("Required Education/Experience/Skills: BS degree in Engineering from an accredited engineering school, plus "
     "zero (0) to five (5) years of experience.", 0),  # Barrios
    ("This opportunity is ideal for someone with around 18 months to 4 years' experience in a SOC", 1.5),  # Macquarie
    ("3+ years of experience in ML Engineering or Applied ML with 8+ years of overall experience", 8),  # Aircall
    ("Minimum of 3 years of experience in the design/development/test of embedded real-time control software, of "
     "which 2-3 years overall experience in software", 3),  # Moog: an overall subset does not lower the bar
    ("Hold a Ph.D. or Master’s degree in a quantitative discipline with a minimum of four years’ experience applying "
     "advanced machine learning, or possess a Bachelor’s degree with at least six years of directly relevant experience.",
     6),  # Mimecast
    # degree paths in one sentence, doctorate first (KLA): the bachelor's is the bar
    ("Doctorate (Academic) Degree and 0 years related work experience; Master's Level Degree and related work "
     "experience of 3 years; Bachelor's Level Degree and related work experience of 5 years.", 5),
    # ";" between two requirements, not two paths (SkyePoint, Jabil)
    ("Required Qualifications: Bachelor’s degree in Computer Science, Software Engineering, Information Systems, "
     "Engineering, or related field; 8+ years of relevant experience for mid-level assignments", 8),
    ("Requires Advanced Diploma, Bachelors, or Masters in appropriate fields; 2 to 4 years work-related experience "
     "in the EMS or equivalent industry", 2),
    # "or equivalent experience" in an earlier clause does not void the years (CACI)
    ("Required: Bachelor's degree in a related technical discipline or equivalent experience, with 5+ years of "
     "relevant engineering experience.", 5),
    ("Minimum three (3) years work experience working with web application frameworks (e.g., Angular (preferred), React)",
     3),  # the aside prefers Angular, not the years
])
def test_minimum_years(line, years):
    assert screen(line).min_years == years
    assert screen(line).experience == [line]


@pytest.mark.parametrize("line", [
    "15 years full time education",
    "We have been living and breathing the world of real estate information for over 35 years, giving us the perspective",
    "Despite 30+ years of combined AI experience on the founding team, we know today’s landscape changes too fast.",
    "Drawing on more than 150 years of experience, we are leading the way in safety.",
    "If you are under 18 years of age, you may need to obtain the necessary working papers.",
    "Expected to have completed at least two years of undergraduate study before the internship begins.",
    "Demonstrated programming experience through internships, or up to 2 years of professional software development experience.",
    "Have fewer than four years of experience? We also welcome exceptional early-career candidates.",
    "Those eligible for an L-1 visa would require at least one-year of qualifying experience in the last three years",
    "Bachelor's or Associate degree in Computer Science, or 4+ years of relevant job or military experience in lieu of degree",
    "IAT III certifications may be substituted for a relevant Bachelor’s degree or 4 years of relevant experience",
    "Five years of additional systems engineering experience may be substituted for a bachelor's degree.",
    "Required Qualifications: Bachelor's degree or equivalent, or 3+ years of relevant work experience instead of a degree",
    "Bachelor’s degree in Computer Science, Information Technology, or a related field, or five (5) years of equivalent "
    "experience in DevOps engineering.",
    # no word "experience" and the years do not lead the line: not a requirement
    "With over 25 years of aerospace and defense engineering expertise, our commitment to delivering high-quality, "
    "transformative solutions sets us apart",
    "As a fast growing startup with 1000+ customers and 10+ years of runway, we're in a pretty good spot.",
    "What you'll get in return is: 25 days’ annual leave, rising incrementally to 30 days after six years of service.",
    "Today, Marvin is also proud to have been named a Top Large Employer by Forbes Magazine two years in a row, in 2024.",
    "For employees working at least 35 hours per week, the vacation accrual rate is 13 days annually for the first "
    "three years of employment",
    "- Generous equity grant vested over 4 years",
    "Junior (0 to 4 years)",
    "Several years of hands on GCP experience",
    "Preferred that the candidate has 1-5 years of experience in the following:",
    "Exposure to routing software with 3+ years of experience is a strong plus.",  # constructed around a real "is a strong plus"
])
def test_not_a_minimum(line):
    assert screen(line).min_years is None and screen(line).experience == []


def test_the_minimum_is_the_highest_required_line_and_leads():
    # Capital One: every basic line must be met, so the bar is 4, not 2
    jd = ("Basic Qualifications:\nAt least 2 years of experience with SQL\n"
          "At least 4 years of experience in application development\n")
    result = screen(jd)
    assert result.min_years == 4
    assert result.experience == ["At least 4 years of experience in application development",
                                 "Basic Qualifications: At least 2 years of experience with SQL"]


@pytest.mark.parametrize("heading", [
    "Preferred Qualifications", "Preferred Qualifications:", "Nice If You Have:", "NICE TO HAVE",
    "Bonus Points If You Have", "Desired:", "Qualifications We Prefer", "HELPFUL, NOT REQUIRED",
    "Nice to have:", "Preferred qualifications",  # not title case: opened by their first word
])
def test_preferred_section_is_not_a_minimum(heading):
    jd = f"Basic Qualifications\n3+ years of software development experience\n{heading}\n5+ years of Go experience\n"  # constructed
    assert screen(jd).min_years == 3


@pytest.mark.parametrize("heading", ["Education & Experience Recommended", "Recommended Qualifications:"])
def test_recommended_heads_the_requirements(heading):
    # HP and Citi head their only requirements list this way
    assert screen(f"{heading}\n5+ years of professional software development experience\n").min_years == 5


def test_non_degree_paths_are_not_the_minimum():
    # Steampunk's lines: the bachelor's path is the bar, not the no-degree one
    jd = ("No degree and 12+ years of experience.\nAssociate's degree and 10+ years of experience; OR\n"
          "Bachelor's degree and 8+ years of experience; OR\nMasters degree and 6+ years of experience; OR\n")
    assert screen(jd).min_years == 8
    # Peraton's one-sentence form: the first number is the bachelor's path
    assert screen("5 years with BS/BA; or 9 years of experience with a high school diploma.").min_years == 5


def test_preferred_section_ends_at_the_next_heading():
    jd = ("Preferred / Advantageous\nExperience with Istio\nAdditional Information:\n"  # Accenture's layout, trimmed
          "- The candidate should have minimum 12 years of experience in AWS.\n")
    assert screen(jd).min_years == 12


def test_a_titled_heading_ends_a_preferred_section():
    # PNC: its "Work Experience" block follows "Preferred Skills"
    jd = ("Preferred Skills:\nDeep experience with AWS\nWork Experience\nRoles at this level typically require a "
          "university / college degree, with 5+ years of industry-relevant experience.\n")
    assert screen(jd).min_years == 5


def test_a_short_preferred_bullet_is_not_a_section():
    jd = "Requirements\nProficiency in Fortran preferred\n4+ years of experience with Python\n"
    assert screen(jd).min_years == 4


def test_a_long_preferred_line_is_not_a_section():
    # Orion's lines: a long "Preferred experience ..." line is followed by required ones
    jd = ("Preferred experience with Azure Data Factory, ADLS, Delta/Parquet, AKS, SSIS/MSBI, Power BI, Alteryx.\n"
          "5+ years of experience in application support, technical leadership, or data-platform troubleshooting\n")
    assert screen(jd).min_years == 5


def test_years_cap_boundary():
    assert screen(f"{jd_screen.MAX_YEARS}+ years of experience").min_years == jd_screen.MAX_YEARS
    assert screen(f"{jd_screen.MAX_YEARS + 1}+ years of experience").min_years is None


# --- US citizenship ---------------------------------------------------------


@pytest.mark.parametrize("line", [
    "Must be a US Citizen.",
    "US citizenship required",
    "U.S. citizenship is required, as only U.S. citizens are authorized to access information under this program/contract.",
    "Eligibility Requirements: US Citizen",
    "To comply with these requirements, applicants must qualify as a US Person.",
    "SRC IS A CONTRACTOR FOR THE U.S. GOVERNMENT, THIS POSITION WILL REQUIRE U.S. CITIZENSHIP AS WELL AS A CLEARANCE",
    "Citizenship & Citizenship Verification: This position requires verification of U.S. citizenship.",
    "Must be a U.S. Citizen or Permanent Resident (must be able to work in the U.S. without visa sponsorship)",
])
def test_citizenship(line):
    assert screen(line).citizenship == [line]


@pytest.mark.parametrize("line", [
    "All qualified applicants will receive consideration for employment without regard to age, ancestry, citizenship, color.",
    "We do not discriminate on the basis of race, ethnicity, citizenship, national origin, color, religion.",
    "The E-Verify program is an Internet-based employment eligibility verification system operated by the U.S. "
    "Citizenship and Immigration Services.",
    "U.S. National Base Pay Range: $78,800 - $131,300.",
    "This role may require an export license for candidates with citizenship in certain countries.",
])
def test_not_citizenship(line):
    assert screen(line).citizenship == []


# --- no visa sponsorship ----------------------------------------------------


@pytest.mark.parametrize("line", [
    "However, please note that CoStar Group is not able to provide visa sponsorship for this position.",
    "The company will not consider candidates who require sponsorship for a work-authorized visa, now or in the future.",
    "This position is not eligible for visa sponsorship.",
    "Sponsorship: Not available for this position",
    "Must be legally authorized to work in the United States without the need for employer sponsorship, now or at any time in the future",
    "At this time, Capital One will not sponsor a new applicant for employment authorization.",
    "Onsite position only -- no visa sponsorship available.",  # web example
    "We are unable to sponsor or take over sponsorship of an employment Visa at this time.",  # web example
    "Visa sponsorship isn't provided.",  # as job posts are quoted on Quora
    "This includes, but IS NOT LIMITED TO: F1-OPT, F1-CPT, H-1B, TN, L-1, J-1, etc.",  # Wellmark, after its no-sponsorship line
])
def test_no_sponsorship(line):
    assert screen(line).no_sponsorship == [line]


@pytest.mark.parametrize("line", [
    "Capital One will consider sponsoring a new qualified applicant for employment authorization for this position.",
    "U.S. Visa sponsorship available if you qualify under the following:",
    "- Company-sponsored training and development",
    "Assist the Sponsor in developing standards, methods, and procedures.",
    "export control laws and regulations without sponsorship for an export license.",
    "Must be authorized to work in the United States.",  # web: not a statement about sponsorship
    "Visa sponsorship available; relocation not available.",  # Midpage: the "not" is relocation's
    "Sponsorship for this role is not guaranteed.",  # Amgen: a hedge, not an explicit no
    "However, visa sponsorship is dependent on many factors, and so we can't always guarantee success.",  # Cartesia
])
def test_not_no_sponsorship(line):
    assert screen(line).no_sponsorship == []


# --- security clearance -----------------------------------------------------


@pytest.mark.parametrize("line", [
    "An active TS/SCI with Polygraph clearance is required to be considered.",
    "•    An active TS//SCI security clearance is required prior to start",
    "Ability to obtain and maintain a Secret clearance",
    "Must be able to obtain and maintain a Public Trust clearance",
    "Active Top Secret, Top Secret SCI, or DOE Level Q clearance",
    "Required to obtain and maintain a Top Secret/Sensitive Compartmental Information clearance",  # web example
    "Candidates without Active clearances will be declined",  # "without" here is no negation of the need
    "Non-U.S. citizens may not be eligible to obtain a security clearance.",
    "Must have an active TS/SCI with Poly",  # no word "clearance" (Leidos)
    "Active Top Secret/SCI with SAP eligibility",
])
def test_clearance(line):
    assert screen(line).clearance == [line]


def test_clearance_label_joins_its_value():
    assert screen("Clearance:\nActive TS/SCI\n").clearance == ["Clearance: Active TS/SCI"]
    assert screen("CLEARANCE REQUIRED FOR START:  Yes").clearance == ["CLEARANCE REQUIRED FOR START:  Yes"]
    # CACI stacks labels: only the nearest joins, so they cannot pile up
    assert screen("Qualifications:\nRequired:\nU.S. Citizenship required\n").citizenship == [
        "Required: U.S. Citizenship required"]


@pytest.mark.parametrize("jd", [
    "Minimum Clearance Required to Start: None",
    "Security Clearance Type:\nNone/Not Required\n",
    "Security Clearance Status:\nNot Required\n",
    "Public Trust/Other Required: None",
    "Offers are based on factors, such as the candidate’s experience, education, and security clearances.",
    "Clearance Information",
    "Clearance",
    "Clearance Level",
    "Employee Polygraph Protection Act (EPPA)",  # a legal notice
    "Government that operates efficiently, adapts to change, and strengthens public trust.",  # OpenGov's copy
    "No Clearance",
    "Security Clearance: This position does not require a Security Clearance.",  # Boeing
    # Apogee's fields run together and "Clearance:" is empty
    "Citizenship: Must be a US citizen\xa0Clearance:\xa0Certifications: DAWIA Practitioner Equivalency",
    # machining, not security (GM, GE Vernova)
    "Benchmark competitive vehicles to ensure package competitiveness in clearances, component locations, sizes",
    "Define geometric dimensioning and tolerancing (GD&T) required for proper clearances and fits.",
])
def test_not_clearance(jd):
    assert screen(jd).clearance == []


# --- text handling -----------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   \n\n  "])
def test_empty_text(text):
    assert screen(text).model_dump() == {
        "min_years": None, "experience": [], "citizenship": [], "no_sponsorship": [], "clearance": []}


def test_sentences_split_but_not_inside_abbreviations():
    jd = "We build rockets. Must be a U.S. Citizen. Active Secret clearance required."  # constructed
    result = screen(jd)
    assert result.citizenship == ["Must be a U.S. Citizen."]
    assert result.clearance == ["Active Secret clearance required."]


def test_long_quote_is_truncated_and_duplicates_collapse():
    long = "Must be a US Citizen " + "and more words " * 40
    result = screen(f"{long}\n{long}\n")
    assert len(result.citizenship) == 1
    assert len(result.citizenship[0]) == jd_screen.QUOTE_MAX and result.citizenship[0].endswith("…")


def test_one_sentence_can_raise_several_flags():
    line = "Must be a US Citizen and be able to achieve and maintain a Public Trust clearance."
    result = screen(line)
    assert result.citizenship == [line] and result.clearance == [line]
