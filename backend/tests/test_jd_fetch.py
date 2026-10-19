"""T10 — JD from URL: adapters (URL→API transform + fixture parse), the SSRF
guard, the generic extraction path, dispatch, and the /jd/from-url route."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import jd_adapters as A
from app.services import jd_fetch
from app.services.jd_screen import screen

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name):
    return (FIXTURES / name).read_text()


# --- adapter URL → API transforms (pure) -----------------------------------


def test_workday_api_url():
    a = A.by_name("workday")
    url = "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/San-Francisco/Senior-Backend-Engineer_R-123"
    assert a.match(url)
    assert a.api_url(url) == (
        "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/careers/job/San-Francisco/Senior-Backend-Engineer_R-123"
    )


def test_greenhouse_api_url_path_and_query_forms():
    a = A.by_name("greenhouse")
    path_url = "https://job-boards.greenhouse.io/acme/jobs/456"
    assert a.match(path_url)
    assert a.api_url(path_url) == "https://boards-api.greenhouse.io/v1/boards/acme/jobs/456"
    q_url = "https://boards.greenhouse.io/acme?gh_jid=456"
    assert a.match(q_url)
    assert a.api_url(q_url) == "https://boards-api.greenhouse.io/v1/boards/acme/jobs/456"
    # the iframe form careers sites link to: for= is the board, token= the job
    embed = "https://job-boards.greenhouse.io/embed/job_app?for=acme&token=456&jr_id=6aa1e"
    assert a.match(embed)
    assert a.api_url(embed) == "https://boards-api.greenhouse.io/v1/boards/acme/jobs/456"


@pytest.mark.parametrize("url", [
    "https://job-boards.greenhouse.io/embed/job_app?token=456",  # no board
    "https://job-boards.greenhouse.io/embed/job_app?for=&token=456",  # blank board
    "https://job-boards.greenhouse.io/embed/job_app?for=acme",  # no job
    "https://job-boards.greenhouse.io/embed/job_app?gh_jid=456",  # no board
    "https://job-boards.greenhouse.io/embed/job_board?for=acme",  # the whole board, not a job
])
def test_greenhouse_embed_without_board_and_job_not_matched(url):
    # these fall to generic, never to a board literally called "embed"
    assert not A.by_name("greenhouse").match(url)


def test_lever_api_url():
    a = A.by_name("lever")
    url = "https://jobs.lever.co/acme/789"
    assert a.match(url)
    assert a.api_url(url) == "https://api.lever.co/v0/postings/acme/789"


def test_ashby_api_url_uses_org_slug():
    a = A.by_name("ashby")
    url = "https://jobs.ashbyhq.com/acme/aaa-111"
    assert a.match(url)
    assert a.api_url(url) == "https://api.ashbyhq.com/posting-api/job-board/acme"


def test_ashby_embedded_form_not_matched():
    # ?ashby_jid= form carries no slug in the URL → don't match → generic/paste.
    a = A.by_name("ashby")
    assert not a.match("https://www.ashbyhq.com/careers?ashby_jid=aaa-111")


# --- adapter parse (saved JSON fixtures) -----------------------------------


def test_workday_parse_strips_html():
    a = A.by_name("workday")
    src = a.parse(json.loads(_fixture("workday.json")), "https://acme.wd5.myworkdayjobs.com/x")
    assert src.title == "Senior Backend Engineer"
    assert src.location == "San Francisco, CA"
    assert "<" not in src.text and "Python & Go" in src.text and "Kubernetes" in src.text
    assert src.adapter == "workday"


def test_greenhouse_parse_unescapes_and_strips():
    a = A.by_name("greenhouse")
    src = a.parse(json.loads(_fixture("greenhouse.json")), "https://job-boards.greenhouse.io/acme/jobs/456")
    assert src.title == "Data Engineer"
    assert src.location == "Remote - US"
    assert src.company == "Acme"
    assert "<" not in src.text and "Spark" in src.text and "Airflow" in src.text
    assert src.adapter == "greenhouse"


def test_lever_parse_uses_plain_description():
    a = A.by_name("lever")
    src = a.parse(json.loads(_fixture("lever.json")), "https://jobs.lever.co/acme/789")
    assert src.title == "Staff Frontend Engineer"
    assert src.location == "New York"
    assert "Build React apps at scale." in src.text
    assert src.adapter == "lever"


def test_lever_list_only_posting_contains_responsibilities_and_requirements():
    # Live Binance posting 6fff9a51-f9e7-4d91-99b6-bf0e6add4708 had empty
    # descriptionPlain and all its role text in lists (verified 2026-09-19).
    src = A.by_name("lever").parse({
        "descriptionPlain": "",
        "lists": [{"text": "Responsibilities", "content": "<ul><li>Build APIs</li><li>Test software</li></ul>"},
                  {"text": "Requirements", "content": "<div>Java &amp; MySQL<br>Distributed systems</div>"}],
        "additionalPlain": "Remote work available.",
    }, "https://jobs.lever.co/acme/1")
    assert src.text == "Responsibilities\n\nBuild APIs\nTest software\n\nRequirements\n\nJava & MySQL\nDistributed systems\n\nRemote work available."


def test_lever_description_is_not_duplicated_and_html_fallback_is_readable():
    src = A.by_name("lever").parse({
        "descriptionPlain": "Opening and body", "openingPlain": "Opening", "descriptionBodyPlain": "body",
        "lists": [], "additional": "<div>Closing &amp; benefits</div>",
    }, "https://jobs.lever.co/acme/1")
    assert src.text == "Opening and body\n\nClosing & benefits"


def test_ashby_parse_filters_board_by_jid():
    a = A.by_name("ashby")
    src = a.parse(json.loads(_fixture("ashby.json")), "https://jobs.ashbyhq.com/acme/aaa-111")
    assert src.title == "ML Engineer"  # not the "other-000" recruiter job
    assert "PyTorch" in src.text
    assert src.adapter == "ashby"


def test_ashby_parse_missing_jid_raises():
    a = A.by_name("ashby")
    with pytest.raises(jd_fetch.JdFetchError):
        a.parse(json.loads(_fixture("ashby.json")), "https://jobs.ashbyhq.com/acme/zzz-999")


# --- apply_url extraction (T16): the adapter's apply form, not source_url ----


def test_adapters_expose_apply_url():
    gh = A.by_name("greenhouse").parse(
        json.loads(_fixture("greenhouse.json")), "https://job-boards.greenhouse.io/acme/jobs/456"
    )
    assert gh.apply_url == "https://job-boards.greenhouse.io/acme/jobs/456"  # absolute_url

    lv = A.by_name("lever").parse(json.loads(_fixture("lever.json")), "https://jobs.lever.co/acme/789")
    assert lv.apply_url == "https://jobs.lever.co/acme/789"  # hostedUrl

    ash = A.by_name("ashby").parse(
        json.loads(_fixture("ashby.json")), "https://jobs.ashbyhq.com/acme/aaa-111"
    )
    assert ash.apply_url == "https://jobs.ashbyhq.com/acme/aaa-111/application"  # applyUrl, not the listing

    wd = A.by_name("workday").parse(json.loads(_fixture("workday.json")), "https://acme.wd5.myworkdayjobs.com/x")
    assert wd.apply_url == "https://acme.wd5.myworkdayjobs.com/x"  # the posting URL is the apply page


def test_generic_path_has_no_apply_url(monkeypatch):
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda url, **kw: _fixture("generic_job.html").encode())
    monkeypatch.setattr(jd_fetch.config, "OLLAMA_API_KEY", None)
    src = jd_fetch.fetch_jd_from_url("https://careers.example.com/platform-engineer")
    assert src.apply_url is None  # paste/generic → no one-click apply


# --- SSRF guard ------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/internal",
    "http://[::1]/x",
    "ftp://example.com/x",
    "file:///etc/passwd",
])
def test_ssrf_blocks_bad_urls(url):
    with pytest.raises(jd_fetch.JdFetchError):
        jd_fetch._check_url(url)


def test_ssrf_validates_resolved_ip(monkeypatch):
    # A public-looking hostname that resolves to a private IP must be blocked.
    monkeypatch.setattr(jd_fetch, "_resolve_ips", lambda host: {"10.0.0.5"})
    with pytest.raises(jd_fetch.JdFetchError):
        jd_fetch._check_url("http://evil.example.com/")


def test_ssrf_allows_public_host(monkeypatch):
    monkeypatch.setattr(jd_fetch, "_resolve_ips", lambda host: {"93.184.216.34"})
    jd_fetch._check_url("https://example.com/jobs/1")  # no raise


def test_ssrf_blocks_redirect_to_private_ip(monkeypatch):
    monkeypatch.setattr(
        jd_fetch, "_resolve_ips",
        lambda host: {"93.184.216.34"} if host == "public.example.com" else {"10.0.0.5"},
    )
    transport = httpx.MockTransport(
        lambda req: httpx.Response(302, headers={"location": "http://internal.evil/"})
    )
    with pytest.raises(jd_fetch.JdFetchError):
        jd_fetch._guarded_get("http://public.example.com/job", transport=transport)


def test_guarded_get_enforces_size_cap(monkeypatch):
    monkeypatch.setattr(jd_fetch, "_resolve_ips", lambda host: {"93.184.216.34"})
    monkeypatch.setattr(jd_fetch.config, "JD_FETCH_MAX_BYTES", 100)
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=b"x" * 500))
    with pytest.raises(jd_fetch.JdFetchError):
        jd_fetch._guarded_get("http://public.example.com/big", transport=transport)


# --- generic extraction path ----------------------------------------------


def test_generic_extracts_and_strips_chrome(monkeypatch):
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda url, **kw: _fixture("generic_job.html").encode())
    monkeypatch.setattr(jd_fetch.config, "OLLAMA_API_KEY", None)  # skip LLM cleanup
    src = jd_fetch.fetch_jd_from_url("https://careers.example.com/platform-engineer")
    assert src.adapter == "generic"
    assert "Kubernetes" in src.text
    assert "About Us" not in src.text  # nav stripped
    assert "Privacy Policy" not in src.text  # footer stripped
    assert src.warnings == []


def test_generic_short_page_warns(monkeypatch):
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda url, **kw: b"<html><body><p>hi</p></body></html>")
    monkeypatch.setattr(jd_fetch.config, "OLLAMA_API_KEY", None)
    src = jd_fetch.fetch_jd_from_url("https://careers.example.com/thin")
    assert src.warnings  # too short → warned, no crash
    assert src.adapter == "generic"


# --- dispatch --------------------------------------------------------------


def test_dispatch_routes_to_matching_adapter(monkeypatch):
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda url, **kw: _fixture("lever.json").encode())
    src = jd_fetch.fetch_jd_from_url("https://jobs.lever.co/acme/789")
    assert src.adapter == "lever"
    assert src.title == "Staff Frontend Engineer"


def test_every_fetch_path_carries_the_screen(monkeypatch):
    # T39: the adapter path and the generic fallback both screen the JD
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda url, **kw: _fixture("lever.json").encode())
    assert jd_fetch.fetch_jd_from_url("https://jobs.lever.co/acme/789").screen is not None
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda url, **kw: _fixture("generic_job.html").encode())
    monkeypatch.setattr(jd_fetch.config, "OLLAMA_API_KEY", None)
    src = jd_fetch.fetch_jd_from_url("https://some-random-company.com/careers/1")
    assert src.adapter == "generic" and src.screen == screen(src.text)


def test_workday_double_escaped_line_break_becomes_a_line():
    # Workday sends "&amp;#xa;" (5 of 70 live postings); it once showed as "&#xa;"
    data = {"jobPostingInfo": {"jobDescription": "<p>Security Clearance Type:</p>&amp;#xa;None/Not Required"}}
    src = A.by_name("workday").parse(data, "https://acme.wd5.myworkdayjobs.com/x")
    assert src.text == "Security Clearance Type:\nNone/Not Required"


def test_dispatch_unknown_host_falls_to_generic(monkeypatch):
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda url, **kw: _fixture("generic_job.html").encode())
    monkeypatch.setattr(jd_fetch.config, "OLLAMA_API_KEY", None)
    src = jd_fetch.fetch_jd_from_url("https://some-random-company.com/careers/1")
    assert src.adapter == "generic"


def test_adapter_api_404_falls_back_to_generic(monkeypatch):
    # An unlisted/confidential Lever posting: live on jobs.lever.co, but the
    # public API 404s. We must scrape the posting page, not surface the 404.
    def fake_get(url, **kw):
        if "api.lever.co" in url:
            raise jd_fetch.JdFetchError("fetch failed: HTTP 404")
        return _fixture("generic_job.html").encode()  # the posting page

    monkeypatch.setattr(jd_fetch, "_guarded_get", fake_get)
    monkeypatch.setattr(jd_fetch.config, "OLLAMA_API_KEY", None)
    src = jd_fetch.fetch_jd_from_url("https://jobs.lever.co/acme/unlisted-123")
    assert src.adapter == "generic"  # fell back instead of raising
    assert "Kubernetes" in src.text


# --- /jd/from-url route ----------------------------------------------------


def test_route_returns_jdsource(monkeypatch):
    from app.schemas.jd import JdSource
    monkeypatch.setattr(
        jd_fetch, "fetch_jd_from_url",
        lambda url: JdSource(text="Do the job.", title="Engineer", source_url=url, adapter="lever"),
    )
    r = TestClient(app).post("/jd/from-url", json={"url": "https://jobs.lever.co/acme/789"})
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "Do the job." and body["adapter"] == "lever"


def test_route_blocked_url_is_4xx(monkeypatch):
    def boom(url):
        raise jd_fetch.JdFetchError("blocked non-public address")
    monkeypatch.setattr(jd_fetch, "fetch_jd_from_url", boom)
    r = TestClient(app).post("/jd/from-url", json={"url": "http://169.254.169.254/"})
    assert r.status_code == 400


# --- T28: posting freshness + pasted-link company tracking -----------------

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app import db as _db
from app.models import TrackedCompany
from app.schemas.jd import JdSource


@pytest.mark.parametrize("raw, expected", [
    ("2026-09-14T13:36:20-04:00", datetime(2026, 9, 14, 17, 36, 20)),   # Greenhouse, offset -> UTC
    ("2026-09-11T19:18:21.372+00:00", datetime(2026, 9, 11, 19, 18, 21, 372000)),  # Ashby
    ("2026-09-11T19:18:21Z", datetime(2026, 9, 11, 19, 18, 21)),         # Z suffix
    (1789694961378, datetime(2026, 9, 18, 1, 29, 21, 378000)),          # Lever epoch ms (int)
    ("1789694961378", datetime(2026, 9, 18, 1, 29, 21, 378000)),        # ...and as text
    ("2026-09-22", datetime(2026, 9, 22)),                               # Workday, date only
    ("2026-09-22T10:00:00", datetime(2026, 9, 22, 10)),                  # naive = already UTC
])
def test_parse_ats_date_normalises_every_ats_format_to_naive_utc(raw, expected):
    assert A.parse_ats_date(raw) == expected


@pytest.mark.parametrize("raw", [None, "", 0, "not-a-date", "Posted Today", "-5", "1.5e12",
                                 "9" * 30, True, "2026-13-45"])
def test_parse_ats_date_never_raises_on_junk(raw):
    assert A.parse_ats_date(raw) is None


def test_adapters_carry_live_date_fields():
    # Field names and values from the live APIs (2026-09-22): figma/6143238004,
    # binance/60ee32bb..., ramp/b3b0875d..., and an nvidia job shown "Posted Today".
    gh = A.by_name("greenhouse").parse(
        {"content": "x", "first_published": "2026-09-14T13:36:20-04:00", "updated_at": "2026-09-17T19:16:13-04:00"},
        "https://job-boards.greenhouse.io/figma/jobs/6143238004")
    assert (gh.posted_at, gh.updated_at) == (datetime(2026, 9, 14, 17, 36, 20), datetime(2026, 9, 17, 23, 16, 13))

    lv = A.by_name("lever").parse({"descriptionPlain": "x", "createdAt": 1789694961378},
                                  "https://jobs.lever.co/binance/60ee32bb")
    assert (lv.posted_at, lv.updated_at) == (datetime(2026, 9, 18, 1, 29, 21, 378000), None)

    ash = A.by_name("ashby").parse(
        {"jobs": [{"id": "b3b0875d", "descriptionPlain": "x", "publishedAt": "2026-09-11T19:18:21.372+00:00"}]},
        "https://jobs.ashbyhq.com/ramp/b3b0875d")
    assert (ash.posted_at, ash.updated_at) == (datetime(2026, 9, 11, 19, 18, 21, 372000), None)

    wd = A.by_name("workday").parse({"jobPostingInfo": {"jobDescription": "x", "startDate": "2026-09-22"}},
                                    "https://nvidia.wd5.myworkdayjobs.com/x/job/y")
    assert (wd.posted_at, wd.updated_at) == (date(2026, 9, 22), None)
    assert type(wd.posted_at) is date  # a calendar day, not UTC midnight
    assert wd.model_dump(mode="json")["posted_at"] == "2026-09-22"


def test_missing_or_junk_dates_do_not_break_the_fetch():
    # The saved fixtures carry no date fields at all.
    src = A.by_name("greenhouse").parse(json.loads(_fixture("greenhouse.json")),
                                        "https://job-boards.greenhouse.io/acme/jobs/456")
    assert (src.posted_at, src.updated_at) == (None, None) and src.text
    junk = A.by_name("greenhouse").parse({"content": "x", "first_published": "soon", "updated_at": 42.5},
                                         "https://job-boards.greenhouse.io/acme/jobs/456")
    assert (junk.posted_at, junk.updated_at) == (None, None)


@pytest.mark.parametrize("name, url, slug", [
    ("greenhouse", "https://job-boards.greenhouse.io/figma/jobs/6143238004", "figma"),
    ("greenhouse", "https://boards.greenhouse.io/Figma/jobs/6143238004?gh_jid=6143238004", "figma"),
    ("greenhouse", "https://boards.greenhouse.io/figma?gh_jid=6143238004", "figma"),
    ("greenhouse", "https://job-boards.greenhouse.io/embed/job_app?for=StackAV&token=5234073007", "stackav"),
    ("lever", "https://jobs.lever.co/binance/60ee32bb-4dfb-4055-98a1-ec3be5479359/apply", "binance"),
    ("ashby", "https://jobs.ashbyhq.com/ramp/b3b0875d-cbf2-41ed-bda3-2714c82c4b57/application", "ramp"),
    # T44: Lever answers only to the name as written; Workable accounts are lowercase; Ashby names hold spaces
    ("lever", "https://jobs.lever.co/CesiumAstro/05d21f28-ddc8-49b4-b602-44bac099310c/apply", "CesiumAstro"),
    ("workable", "https://apply.workable.com/TickPick/j/5840ECEB50/", "tickpick"),
    ("ashby", "https://jobs.ashbyhq.com/Flock%20Safety/417830d1-e891-44aa-bbfb-82f6e19841de/application",
     "flock safety"),
])
def test_board_slug_is_what_the_harvester_lists(name, url, slug):
    adapter = A.by_name(name)
    assert adapter.match(url)
    assert adapter.board_slug(url) == slug


def _paste(monkeypatch, source: JdSource):
    monkeypatch.setattr(jd_fetch, "fetch_jd_from_url", lambda url: source)
    return TestClient(app).post("/jd/from-url", json={"url": source.source_url})


def _companies():
    with _db.SessionLocal() as db:
        return {c.slug: (c.provider, c.discovery_source) for c in db.execute(select(TrackedCompany)).scalars()}


def test_pasted_link_adds_its_company_once(monkeypatch):
    src = JdSource(text="x", source_url="https://job-boards.greenhouse.io/Newco/jobs/1", adapter="greenhouse",
                   posted_at=datetime(2026, 9, 14, 17, 36, 20))
    first = _paste(monkeypatch, src)
    assert first.status_code == 200
    assert first.json()["board"] == "added"
    assert first.json()["posted_at"] == "2026-09-14T17:36:20"  # naive UTC, like the Board feed
    assert type(JdSource.model_validate(first.json()).posted_at) is datetime  # a timestamp stays one
    assert _companies() == {"newco": ("greenhouse", "pasted")}

    again = _paste(monkeypatch, src)
    assert again.json()["board"] == "tracked"
    assert _companies() == {"newco": ("greenhouse", "pasted")}


def test_existing_company_is_left_untouched(monkeypatch):
    with _db.SessionLocal() as db:
        db.add(TrackedCompany(slug="acme", provider="lever", discovery_source="github"))
        db.commit()
    r = _paste(monkeypatch, JdSource(text="x", source_url="https://jobs.ashbyhq.com/acme/1", adapter="ashby"))
    assert r.json()["board"] == "tracked"
    assert _companies() == {"acme": ("lever", "github")}  # provider not flipped (the T26 scout rule)


def test_pasting_a_parked_company_queues_it_for_the_next_harvest(monkeypatch):
    """T29: the ATS just answered, so a board exists. If the recorded board is the
    dead one, the harvester's re-resolve moves it; the paste only un-parks it."""
    with _db.SessionLocal() as db:
        db.add(TrackedCompany(slug="notion", provider="greenhouse", discovery_source="github",
                              gone_at=datetime(2026, 9, 22), last_synced_at=datetime(2026, 9, 22)))
        db.commit()
    r = _paste(monkeypatch, JdSource(text="x", source_url="https://jobs.ashbyhq.com/notion/1", adapter="ashby"))
    assert r.json()["board"] == "tracked"
    with _db.SessionLocal() as db:
        c = db.get(TrackedCompany, "notion")
        assert (c.provider, c.gone_at, c.last_synced_at) == ("greenhouse", None, None)


