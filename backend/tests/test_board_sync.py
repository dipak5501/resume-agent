import pytest
from datetime import datetime, timezone
from app.services import board_policy
from app.services.board_sync import is_target_role


@pytest.fixture(autouse=True)
def posting_clock(monkeypatch):
    # Existing sync fixtures were published Jan 2; keep age tests deterministic.
    monkeypatch.setattr(board_policy, "utcnow", lambda: datetime(2026, 1, 3, 12))


@pytest.fixture(autouse=True)
def no_curated_boards(monkeypatch):
    # _harvest_cycle seeds the F500 list; these tests count exactly their own boards.
    from app.services import board_sync
    monkeypatch.setattr(board_sync, "F500_BOARDS", [])


def test_admits_the_generalist_and_in_band_engineering_roles():
    for t in [
        "Software Engineer", "sOfTwArE EnGiNeEr", "Software Engineer, Compute Foundations",
        "Software Development Engineer", "SDE I", "New Grad SWE", "Software Developer",
        "Member of Technical Staff",          # bare "staff" used to reject this
        "Frontend Engineer, Payments & Risk",  # "frontend" was missing entirely
        "Backend Developer", "Full Stack Web Developer", "Forward Deployed Engineer",
        "AI Engineer", "Data Engineer", "Platform Engineer", "Infrastructure Engineer",
        "Site Reliability Engineer", "Cloud Security Engineer", "Software Engineer II, Fullstack",
        "Software Engineer, Sales Platform",   # team name must not poison the role
    ]:
        assert is_target_role(t) is True, t


def test_rejects_non_engineering_roles_that_merely_mention_ai():
    """A bare \\bai\\b used to admit anything AI-adjacent, engineering or not."""
    for t in [
        "AI Recruiter", "Director, Applied AI", "Account Executive, AI Sales",
        "Business Systems Analyst, Sales AI & Automation", "Applied AI Architect",
        "Product Marketing Manager", "Sales Development Rep", "HR Coordinator",
        "Machine Learning Specialist",  # a specialist role, not an engineering one
        "Copywriter, Developer",                  # role is Copywriter; "developer" is the team
    ]:
        assert is_target_role(t) is False, t


def test_rejects_above_band_seniority_including_the_sr_abbreviation():
    for t in [
        "Senior Software Engineer", "SENIOR swe", "Senior SWE",
        "Sr. Software Engineer - Ingestion Core team",  # "sr." was never excluded
        "Sr Software Engineer (Backend)",               # nor bare "sr"
        "Staff Machine Learning Engineer", "Lead AI Researcher", "Principal Full Stack",
        "Manager, Software Engineering", "Lead backend engineer",
    ]:
        assert is_target_role(t) is False, t


def test_rejects_unwanted_domains_and_non_software_engineering():
    for t in [
        "Software Engineer in Test, LUS", "Software Quality Assurance Engineer", "SDET II",
        "Software Engineer, iOS", "Android Engineer, Terminal", "Mobile Engineer, Treasury",
        "Data Center Electrical Engineer", "Manufacturing Quality Engineer",
    ]:
        assert is_target_role(t) is False, t


def test_rejects_customer_facing_and_internal_it_engineering():
    """Product support and customer engineering stay out. IT support and network
    engineering are computer-science roles and are covered separately."""
    for t in [
        "AV Engineer", "Silicon Engineer",
        "Product Support Engineer III", "Technical Support Engineer, Metronome",
        "Customer Engineer, Korea", "Presales Customer Engineer, Enterprise (Sydney)",
        "Solutions Engineer", "Solutions Integration Engineer IV", "Technical Solutions Engineer",
        "Partner Engineer, Spain", "Recruiting Solutions Engineer", "Salesforce Developer",
        "Developer Relations", "Technical Documentation and Content Engineer, Claude Docs",
    ]:
        assert is_target_role(t) is False, t


def test_security_engineering_is_kept():
    """The user wants security; only QA/test and mobile are excluded domains."""
    for t in ["Cloud Security Engineer", "Red Team Engineer, Safeguards",
              "Threat Intelligence Engineer", "Vulnerability Management Engineer", "GRC Engineer"]:
        assert is_target_role(t) is True, t


def test_a_team_name_never_triggers_the_non_software_gate():
    """Those words are only disqualifying in the ROLE, not the team it sits on."""
    for t in ["Software Engineer, Network Firewall", "Software Engineer, Enterprise Integrations",
              "Software Engineer, Business Technology", "Software Engineer, Payments and Risk"]:
        assert is_target_role(t) is True, t


def test_search_quality_is_relevance_work_not_qa():
    """A bare "quality"/"test" exclusion would wrongly drop real SWE roles."""
    assert is_target_role("Software Engineer, Search Quality") is True
    assert is_target_role("Software Engineer, Data Quality and Governance") is True


def test_deliberately_kept_edge_categories():
    """User reviewed these three on 2026-09-18 and chose to keep them. They sit
    just outside the stated band, so pin them: a future tightening that drops
    them must be a decision, not an accident."""
    for t in [
        "Software Engineer, Intern",                        # below new grad
        "Software Engineering Internship - San Francisco",
        "Software Engineering Intern (2027 Start) - Winter",
        "Firmware Engineer",                                # embedded, not backend/infra
        "Integration Engineer, Metronome",                  # customer-integration work
    ]:
        assert is_target_role(t) is True, t


# --- T29: software must be positively identified ------------------------------
# A bare "engineer" let aerospace/defense boards flood the feed: 144 of 450 kept
# titles in the 2026-09-23 audit were hardware, facilities or supply-chain roles.
# Every title below is real, taken from that audit.

def test_hardware_and_facilities_engineering_is_rejected():
    for t in [
        "Propulsion Engineer (Raptor Test)", "Avionics Systems Engineer (Starship)",
        "Systems Engineer II, Avionics", "Fluids Engineer - Propulsion Valves, Ducts, Lines",
        "Structural Engineer (Starship Infrastructure)", "Wiring Harness Engineer",
        "Winter 2027 EWIS Harness Engineer Co-op", "PCB Layout Engineer", "RF Electronics Engineer",
        "Powerpack Engineer Level II", "Battery Engineer (Falcon & Dragon)",
        "Supplier Development Engineer, SMT (Starlink)", "Physical Design Engineer, Timing",
        "Midcore Design Verification Engineer", "Controls Engineer, Manufacturing Automation",
        "Robotics Engineer, Manufacturing Automation", "Product Quality Engineer",
        "Construction Project Engineer (MEP)", "Environmental Engineer, Compliance/Air Programs",
        "HVAC Programmer", "CMM Programmer (Valves) - 2nd Shift", "Launch Vehicle Engineer",
        "Engineer II, Propulsion - Engine Performance (R5907)",
        "Engineering Technician, Vacuum & Cryogenic Systems",
    ]:
        assert is_target_role(t) is False, t


def test_non_software_engineer_titles_without_hardware_words_are_rejected():
    """No hardware word, but nothing says software either."""
    for t in ["Operations Engineer (Starshield)", "Deployment Engineer", "Account Engineer",
              "GTM Engineer", "Technical Success Engineer", "Test & Evaluation Engineer",
              "Deployed Engineer, Professional Services", "Software Asset Coordinator"]:
        assert is_target_role(t) is False, t


def test_software_work_is_kept_even_when_the_team_names_hardware():
    """The ROLE decides. A hardware word in the team must not reject a SWE."""
    for t in [
        "Backend Engineer, Control Plane", "Full Stack Engineer, Launch Software",
        "Software Engineer, Manufacturing Infrastructure", "Software Supply Chain Security Engineer",
        "Software Engineer (Controls Software)", "Firmware Engineer, Manufacturing Test",
        "Data Engineer, Ground Network Engineering (Gateway)", "Robotics Software Engineer - Grasping",
        "Engineer- Data Visualization Platform", "Systems Engineer, Email Service",
        "Performance Engineer, Inference Engine", "Engine Programmer Intern",
    ]:
        assert is_target_role(t) is True, t


def test_seniority_anywhere_in_the_title_is_rejected():
    """The head-only check let the level hide in the tail."""
    for t in [
        "BESS Project Engineer, Senior or Staff", "Software Engineer, Full Stack (Senior, Staff+)",
        "Site Reliability Engineer (SRE) Manager", "Member of Technical Staff - Lead, Machines",
        "Backend Engineer - Senior", "Chief Engineer, Navy Airpower",
    ]:
        assert is_target_role(t) is False, t
    for t in ["Member of Technical Staff - Storage", "Software Engineer (Staffing Platform)",
              "Software Engineer, Leadership Tools"]:
        assert is_target_role(t) is True, t


def test_the_role_is_found_after_a_marker_or_program_prefix():
    """Real titles the head-only read dropped."""
    for t in [
        "Intern, Software Engineering, 2027", "Flight Software Intern (Summer 2027)",
        "Flight Software Associate (Winter 2027)", "CONTRACT - Web Development Engineer",
        "AI Inference Core - Infrastructure SW Engineer",
        "Binance Accelerator Programm - Software Engineer (Convert)",
    ]:
        assert is_target_role(t) is True, t


def test_software_named_after_a_generic_head_is_kept():
    """T40: real titles the 2026-10-06 audit found live, in window and in the
    US, yet rejected: the software part sat after a bare head ("Engineer,"),
    an abbreviation, a "University" marker, an en dash or a leading "(Jr)"."""
    for t in [
        "Engineer, Desktop Software",                                    # Danaher
        "Engr, Software 1",                                              # KLA
        "New Graduate Engineer, Software (Starfall)",                    # SpaceX
        "University, Software Developer",                                # Booz Allen
        "Early Career NASA Space Reactor – 1 Freedom Flight Software Development Engineer",  # CACI
        "(Jr) Machine Learning (ML) Developer",                          # Laminar
    ]:
        assert is_target_role(t) is True, t


def test_the_generic_head_rescue_still_rejects_what_it_should():
    for t in ["Engineer, Software Sales", "Engineer, Desktop Software Support",
              "(Sr) Software Engineer", "University Recruiter, Software Engineering",
              "Engr, Senior Software", "Engineer, Software Test", "Engineer, Embedded Software Hardware",
              # T40 corpus review (22,875 real titles): Snr is Senior, SFDC is Salesforce,
              # and a "Software Test & X Engineer" is the QA role "test engineer" already drops
              "Snr Engineer, Software", "Snr. Site Reliability Engineer (Remote)", "Sfdc – Developer 1",
              "Software Test & Validation Engineer"]:
        assert is_target_role(t) is False, t


def test_a_parenthesis_that_ends_a_phrase_still_splits_the_title():
    """T40 corpus review: blanking every "(...)" merged this head with its tail."""
    assert is_target_role("Software Engineer (FrontEnd) -Faculty Specialist") is True
    assert is_target_role("Modeling & Simulation Artificial Intelligence (AI)/ Machine Learning Engineer") is True


def test_help_desk_and_other_cs_roles_are_included_with_software():
    """Business help desk and the wider CS band sit beside the software titles
    already kept. Seniority, sales, and product support still drop out."""
    for t in [
        "Business Help Desk", "IT Help Desk", "Help Desk Analyst", "Service Desk Analyst",
        "IT Support", "IT Support Engineer", "I.T. Support Specialist",
        "Desktop Support", "Desktop Support Specialist", "Information Technology Support",
        "Data Analyst", "Data Scientist", "Data Scientist, Developer Productivity",
        "Business Intelligence Analyst", "Systems Administrator", "System Administrator",
        "Systems Analyst", "IT Analyst", "IT Specialist", "Cybersecurity Analyst",
        "Information Security Analyst", "SOC Analyst", "Network Engineer II",
        "Network Administrator", "Computer Science New Grad", "New Grad Computer Scientist",
        "Software Engineer", "New Grad Software Engineer", "Data Engineer",
    ]:
        assert is_target_role(t) is True, t
    for t in [
        "Senior Business Help Desk", "Help Desk Manager", "IT Support Recruiter",
        "Business Help Desk, Sales", "Product Support Engineer III",
        "Technical Support Engineer, Metronome", "Physical Security Analyst",
        "Professor of Computer Science", "Business Systems Analyst, Sales AI & Automation",
        "Machine Learning Specialist",
    ]:
        assert is_target_role(t) is False, t
    # Internships are classified in, then the feed hides them by default.
    assert is_target_role("Business Help Desk Intern") is True
    assert is_target_role("IT Help Desk Intern") is True


def test_a_person_role_before_a_dash_is_not_rescued():
    for t in ["Technical Recruiter - Software Engineering", "Recruiting Coordinator - Engineering",
              "Sales - Software Engineer", "Intern, Marketing", "Contract - Account Executive"]:
        assert is_target_role(t) is False, t


# --- location: US + Canada, any state or city (T26 item 3) -------------------
# The old EXCLUDE_LOCATIONS was a ~25-string denylist: it never asked "is this
# US/Canada?", only "is this one of 25 places I know?". It has no tests at all,
# which is how a refactor silently deleted it (NameError on every posting,
# swallowed by sync_company_jobs' broad except - the board would just go empty).

from app.services.board_sync import is_target_location