@pytest.mark.parametrize("adapter, url", [
    ("generic", "https://careers.example.com/jobs/1"),      # includes an ATS whose API failed over to generic
    ("eightfold", "https://qualcomm.eightfold.ai/careers/job/446721162271"),  # no `domain` in its links
])
def test_untrackable_sources_add_nothing(monkeypatch, adapter, url):
    r = _paste(monkeypatch, JdSource(text="x", source_url=url, adapter=adapter))
    assert r.status_code == 200 and r.json()["board"] is None
    assert _companies() == {}


def test_a_pasted_link_tracks_its_board_by_the_name_the_vendor_answers_to(monkeypatch):
    """T44: a cased Lever board parked under its lowercase name; a spaced Ashby
    link was refused as a suspicious slug."""
    for adapter, url in [("lever", "https://jobs.lever.co/CesiumAstro/05d21f28-ddc8-49b4-b602-44bac099310c"),
                         ("ashby", "https://jobs.ashbyhq.com/Flock%20Safety/417830d1-e891-44aa-bbfb-82f6e19841de")]:
        assert _paste(monkeypatch, JdSource(text="x", source_url=url, adapter=adapter)).json()["board"] == "added"
    assert _companies() == {"CesiumAstro": ("lever", "pasted"), "flock safety": ("ashby", "pasted")}


def test_suspicious_slug_still_returns_the_jd_but_is_not_tracked(monkeypatch):
    r = _paste(monkeypatch, JdSource(text="the jd", source_url="https://job-boards.greenhouse.io/a..b/jobs/1",
                                     adapter="greenhouse"))
    assert r.status_code == 200 and r.json()["text"] == "the jd" and r.json()["board"] is None
    assert _companies() == {}


def test_failed_fetch_tracks_nothing(monkeypatch):
    def boom(url):
        raise jd_fetch.JdFetchError("fetch failed: HTTP 500")
    monkeypatch.setattr(jd_fetch, "fetch_jd_from_url", boom)
    r = TestClient(app).post("/jd/from-url", json={"url": "https://job-boards.greenhouse.io/newco/jobs/1"})
    assert r.status_code == 400 and _companies() == {}


def test_generic_warns_when_llm_cleanup_finds_no_job(monkeypatch):
    # Live nuro.ai/careersitem?gh_jid=7793005 (2026-09-22): 925 chars of nav
    # chrome passed the length gate, the LLM answered with this 46-char line,
    # and it was handed back as the JD with no warning.
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda url, **kw: _fixture("generic_job.html").encode())
    monkeypatch.setattr(jd_fetch.config, "OLLAMA_API_KEY", "set")
    monkeypatch.setattr(jd_fetch, "_llm_cleanup", lambda text: "No job description found in the provided text.")
    src = jd_fetch.fetch_jd_from_url("https://nuro.ai/careersitem?gh_jid=7793005")
    assert src.adapter == "generic" and src.warnings