def test_keeps_us_and_canada_in_any_form():
    for l in [
        "San Francisco, CA", "Austin", "Atlanta", "Raleigh, NC", "Washington, DC",
        "Remote - United States", "US-San Francisco; US-NYC; US-Remote",
        "NYC, SF, Seattle, US", "US-SF, US-SEA", "CHI and DUB",
        "Toronto, ON, Canada", "Montreal, Canada", "Vancouver, British Columbia",
        "London, Ontario",          # the Canadian London must beat the UK one
        "AMER", "USCA",             # US/Canada region codes
        "Remote - LA; Remote - OK; Remote - TX",  # LA here is Louisiana
    ]:
        assert is_target_location(l) is True, l


def test_every_us_state_and_canadian_province_is_recognised_by_name():
    """A gap here is a silent false drop: "Fargo, North Dakota; Bangalore, India"
    would lose its US half and be rejected outright."""
    from app.services.board_sync import _DOMESTIC
    states = ["alabama","alaska","arizona","arkansas","california","colorado",
        "connecticut","delaware","florida","georgia","hawaii","idaho","illinois",
        "indiana","iowa","kansas","kentucky","louisiana","maine","maryland",
        "massachusetts","michigan","minnesota","mississippi","missouri","montana",
        "nebraska","nevada","new hampshire","new jersey","new mexico","new york",
        "north carolina","north dakota","ohio","oklahoma","oregon","pennsylvania",
        "rhode island","south carolina","south dakota","tennessee","texas","utah",
        "vermont","virginia","washington","west virginia","wisconsin","wyoming"]
    provinces = ["ontario","british columbia","quebec","alberta","manitoba",
        "saskatchewan","nova scotia","new brunswick","newfoundland",
        "prince edward island","yukon","northwest territories","nunavut"]
    assert len(states) == 50
    for name in states + provinces:
        assert _DOMESTIC.search(name), name
    assert is_target_location("Fargo, North Dakota; Bangalore, India") is True


def test_drops_foreign_only_postings():
    for l in [
        "Bengaluru", "Bengaluru, India", "Dublin", "London, UK", "Berlin",
        "Tel Aviv, Israel", "Zurich, Switzerland", "Seoul, South Korea", "Ukraine",
        "Bangkok", "Auckland", "CDMX", "Mexico City, MX", "Luxembourg",
        "Riyadh, Saudi Arabia", "Singapore", "EMEA", "APAC",
        "Bengaluru, India; Delhi, India; Mumbai, India",
    ]:
        assert is_target_location(l) is False, l


def test_any_valid_wins_on_multi_location_postings():
    """A US role also offered abroad is still a US role. The old denylist dropped
    these outright because a foreign name appeared anywhere in the string."""
    for l in [
        "New York, NY | London, UK", "San Francisco, CA; Bengaluru",
        "Raleigh, NC; Bangalore, India", "Austin, TX | Dublin",
        "Dublin, IE; London, UK; New York City, NY",
    ]:
        assert is_target_location(l) is True, l


def test_two_letter_country_codes_are_not_mistaken_for_us_states():
    """NL is Newfoundland *and* the Netherlands; DE Delaware and Germany; IL
    Illinois and Israel. A foreign city in the same unit must win."""
    for l in [
        "Amsterdam, NL", "Berlin, DE", "Tel Aviv, IL", "Bogota, CO",
        "Buenos Aires, AR", "Jakarta, ID", "Panama City, PA", "Bratislava, SK",
        "Valletta, MT", "Casablanca, MA", "Vientiane, LA", "Lima, PE", "Mumbai, IN",
    ]:
        assert is_target_location(l) is False, l


def test_accented_and_local_spellings_are_recognised_as_foreign():
    """Greenhouse sends "Zurich, CH" with an umlaut, and the foreign list holds
    the English exonym. Found live: "Zurich, CH" was being kept as a US job."""
    for l in ["Z\u00fcrich, CH", "M\u00fcnchen, DE", "Krak\u00f3w, PL", "S\u00e3o Paulo, BR",
              "Bogot\u00e1, CO", "Malm\u00f6, SE", "D\u00fcsseldorf", "Gen\u00e8ve", "Wien, AT",
              "Praha", "Lisboa", "Milano", "K\u00f8benhavn", "\u0141\u00f3d\u017a, PL", "G\u00f6teborg"]:
        assert is_target_location(l) is False, l


def test_accent_folding_never_breaks_a_domestic_match():
    """Transliteration must preserve case: _DOMESTIC_CODE matches UPPERCASE
    codes, so lowercasing here stops "Raleigh, NC" counting and silently
    breaks any-valid-wins. That regression happened; this pins it."""
    for l in ["Montr\u00e9al, Canada", "Raleigh, NC", "Raleigh, NC; Bangalore, India",
              "Wilmington, DE", "Indianapolis, IN", "Chicago, IL", "Denver, CO",
              "Boston, MA", "New Orleans, LA", "Philadelphia, PA", "Atlanta, GA"]:
        assert is_target_location(l) is True, l


def test_unambiguous_foreign_country_codes_are_rejected():
    """CH/SE/AT are not US states, so they read as foreign safely. Codes that
    ARE also US states (DE, NL, IL, IN, CO...) are deliberately excluded."""
    assert is_target_location("Basel, CH") is False
    assert is_target_location("Lund, SE") is False
    assert is_target_location("Graz, AT") is False
    assert is_target_location("Wilmington, DE") is True   # Delaware, not Germany


def test_unrecognised_or_missing_locations_are_kept():
    """Losing a real job is worse than showing one the user can skip."""
    for l in [None, "", "N/A", "Hybrid", "In-Office", "Distributed", "LOCATION"]:
        assert is_target_location(l) is True, repr(l)


def test_lowercase_words_never_match_a_state_code():
    """"OR" is Oregon, "or" is not. Codes match uppercase + comma/dash-preceded."""
    assert is_target_location("Poland - Remote OR Romania - Remote") is False
    assert is_target_location("Remote in Germany") is False


def test_world_regions_are_foreign():
    """T29 audit: all six were on the Board as "unknown, so kept"."""
    for l in ["Asia", "Europe", "Remote (Europe)", "Middle East", "Middle East & North Africa",
              "Ljubljana, Slovenia"]:
        assert is_target_location(l) is False, l


def test_a_region_never_hides_a_us_option():
    """Bare "US" must count as domestic, or a region beside it drops the job."""
    for l in ["Remote - US or Europe", "US | Europe", "Remote (US, Europe)", "US Remote"]:
        assert is_target_location(l) is True, l


# --- posting date (T26 finding A) -------------------------------------------
# Greenhouse bulk-rewrites `updated_at`, collapsing whole boards onto a handful
# of timestamps, which clumps the feed by company and buries new roles. The true
# posting date is `first_published`.

import asyncio
import json
from pathlib import Path


import httpx

from app.services import board_sync
from app.services.board_sync import UNDATED, fetch_greenhouse, parse_ats_date


def _fake_board(payload, status=200, headers=None):
    """Stand in for httpx.AsyncClient. Mirrors the streaming API board_sync uses
    (client.stream -> aiter_bytes), not .get(), so the fake cannot drift into
    testing a code path the real fetcher does not take."""
    body = json.dumps(payload).encode()

    class Resp:
        status_code = status

        def __init__(self):
            # httpx.Headers, not a dict: real header lookup is case-insensitive
            # and a plain dict would make "Retry-After" invisible to .get("retry-after").
            self.headers = httpx.Headers(headers or {})

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"HTTP {self.status_code}", request=httpx.Request("GET", "https://x"),
                    response=httpx.Response(self.status_code))

        async def aiter_bytes(self):
            yield body

        async def aread(self):
            return body

    class Stream:
        async def __aenter__(self): return Resp()
        async def __aexit__(self, *a): return False

    class Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def stream(self, method, url, **kw): return Stream()

    return Client


def test_greenhouse_prefers_first_published_over_updated_at(monkeypatch):
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({"jobs": [{
        "title": "Software Engineer",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
        "location": {"name": "San Francisco"},
        "first_published": "2026-01-02T00:00:00-05:00",
        "updated_at": "2026-09-17T00:00:00-04:00",  # bulk-rewritten, must lose
    }]}))
    [job] = asyncio.run(fetch_greenhouse("acme"))
    assert job["published_at"] == "2026-01-02T00:00:00-05:00"


def test_greenhouse_does_not_use_edit_time_when_unpublished(monkeypatch):
    """An edit timestamp is not evidence of publication."""
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({"jobs": [{
        "title": "Software Engineer",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
        "location": {"name": "Remote"},
        "updated_at": "2026-09-17T00:00:00-04:00",
    }]}))
    [job] = asyncio.run(fetch_greenhouse("acme"))
    assert job["published_at"] is None


def test_undated_job_sorts_last_instead_of_floating_to_the_top():
    """now() would re-stamp undated jobs every sync, pinning them to the top."""
    assert parse_ats_date(None) == UNDATED
    assert parse_ats_date("not-a-date") == UNDATED
    assert parse_ats_date("2026-05-01T00:00:00Z") > UNDATED


def test_real_posting_dates_still_parse_per_provider():
    ashby = parse_ats_date("2026-03-12T16:38:15.322+00:00")
    lever = parse_ats_date("1711403416463")  # epoch ms
    greenhouse = parse_ats_date("2026-09-17T13:05:33-04:00")
    assert ashby.year == 2026 and lever.year == 2024 and greenhouse.year == 2026
    assert all(d.tzinfo is None for d in (ashby, lever, greenhouse))  # naive UTC


# --- canonical Greenhouse URL (T26 item 4) ----------------------------------
# Greenhouse's absolute_url points at the company's own careers site for ~44% of
# the postings that reach the board, which jd_adapters.Greenhouse cannot match,
# so tailoring silently used the generic scraper and got 26-44% of the JD.

from app.services import jd_adapters
from app.services.board_sync import greenhouse_url


def test_builds_the_canonical_board_url_not_the_branded_one():
    job = {"id": 8172487, "absolute_url": "https://stripe.com/jobs/search?gh_jid=8172487"}
    assert greenhouse_url("stripe", job) == "https://job-boards.greenhouse.io/stripe/jobs/8172487"


def test_the_url_we_store_is_one_the_greenhouse_adapter_can_actually_use():
    """The contract between board_sync and jd_adapters, pinned in one place.

    This is the T18 lesson: the two modules know about the same ATS and drifted
    apart silently. If either side changes its URL shape, this fails.
    """
    gh = jd_adapters.by_name("greenhouse")
    url = greenhouse_url("stripe", {"id": 8172487, "absolute_url": "https://stripe.com/x"})
    assert gh.match(url) is True
    assert gh.api_url(url) == "https://boards-api.greenhouse.io/v1/boards/stripe/jobs/8172487"


def test_the_branded_url_is_exactly_what_the_adapter_cannot_match():
    """Pins WHY this fix exists, so nobody 'simplifies' it back to absolute_url."""
    gh = jd_adapters.by_name("greenhouse")
    for branded in [
        "https://stripe.com/jobs/search?gh_jid=8172487",
        "https://www.pinterestcareers.com/jobs/?gh_jid=6922682",
        "https://www.brex.com/careers?gh_jid=123",
        "https://careers.airbnb.com/positions/456",
    ]:
        assert gh.match(branded) is False, branded


def test_falls_back_to_absolute_url_when_there_is_no_id():
    job = {"absolute_url": "https://boards.greenhouse.io/acme/jobs/9"}
    assert greenhouse_url("acme", job) == "https://boards.greenhouse.io/acme/jobs/9"
    assert greenhouse_url("acme", {}) is None


def test_a_zero_id_is_still_an_id():
    """`if not jid` would wrongly treat 0 as missing; the check must be `is None`."""
    assert greenhouse_url("acme", {"id": 0, "absolute_url": "https://x.com/y"}) == \
        "https://job-boards.greenhouse.io/acme/jobs/0"


def test_location_fanout_rows_keep_distinct_urls():
    """One role posted in N locations has N distinct Greenhouse ids, so
    canonicalising must not collapse them into a single primary key."""
    jobs = [{"id": i, "absolute_url": "https://databricks.com/x"} for i in (101, 102, 103)]
    urls = {greenhouse_url("databricks", j) for j in jobs}
    assert len(urls) == 3


def test_fetch_greenhouse_stores_the_canonical_url(monkeypatch):
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({"jobs": [{
        "id": 555, "title": "Software Engineer",
        "absolute_url": "https://stripe.com/jobs/search?gh_jid=555",
        "location": {"name": "San Francisco, CA"},
        "first_published": "2026-01-02T00:00:00-05:00",
    }]}))
    [job] = asyncio.run(board_sync.fetch_greenhouse("stripe"))
    assert job["url"] == "https://job-boards.greenhouse.io/stripe/jobs/555"
    assert jd_adapters.by_name("greenhouse").match(job["url"]) is True