def test_generic_llm_cleanup_of_a_real_jd_does_not_warn(monkeypatch):
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda url, **kw: _fixture("generic_job.html").encode())
    monkeypatch.setattr(jd_fetch.config, "OLLAMA_API_KEY", "set")
    monkeypatch.setattr(jd_fetch, "_llm_cleanup", lambda text: text)
    assert jd_fetch.fetch_jd_from_url("https://careers.example.com/jobs/1").warnings == []


# --- T36: Workday link forms, Oracle, SmartRecruiters, Eightfold, Amazon, Apple ---

@pytest.mark.parametrize("url, api", [
    ("https://wd5.myworkdaysite.com/recruiting/chewy/External/job/Bellevue-WA/Software-Engineer_R1",
     "https://chewy.wd5.myworkdayjobs.com/wday/cxs/chewy/External/job/Bellevue-WA/Software-Engineer_R1"),
    ("https://wd5.myworkdaysite.com/en-US/recruiting/guidewire/external/job/US-Remote/SWE_R2",
     "https://guidewire.wd5.myworkdayjobs.com/wday/cxs/guidewire/external/job/US-Remote/SWE_R2"),
    ("https://NVIDIA.wd5.myworkdayjobs.com/en-us/NVIDIAExternalCareerSite/job/US-CA/SWE_JR1?source=x",
     "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/job/US-CA/SWE_JR1"),
])
def test_workday_link_forms_all_reach_the_api(url, api):
    a = A.by_name("workday")
    assert a.match(url) and a.api_url(url) == api


@pytest.mark.parametrize("url", [
    "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",           # the site, not a job
    "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/x/job/y",          # the API itself
    "https://nvidia.wd5.myworkdayjobs.com/en-US/job/y",
    "https://wd5.myworkdaysite.com/recruiting/chewy",                        # no site
    "https://nvidia.wd5.myworkdayjobs.com.evil.com/x/job/y",
    "https://evil.com/nvidia.wd5.myworkdayjobs.com/x/job/y",
])
def test_workday_does_not_match_non_jobs_or_other_hosts(url):
    assert not A.by_name("workday").match(url)


def _api_then_page(monkeypatch, api_answer, page_answer=b"<html>shell</html>"):
    calls = []

    def get(url, **kw):
        calls.append(url)
        answer = api_answer if len(calls) == 1 else page_answer
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(jd_fetch, "_guarded_get", get)
    return calls


@pytest.mark.parametrize("url", [
    "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-CA/SWE_JR1",
    "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001/job/1",
    "https://apply.careers.microsoft.com/careers/job/1970393557006854",
    "https://www.amazon.jobs/en/jobs/10558915/sde-i",
    "https://jobs.apple.com/en-us/details/200684986",
    "https://jobs.smartrecruiters.com/ServiceNow/744000151698539",
])
def test_a_404_from_a_source_behind_a_js_shell_is_final(monkeypatch, url):
    # Workday's page answers 200 even for a job that does not exist (verified),
    # so scraping it after the API 404s would only find an empty shell.
    calls = _api_then_page(monkeypatch, jd_fetch.JdFetchError("gone", status_code=404))
    with pytest.raises(jd_fetch.JdUnavailable):
        jd_fetch.fetch_jd_from_url(url)
    assert len(calls) == 1


def test_greenhouse_still_asks_the_page_after_an_api_404(monkeypatch):
    # unlisted postings: the API 404s while the page carries the JD (T26)
    calls = _api_then_page(monkeypatch, jd_fetch.JdFetchError("gone", status_code=404),
                           _fixture("generic_job.html").encode())
    assert jd_fetch.fetch_jd_from_url("https://job-boards.greenhouse.io/acme/jobs/1").adapter == "generic"
    assert len(calls) == 2


ORACLE_JOB = "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001/job/344707"