def test_ashby_and_lever_urls_are_already_canonical_and_untouched(monkeypatch):
    """Only Greenhouse had the branded-host problem; do not 'fix' the others."""
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({"jobs": [{
        "title": "Software Engineer", "location": "Remote, US",
        "jobUrl": "https://jobs.ashbyhq.com/openai/abc-123", "publishedAt": "2026-03-12T16:38:15Z",
    }]}))
    [job] = asyncio.run(board_sync.fetch_ashby("openai"))
    assert job["url"] == "https://jobs.ashbyhq.com/openai/abc-123"
    assert jd_adapters.by_name("ashby").match(job["url"]) is True


# --- the write path (T26): sync_company_jobs has never been tested ----------
# Its `except Exception: print(...)` turns any bug into a silently empty board.
# That is exactly how a NameError in is_target_location survived a green suite.
# These assert on real rows, so a swallowed exception shows up as zero rows.

from app import db as _db          # resolve SessionLocal at CALL time: conftest's
from app.models import JobPosting, TrackedCompany  # temp-db fixture rebinds it, and a
                                   # module-level `from app.db import SessionLocal`
                                   # would capture the real database instead.


def _sync(monkeypatch, jobs, slug="stripe", provider="greenhouse"):
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({"jobs": jobs}))
    with _db.SessionLocal() as db:
        company = db.get(TrackedCompany, slug) or TrackedCompany(slug=slug, provider=provider)
        db.add(company)
        db.commit()
        asyncio.run(board_sync.sync_company_jobs(db, company))
    with _db.SessionLocal() as db:
        return {r.url: r for r in db.query(JobPosting).all()}


def _gh(jid, title, location, published="2026-01-02T00:00:00-05:00"):
    return {"id": jid, "title": title, "location": {"name": location},
            "absolute_url": f"https://stripe.com/jobs/search?gh_jid={jid}",
            "first_published": published}


def test_sync_writes_only_matching_jobs_with_the_canonical_url(monkeypatch):
    rows = _sync(monkeypatch, [
        _gh(1, "Software Engineer, Payments", "San Francisco, CA"),   # keep
        _gh(2, "Senior Software Engineer", "San Francisco, CA"),      # too senior
        _gh(3, "Software Engineer, iOS", "San Francisco, CA"),        # mobile
        _gh(4, "Account Executive, AI Sales", "San Francisco, CA"),   # not engineering
        _gh(5, "Software Engineer, Core", "Bengaluru, India"),        # foreign
    ])
    assert list(rows) == ["https://job-boards.greenhouse.io/stripe/jobs/1"], list(rows)
    row = rows["https://job-boards.greenhouse.io/stripe/jobs/1"]
    assert row.status == "open"
    assert row.company_slug == "stripe"
    assert row.created_at.year == 2026 and row.created_at.month == 1  # first_published


def test_sync_keeps_a_us_job_that_is_also_offered_abroad(monkeypatch):
    rows = _sync(monkeypatch, [_gh(7, "Backend Engineer", "New York, NY | London, UK")])
    assert len(rows) == 1


def test_a_posting_that_disappears_is_closed_not_deleted(monkeypatch):
    first = _sync(monkeypatch, [_gh(1, "Software Engineer", "San Francisco, CA"),
                                _gh(2, "Backend Engineer", "Austin, TX")])
    assert len(first) == 2 and all(r.status == "open" for r in first.values())
    second = _sync(monkeypatch, [_gh(1, "Software Engineer", "San Francisco, CA")])
    assert second["https://job-boards.greenhouse.io/stripe/jobs/1"].status == "open"
    assert second["https://job-boards.greenhouse.io/stripe/jobs/2"].status == "closed"


def test_an_empty_board_closes_everything_without_losing_rows(monkeypatch):
    _sync(monkeypatch, [_gh(1, "Software Engineer", "Austin, TX")])
    rows = _sync(monkeypatch, [])
    assert len(rows) == 1
    assert all(r.status == "closed" for r in rows.values())


def test_resync_is_idempotent(monkeypatch):
    jobs = [_gh(1, "Software Engineer", "Austin, TX")]
    _sync(monkeypatch, jobs)
    rows = _sync(monkeypatch, jobs)
    assert len(rows) == 1 and rows["https://job-boards.greenhouse.io/stripe/jobs/1"].status == "open"


def test_a_job_with_no_title_or_url_is_skipped_not_crashed(monkeypatch):
    rows = _sync(monkeypatch, [
        {"id": 9, "title": None, "location": {"name": "Austin, TX"}, "first_published": None},
        _gh(1, "Software Engineer", "Austin, TX"),
    ])
    assert list(rows) == ["https://job-boards.greenhouse.io/stripe/jobs/1"]


# --- item 6: architecture ---------------------------------------------------

def test_ats_endpoints_live_in_one_module():
    """T18's lesson: board_sync and jd_adapters both know these hosts, and two
    copies of the same knowledge drift silently. board_sync must not build ATS
    URLs of its own - it asks the adapter."""
    src = Path(board_sync.__file__).read_text()
    for host in ("api.ashbyhq.com", "boards-api.greenhouse.io", "api.lever.co"):
        assert host not in src, f"{host} is hardcoded in board_sync; use jd_adapters.list_url"
    for name, expected in [
        ("ashby", "https://api.ashbyhq.com/posting-api/job-board/acme"),
        ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/acme/jobs"),
        ("lever", "https://api.lever.co/v0/postings/acme?mode=json"),
    ]:
        assert jd_adapters.by_name(name).list_url("acme") == expected


def test_ashby_list_and_single_job_urls_are_the_same_endpoint():
    """Ashby has no per-job endpoint; if these ever diverge one of them is wrong."""
    a = jd_adapters.by_name("ashby")
    assert a.api_url("https://jobs.ashbyhq.com/acme/1234") == a.list_url("acme")


def test_we_identify_ourselves_honestly():
    assert "resume-agent" in board_sync.USER_AGENT
    assert "Chrome" not in board_sync.USER_AGENT


def test_traversal_shaped_slugs_are_refused():
    # single inner spaces are names since T44 ("flock safety" on Ashby); these are not
    for slug in ("../evil", "a/b", "foo  bar", " foo", "foo ", "", "..", "a\\\\b", "x..", "figma\n"):  # $ alone admits a trailing newline
        with pytest.raises(ValueError):
            asyncio.run(board_sync._get_board("greenhouse", slug))


def test_retry_after_accepts_seconds_and_http_dates():
    from email.utils import format_datetime
    from datetime import timedelta as _td

    def resp(value):
        return httpx.Response(429, headers={"Retry-After": value} if value else {})

    assert board_sync._retry_after_seconds(resp("120")) == 120
    assert board_sync._retry_after_seconds(resp(""), default=7) == 7
    assert board_sync._retry_after_seconds(resp("not-a-date"), default=9) == 9
    future = datetime.now(timezone.utc) + _td(seconds=90)
    assert 60 <= board_sync._retry_after_seconds(resp(format_datetime(future))) <= 95
    past = datetime.now(timezone.utc) - _td(seconds=90)
    assert board_sync._retry_after_seconds(resp(format_datetime(past))) == 0  # never negative


def test_rate_limiting_raises_instead_of_sleeping_inside_the_company_call():
    """A fixed sleep inside sync_company_jobs stalled every remaining company
    behind one unhappy vendor. It must surface to the loop instead."""
    for status in (403, 429):
        with pytest.raises(board_sync.RateLimited) as got:
            asyncio.run(_get_with(status, {"Retry-After": "42"}))
        assert got.value.retry_after == 42


async def _get_with(status, headers):
    import unittest.mock as m
    with m.patch.object(board_sync.httpx, "AsyncClient", _fake_board({}, status=status, headers=headers)):
        return await board_sync._get_board("greenhouse", "acme")


def test_a_missing_board_is_not_an_error(monkeypatch):
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({}, status=404))
    assert asyncio.run(board_sync._get_board("greenhouse", "gone")) is None
    # None, not [] - "we could not see the board" must stay distinguishable from
    # "the board is empty", because only the latter justifies closing postings.
    assert asyncio.run(board_sync.fetch_greenhouse("gone")) is None
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({"jobs": []}))
    assert asyncio.run(board_sync.fetch_greenhouse("empty")) == []


def test_a_transient_404_does_not_close_a_companys_whole_feed(monkeypatch):
    """A 404 means we did not observe the board. Closing everything on it would
    wipe a company's feed on one bad request, then reopen it next cycle."""
    _company("acme")
    with _db.SessionLocal() as db:
        company = db.get(TrackedCompany, "acme")
        monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({"jobs": [
            {"id": 1, "title": "Software Engineer", "location": {"name": "Austin, TX"},
             "first_published": "2026-01-02T00:00:00-05:00"}]}))
        assert asyncio.run(board_sync.sync_company_jobs(db, company)) == 1

        monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({}, status=404))
        assert asyncio.run(board_sync.sync_company_jobs(db, company)) == 0
    with _db.SessionLocal() as db:
        assert [r.status for r in db.query(JobPosting).all()] == ["open"]


def test_an_observed_empty_board_still_closes_its_postings(monkeypatch):
    """The other half: a 200 with no jobs IS evidence the postings are gone."""
    _company("acme")
    with _db.SessionLocal() as db:
        company = db.get(TrackedCompany, "acme")
        monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({"jobs": [
            {"id": 1, "title": "Software Engineer", "location": {"name": "Austin, TX"},
             "first_published": "2026-01-02T00:00:00-05:00"}]}))
        asyncio.run(board_sync.sync_company_jobs(db, company))
        monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({"jobs": []}))
        asyncio.run(board_sync.sync_company_jobs(db, company))
    with _db.SessionLocal() as db:
        assert [r.status for r in db.query(JobPosting).all()] == ["closed"]


def test_an_oversized_board_is_refused_rather_than_buffered(monkeypatch):
    monkeypatch.setattr(board_sync, "BOARD_MAX_BYTES", 10)
    monkeypatch.setattr(board_sync.httpx, "AsyncClient",
                        _fake_board({"jobs": [{"title": "x" * 500}]}))
    with pytest.raises(ValueError, match="exceeds"):
        asyncio.run(board_sync._get_board("greenhouse", "acme"))


def test_vendor_failure_and_our_own_bug_are_told_apart(monkeypatch):
    """The whole point of 13b. A vendor problem is expected noise; a NameError in
    our filters must never be swallowed into a silently empty board."""
    with _db.SessionLocal() as db:
        company = TrackedCompany(slug="acme", provider="greenhouse")
        db.add(company); db.commit()

        monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({}, status=500))
        with pytest.raises(board_sync.BoardVendorError):
            asyncio.run(board_sync.sync_company_jobs(db, company))

        monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({"jobs": [{"title": "Software Engineer", "id": 1, "location": {"name": "Austin, TX"}}]}))
        monkeypatch.setattr(board_sync, "is_target_role", lambda t: (_ for _ in ()).throw(NameError("boom")))
        with pytest.raises(NameError):
            asyncio.run(board_sync.sync_company_jobs(db, company))


def _company(slug="acme", provider="greenhouse", last_synced=None, next_check=None):
    with _db.SessionLocal() as db:
        c = TrackedCompany(slug=slug, provider=provider, last_synced_at=last_synced,
                           next_check_at=next_check)
        db.add(c); db.commit()


def test_a_restart_only_checks_boards_that_are_due(monkeypatch):
    """A full ~1000-request cycle used to fire on every uvicorn restart."""
    now = board_policy.utcnow()  # the harvester's clock, pinned by posting_clock
    _company("later", next_check=now + timedelta(minutes=5))
    _company("due", next_check=now - timedelta(minutes=1))
    _company("never", next_check=None)
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({"jobs": []}))
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    stats = asyncio.run(board_sync._harvest_cycle())
    assert stats["companies"] == 2
    with _db.SessionLocal() as db:
        assert db.get(TrackedCompany, "later").last_synced_at is None


def test_one_rate_limited_vendor_does_not_stall_the_rest(monkeypatch):
    _company("a"); _company("b")
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    monkeypatch.setattr(board_sync, "MAX_BACKOFF", 0.01)
    monkeypatch.setattr(board_sync.httpx, "AsyncClient",
                        _fake_board({}, status=429, headers={"Retry-After": "99999"}))
    slept = []
    real_sleep = asyncio.sleep
    async def spy(sec, *a, **k):
        slept.append(sec); return await real_sleep(0)
    monkeypatch.setattr(board_sync.asyncio, "sleep", spy)
    stats = asyncio.run(board_sync._harvest_cycle())
    assert stats["companies"] == 2               # both attempted, not abandoned
    assert max(slept) <= board_sync.MAX_BACKOFF  # Retry-After honoured but capped


def test_a_vendor_error_is_counted_not_crashed(monkeypatch):
    _company("a")
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({}, status=503))
    stats = asyncio.run(board_sync._harvest_cycle())
    assert stats["vendor_errors"] == 1 and stats["bugs"] == 0


def test_our_own_bug_is_counted_separately_and_reported(monkeypatch, capsys):
    _company("a")
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    monkeypatch.setattr(board_sync.httpx, "AsyncClient",
                        _fake_board({"jobs": [{"id": 1, "title": "Software Engineer",
                                               "location": {"name": "Austin, TX"}}]}))
    monkeypatch.setattr(board_sync, "is_target_role",
                        lambda t: (_ for _ in ()).throw(NameError("EXCLUDE_LOCATIONS")))
    stats = asyncio.run(board_sync._harvest_cycle())
    assert stats["bugs"] == 1 and stats["vendor_errors"] == 0
    captured = capsys.readouterr()
    assert "OUR code" in captured.out          # the summary line
    assert "NameError" in captured.err         # the traceback, correctly on stderr