def test_oracle_detail():
    a = A.by_name("oracle")
    assert a.match(ORACLE_JOB) and not a.match(ORACLE_JOB.rsplit("/job/", 1)[0])
    assert a.api_url(ORACLE_JOB) == ("https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
                                     "recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
                                     "&finder=ById;Id=%22344707%22,siteNumber=CX_45001")
    src = a.parse({"items": [{"Title": "Software Engineer", "PrimaryLocation": "Nashville, TN, United States",
                              "ExternalDescriptionStr": "<p>Build &amp; ship</p>", "ExternalResponsibilitiesStr": None,
                              "ExternalQualificationsStr": "<ul><li>Python</li></ul>",
                              "ExternalPostedStartDate": "2026-09-24T17:20:33+00:00"}]}, ORACLE_JOB)
    assert src.text == "Build & ship\n\nPython"
    assert (src.title, src.location, src.posted_at) == ("Software Engineer", "Nashville, TN, United States",
                                                        datetime(2026, 9, 24, 17, 20, 33))
    assert A.by_name("oracle").board_of(ORACLE_JOB) == (
        "eeho", "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001")


def test_an_oracle_id_it_does_not_know_is_unavailable(monkeypatch):
    # verified: a 200 with no items, not a 404
    _api_then_page(monkeypatch, json.dumps({"items": [], "count": 0}).encode())
    with pytest.raises(jd_fetch.JdUnavailable):
        jd_fetch.fetch_jd_from_url(ORACLE_JOB)


def test_smartrecruiters_detail():
    a = A.by_name("smartrecruiters")
    url = "https://jobs.smartrecruiters.com/ServiceNow/744000151698539-principal-software-engineer"
    assert a.match(url) and a.match("https://jobs.smartrecruiters.com/ServiceNow/744000151698539")
    assert not a.match("https://jobs.smartrecruiters.com/oneclick-ui/company/x")
    assert a.api_url(url) == "https://api.smartrecruiters.com/v1/companies/ServiceNow/postings/744000151698539"
    assert a.board_slug(url) == "servicenow"
    src = a.parse({"name": "Software Engineer", "releasedDate": "2026-09-24T20:14:46.889Z",
                   "applyUrl": url + "?oga=true", "company": {"name": "ServiceNow"},
                   "location": {"fullLocation": "Santa Clara, CALIFORNIA, United States"},
                   "jobAd": {"sections": {"companyDescription": {"text": "<p>About us</p>"},
                                          "jobDescription": {"text": "<p>Build</p>"},
                                          "qualifications": {"text": "<p>Python</p>"}}}}, url)
    assert src.text == "Build\n\nPython"  # the company blurb is not the job
    assert (src.company, src.apply_url, src.posted_at) == ("ServiceNow", url + "?oga=true",
                                                          datetime(2026, 9, 24, 20, 14, 46, 889000))


def test_eightfold_detail():
    a = A.by_name("eightfold")
    url = "https://qualcomm.eightfold.ai/careers/job/446721162271"
    assert a.match(url) and a.match("https://apply.careers.microsoft.com/careers/job/1970393557006854")
    assert not a.match("https://evil.ai/careers/job/1") and not a.match("https://qualcomm.eightfold.ai/careers")
    assert a.api_url(url) == "https://qualcomm.eightfold.ai/api/pcsx/position_details?position_id=446721162271&hl=en"
    src = a.parse({"status": 200, "data": {"name": "Backend Software Engineer", "jobDescription": "<p>Build</p>",
                                           "locations": ["San Diego, California, United States"],
                                           "postedTs": 1790281689,
                                           "publicUrl": "https://careers.qualcomm.com/careers/job/446721162271"}}, url)
    assert (src.text, src.location, src.apply_url) == ("Build", "San Diego, California, United States",
                                                       "https://careers.qualcomm.com/careers/job/446721162271")
    assert src.posted_at == datetime(2026, 9, 24, 20, 28, 9)  # seconds, not Lever's milliseconds
    with pytest.raises(ValueError):  # the real "gone" is an HTTP 404, tested above
        a.parse({"status": 200, "data": {}}, url)


def test_amazon_reads_the_page_itself(monkeypatch):
    page = ("<html><head><title>Software Development Engineer I</title></head>"
            "<body><article><h1>Software Development Engineer I</h1>"
            + "".join(f"<p>Build distributed systems that serve millions of customers, part {i}.</p>"
                      for i in range(12))
            + "</article></body></html>").encode()
    calls = _api_then_page(monkeypatch, page)
    src = jd_fetch.fetch_jd_from_url("https://www.amazon.jobs/en/jobs/10558915/sde-i")
    assert src.adapter == "amazon" and "distributed systems" in src.text and len(calls) == 1
    assert src.title == "Software Development Engineer I"
    assert not A.by_name("amazon").match("https://www.amazon.jobs/en/search?base_query=sde")


def _apple(job):
    # a bogus id's page carries only "root" (verified); a real one adds jobDetails
    state = {"loaderData": {"root": {}, **({"jobDetails": {"jobsData": job}} if job is not None else {})}}
    data = json.dumps(json.dumps(state))
    return f"<script>window.__staticRouterHydrationData = JSON.parse({data});</script>".encode()


def test_apple_reads_the_data_in_its_page(monkeypatch):
    _api_then_page(monkeypatch, _apple({
        "postingTitle": "Firmware Engineer", "jobSummary": "At Apple.", "description": "Build HID.",
        "minimumQualifications": "C/C++", "preferredQualifications": None,
        "postDateInGMT": "2026-09-22T00:46:38.691+00:00",
        "locations": [{"city": "Cupertino", "stateProvince": "California", "countryName": "United States"},
                      {"name": "United States", "countryName": "United States"}]}))
    src = jd_fetch.fetch_jd_from_url("https://jobs.apple.com/en-us/details/200684986")
    assert src.text == "At Apple.\n\nBuild HID.\n\nC/C++"
    assert src.location == "Cupertino, California, United States | United States"
    assert src.posted_at == datetime(2026, 9, 22, 0, 46, 38, 691000)


def test_an_apple_page_without_its_job_is_unavailable(monkeypatch):
    # verified: a bogus id is still a 200 page, just without jobDetails
    _api_then_page(monkeypatch, _apple(None))
    with pytest.raises(jd_fetch.JdUnavailable):
        jd_fetch.fetch_jd_from_url("https://jobs.apple.com/en-us/details/999999999")


@pytest.mark.parametrize("adapter, url, slug, boards", [
    ("workday", "https://wd5.myworkdaysite.com/recruiting/chewy/External/job/Bellevue-WA/SWE_R1",
     "chewy", ["https://chewy.wd5.myworkdayjobs.com/External"]),
    ("oracle", ORACLE_JOB, "eeho", ["https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001"]),
    ("smartrecruiters", "https://jobs.smartrecruiters.com/ServiceNow/744000151698539", "servicenow", None),
])
def test_a_pasted_link_tracks_its_board(monkeypatch, adapter, url, slug, boards):
    assert _paste(monkeypatch, JdSource(text="x", source_url=url, adapter=adapter)).json()["board"] == "added"
    with _db.SessionLocal() as db:
        company = db.get(TrackedCompany, slug)
        assert (company.provider, company.boards, company.discovery_source) == (adapter, boards, "pasted")
    assert _paste(monkeypatch, JdSource(text="x", source_url=url, adapter=adapter)).json()["board"] == "tracked"


@pytest.mark.parametrize("url, answer", [
    (ORACLE_JOB, json.dumps({"title": "Service Unavailable"}).encode()),     # no items at all
    ("https://apply.careers.microsoft.com/careers/job/1", json.dumps({"status": 200}).encode()),
    ("https://jobs.apple.com/en-us/details/200684986", _apple({})),           # jobDetails, no jobsData
    ("https://jobs.apple.com/en-us/details/200684986", b"<html>maintenance</html>"),
])
def test_an_ambiguous_answer_never_closes_a_job(monkeypatch, url, answer):
    # Only each vendor's verified "gone" signal may raise JdUnavailable; anything
    # else falls back to the page, which the Board treats as "retry", not closed.
    _api_then_page(monkeypatch, answer)
    assert jd_fetch.fetch_jd_from_url(url).adapter == "generic"


def test_a_thin_amazon_page_falls_back_to_the_generic_warning(monkeypatch):
    _api_then_page(monkeypatch, b"<html><body>Robot check</body></html>")
    src = jd_fetch.fetch_jd_from_url("https://www.amazon.jobs/en/jobs/10558915/sde-i")
    assert src.adapter == "generic" and src.warnings


def test_a_closed_smartrecruiters_posting_is_unavailable(monkeypatch):
    # verified live: closed postings answer 200 with "active": false, and so does their page
    calls = _api_then_page(monkeypatch, json.dumps({"active": False, "name": "Software Engineer",
                                                    "jobAd": {"sections": {}}}).encode())
    with pytest.raises(jd_fetch.JdUnavailable):
        jd_fetch.fetch_jd_from_url("https://jobs.smartrecruiters.com/Visa/744000106245998")
    assert len(calls) == 1


@pytest.mark.parametrize("body, closed", [
    (b'{"errorCode":"S22","errorCaseId":"F6D1CAMUG2BEV4","httpStatus":403,"message":"permission denied"}', True),
    (b"<html>Just a moment...</html>", False),  # a CDN challenge says nothing about the job
])
def test_a_closed_workday_job_is_a_json_403(monkeypatch, body, closed):
    url = "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-CA/SWE_JR1"
    transport = httpx.MockTransport(lambda request: httpx.Response(403, content=body))
    real = jd_fetch._guarded_get
    monkeypatch.setattr(jd_fetch, "_check_url", lambda url: None)
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda u, **kw: real(u, transport=transport))
    if closed:
        with pytest.raises(jd_fetch.JdUnavailable):
            jd_fetch.fetch_jd_from_url(url)
    else:
        with pytest.raises(jd_fetch.JdFetchError) as info:
            jd_fetch.fetch_jd_from_url(url)
        assert not isinstance(info.value, jd_fetch.JdUnavailable)


@pytest.mark.parametrize("url", [
    "https://fa-espx-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/2422377",
    "https://jobs.smartrecruiters.com/ServiceNow/2274d8e3-af4a-4935-b065-f65622b5ea3f",
])
def test_link_forms_found_in_simplify_history_are_matched(url):
    # 244 of 2,383 Oracle links use a hyphenated pod; old SmartRecruiters ids are UUIDs
    assert any(a.match(url) for a in A.ADAPTERS if a.name in ("oracle", "smartrecruiters"))


def test_a_pasted_link_whose_board_we_cannot_track_still_returns_its_jd(monkeypatch):
    # match() accepts it, but board_of() refuses the dotted site name: this was a 500
    url = "https://acme.wd5.myworkdayjobs.com/Site.Name/job/US/SWE_R1"
    r = _paste(monkeypatch, JdSource(text="the jd", source_url=url, adapter="workday"))
    assert r.status_code == 200 and r.json()["text"] == "the jd" and r.json()["board"] is None
    assert _companies() == {}


# --- T37: Workable and iCIMS ---------------------------------------------------

WK_JOB = "https://apply.workable.com/tickpick/j/F4AEB07453/apply"