def test_a_cycle_that_writes_nothing_says_so(monkeypatch, capsys):
    """The silent-empty-board failure mode, made audible."""
    _company("a")
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _fake_board({"jobs": []}))
    stats = asyncio.run(board_sync._harvest_cycle())
    assert stats["kept"] == 0
    assert "no eligible postings" in capsys.readouterr().out


def test_a_normal_cycle_reports_what_it_kept(monkeypatch, capsys):
    _company("a")
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    monkeypatch.setattr(board_sync.httpx, "AsyncClient",
                        _fake_board({"jobs": [{"id": 1, "title": "Software Engineer",
                                               "location": {"name": "Austin, TX"},
                                               "first_published": "2026-01-02T00:00:00-05:00"}]}))
    stats = asyncio.run(board_sync._harvest_cycle())
    assert stats["kept"] == 1 and stats["bugs"] == 0 and stats["vendor_errors"] == 0
    assert "no eligible postings" not in capsys.readouterr().out


def test_prefix_style_exclusions_match_their_longer_forms():
    """The alternation is wrapped in \\b(...)\\b, so a stem like "facilit" never
    matched "Facilities". Found by auditing what a live harvest actually wrote."""
    for t in ["Facilities Engineer", "Facility Engineer",
              "Datacenter Engineer", "Data Centre Engineer", "Data Center Engineer"]:
        assert is_target_role(t) is False, t


def test_recruiter_titles_are_rejected_by_the_engineering_gate_alone():
    """Deliberately NOT handled by the non-software list: a "recruit" stem would
    also reject "Recruiting Analytics Data Engineer", which is a real data role."""
    for t in ["AI Recruiter", "Technical Recruiter", "Recruiting Coordinator",
              "Recruiter, Technical", "Recruiting Manager"]:
        assert is_target_role(t) is False, t
    assert is_target_role("Recruiting Analytics Data Engineer") is True
    assert is_target_role("Analytics Engineer") is True


def test_an_unknown_or_listless_provider_fails_clearly():
    """A bare next() in by_name surfaced as "RuntimeError: coroutine raised
    StopIteration" - useless when a scout inserts an unexpected provider.
    Workday is a real adapter with no board-listing endpoint."""
    with pytest.raises(LookupError):
        jd_adapters.by_name("nope")
    for provider in ("nosuchprovider", "workday"):
        with pytest.raises(ValueError, match="cannot list a board"):
            asyncio.run(board_sync._get_board(provider, "acme"))


def test_the_scout_identifies_itself_too():
    """It fetches GitHub and Serper; it was sending no User-Agent at all."""
    src = Path(board_sync.__file__).read_text()
    scout = src[src.index("async def _scout("):src.index("async def scout_loop")]
    assert "AsyncClient(timeout=15.0)" not in scout, "scout client sends no User-Agent"
    assert "USER_AGENT" in scout


def test_one_failing_company_does_not_lose_another_companys_work(monkeypatch):
    """Each failure path rolls the session back. Prove that rollback does not
    discard a sibling company's committed postings."""
    _company("good"); _company("bad")
    good_board = {"jobs": [{"id": 1, "title": "Software Engineer",
                            "location": {"name": "Austin, TX"},
                            "first_published": "2026-01-02T00:00:00-05:00"}]}
    # Routed by URL: a lane reuses one client for all its boards (T30).
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _routed({
        "/boards/good/": (good_board, 200, {}), "/boards/bad/": ({}, 500, {})}))
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    stats = asyncio.run(board_sync._harvest_cycle())
    assert stats["kept"] == 1 and stats["vendor_errors"] == 1 and stats["bugs"] == 0
    with _db.SessionLocal() as db:
        assert db.query(JobPosting).count() == 1


def test_only_one_traceback_is_printed_however_many_companies_break(monkeypatch, capsys):
    """900 identical tracebacks is noise; one is a signal. The count carries the rest."""
    for i in range(4):
        _company(f"c{i}")
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    monkeypatch.setattr(board_sync.httpx, "AsyncClient",
                        _fake_board({"jobs": [{"id": 1, "title": "Software Engineer",
                                               "location": {"name": "Austin, TX"}}]}))
    monkeypatch.setattr(board_sync, "is_target_role",
                        lambda t: (_ for _ in ()).throw(NameError("boom")))
    stats = asyncio.run(board_sync._harvest_cycle())
    assert stats["bugs"] == 4
    # count tracebacks, not the exception name: one traceback mentions NameError
    # several times across its frames.
    assert capsys.readouterr().err.count("Traceback (most recent call last)") == 1


# --- scout (had zero coverage) ---------------------------------------------

def test_discover_slugs_finds_all_three_providers():
    text = ("boards.greenhouse.io/acme jobs.ashbyhq.com/Beta "
            "jobs.lever.co/gamma and some prose")
    assert sorted(board_sync.discover_slugs(text)) == [
        ("ashby", "beta"), ("greenhouse", "acme"), ("lever", "gamma")]


def test_discover_slugs_rejects_traversal_shaped_slugs():
    """The capture class permits dots, so "boards.greenhouse.io/../x" yields "..".
    Stored unfiltered it fails EVERY harvest cycle forever as a vendor error."""
    found = board_sync.discover_slugs("boards.greenhouse.io/.. and jobs.lever.co/ok")
    assert found == [("lever", "ok")]


def test_discover_slugs_dedupes_case_only_where_the_vendor_ignores_it():
    """T44: Greenhouse, Ashby and SmartRecruiters ignore case; Lever 404s a name in
    the wrong case both ways (palantir, CesiumAstro), and a year of Wayback held 178
    Lever boards that answer only as written. Workable accounts are all lowercase
    (TickPick redirects to /oops), so a capitalised link is repaired."""
    text = ("boards.greenhouse.io/Figma boards.greenhouse.io/figma jobs.ashbyhq.com/Acme jobs.ashbyhq.com/ACME "
            "jobs.lever.co/CesiumAstro jobs.lever.co/Palantir jobs.lever.co/palantir "
            "apply.workable.com/TickPick/j/5840ECEB50/")
    assert board_sync.discover_slugs(text) == [
        ("greenhouse", "figma"), ("ashby", "acme"),
        ("lever", "CesiumAstro"), ("lever", "Palantir"), ("lever", "palantir"), ("workable", "tickpick")]


def test_an_ashby_board_with_a_space_in_its_name_is_found_whole():
    """T44: 127 live Ashby boards have a space (Flock%20Safety); the pattern stopped
    at "%" and tracked "flock", another company's board. Scraped junk after a name
    (a backslash: 143 of 347 encoded Wayback names) is not part of it."""
    text = ("https://jobs.ashbyhq.com/Superhuman%20Platform%20Inc/134c?embed=true jobs.ashbyhq.com/trunk%20tools%5C "
            "jobs.ashbyhq.com/Xpansiv%20/1 jobs.ashbyhq.com/Flock%20Safety/41 "
            "jobs.ashbyhq.com/%20/x jobs.ashbyhq.com/a%20%20b/1")  # nothing but a space; a double space
    assert board_sync.discover_slugs(text) == [("ashby", "flock safety"), ("ashby", "superhuman platform inc"),
                                               ("ashby", "trunk tools"), ("ashby", "xpansiv")]


def test_a_slug_may_hold_single_inner_spaces_only():
    ok, bad = ["trunk tools", "superhuman platform inc", "a.b-c_d"], [" trunk", "trunk ", "a  b", "a..b", "a b..c", ""]
    assert all(board_sync._SLUG_OK.fullmatch(s) for s in ok)
    assert not any(board_sync._SLUG_OK.fullmatch(s) for s in bad)


def test_a_spaced_ashby_board_is_requested_with_the_space_encoded():
    seen = []

    def handler(request):
        seen.append(request.url.raw_path)
        return httpx.Response(200, json={"jobs": []})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(board_sync._get_board("ashby", "superhuman platform inc", client)) == {"jobs": []}
    assert seen == [b"/posting-api/job-board/superhuman%20platform%20inc"]


def _listings(body, status=200):
    """Stand in for the scout's client: GET returns SimplifyJobs listings.json.
    body is the parsed JSON, or an exception for .json() to raise."""
    class Resp:
        status_code = status
        def json(self):
            if isinstance(body, Exception):
                raise body
            return body
    class Client:
        async def get(self, url, **kw):
            assert url == board_sync.SIMPLIFY_LISTINGS
            return Resp()
    return Client()


def test_scout_tracks_new_companies(monkeypatch):
    client = _listings([{"active": True, "url": "https://job-boards.greenhouse.io/newco/jobs/1"},
                        {"active": True, "url": "https://jobs.lever.co/otherco/abc?lever-source=Simplify"}])
    with _db.SessionLocal() as db:
        added = asyncio.run(board_sync._scout_github(client, db))
        assert added == 2
        slugs = {c.slug: c for c in db.query(TrackedCompany).all()}
    assert slugs["newco"].provider == "greenhouse"
    assert slugs["newco"].discovery_source == "simplify"
    assert slugs["otherco"].provider == "lever"


def test_scout_counts_only_companies_that_are_new(monkeypatch):
    """It used to print every sighting as if it were a discovery."""
    client = _listings([{"active": True, "url": "https://jobs.ashbyhq.com/acme/1"},
                        {"active": True, "url": "https://jobs.ashbyhq.com/acme/2"}])
    with _db.SessionLocal() as db:
        assert asyncio.run(board_sync._scout_github(client, db)) == 1
        assert asyncio.run(board_sync._scout_github(client, db)) == 0


def test_scout_ignores_closed_and_malformed_listings(monkeypatch):
    client = _listings([{"active": False, "url": "https://jobs.ashbyhq.com/closedco/1"},
                        {"active": "yes", "url": "https://jobs.ashbyhq.com/truthyco/1"},
                        {"active": True, "url": None}, {"active": True}, "a string", 7,
                        {"active": True, "url": "https://boards.greenhouse.io/embed/job_app?token=1"},
                        {"active": True, "url": "https://jobs.ashbyhq.com/embedding-vc/1"}])
    with _db.SessionLocal() as db:
        assert asyncio.run(board_sync._scout_github(client, db)) == 1
        assert [c.slug for c in db.query(TrackedCompany)] == ["embedding-vc"]


@pytest.mark.parametrize("body", [ValueError("not json"), {"not": "a list"}])
def test_a_broken_listings_file_is_vendor_noise_not_a_crash(monkeypatch, body, capsys):
    with _db.SessionLocal() as db:
        assert asyncio.run(board_sync._scout_github(_listings(body), db)) == 0
    assert "[scout] listings.json" in capsys.readouterr().out


def test_scout_does_not_flip_an_existing_companys_provider(monkeypatch):
    """Overwriting provider orphans the postings harvested under the old one."""
    _company("acme", provider="greenhouse")
    with _db.SessionLocal() as db:
        asyncio.run(board_sync._scout_github(_listings([{"active": True, "url": "https://jobs.lever.co/acme/1"}]), db))
        assert db.get(TrackedCompany, "acme").provider == "greenhouse"


def test_scout_skips_a_source_that_does_not_return_200(monkeypatch):
    client = _listings([{"active": True, "url": "https://jobs.ashbyhq.com/shouldnotappear/1"}], status=404)
    with _db.SessionLocal() as db:
        assert asyncio.run(board_sync._scout_github(client, db)) == 0
        assert db.query(TrackedCompany).count() == 0


def test_scout_skips_serper_without_a_key(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    with _db.SessionLocal() as db:
        assert asyncio.run(board_sync._scout_serper(object(), db)) == 0


# --- T29: dead and moved boards, conditional GET, rolling cadence ------------

from datetime import timedelta


@pytest.fixture(autouse=True)
def fresh_etags():
    board_sync._ETAGS.clear(); board_sync._UNCOMMITTED_ETAGS.clear()
    yield
    board_sync._ETAGS.clear(); board_sync._UNCOMMITTED_ETAGS.clear()


def _routed(routes, seen=None):
    """Like _fake_board, but answers per vendor host and records each request.
    routes: {host fragment: (payload, status, headers) or a callable(headers)
    returning one}. Any host not routed answers 404, like a vendor without
    that slug."""
    def answer(url, headers):
        for fragment, route in routes.items():
            if fragment in url:
                return route(headers) if callable(route) else route
        return ({}, 404, {})

    class Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def stream(self, method, url, headers=None, **kw):
            if seen is not None:
                seen.append((url, dict(headers or {})))
            payload, status, hdrs = answer(url, headers or {})
            return _fake_board(payload, status=status, headers=hdrs)().stream(method, url)
    return Client


GH, ASHBY, LEVER = "boards-api.greenhouse.io", "api.ashbyhq.com", "api.lever.co"
_ASHBY_JOB = {"id": "a1", "title": "Software Engineer", "location": "Austin, TX",
              "jobUrl": "https://jobs.ashbyhq.com/acme/a1", "publishedAt": "2026-01-02T00:00:00Z"}
_GH_JOB = {"id": 1, "title": "Software Engineer", "location": {"name": "Austin, TX"},
           "first_published": "2026-01-02T00:00:00-05:00"}


def _sync_acme(monkeypatch, client):
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", client)
    with _db.SessionLocal() as db:
        company = db.get(TrackedCompany, "acme")
        result = asyncio.run(board_sync.sync_company_jobs(db, company))
    with _db.SessionLocal() as db:
        return result, db.get(TrackedCompany, "acme"), {r.url: r for r in db.query(JobPosting)}


def test_a_board_that_moved_ats_is_followed(monkeypatch):
    """Notion, Sentry, Zapier... 404'd on their recorded ATS for hours on end."""
    _company("acme", provider="greenhouse")
    kept, company, rows = _sync_acme(monkeypatch, _routed({ASHBY: ({"jobs": [_ASHBY_JOB]}, 200, {})}))
    assert kept == 1 and company.provider == "ashby" and company.gone_at is None
    assert list(rows) == ["https://jobs.ashbyhq.com/acme/a1"]


def test_the_old_ats_postings_close_once_the_move_is_seen(monkeypatch):
    _company("acme", provider="greenhouse")
    _sync_acme(monkeypatch, _routed({GH: ({"jobs": [_GH_JOB]}, 200, {})}))
    _, _, rows = _sync_acme(monkeypatch, _routed({ASHBY: ({"jobs": [_ASHBY_JOB]}, 200, {})}))
    assert rows["https://job-boards.greenhouse.io/acme/jobs/1"].status == "closed"
    assert rows["https://jobs.ashbyhq.com/acme/a1"].status == "open"


def test_a_board_on_no_ats_is_parked_and_keeps_its_postings(monkeypatch):
    _company("acme", provider="greenhouse")
    _sync_acme(monkeypatch, _routed({GH: ({"jobs": [_GH_JOB]}, 200, {})}))
    seen = []
    kept, company, rows = _sync_acme(monkeypatch, _routed({}, seen))
    assert kept == 0 and company.gone_at is not None and company.provider == "greenhouse"
    assert sorted(u.split("/")[2] for u, _ in seen) == sorted([GH, LEVER, ASHBY])  # all three asked
    assert [r.status for r in rows.values()] == ["open"]  # a 404 is not proof of closure


def test_a_parked_board_is_rechecked_after_a_week_not_before(monkeypatch):
    now = board_policy.utcnow()
    _company("dead")
    seen = []
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _routed({}, seen))  # 404 everywhere
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    asyncio.run(board_sync._harvest_cycle())
    with _db.SessionLocal() as db:
        c = db.get(TrackedCompany, "dead")
        assert (c.gone_at, c.next_check_at) == (now, now + board_sync.PARK_FOR)
    asked = len(seen)
    monkeypatch.setattr(board_policy, "utcnow", lambda: now + board_sync.PARK_FOR - timedelta(seconds=1))
    asyncio.run(board_sync._harvest_cycle())
    assert len(seen) == asked                                   # a second early: not asked
    monkeypatch.setattr(board_policy, "utcnow", lambda: now + board_sync.PARK_FOR)
    asyncio.run(board_sync._harvest_cycle())
    assert len(seen) > asked                                    # a week on: rechecked


def test_a_board_that_comes_back_is_unparked(monkeypatch):
    with _db.SessionLocal() as db:
        db.add(TrackedCompany(slug="acme", provider="greenhouse", gone_at=datetime(2025, 1, 1)))
        db.commit()
    kept, company, _ = _sync_acme(monkeypatch, _routed({GH: ({"jobs": [_GH_JOB]}, 200, {})}))
    assert kept == 1 and company.gone_at is None


def test_a_stale_etag_on_the_other_ats_cannot_hide_a_moved_board(monkeypatch):
    """A 304 carries no jobs, so re-resolve must ask unconditionally."""
    _company("acme", provider="greenhouse")
    board_sync._ETAGS[("ashby", "acme")] = '"old"'
    ashby = lambda h: ({}, 304, {}) if "If-None-Match" in h else ({"jobs": [_ASHBY_JOB]}, 200, {})
    kept, company, _ = _sync_acme(monkeypatch, _routed({ASHBY: ashby}))
    assert kept == 1 and company.provider == "ashby"


def _not_modified_since(etag):
    return lambda h: ({}, 304, {}) if h.get("If-None-Match") == etag else ({"jobs": []}, 200, {})


def test_an_unchanged_board_is_not_reprocessed(monkeypatch):
    _company("acme", provider="greenhouse")
    seen = []
    etagged = _routed({GH: ({"jobs": [_GH_JOB]}, 200, {"ETag": 'W/"v1"'})}, seen)
    assert _sync_acme(monkeypatch, etagged)[0] == 1
    kept, company, rows = _sync_acme(monkeypatch, _routed({GH: _not_modified_since('W/"v1"')}, seen))
    assert kept is None                                    # "unchanged", not "0 kept"
    assert seen[-1][1]["If-None-Match"] == 'W/"v1"'
    assert [r.status for r in rows.values()] == ["open"]   # an empty 200 would have closed it
    assert company.last_synced_at is not None


def test_a_parked_board_that_answers_304_on_recheck_is_unparked(monkeypatch):
    """Its ETag survives the park, so an unchanged board comes back as a 304."""
    _company("acme", provider="greenhouse")
    _sync_acme(monkeypatch, _routed({GH: ({"jobs": [_GH_JOB]}, 200, {"ETag": '"v1"'})}))
    assert _sync_acme(monkeypatch, _routed({}))[1].gone_at is not None   # 404 everywhere: parked
    kept, company, _ = _sync_acme(monkeypatch, _routed({GH: _not_modified_since('"v1"')}))
    assert kept is None and company.gone_at is None


def test_an_etag_is_trusted_only_after_its_rows_commit(monkeypatch):
    """If processing crashes, the next request must refetch, not get a 304 that
    pins whatever half-state the crash left."""
    _company("acme", provider="greenhouse")
    real_filter = board_sync.is_target_role
    monkeypatch.setattr(board_sync, "is_target_role", lambda t: (_ for _ in ()).throw(NameError("bug")))
    with pytest.raises(NameError):
        _sync_acme(monkeypatch, _routed({GH: ({"jobs": [_GH_JOB]}, 200, {"ETag": '"v1"'})}))
    assert board_sync._ETAGS == {}
    # NOT monkeypatch.undo(): it would also undo conftest's temp-DB patch.
    monkeypatch.setattr(board_sync, "is_target_role", real_filter)
    seen = []
    _sync_acme(monkeypatch, _routed({GH: ({"jobs": [_GH_JOB]}, 200, {"ETag": '"v2"'})}, seen))
    assert "If-None-Match" not in seen[0][1]
    assert board_sync._ETAGS == {("greenhouse", "acme"): '"v2"'}


def test_an_etag_dropped_by_the_vendor_is_forgotten(monkeypatch):
    _company("acme", provider="greenhouse")
    _sync_acme(monkeypatch, _routed({GH: ({"jobs": [_GH_JOB]}, 200, {"ETag": '"v1"'})}))
    _sync_acme(monkeypatch, _routed({GH: ({"jobs": [_GH_JOB]}, 200, {})}))
    assert board_sync._ETAGS == {}


def test_an_all_unchanged_pass_does_not_cry_empty_board(monkeypatch, capsys):
    _company("a")
    board_sync._ETAGS[("greenhouse", "a")] = '"v1"'
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _routed({GH: ({}, 304, {})}))
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    stats = asyncio.run(board_sync._harvest_cycle())
    assert stats["unchanged"] == 1 and stats["kept"] == 0
    assert "no eligible postings" not in capsys.readouterr().out


@pytest.mark.parametrize("status", [503, 429])
def test_a_failing_board_waits_the_interval_instead_of_every_pass(monkeypatch, status):
    """With a 60s poll, an unstamped failure would be refetched ~60 times an hour."""
    _company("a")
    seen = []
    monkeypatch.setattr(board_sync.httpx, "AsyncClient",
                        _routed({GH: ({}, status, {"Retry-After": "0"})}, seen))
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    asyncio.run(board_sync._harvest_cycle())
    second = asyncio.run(board_sync._harvest_cycle())
    assert len(seen) == 1 and second["companies"] == 0


def test_a_quiet_pass_prints_nothing(monkeypatch, capsys):
    _company("a", next_check=board_policy.utcnow() + timedelta(hours=1))
    stats = asyncio.run(board_sync._harvest_cycle())
    assert stats["companies"] == 0 and capsys.readouterr().out == ""