def test_workable_detail():
    a = A.by_name("workable")
    assert a.match(WK_JOB) and a.match("https://apply.workable.com/tickpick/j/F4AEB07453/")
    assert not a.match("https://apply.workable.com/api/v1/widget/accounts/tickpick")
    assert not a.match("https://evil.com/tickpick/j/F4AEB07453/")
    assert a.api_url(WK_JOB) == "https://apply.workable.com/api/v2/accounts/tickpick/jobs/F4AEB07453"
    assert a.board_slug(WK_JOB) == "tickpick"
    src = a.parse({"title": "General Counsel", "published": "2026-09-16T00:00:00.000Z",
                   "description": "<p>Lead</p>", "requirements": "<ul><li>JD</li></ul>", "benefits": "",
                   "location": {"country": "United States", "countryCode": "US", "city": "New York",
                                "region": "New York"},
                   "locations": []}, WK_JOB)
    assert (src.text, src.location, src.posted_at) == (
        "Lead\n\nJD", "New York, New York, United States", date(2026, 9, 16))
    hid = a.parse({"title": "x", "locations": [
        {"city": "McLean", "region": "Virginia", "country": "United States", "hidden": False},
        {"city": "", "region": None, "country": "Germany", "hidden": True}]}, WK_JOB)
    assert hid.location == "McLean, Virginia, United States"  # the employer hid Germany
    assert src.apply_url == "https://apply.workable.com/tickpick/j/F4AEB07453/apply"


IC_JOB = "https://careers-gdms.icims.com/jobs/74456/advanced-systems-engineer/job"


def _icims_page(**extra):
    posting = {"@type": "JobPosting", "title": "Advanced Systems Engineer",
               "description": "<p>Build</p>",  # raw tags, as live
               "datePosted": "2026-08-20T04:00:00.000Z",
               "jobLocation": [{"address": {"addressLocality": "Manassas", "addressRegion": "VA",
                                            "addressCountry": "US"}}],
               **extra}
    return f'<script type="application/ld+json">{json.dumps(posting)}</script>'.encode()


def test_icims_detail_reads_the_json_ld_of_the_iframe_page(monkeypatch):
    a = A.by_name("icims")
    assert a.match(IC_JOB) and a.match(IC_JOB + "?mobile=true&needsRedirect=false")
    assert a.api_url(IC_JOB + "?mobile=true") == IC_JOB + "?in_iframe=1"  # the bare page is a shell
    # Simplify's usual form has no title slug (125 of 130 active links); verified to serve the same page
    short = "https://careers-gdms.icims.com/jobs/74456/job?mobile=true&needsRedirect=false"
    assert a.match(short) and a.api_url(short) == "https://careers-gdms.icims.com/jobs/74456/job?in_iframe=1"
    for bad in ("https://www.icims.com/jobs/1/x/job", "https://careers-gdms.icims.com/jobs/search?pr=0",
                "https://careers-gdms.icims.com.evil.com/jobs/1/x/job", "https://evil.com/jobs/1/x/job"):
        assert not a.match(bad), bad
    assert a.board_of(IC_JOB) == ("careers-gdms", "https://careers-gdms.icims.com")
    assert a.board_of("https://careers-gdms.icims.com/connect") is None  # not a jobs page
    calls = _api_then_page(monkeypatch, _icims_page())
    src = jd_fetch.fetch_jd_from_url(IC_JOB)
    assert (src.adapter, src.title, src.location, src.posted_at, src.text) == (
        "icims", "Advanced Systems Engineer", "Manassas, VA, US", date(2026, 8, 20), "Build")
    assert calls == [IC_JOB + "?in_iframe=1"]


def test_a_pasted_icims_link_shows_no_placeholder_location(monkeypatch):
    """T42: careers-mci2 50267 - every address field "UNAVAILABLE" but the country."""
    where = [{"address": {"addressLocality": "UNAVAILABLE", "addressRegion": "UNAVAILABLE", "addressCountry": "US",
                          "postalCode": "UNAVAILABLE", "streetAddress": "UNAVAILABLE"}}]
    _api_then_page(monkeypatch, _icims_page(jobLocation=where))
    assert jd_fetch.fetch_jd_from_url(IC_JOB).location == "US"


def test_a_pasted_icims_link_with_a_faked_post_date_says_no_date(monkeypatch):
    """T41: 21 of 95 portals send the request time minus 2 years; it read as "2 years ago"."""
    fake = datetime.now(timezone.utc) - timedelta(days=730)
    _api_then_page(monkeypatch, _icims_page(datePosted=f"{fake:%Y-%m-%dT%H:%M:%S.%f}"[:-3] + "Z"))
    assert jd_fetch.fetch_jd_from_url(IC_JOB).posted_at is None


@pytest.mark.parametrize("url, status", [(IC_JOB, 410), (WK_JOB, 404)])  # both verified on real closed jobs
def test_a_closed_icims_or_workable_job_is_unavailable(monkeypatch, url, status):
    calls = _api_then_page(monkeypatch, jd_fetch.JdFetchError("gone", status_code=status))
    with pytest.raises(jd_fetch.JdUnavailable):
        jd_fetch.fetch_jd_from_url(url)
    assert len(calls) == 1


def test_an_icims_page_without_a_posting_falls_back_to_the_generic_path(monkeypatch):
    _api_then_page(monkeypatch, b"<html>maintenance</html>", _fixture("generic_job.html").encode())
    assert jd_fetch.fetch_jd_from_url(IC_JOB).adapter == "generic"


@pytest.mark.parametrize("adapter, url, slug, boards", [
    ("workable", WK_JOB, "tickpick", None),
    ("icims", IC_JOB, "careers-gdms", ["https://careers-gdms.icims.com"]),
])
def test_a_pasted_workable_or_icims_link_tracks_its_board(monkeypatch, adapter, url, slug, boards):
    assert _paste(monkeypatch, JdSource(text="x", source_url=url, adapter=adapter)).json()["board"] == "added"
    with _db.SessionLocal() as db:
        company = db.get(TrackedCompany, slug)
        assert (company.provider, company.boards) == (adapter, boards)