@pytest.mark.parametrize("due_in, expected", [(12, 12.0), (3600, 30.0), (None, 30.0)])
def test_an_idle_worker_sleeps_until_the_next_board_is_due(monkeypatch, due_in, expected):
    """Never a busy loop, and never longer than WORKER_IDLE, so a board pasted
    meanwhile is picked up within 30 s."""
    if due_in is not None:
        _company("soon", next_check=board_policy.utcnow() + timedelta(seconds=due_in))
    slept = []
    async def sleep(seconds):
        slept.append(seconds)
        raise asyncio.CancelledError
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _routed({}))
    monkeypatch.setattr(board_sync.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(board_sync._vendor_worker("greenhouse", board_sync._new_stats()))
    assert slept == [expected]


def test_an_existing_db_file_gains_the_gone_at_column(tmp_path, monkeypatch):
    """create_all never ALTERs; without the migration every harvest would crash."""
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tracked_companies (slug VARCHAR PRIMARY KEY, "
                          "provider VARCHAR, discovery_source VARCHAR, last_synced_at DATETIME)"))
        conn.execute(text("INSERT INTO tracked_companies VALUES ('acme', 'lever', 'github', NULL)"))
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(_db, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    _db.init_db()
    assert "gone_at" in {c["name"] for c in inspect(engine).get_columns("tracked_companies")}
    with _db.SessionLocal() as db:
        c = db.get(TrackedCompany, "acme")
        assert (c.gone_at, c.next_check_at, c.check_interval) == (None, None, None)  # T31 columns
    assert any("next_check_at" in ix["column_names"] for ix in inspect(engine).get_indexes("tracked_companies"))


def test_an_existing_db_file_gains_the_first_seen_column(tmp_path, monkeypatch):
    """T46: postings stored before it have no first sight (NULL), never a guess."""
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import sessionmaker
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE job_postings (url VARCHAR PRIMARY KEY, company_slug VARCHAR, title VARCHAR, "
                          "location VARCHAR, status VARCHAR, created_at DATETIME, updated_at DATETIME)"))
        conn.execute(text("INSERT INTO job_postings VALUES ('u', 'acme', 'SWE', NULL, 'open', "
                          "'2026-10-01 00:00:00', '2026-10-01 00:00:00')"))
    monkeypatch.setattr(_db, "engine", engine)
    monkeypatch.setattr(_db, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    _db.init_db()
    assert "first_seen_at" in {c["name"] for c in inspect(engine).get_columns("job_postings")}
    with _db.SessionLocal() as db:
        assert db.get(JobPosting, "u").first_seen_at is None


def test_discover_slugs_never_yields_the_greenhouse_embed_path():
    text = "https://boards.greenhouse.io/embed/job_app?token=7669159003 jobs.ashbyhq.com/embedding-vc/x"
    assert board_sync.discover_slugs(text) == [("ashby", "embedding-vc")]


def test_serper_rotates_the_phrase_across_every_site(monkeypatch, capsys):
    monkeypatch.setenv("SERPER_API_KEY", "k")
    asked = []
    class Resp:
        status_code = 200
        def __init__(self, q): self.q = q
        def json(self):
            if "jobs.ashbyhq.com" in self.q:
                return {"organic": [{"link": "https://jobs.ashbyhq.com/newco/1"},
                                    {"link": "https://jobs.ashbyhq.com/newco/2"}]}
            if "myworkdayjobs.com" in self.q:  # T36: a Workday result becomes a board
                return {"organic": [{"link": "https://acme.wd5.myworkdayjobs.com/en-US/External/job/X/SWE_R1"}]}
            return {"organic": [{"link": "https://www.youtube.com/watch?v=x"}]}  # site: fell back
    class Client:
        async def post(self, url, json=None, **kw):
            asked.append(json); return Resp(json["q"])
    with _db.SessionLocal() as db:
        assert asyncio.run(board_sync._scout_serper(Client(), db)) == 2
        assert db.get(TrackedCompany, "acme").boards == ["https://acme.wd5.myworkdayjobs.com/External"]
    assert [q["q"].split('"')[0].strip() for q in asked] == [f"site:{s}" for s in board_sync.SERPER_SITES]
    assert len({q["q"].split('"')[1] for q in asked}) == 1          # one phrase per day
    assert all(set(q) == {"q"} for q in asked)                        # no page/tbs: both break site:
    out = capsys.readouterr().out
    assert "0 boards in 1 results" in out                              # a fallback is visible


def test_every_serper_phrase_is_used_across_a_full_rotation():
    """One phrase per day, including help desk and the other CS roles.
    Still one query per site, so a day does not cost more credits."""
    import datetime as dt
    n = len(board_sync.SERPER_PHRASES)
    days = [dt.date(2026, 9, 23) + dt.timedelta(d) for d in range(n)]
    used = {board_sync.SERPER_PHRASES[d.toordinal() % n] for d in days}
    assert used == set(board_sync.SERPER_PHRASES)
    joined = " ".join(board_sync.SERPER_PHRASES).lower()
    for phrase in ("software engineer", "business help desk", "it support", "network engineer",
                   "computer science new grad"):
        assert phrase in joined


_JSEARCH_KEY_NAMES = ("JSEARCH_API_KEY", "OPENWEBNINJA_API_KEY", "RAPIDAPI_KEY",
                      "JSEARCH_API_URL", "JSEARCH_API_HOST")
_DESK_URL = "https://www.linkedin.com/jobs/view/desk-100"
_SWE_URL = "https://www.linkedin.com/jobs/view/swe-100"
_INTERN_URL = "https://www.linkedin.com/jobs/view/intern-100"
_DESK_NEXT = "https://www.linkedin.com/jobs/view/desk-100b"


def _clear_jsearch_env(monkeypatch):
    for name in _JSEARCH_KEY_NAMES:
        monkeypatch.delenv(name, raising=False)


def _jsearch_job(**over):
    job = {
        "job_id": "desk-100",
        "job_uid": "uid-desk",
        "job_title": "Business Help Desk",
        "employer_name": "Northwind",
        "employer_website": "https://northwind.example",
        "job_publisher": "LinkedIn",
        "job_employment_type": "Full-time",
        "job_employment_types": ["FULLTIME"],
        "job_apply_link": _DESK_URL,
        "job_apply_is_direct": False,
        "apply_options": [{
            "apply_link": "https://example.invalid/not-this",
            "is_direct": False,
            "publisher": "LinkedIn",
        }],
        "job_description": "<p>Answer the business help desk queue.</p>",
        "job_is_remote": False,
        "job_posted_at": "2026-01-02T15:00:00.000Z",
        "job_location": "San Francisco, CA",
        "job_city": "San Francisco",
        "job_state": "CA",
        "job_country": "US",
        "job_google_link": "https://www.google.com/search?q=desk",
        "job_min_salary": None,
        "job_max_salary": None,
        "job_salary_period": None,
        "job_highlights": {"Qualifications": ["Help desk experience"]},
    }
    job.update(over)
    return job


def test_jsearch_mapping_prefers_the_apply_link_and_parses_posted_time():
    now = board_policy.utcnow()
    mapped = board_sync.map_jsearch_job(_jsearch_job(), now)
    assert mapped["url"] == _DESK_URL
    assert mapped["title"] == "Business Help Desk"
    assert mapped["company"] == "Northwind"
    assert mapped["location"] == "San Francisco, CA"
    assert mapped["country"] == "US"
    assert mapped["employment"] == {"FULLTIME"}
    assert "Answer the business help desk queue." in mapped["description"]
    assert "Help desk experience" in mapped["description"]
    assert mapped["published_at"] == datetime(2026, 1, 2, 15, 0)
    relative = board_sync.map_jsearch_job(_jsearch_job(job_posted_at="2 days ago"), now)
    assert relative["published_at"] == now - timedelta(days=2)
    via_option = board_sync.map_jsearch_job(_jsearch_job(
        job_apply_link=None,
        apply_options=[{"apply_link": "https://boards.example/direct", "is_direct": True, "publisher": "Acme"},
                       {"apply_link": "https://boards.example/other", "is_direct": False, "publisher": "Indeed"}],
    ), now)
    assert via_option["url"] == "https://boards.example/direct"


def test_jsearch_stores_fulltime_jobs_and_hides_interns(monkeypatch):
    """A mocked Google Jobs page lands on the board. The one sample role is not the catalog."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models import JobPosting

    _clear_jsearch_env(monkeypatch)
    monkeypatch.setenv("JSEARCH_API_KEY", "k")
    _company("acme", provider="greenhouse")
    _sync_acme(monkeypatch, _routed({GH: ({"jobs": [_GH_JOB]}, 200, {})}))
    greenhouse = "https://job-boards.greenhouse.io/acme/jobs/1"
    payload = {"status": "OK", "data": [
        _jsearch_job(),
        _jsearch_job(job_id="swe-100", job_title="Software Engineer", employer_name="Contoso",
                     job_apply_link=_SWE_URL, job_location="Austin, TX",
                     job_description="Build the API platform.", job_highlights={}),
        _jsearch_job(job_id="intern-100", job_title="Business Help Desk Intern",
                     employer_name="Fabrikam", job_apply_link=_INTERN_URL,
                     job_description="Internship on the help desk.", job_highlights={}),
        _jsearch_job(job_id="part-100", job_title="IT Support", employer_name="Partco",
                     job_apply_link="https://www.linkedin.com/jobs/view/part-100",
                     job_employment_type="Part-time", job_employment_types=["PARTTIME"],
                     job_description="Part-time support.", job_highlights={}),
        _jsearch_job(job_id="uk-100", job_title="Software Engineer", employer_name="London Co",
                     job_apply_link="https://www.linkedin.com/jobs/view/uk-100",
                     job_location="London, UK", job_country="GB",
                     job_description="London software role.", job_highlights={}),
    ]}

    class Client:
        def __init__(self):
            self.calls = []

        async def get(self, url, params=None, headers=None, **kwargs):
            self.calls.append((url, params, headers))
            class Resp:
                status_code = 200
                def json(self):
                    return payload
            return Resp()

    client = Client()
    with _db.SessionLocal() as db:
        assert asyncio.run(board_sync._scout_jsearch(client, db)) == 3
        assert asyncio.run(board_sync._scout_jsearch(client, db)) == 0
    assert len(client.calls) == 2  # dedup is storage, not a second kind of search
    url, params, headers = client.calls[0]
    assert url == "https://jsearch.p.rapidapi.com/search"
    assert headers["X-RapidAPI-Key"] == "k"
    assert headers["X-RapidAPI-Host"] == "jsearch.p.rapidapi.com"
    assert params["country"] == "us" and params["employment_types"] == "FULLTIME"
    assert params["num_pages"] == "1"
    assert params["query"] in board_sync.JSEARCH_QUERIES

    with _db.SessionLocal() as db:
        rows = {row.url: row for row in db.query(JobPosting)}
        assert rows[greenhouse].status == "open" and rows[greenhouse].company_slug == "acme"
        assert rows[greenhouse].title == "Software Engineer"
        desk = rows[_DESK_URL]
        assert (desk.title, desk.location, desk.company_slug) == (
            "Business Help Desk", "San Francisco, CA", "jsearch-northwind")
        assert db.get(TrackedCompany, "jsearch-northwind").name == "Northwind"
        assert desk.created_at == datetime(2026, 1, 2, 15, 0)
        assert "Answer the business help desk queue." in desk.description
        assert rows[_SWE_URL].title == "Software Engineer"
        assert rows[_INTERN_URL].title == "Business Help Desk Intern"
        assert "https://www.linkedin.com/jobs/view/part-100" not in rows
        assert "https://www.linkedin.com/jobs/view/uk-100" not in rows
        # Same job_id, new apply link: one row, and the Greenhouse posting stays.
        again = dict(payload)
        again["data"] = [{**payload["data"][0], "job_apply_link": _DESK_NEXT}]
        payload = again

        class Once:
            async def get(self, url, params=None, headers=None, **kwargs):
                class Resp:
                    status_code = 200
                    def json(self):
                        return payload
                return Resp()

        assert asyncio.run(board_sync._scout_jsearch(Once(), db)) == 0
        rows = {row.url: row for row in db.query(JobPosting)}
        assert _DESK_URL not in rows and rows[_DESK_NEXT].external_id == "desk-100"
        assert rows[greenhouse].status == "open" and rows[greenhouse].company_slug == "acme"

    _sync_acme(monkeypatch, _routed({GH: ({"jobs": [_GH_JOB]}, 200, {})}))
    with _db.SessionLocal() as db:
        rows = {row.url: row for row in db.query(JobPosting)}
        assert rows[greenhouse].status == "open"
        assert rows[_DESK_NEXT].status == "open" and rows[_SWE_URL].status == "open"

    feed = TestClient(app).get("/board").json()
    shown = {job["url"]: job for job in feed["jobs"]}
    assert shown[_DESK_NEXT]["company_name"] == "Northwind"
    assert shown[_DESK_NEXT]["location"] == "San Francisco, CA"
    assert shown[_SWE_URL]["company_name"] == "Contoso"
    assert _INTERN_URL not in shown and greenhouse in shown
    with_interns = TestClient(app).get("/board?include_interns=true").json()
    assert _INTERN_URL in {job["url"] for job in with_interns["jobs"]}


def test_jsearch_skips_the_call_without_a_key(monkeypatch, capsys):
    _clear_jsearch_env(monkeypatch)

    class Client:
        async def get(self, *args, **kwargs):
            raise AssertionError("live call without a key")

    with _db.SessionLocal() as db:
        assert asyncio.run(board_sync._scout_jsearch(Client(), db)) == 0
        assert db.query(JobPosting).count() == 0
    assert "skipping Google Jobs" in capsys.readouterr().out


def test_openwebninja_key_uses_its_own_endpoint(monkeypatch):
    _clear_jsearch_env(monkeypatch)
    monkeypatch.setenv("OPENWEBNINJA_API_KEY", "k")
    url, headers = board_sync._jsearch_target()
    assert url == "https://api.openwebninja.com/jsearch/search"
    assert set(headers) == {"x-api-key"}
    monkeypatch.setenv("JSEARCH_API_KEY", "k")
    url, headers = board_sync._jsearch_target()
    assert url == "https://jsearch.p.rapidapi.com/search"
    assert headers["X-RapidAPI-Host"] == "jsearch.p.rapidapi.com"


def test_jsearch_rotates_one_query_and_does_not_refire_every_minute(tmp_path, monkeypatch):
    """The board wakes every minute. JSearch spends one query, then waits hours."""
    phrases = {q.lower() for q in board_sync.JSEARCH_QUERIES}
    for phrase in ("business help desk", "it help desk", "it support", "software engineer", "computer science"):
        assert phrase in phrases
    assert board_sync.JSEARCH_INTERVAL >= timedelta(hours=1)
    assert board_sync.SCOUT_CHECK <= 60
    step = board_sync.JSEARCH_INTERVAL
    origin = datetime(2026, 6, 1, tzinfo=timezone.utc)
    base_ts = (origin.timestamp() // step.total_seconds()) * step.total_seconds()
    base = datetime.fromtimestamp(base_ts, tz=timezone.utc)
    seen = [board_sync.jsearch_query_at(base + step * i) for i in range(len(board_sync.JSEARCH_QUERIES))]
    assert len(set(seen)) == len(board_sync.JSEARCH_QUERIES)
    assert board_sync.jsearch_query_at(base) == board_sync.jsearch_query_at(base + step - timedelta(seconds=1))
    assert board_sync.jsearch_query_at(base) != board_sync.jsearch_query_at(base + step)

    monkeypatch.setattr(board_sync.config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("JSEARCH_API_KEY", "k")
    for marker in ("simplify_last_run", "scout_last_run", "wayback_last_run"):
        (tmp_path / marker).touch()
    calls = []

    async def jsearch(client, db):
        calls.append("jsearch")
        return 0

    async def free(client, db):
        return 0

    wakes = []

    async def sleep(_):
        wakes.append(1)
        if len(wakes) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(board_sync, "_scout_github", free)
    monkeypatch.setattr(board_sync, "_scout_serper", free)
    monkeypatch.setattr(board_sync, "_scout_jsearch", jsearch)
    monkeypatch.setattr(board_sync, "_scout_wayback", free)
    monkeypatch.setattr(board_sync.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(board_sync.scout_loop())
    assert calls == ["jsearch"]


def test_the_scout_runs_daily_across_restarts(tmp_path, monkeypatch):
    """A --reload restart used to rerun the whole scout, spending Serper credits."""
    import os, time
    monkeypatch.setattr(board_sync.config, "DATA_DIR", tmp_path)
    for name, every in (("simplify_last_run", board_sync.SIMPLIFY_INTERVAL),
                        ("scout_last_run", board_sync.SCOUT_INTERVAL),
                        ("wayback_last_run", board_sync.WAYBACK_INTERVAL)):
        assert board_sync._scout_due(name, every) is True        # fresh install: run now
        marker = tmp_path / name
        marker.touch()
        assert board_sync._scout_due(name, every) is False       # a restart an hour later
        old = time.time() - every.total_seconds() - 1
        os.utime(marker, (old, old))
        assert board_sync._scout_due(name, every) is True        # once the interval passed


@pytest.mark.parametrize("fails", [False, True])
def test_the_marker_is_touched_only_after_a_successful_scout(tmp_path, monkeypatch, fails):
    monkeypatch.setattr(board_sync.config, "DATA_DIR", tmp_path)
    async def github(client, db):
        if fails:
            raise RuntimeError("boom")
        return 0
    async def serper(client, db): return 0
    async def wayback(client, db): return 0
    async def stop(_): raise asyncio.CancelledError
    monkeypatch.setattr(board_sync, "_scout_github", github)
    monkeypatch.setattr(board_sync, "_scout_serper", serper)
    monkeypatch.setattr(board_sync, "_scout_wayback", wayback)
    monkeypatch.setattr(board_sync.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(board_sync.scout_loop())
    assert (tmp_path / "simplify_last_run").exists() is (not fails)
    assert (tmp_path / "scout_last_run").exists()     # T45: Serper's own marker, never blocked by Simplify
    assert (tmp_path / "wayback_last_run").exists()   # one source failing never blocks another


def test_a_scout_that_is_not_due_does_no_network_io(tmp_path, monkeypatch):
    monkeypatch.setattr(board_sync.config, "DATA_DIR", tmp_path)
    for marker in ("simplify_last_run", "scout_last_run", "jsearch_last_run", "wayback_last_run"):
        (tmp_path / marker).touch()
    def no_client(**kw): raise AssertionError("scout touched the network while not due")
    async def stop(_): raise asyncio.CancelledError
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", no_client)
    monkeypatch.setattr(board_sync.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(board_sync.scout_loop())


def test_simplify_runs_every_two_hours_but_serper_stays_daily(tmp_path, monkeypatch):
    """T45: Simplify is a free GitHub file that changes ~30 times a day; Serper
    costs 7 credits a run. Every 2 hours for both would be 84 credits a day."""
    import os, time
    monkeypatch.setattr(board_sync.config, "DATA_DIR", tmp_path)
    calls = []
    async def github(client, db): calls.append("simplify"); return 0
    async def serper(client, db): calls.append("serper"); return 0
    async def wayback(client, db): calls.append("wayback"); return 0
    async def stop(_): raise asyncio.CancelledError
    monkeypatch.setattr(board_sync, "_scout_github", github)
    monkeypatch.setattr(board_sync, "_scout_serper", serper)
    monkeypatch.setattr(board_sync, "_scout_wayback", wayback)
    monkeypatch.setattr(board_sync.asyncio, "sleep", stop)
    assert board_sync.SIMPLIFY_INTERVAL == timedelta(hours=2) and board_sync.SCOUT_INTERVAL == timedelta(hours=24)
    assert board_sync.SCOUT_CHECK <= 60  # the loop wakes with the board refresh; Serper stays daily

    def loop_after(**ages):
        for marker, hours in ages.items():
            (tmp_path / marker).touch()
            os.utime(tmp_path / marker, (time.time() - hours * 3600,) * 2)
        calls.clear()
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(board_sync.scout_loop())
        return calls
    assert loop_after(simplify_last_run=2.01, scout_last_run=1, wayback_last_run=1) == ["simplify"]
    assert loop_after(simplify_last_run=1, scout_last_run=1, wayback_last_run=1) == []
    assert loop_after(simplify_last_run=1, scout_last_run=3, wayback_last_run=1) == []  # Serper 3 h ago: not again
    assert loop_after(simplify_last_run=2.01, scout_last_run=24.01, wayback_last_run=1) == ["simplify", "serper"]


def test_a_failing_serper_run_waits_a_day_instead_of_retrying(tmp_path, monkeypatch, capsys):
    """T45: checks every 10 minutes would retry a Serper run that failed after its
    paid queries 6 times an hour (up to 42 credits). A paid scout counts as done
    once started; the free ones still retry."""
    monkeypatch.setattr(board_sync.config, "DATA_DIR", tmp_path)
    for marker in ("simplify_last_run", "wayback_last_run"):
        (tmp_path / marker).touch()
    calls, checks = [], []
    async def serper(client, db):
        calls.append("serper")
        raise ValueError("malformed answer after the paid queries")
    async def free(client, db): return 0
    async def sleep(_):
        checks.append(1)
        if len(checks) == 6:
            raise asyncio.CancelledError  # an hour of 10-minute checks
    monkeypatch.setattr(board_sync, "_scout_github", free)
    monkeypatch.setattr(board_sync, "_scout_serper", serper)
    monkeypatch.setattr(board_sync, "_scout_wayback", free)
    monkeypatch.setattr(board_sync.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(board_sync.scout_loop())
    assert calls == ["serper"]
    assert "malformed answer" in capsys.readouterr().err  # still loud: a bug is not swallowed


def test_new_and_stalest_companies_are_harvested_first(monkeypatch):
    """A pasted company (never attempted) must not wait behind the whole list."""
    now = board_policy.utcnow()
    _company("old", next_check=now - board_sync.HARVEST_INTERVAL * 5)
    _company("older", next_check=now - board_sync.HARVEST_INTERVAL * 9)
    _company("pasted", next_check=None)
    seen = []
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _routed({GH: ({"jobs": []}, 200, {})}, seen))
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    asyncio.run(board_sync._harvest_cycle())
    assert [u.split("/")[-2] for u, _ in seen] == ["pasted", "older", "old"]


def test_hiring_boards_are_checked_before_the_cold_backlog(monkeypatch):
    """A day-old never-checked import must not sit ahead of a board that already
    lists our roles. Quiet boards stay in the cold queue with the imports."""
    now = board_policy.utcnow()
    _company("cold", next_check=now - timedelta(days=1))
    _company("quiet", next_check=now - timedelta(days=2))
    _company("hiring", next_check=now - timedelta(minutes=30))
    _company("pasted", next_check=None)
    with _db.SessionLocal() as db:
        db.get(TrackedCompany, "hiring").check_interval = 30 * 60
        db.get(TrackedCompany, "quiet").check_interval = int(board_sync.QUIET_INTERVAL.total_seconds())
        db.commit()
    seen = []
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _routed({GH: ({"jobs": []}, 200, {})}, seen))
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    asyncio.run(board_sync._harvest_cycle())
    assert [u.split("/")[-2] for u, _ in seen] == ["pasted", "hiring", "quiet", "cold"]


def test_the_cold_set_rotates_without_blocking_priority_boards(monkeypatch):
    """A burst of hiring boards, then one cold import, then the rest of the
    hiring boards. The import is not checked every minute, and it does not
    sit in front of boards that already list our roles."""
    now = board_policy.utcnow()
    count = board_sync.WIDE_EVERY + 1
    for i in range(count):
        _company(f"h{i}", next_check=now - timedelta(minutes=count - i))
    _company("cold", next_check=now - timedelta(days=2))
    with _db.SessionLocal() as db:
        for i in range(count):
            db.get(TrackedCompany, f"h{i}").check_interval = 60
        db.commit()
    seen = []
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _routed({GH: ({"jobs": []}, 200, {})}, seen))
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    asyncio.run(board_sync._harvest_cycle())
    slugs = [u.split("/")[-2] for u, _ in seen]
    assert slugs == [f"h{i}" for i in range(board_sync.WIDE_EVERY)] + ["cold", f"h{board_sync.WIDE_EVERY}"]


def test_adopting_the_minute_cadence_leaves_the_cold_backlog_alone():
    now = board_policy.utcnow()
    _company("hiring", next_check=now + timedelta(hours=2))
    _company("quiet", next_check=now + timedelta(hours=20))
    _company("cold", next_check=now + timedelta(hours=5))
    with _db.SessionLocal() as db:
        db.get(TrackedCompany, "hiring").check_interval = 2 * 3600
        db.get(TrackedCompany, "quiet").check_interval = int(board_sync.QUIET_INTERVAL.total_seconds())
        db.commit()
        board_sync.adopt_minute_cadence(db)
        hiring, quiet, cold = (db.get(TrackedCompany, slug) for slug in ("hiring", "quiet", "cold"))
        assert hiring.check_interval == 60
        assert hiring.next_check_at <= now + timedelta(seconds=1)
        assert quiet.next_check_at == now + timedelta(hours=20)
        assert quiet.check_interval == int(board_sync.QUIET_INTERVAL.total_seconds())
        assert cold.next_check_at == now + timedelta(hours=5)
        assert cold.check_interval is None


# --- T30: one lane per vendor, peak-hours cadence, a brake per vendor --------

def _companies_at(*rows):
    """(slug, provider, minutes overdue) - the most overdue is checked first."""
    now = board_policy.utcnow()
    with _db.SessionLocal() as db:
        for slug, provider, age in rows:
            db.add(TrackedCompany(slug=slug, provider=provider,
                                  next_check_at=now - timedelta(minutes=age)))
        db.commit()


def _empty_everywhere(seen=None):
    return _routed({GH: ({"jobs": []}, 200, {}), ASHBY: ({"jobs": []}, 200, {}),
                    LEVER: ([], 200, {})}, seen)


def _host(url):
    return url.split("/")[2]


def test_vendor_lanes_run_side_by_side(monkeypatch):
    """Sequentially the three stalest (all Greenhouse) would go first."""
    _companies_at(("g1", "greenhouse", 900), ("g2", "greenhouse", 890), ("g3", "greenhouse", 880),
                  ("a1", "ashby", 200), ("l1", "lever", 100))
    seen = []
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _empty_everywhere(seen))
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    stats = asyncio.run(board_sync._harvest_cycle())
    assert stats["companies"] == 5
    assert {_host(u) for u, _ in seen[:3]} == {GH, ASHBY, LEVER}


def test_a_throttled_vendor_does_not_hold_up_the_others(monkeypatch):
    _companies_at(("g1", "greenhouse", 900), ("g2", "greenhouse", 890),
                  ("a1", "ashby", 200), ("a2", "ashby", 190), ("l1", "lever", 100))
    seen = []
    throttled = {"first": True}
    def greenhouse(headers):
        if throttled.pop("first", False):
            return ({}, 429, {"Retry-After": "120"})
        return ({"jobs": []}, 200, {})
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _routed(
        {GH: greenhouse, ASHBY: ({"jobs": []}, 200, {}), LEVER: ([], 200, {})}, seen))
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    real_sleep = asyncio.sleep
    async def sleep(seconds):  # the 120 s back-off takes a real, short while
        await real_sleep(0.05 if seconds >= 1 else 0)
    monkeypatch.setattr(board_sync.asyncio, "sleep", sleep)
    stats = asyncio.run(board_sync._harvest_cycle())
    urls = [u for u, _ in seen]
    g2 = next(i for i, u in enumerate(urls) if "/boards/g2/" in u)
    assert all(i < g2 for i, u in enumerate(urls) if GH not in u)  # others finished meanwhile
    assert stats["rate_limited"] == 1 and stats["companies"] == 5


def test_each_lane_reuses_one_connection(monkeypatch):
    """One client per vendor per pass, even when a moved board is re-resolved."""
    _companies_at(*[(f"g{i}", "greenhouse", 900 - i) for i in range(4)],
                  ("a1", "ashby", 200), ("a2", "ashby", 190), ("l1", "lever", 100))
    made = []
    base = _routed({GH: ({"jobs": []}, 200, {}), ASHBY: ({"jobs": []}, 200, {}), LEVER: ([], 200, {}),
                    "/boards/g3/": ({}, 404, {})})  # g3 404s -> looked up on Ashby/Lever
    class Counting(base):
        def __init__(self, **kw):
            made.append(kw); super().__init__(**kw)
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", Counting)
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    asyncio.run(board_sync._harvest_cycle())
    assert len(made) == len(board_sync._lanes())  # one per worker, idle ones included


H = timedelta(hours=1)


@pytest.mark.parametrize("current, lists_target, new_jobs, peak, expected", [
    (H, True, 2, True, 60),                       # a new job for our roles: down to a minute
    (25 * 60, True, 1, True, 60),                 # ... never below that floor
    (H, True, 0, True, 60),                       # nothing new: still about a minute
    (2 * H, True, 0, True, 60),                   # ... the ceiling is a minute while it lists our roles
    (H, True, 0, False, 60),                      # overnight: no growth, and not pushed out to an hour
    (H, False, 0, True, 24 * 3600),               # lists none of our roles: daily
    (24 * H, True, 0, True, 60),                  # starts listing our roles: onto the minute cadence
    (24 * H, True, 3, True, 60),                  # ... including when it is also posting new ones
    (H, None, 0, True, 60),                       # 304, an active board: stays on a minute
    (24 * H, None, 0, True, 24 * 3600),           # 304, a quiet board: stays daily
    (3 * H, None, 0, True, 60),                   # 304 on a board from an old multi-hour ceiling: still active
])
def test_the_revisit_rule(current, lists_target, new_jobs, peak, expected):
    current = current if isinstance(current, timedelta) else timedelta(seconds=current)
    got = board_sync.next_interval(current, lists_target=lists_target, new_jobs=new_jobs, peak=peak)
    assert got == timedelta(seconds=expected)


@pytest.mark.parametrize("hour, peak", [(12, False), (13, True), (19, True), (0, True), (1, False)])
def test_peak_hours_are_13_to_01_utc(hour, peak):
    """91% of weekday postings land 13:00-01:00 UTC (T30 audit)."""
    assert board_sync._is_peak(datetime(2026, 9, 23, hour, 30)) is peak


@pytest.mark.parametrize("hour", [15, 6, 0, 1, 12])
def test_a_hiring_board_is_due_again_in_about_a_minute(hour):
    """Peak or overnight: listing our roles is a one-minute revisit, not an hourly floor."""
    at = datetime(2026, 1, 5, hour)
    c = TrackedCompany(slug="x", provider="greenhouse", check_interval=2 * 3600)
    board_sync._reschedule(c, at, lists_target=True, new_jobs=1)
    assert c.check_interval == 60
    assert c.next_check_at == at + timedelta(seconds=60)


def _board_with(*jobs):
    return _routed({GH: ({"jobs": list(jobs)}, 200, {})})


def test_a_board_that_starts_posting_our_roles_is_checked_sooner(monkeypatch):
    now = board_policy.utcnow().replace(hour=15)          # US business hours
    monkeypatch.setattr(board_policy, "utcnow", lambda: now)
    posted = (now - timedelta(hours=2)).isoformat()
    _company("acme")
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _board_with(
        {"id": 1, "title": "Software Engineer", "location": {"name": "Austin, TX"}, "first_published": posted}))
    asyncio.run(board_sync._harvest_cycle())
    with _db.SessionLocal() as db:
        c = db.get(TrackedCompany, "acme")
        assert c.check_interval == 60 and c.next_check_at == now + timedelta(seconds=60)
    # Same job again: it is not new, and the board stays on the minute cadence.
    monkeypatch.setattr(board_policy, "utcnow", lambda: now + timedelta(seconds=60))
    asyncio.run(board_sync._harvest_cycle())
    with _db.SessionLocal() as db:
        assert db.get(TrackedCompany, "acme").check_interval == 60


def test_a_board_without_our_roles_is_checked_daily(monkeypatch):
    now = board_policy.utcnow().replace(hour=15)
    monkeypatch.setattr(board_policy, "utcnow", lambda: now)
    _company("acme")
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _board_with(
        {"id": 1, "title": "Account Executive", "location": {"name": "Austin, TX"},
         "first_published": now.isoformat()}))
    asyncio.run(board_sync._harvest_cycle())
    with _db.SessionLocal() as db:
        assert db.get(TrackedCompany, "acme").next_check_at == now + timedelta(hours=24)


def test_an_old_job_for_our_roles_keeps_the_board_on_the_minute_cadence(monkeypatch):
    """Listing our roles at all earns about a minute, not the daily quiet watch."""
    now = board_policy.utcnow().replace(hour=15)
    monkeypatch.setattr(board_policy, "utcnow", lambda: now)
    _company("acme")
    with _db.SessionLocal() as db:
        db.get(TrackedCompany, "acme").check_interval = 24 * 3600
        db.commit()
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _board_with(
        {"id": 1, "title": "Software Engineer", "location": {"name": "Austin, TX"},
         "first_published": (now - timedelta(days=40)).isoformat()}))
    asyncio.run(board_sync._harvest_cycle())
    with _db.SessionLocal() as db:
        assert db.get(TrackedCompany, "acme").check_interval == 60


def test_a_strained_vendor_is_slowed_then_recovers(monkeypatch):
    """Like Googlebot: widen the gap on 5xx, narrow it again on success."""
    _companies_at(*[(f"g{i}", "greenhouse", 900 - i) for i in range(6)])
    failing = {"/boards/g0/", "/boards/g1/", "/boards/g2/"}
    def greenhouse_for(slug_part):
        return ({}, 503, {}) if slug_part in failing else ({"jobs": []}, 200, {})
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _routed(
        {f"/boards/g{i}/": greenhouse_for(f"/boards/g{i}/") for i in range(6)}))
    monkeypatch.setattr(board_sync, "JITTER", (1, 1))
    gaps = []
    async def sleep(seconds): gaps.append(seconds)
    monkeypatch.setattr(board_sync.asyncio, "sleep", sleep)
    asyncio.run(board_sync._harvest_cycle())
    assert gaps == [2, 4, 8, 4, 2, 1]


def test_the_brake_is_capped(monkeypatch):
    _companies_at(*[(f"g{i}", "greenhouse", 900 - i) for i in range(6)])
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _routed({GH: ({}, 503, {})}))
    monkeypatch.setattr(board_sync, "JITTER", (3, 3))
    gaps = []
    async def sleep(seconds): gaps.append(seconds)
    monkeypatch.setattr(board_sync.asyncio, "sleep", sleep)
    asyncio.run(board_sync._harvest_cycle())
    assert max(gaps) == 3 * board_sync.MAX_SLOWDOWN == 30


def _vendor_error(cause):
    try:
        raise board_sync.BoardVendorError("x") from cause
    except board_sync.BoardVendorError as e:
        return e


def test_only_a_struggling_vendor_counts_as_strain():
    req = httpx.Request("GET", "https://x")
    status = lambda code: httpx.HTTPStatusError("s", request=req, response=httpx.Response(code, request=req))
    assert board_sync._strained(_vendor_error(httpx.ReadTimeout("slow", request=req)))
    assert board_sync._strained(_vendor_error(httpx.ConnectError("down", request=req)))
    assert board_sync._strained(_vendor_error(status(503)))
    assert not board_sync._strained(_vendor_error(status(400)))            # our request, not their load
    assert not board_sync._strained(_vendor_error(ValueError("bad JSON")))  # their data, not their load
    assert not board_sync._strained(board_sync.BoardVendorError("unknown provider 'x'"))  # no cause


def test_a_vendor_error_always_names_what_went_wrong(monkeypatch):
    """httpx timeouts often carry an empty message; the log line said nothing."""
    async def timeout(slug, client=None):
        raise httpx.ReadTimeout("", request=httpx.Request("GET", "https://x"))
    monkeypatch.setitem(board_sync.FETCHERS, "lever", timeout)
    with pytest.raises(board_sync.BoardVendorError, match="lever/acme: ReadTimeout"):
        asyncio.run(board_sync._fetch("lever", "acme"))



# --- T31: discovery from the Internet Archive, frontier health ----------------

class _Cdx:
    """Stand in for the scout client: answers the Wayback CDX API per host."""
    def __init__(self, answers):
        self.answers, self.asked = answers, []
    async def get(self, url, params=None, **kw):
        assert url == board_sync.WAYBACK_CDX
        self.asked.append(params)
        answer = self.answers.get(params["url"].rstrip("/"), (200, ""))
        if isinstance(answer, Exception):
            raise answer
        status, text = answer
        return type("R", (), {"status_code": status, "text": text})()


def test_wayback_tracks_new_boards_with_staggered_first_checks():
    now = board_policy.utcnow()
    _company("known", provider="ashby")
    cdx = _Cdx({
        "jobs.ashbyhq.com": (200, "https://jobs.ashbyhq.com/newco/abc\nhttps://jobs.ashbyhq.com/known/1\n"
                                  "https://jobs.ashbyhq.com/newco/def"),
        "job-boards.greenhouse.io": (200, "https://job-boards.greenhouse.io/gh1/jobs/9"),
        "boards.greenhouse.io": (200, "https://boards.greenhouse.io/embed/job_app?token=1"),
        "jobs.lever.co": (200, "https://jobs.lever.co/lv1/uuid")})
    with _db.SessionLocal() as db:
        assert asyncio.run(board_sync._scout_wayback(cdx, db)) == 3     # newco, gh1, lv1
        rows = {c.slug: c for c in db.query(TrackedCompany)}
    assert set(rows) == {"known", "newco", "gh1", "lv1"}                # never "embed"
    for slug in ("newco", "gh1", "lv1"):
        assert rows[slug].discovery_source == "wayback"
        assert now <= rows[slug].next_check_at <= now + board_sync.WAYBACK_SPREAD
    assert rows["known"].next_check_at is None                         # untouched
    assert {p["from"] for p in cdx.asked} == {(now - timedelta(days=365)).strftime("%Y%m%d")}


def test_a_bulk_import_is_spread_over_a_day_not_due_at_once():
    lines = "\n".join(f"https://jobs.lever.co/co{i}/x" for i in range(400))
    with _db.SessionLocal() as db:
        asyncio.run(board_sync._scout_wayback(_Cdx({"jobs.lever.co": (200, lines)}), db))
        due = sorted(c.next_check_at for c in db.query(TrackedCompany))
    span = (due[-1] - due[0]).total_seconds()
    assert len(due) == 400 and span > 0.9 * board_sync.WAYBACK_SPREAD.total_seconds()


def test_wayback_skips_a_refusing_or_failing_host_and_keeps_going(capsys):
    cdx = _Cdx({"jobs.ashbyhq.com": (429, ""),
                "job-boards.greenhouse.io": httpx.ReadTimeout("", request=httpx.Request("GET", "https://x")),
                "jobs.lever.co": (200, "https://jobs.lever.co/still/x")})
    with _db.SessionLocal() as db:
        assert asyncio.run(board_sync._scout_wayback(cdx, db)) == 1
    out = capsys.readouterr().out
    assert "jobs.ashbyhq.com returned 429" in out and "ReadTimeout" in out
    assert len(cdx.asked) == 4                                          # every host still tried


def test_wayback_says_when_a_host_hit_the_result_limit(monkeypatch, capsys):
    monkeypatch.setattr(board_sync, "WAYBACK_LIMIT", 2)
    cdx = _Cdx({"jobs.lever.co": (200, "https://jobs.lever.co/a/1\nhttps://jobs.lever.co/b/1")})
    with _db.SessionLocal() as db:
        asyncio.run(board_sync._scout_wayback(cdx, db))
    assert "hit the 2 URL limit" in capsys.readouterr().out


def test_pasting_a_board_scheduled_for_later_makes_it_due_now():
    later = board_policy.utcnow() + timedelta(hours=20)
    _company("acme", next_check=later)
    with _db.SessionLocal() as db:
        board_sync.track_company(db, "greenhouse", "acme", "pasted")
        db.commit()
        assert db.get(TrackedCompany, "acme").next_check_at is None


def test_an_unchanged_board_keeps_adapting(monkeypatch):
    """A 304 carries no jobs, but "nothing new" is still information."""
    now = board_policy.utcnow().replace(hour=15)
    monkeypatch.setattr(board_policy, "utcnow", lambda: now)
    _company("acme")
    board_sync._ETAGS[("greenhouse", "acme")] = '"v1"'
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _routed({GH: ({}, 304, {})}))
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    assert asyncio.run(board_sync._harvest_cycle())["unchanged"] == 1
    with _db.SessionLocal() as db:
        assert db.get(TrackedCompany, "acme").check_interval == 60   # active board, minute cadence


def test_the_worker_measures_how_overdue_it_runs(monkeypatch):
    now = board_policy.utcnow()
    _company("late", next_check=now - timedelta(minutes=7))
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _empty_everywhere())
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    assert asyncio.run(board_sync._harvest_cycle())["max_lag"] == 7 * 60


def test_health_lines_are_printed_and_reset(monkeypatch, capsys):
    _company("late", next_check=board_policy.utcnow() - timedelta(minutes=7))
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", _empty_everywhere())
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    stats = board_sync._new_stats()   # report_every=0: a report on every loop, no clock patching
    async def stop(seconds):
        if seconds > 0.5:                                # the idle sleep, after the report
            raise asyncio.CancelledError
    monkeypatch.setattr(board_sync.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(board_sync._vendor_worker("greenhouse", stats, report_every=0))
    out = capsys.readouterr().out
    assert "[board] greenhouse:" in out and "'companies': 1" in out and "'max_lag': 420.0" in out
    assert stats == board_sync._new_stats()             # reset after printing


def test_a_quiet_vendor_window_does_not_cry_empty_feed(monkeypatch, capsys):
    """Most tracked boards list none of our roles now; only a whole cycle
    keeping nothing is worth the warning."""
    stats = board_sync._new_stats()
    stats["companies"] = 40
    board_sync._report(stats, "lever")
    assert "no eligible postings" not in capsys.readouterr().out


def test_a_vendor_worker_survives_its_own_crash(monkeypatch, capsys):
    """e.g. the DB briefly unavailable: that vendor must not go dark forever."""
    calls = []
    async def worker(provider, stats, **kw):
        calls.append(provider)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        raise asyncio.CancelledError
    async def sleep(seconds): pass
    monkeypatch.setattr(board_sync, "_vendor_worker", worker)
    monkeypatch.setattr(board_sync.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(board_sync._worker_forever("lever"))
    assert calls == ["lever", "lever"] and "database is locked" in capsys.readouterr().err



def test_discovery_drops_ats_paths_that_are_not_boards():
    """All measured on the live Wayback import: none of these was a live board."""
    junk = ["api", "embed", "root.020bfab2_066d_4da7_8334_348b307461ea", "favicon.ico", "robots.txt",
            ".sitemap.xml", "oxygen.txt", "manifest.json", "x" * 65]
    real = ["arch.co", "kraken.com", "globalenergyallianceforpeopleandplanetgeappllc", "embedding-vc", "apiary"]
    text = " ".join(f"jobs.ashbyhq.com/{s}/1" for s in junk + real)
    assert [s for _, s in board_sync.discover_slugs(text)] == sorted(real)
