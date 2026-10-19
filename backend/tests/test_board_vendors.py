"""T36 - Workday, Oracle, SmartRecruiters, Eightfold, Amazon and Apple boards.
Every vendor behaviour faked here was observed live on 2026-09-24."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db as _db
from app.main import app
from app.models import JobPosting, TrackedCompany
from app.services import board_policy, board_sync, jd_adapters

NOW = datetime(2026, 9, 24, 12)
REAL_F500 = board_sync.F500_BOARDS  # before the fixture below empties it
REAL_SLEEP = asyncio.sleep  # the fixture below makes board_sync's sleeps instant
WD = "https://acme.wd5.myworkdayjobs.com/External"
WD_API = "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/External"


@pytest.fixture(autouse=True)
def harness(monkeypatch):
    monkeypatch.setattr(board_policy, "utcnow", lambda: NOW)
    monkeypatch.setattr(board_sync, "F500_BOARDS", [])
    for cache in ("_ETAGS", "_UNCOMMITTED_ETAGS", "_WORKDAY_DETAILS", "_ROBOTS", "_ICIMS_POSTINGS", "_WORKDAY_FILTERS"):
        monkeypatch.setattr(board_sync, cache, {})
    slept = []

    async def no_sleep(seconds, *a, **k):
        slept.append(seconds)
    monkeypatch.setattr(board_sync.asyncio, "sleep", no_sleep)
    return slept


def client(handler, seen=None):
    """handler(method, url, json_body) -> (status, payload, headers). A bytes
    payload is sent as is (HTML), anything else as JSON."""
    seen = [] if seen is None else seen

    class Resp:
        def __init__(self, status, body, headers):
            self.status_code, self.body, self.headers = status, body, httpx.Headers(headers)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=httpx.Request("GET", "https://x"),
                                            response=httpx.Response(self.status_code))

        async def aread(self):
            return self.body

        async def aiter_bytes(self):
            yield self.body

    class Client:
        def stream(self, method, url, headers=None, json=None):
            seen.append((method, url, json))
            status, payload, hdrs = handler(method, url, json)
            body = payload if isinstance(payload, bytes) else _json(payload)

            @asynccontextmanager
            async def response():
                yield Resp(status, body, hdrs or {})
            return response()

    return Client()


def _json(value):
    return json.dumps(value).encode()


def run(coro):
    return asyncio.run(coro)


# --- Workday ------------------------------------------------------------------

def wd_jobs(n, start=0, posted="Posted Today", loc="Austin, TX", title="Software Engineer", prefix="R"):
    return [{"title": title, "externalPath": f"/job/Austin/SWE_{prefix}{i}", "locationsText": loc,
             "postedOn": posted} for i in range(start, start + n)]


def workday_site(jobs, reported=None):
    """A real site: `total` on page 1 only, capped at 2000, and an offset at or
    past it wraps back to page 1."""
    total = len(jobs) if reported is None else reported

    def page(offset):
        if offset >= total:
            offset = 0  # the wrap
        return {"total": total if offset == 0 else 0, "jobPostings": jobs[offset:offset + 20]}
    return page


def workday(sites, detail=None):
    """sites: {site name: page(offset) or (status, payload)}."""
    def handler(method, url, body):
        if method == "GET":
            return detail(url) if detail else (404, {}, {})
        site = url.split("/")[-2]
        route = sites.get(site, (404, {}))
        return (200, route(body["offset"]), {}) if callable(route) else (*route, {})
    return handler


def test_workday_reads_every_page_and_never_asks_past_total():
    seen = []
    jobs = run(board_sync.fetch_workday("acme", client(workday({"External": workday_site(wd_jobs(45))}), seen), [WD]))
    assert [body["offset"] for _, _, body in seen] == [0, 20, 40]  # 60 would wrap to page 1
    assert [body["limit"] for _, _, body in seen] == [20, 20, 20]  # 21 is an HTTP 400
    assert len(jobs) == 45 and not isinstance(jobs, board_sync.Partial)
    assert jobs[0] == {"title": "Software Engineer", "location": "Austin, TX",
                       "url": f"{WD}/job/Austin/SWE_R0", "published_at": NOW.isoformat(), "country": None}
    assert all(url == f"{WD_API}/jobs" for _, url, _ in seen)


def test_workday_site_at_the_2000_cap_is_partial():
    seen = []
    site = workday_site(wd_jobs(2000), reported=2000)
    jobs = run(board_sync.fetch_workday("acme", client(workday({"External": site}), seen), [WD]))
    assert isinstance(jobs, board_sync.Partial) and len(jobs) == 2000
    assert max(body["offset"] for _, _, body in seen) == 1980


# T43: Workday's country facet, nested under locationMainGroup as on Accenture
US, CA, PR, IN = "bc33aa3152ec42d4995f4791a106ed09", "a30a87ed25634629aa6c3958aa2b91ea", "pr1", "in1"
COUNTRIES = {"facetParameter": "locationMainGroup", "values": [{"facetParameter": "locationCountry", "values": [
    {"descriptor": "United States of America", "id": US, "count": 30}, {"descriptor": "Canada", "id": CA, "count": 5},
    {"descriptor": "Puerto Rico", "id": PR, "count": 1}, {"descriptor": "India", "id": IN, "count": 2500}]}]}
FAMILIES = {"facetParameter": "jobFamilyGroup", "values": [{"descriptor": "Engineering", "id": "f1", "count": 2400}]}


def capped_site(domestic, facets=COUNTRIES, narrowed=None):
    """Page 1 reports the 2,000 cap and carries `facets`; a request filtered by
    country gets the `domestic` rows (reported as `narrowed` when given)."""
    everything, narrow = workday_site(wd_jobs(2000, prefix="X"), reported=2000), workday_site(domestic, narrowed)

    def handler(method, url, body):
        if body["appliedFacets"]:
            return 200, narrow(body["offset"]), {}
        page = everything(body["offset"])
        return 200, {**page, "facets": [facets]} if body["offset"] == 0 else page, {}
    return handler


def test_a_capped_workday_site_is_read_through_the_countries_our_filter_keeps():
    """Accenture lists 2,000 of ~75,000; 6 recent US software jobs sat past row
    2,000. Its US/CA view is 926 rows. Puerto Rico counts: our filter keeps it
    (ABB's Arecibo job), so the countries follow the filter, not a fixed list."""
    seen = []
    fetch = lambda: run(board_sync.fetch_workday("acme", client(capped_site(wd_jobs(36)), seen), [WD]))
    jobs = fetch()
    assert len(jobs) == 36 and not isinstance(jobs, board_sync.Partial)  # complete: absence now closes
    assert [body["appliedFacets"] for _, _, body in seen] == [{}] + [{"locationCountry": [US, CA, PR]}] * 2
    # remembered: the next check asks the filtered view first, and an unchanged one costs one request
    board_sync._commit_etag("workday", "acme")
    seen.clear()
    assert fetch() is board_sync.NOT_MODIFIED
    assert [body["appliedFacets"] for _, _, body in seen] == [{"locationCountry": [US, CA, PR]}]


@pytest.mark.parametrize("facets, narrowed, asked", [
    (COUNTRIES, 2000, 1),   # Walmart: its US view alone overflows
    (FAMILIES, None, 0),    # no country facet (NVIDIA): nothing to ask
])
def test_a_capped_site_without_a_fitting_country_view_stays_partial(facets, narrowed, asked):
    seen = []
    fetch = lambda: run(board_sync.fetch_workday(
        "acme", client(capped_site(wd_jobs(2000, prefix="D"), facets, narrowed), seen), [WD]))
    jobs = fetch()
    assert isinstance(jobs, board_sync.Partial) and len(jobs) == 2000
    assert sum(bool(body["appliedFacets"]) for _, _, body in seen) == asked
    seen.clear()
    fetch()  # remembered: never asked again
    assert not any(body["appliedFacets"] for _, _, body in seen)


def test_an_uncapped_site_is_read_as_before_even_with_a_country_facet():
    """376 of 405 sites are under the cap: no country request, no filter."""
    site, seen = workday_site(wd_jobs(45)), []

    def handler(method, url, body):
        page = site(body["offset"])
        return 200, {**page, "facets": [COUNTRIES]} if body["offset"] == 0 else page, {}
    assert len(run(board_sync.fetch_workday("acme", client(handler, seen), [WD]))) == 45
    assert [body["appliedFacets"] for _, _, body in seen] == [{}, {}, {}]


def test_a_failed_country_request_is_tried_again_next_time(harness):
    calls, site = [], capped_site(wd_jobs(36))

    def flaky(method, url, body):
        calls.append(body["appliedFacets"])
        if body["appliedFacets"] and calls.count(body["appliedFacets"]) <= 4:
            return 500, {}, {}  # every retry of the first filtered ask fails
        return site(method, url, body)
    with pytest.raises(httpx.HTTPStatusError):
        run(board_sync.fetch_workday("acme", client(flaky), [WD]))
    assert board_sync._WORKDAY_FILTERS == {}  # nothing remembered
    jobs = run(board_sync.fetch_workday("acme", client(flaky), [WD]))
    assert len(jobs) == 36 and not isinstance(jobs, board_sync.Partial)


def test_a_complete_country_view_closes_what_it_no_longer_lists():
    _workday_company()
    stale = f"{WD}/job/Pune/Custom-Software-Engineer_ATCI-1"  # Accenture: 233 such no-location India rows stayed open
    with _db.SessionLocal() as db:
        db.add(JobPosting(url=stale, company_slug="acme", title="Custom Software Engineer", location=None,
                          status="open", created_at=NOW - timedelta(days=2), updated_at=NOW))
        db.commit()
    assert _sync(capped_site(wd_jobs(3))) == 3
    assert _postings()[stale][0] == "closed"


def test_workday_merges_a_companys_sites_without_duplicates():
    both = wd_jobs(3)
    sites = {"External": workday_site(both), "Campus": workday_site(both[:1] + wd_jobs(2, prefix="C"))}
    jobs = run(board_sync.fetch_workday("acme", client(workday(sites)),
                                        [WD, "https://acme.wd5.myworkdayjobs.com/Campus"]))
    assert len(jobs) == 5
    assert jobs[0]["url"] == f"{WD}/job/Austin/SWE_R0"  # first site wins


@pytest.mark.parametrize("gone", [(404, {}), (422, {"errorCode": "HTTP_422"}),
                                  (403, {"errorCode": "S22", "httpStatus": 403, "message": "permission denied"})])
def test_a_gone_workday_site_is_skipped_and_all_gone_is_none(gone):
    sites = {"External": gone, "Campus": workday_site(wd_jobs(2))}
    jobs = run(board_sync.fetch_workday("acme", client(workday(sites)),
                                        [WD, "https://acme.wd5.myworkdayjobs.com/Campus"]))
    assert len(jobs) == 2
    assert run(board_sync.fetch_workday("acme", client(workday({"External": gone})), [WD])) is None


def test_a_cdn_403_is_a_rate_limit_retried_then_raised(harness):
    seen = []
    handler = lambda *a: (403, b"<html>Just a moment...</html>", {})
    with pytest.raises(board_sync.RateLimited):
        run(board_sync.fetch_workday("acme", client(handler, seen), [WD]))
    assert len(seen) == 4 and harness == [15, 30, 60]


def test_a_page_rate_limited_mid_board_is_retried_not_dropped(harness):
    site, calls = workday_site(wd_jobs(25)), []

    def handler(method, url, body):
        calls.append(body["offset"])
        if calls.count(20) == 1 and body["offset"] == 20:
            return 429, {}, {"Retry-After": "5"}
        return 200, site(body["offset"]), {}
    jobs = run(board_sync.fetch_workday("acme", client(handler), [WD]))
    assert len(jobs) == 25 and calls == [0, 20, 20]
    assert 5 in harness  # Retry-After honoured when shorter than the step


def test_a_workday_site_vanishing_mid_read_is_an_error_not_a_short_board():
    site = workday_site(wd_jobs(30))
    handler = lambda m, u, body: (200, site(0), {}) if body["offset"] == 0 else (404, {}, {})
    with pytest.raises(ValueError):
        run(board_sync.fetch_workday("acme", client(handler), [WD]))


def test_an_unchanged_workday_board_costs_one_request():
    site, seen = workday_site(wd_jobs(45)), []
    fetch = lambda: run(board_sync.fetch_workday("acme", client(workday({"External": site}), seen), [WD]))
    assert len(fetch()) == 45
    board_sync._commit_etag("workday", "acme")
    seen.clear()
    assert fetch() is board_sync.NOT_MODIFIED and len(seen) == 1
    grown = workday_site(wd_jobs(46))  # one more posting: the total moves
    seen.clear()
    assert len(run(board_sync.fetch_workday("acme", client(workday({"External": grown}), seen), [WD]))) == 46


def test_a_fingerprint_is_trusted_only_once_committed():
    site = workday_site(wd_jobs(3))
    fetch = lambda: run(board_sync.fetch_workday("acme", client(workday({"External": site})), [WD]))
    fetch()
    assert fetch() != board_sync.NOT_MODIFIED  # a sync that never committed pins nothing


def test_workday_names_the_locations_of_a_target_role_once():
    rows = (wd_jobs(1, loc="3 Locations") + wd_jobs(1, 1, loc="2 Locations", title="Senior Software Engineer")
            + wd_jobs(1, 2, loc="2 Locations", posted="Posted 30+ Days Ago"))
    details = []

    def detail(url):
        details.append(url)
        return 200, {"jobPostingInfo": {"location": "US, CA, Santa Clara",
                                        "additionalLocations": ["US, TX, Austin", "Taiwan, Taipei"],
                                        "jobRequisitionLocation": {"country": {"alpha2Code": "US"}}}}, {}
    handler = workday({"External": workday_site(rows)}, detail)
    jobs = run(board_sync.fetch_workday("acme", client(handler), [WD]))
    assert details == [f"{WD_API}/job/Austin/SWE_R0"]  # not the senior role, not the stale one
    assert jobs[0]["location"] == "US, CA, Santa Clara | US, TX, Austin | Taiwan, Taipei"
    assert jobs[0]["country"] == "US"
    assert [j["location"] for j in jobs[1:]] == ["2 Locations", "2 Locations"]
    run(board_sync.fetch_workday("acme", client(handler), [WD]))
    assert len(details) == 1  # cached by URL


@pytest.mark.parametrize("text, days", [
    ("Posted Today", 0), ("Posted Yesterday", 1), ("Posted 2 Days Ago", 2), ("Posted 1 Day Ago", 1),
    ("Posted 30+ Days Ago", None),  # a lower bound, not a date
    ("Posted", None), ("", None), (None, None), (7, None), ("posted today", None),
])
def test_workday_relative_dates(text, days):
    assert board_sync.workday_days(text) == days


def _workday_company(boards=(WD,), slug="acme"):
    with _db.SessionLocal() as db:
        db.add(TrackedCompany(slug=slug, provider="workday", boards=boards and list(boards)))
        db.commit()


def _postings():
    with _db.SessionLocal() as db:
        return {p.url: (p.status, p.created_at) for p in db.scalars(select(JobPosting))}


def _sync(handler, slug="acme"):
    with _db.SessionLocal() as db:
        company = db.get(TrackedCompany, slug)
        return run(board_sync.sync_company_jobs(db, company, client(handler)))


def test_a_workday_posting_keeps_the_stamp_it_was_first_seen_with(monkeypatch):
    _workday_company()
    assert _sync(workday({"External": workday_site(wd_jobs(1))})) == 1
    first = _postings()[f"{WD}/job/Austin/SWE_R0"]
    assert first == ("open", NOW)
    later = NOW + timedelta(hours=20)  # the next day, Workday now says "Posted Yesterday"
    monkeypatch.setattr(board_policy, "utcnow", lambda: later)
    # one more posting too, so the board has changed and every row is upserted again
    assert _sync(workday({"External": workday_site(wd_jobs(2, posted="Posted Yesterday"))})) == 2
    assert _postings()[f"{WD}/job/Austin/SWE_R0"] == ("open", NOW)  # not later - 1 day


@pytest.mark.parametrize("detail, status", [
    ((200, {"jobPostingInfo": {"title": "Software Engineer"}}), "open"),       # live, just past the cap
    ((403, {"errorCode": "S22", "message": "permission denied"}), "closed"),  # Workday's closed job
])
def test_a_partial_read_closes_only_what_the_vendor_confirms_gone(detail, status):
    _workday_company()
    _sync(workday({"External": workday_site(wd_jobs(2))}))
    unseen, asked = f"{WD}/job/Austin/SWE_R1", []

    def answer(url):
        asked.append(url)
        return (*detail, {})
    _sync(workday({"External": workday_site(wd_jobs(1), reported=2000)}, answer))  # capped: R1 unseen
    assert _postings()[unseen][0] == status and asked == [f"{WD_API}/job/Austin/SWE_R1"]


def test_a_whole_read_closes_by_absence_without_asking():
    _workday_company()
    _sync(workday({"External": workday_site(wd_jobs(2))}))
    asked = []
    _sync(workday({"External": workday_site(wd_jobs(1))}, lambda url: asked.append(url)))
    assert _postings()[f"{WD}/job/Austin/SWE_R1"][0] == "closed" and asked == []


def test_old_and_undated_workday_postings_never_reach_the_board():
    _workday_company()
    rows = (wd_jobs(1, posted="Posted 13 Days Ago") + wd_jobs(1, 1, posted="Posted 14 Days Ago")
            + wd_jobs(1, 2, posted="Posted 30+ Days Ago") + wd_jobs(1, 3, posted="Reposted"))
    assert _sync(workday({"External": workday_site(rows)})) == 1
    assert list(_postings()) == [f"{WD}/job/Austin/SWE_R0"]


def test_a_board_vendor_without_a_board_url_is_a_vendor_error():
    _workday_company(boards=None)
    with pytest.raises(board_sync.BoardVendorError):
        _sync(lambda *a: (200, {}, {}))


# --- Oracle -----------------------------------------------------------------

OR = "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001"


def oracle_page(reqs, total):
    return {"items": [{"SearchId": 1, "TotalJobsCount": total, "requisitionList": reqs}]}


def reqs(n, start=0, day="2026-09-24"):
    return [{"Id": str(i), "Title": "Software Engineer", "PostedDate": day,
             "PrimaryLocation": "Austin, TX, United States", "PrimaryLocationCountry": "US",
             "secondaryLocations": [{"Name": "United States", "CountryCode": "US"}]} for i in range(start, start + n)]


def test_oracle_stops_at_the_first_page_reaching_past_14_days():
    pages = {0: reqs(200, day="2026-09-20"), 200: reqs(199, 200, day="2026-09-11") + reqs(1, 399, day="2026-09-10"),
             400: reqs(200, 400, day="2026-09-01")}
    seen = []
    handler = lambda m, url, b: (200, oracle_page(pages[int(url.split("offset=")[1].split(",")[0])], 900), {})
    jobs = run(board_sync.fetch_oracle("oracle", client(handler, seen), [OR]))
    assert len(seen) == 2 and len(jobs) == 400  # the stale one is filtered later, by sync
    assert "sortBy=POSTING_DATES_DESC" in seen[0][1] and "limit=200" in seen[0][1]
    assert jobs[0] == {"title": "Software Engineer", "url": f"{OR}/job/0",
                       "location": "Austin, TX, United States | United States",
                       "published_at": (NOW - timedelta(days=4)).isoformat(), "country": "US"}


def test_a_malformed_oracle_page_is_an_error_not_an_empty_board():
    for bad in ({"items": []}, {"items": [{"SearchId": 1, "requisitionList": [{"Title": "x"}]}]}, []):
        with pytest.raises(ValueError):
            run(board_sync.fetch_oracle("oracle", client(lambda *a, bad=bad: (200, bad, {})), [OR]))


# --- SmartRecruiters ----------------------------------------------------------

def sr_jobs(n, start=0, released="2026-09-24T10:00:00.000Z"):
    return [{"id": str(744000000 + i), "name": "Software Engineer", "releasedDate": released,
             "company": {"identifier": "ServiceNow"},
             "location": {"fullLocation": "Santa Clara, CALIFORNIA, United States"}}
            for i in range(start, start + n)]


def test_smartrecruiters_stops_past_14_days_and_links_the_real_company_id():
    pages = {0: sr_jobs(100), 100: sr_jobs(100, 100, released="2026-09-01T00:00:00Z"), 200: sr_jobs(5, 200)}
    seen = []
    handler = lambda m, url, b: (200, {"totalFound": 205, "content": pages[int(url.split("offset=")[1])]}, {})
    jobs = run(board_sync.fetch_smartrecruiters("servicenow", client(handler, seen)))
    assert len(seen) == 2 and len(jobs) == 200
    assert seen[0][1] == "https://api.smartrecruiters.com/v1/companies/servicenow/postings?limit=100&offset=0"
    assert jobs[0]["url"] == "https://jobs.smartrecruiters.com/ServiceNow/744000000"
    assert jobs[0]["published_at"] == "2026-09-24T10:00:00.000Z"


def test_an_unknown_smartrecruiters_company_is_an_empty_board():
    # verified: 200 {"totalFound":0,"content":[]} - never a 404, so no move check
    assert run(board_sync.fetch_smartrecruiters("nosuch", client(
        lambda *a: (200, {"offset": 0, "limit": 100, "totalFound": 0, "content": []}, {})))) == []
    assert "smartrecruiters" not in board_sync.MOVABLE


# --- Eightfold ----------------------------------------------------------------

EF = "https://apply.careers.microsoft.com/careers?domain=microsoft.com"


def test_eightfold_reads_us_and_canada_once_each_with_seconds_timestamps():
    ts = int(datetime(2026, 9, 24, 17, 20, 33, tzinfo=timezone.utc).timestamp())
    seen = []

    def handler(m, url, b):
        start = int(url.split("start=")[1].split("&")[0])
        us = "United%20States" in url
        ids = list(range(start, min(start + 10, 15))) if us else [0, 100]  # job 0 is in both countries
        return 200, {"status": 200, "data": {"count": 15 if us else 2, "positions": [
            {"id": i, "name": "Software Engineer", "locations": ["Redmond, WA, US"], "postedTs": ts} for i in ids]}}, {}
    jobs = run(board_sync.fetch_eightfold("microsoft", client(handler, seen), [EF]))
    assert len(jobs) == 16 and len({j["url"] for j in jobs}) == 16
    assert [u.split("start=")[1].split("&")[0] for _, u, _ in seen] == ["0", "0", "10"]
    assert jobs[0]["url"] == "https://apply.careers.microsoft.com/careers/job/0"
    assert jd_adapters.parse_ats_date(jobs[0]["published_at"]) == datetime(2026, 9, 24, 17, 20, 33)
    assert "domain=microsoft.com" in seen[0][1] and "sort_by=timestamp" in seen[0][1]


@pytest.mark.parametrize("value", [None, "1790281689", True, 10**20, float("nan")])
def test_eightfold_timestamps_that_are_not_seconds_are_undated(value):
    assert jd_adapters.parse_ats_date(jd_adapters.epoch_seconds(value)) is None


# --- Amazon -------------------------------------------------------------------

def amazon_jobs(n, start=0, posted="September 20, 2026"):
    return [{"title": "Software Development Engineer I", "job_path": f"/en/jobs/{i}/sde-i",
             "normalized_location": "Seattle, Washington, USA", "location": "US, WA, Seattle",
             "posted_date": posted} for i in range(start, start + n)]


def test_amazon_reads_both_countries_and_stops_at_its_cap(monkeypatch):
    monkeypatch.setattr(board_sync, "AMAZON_CAP", 150)
    seen = []

    def handler(m, url, b):
        offset = int(url.split("offset=")[1])
        if "country=CAN" in url:
            return 200, {"hits": 1, "jobs": amazon_jobs(1, 900)}, {}
        return 200, {"hits": 300, "jobs": amazon_jobs(100, offset)}, {}
    jobs = run(board_sync.fetch_amazon("amazon", client(handler, seen)))
    assert isinstance(jobs, board_sync.Partial) and len(jobs) == 201
    assert jobs[0] == {"title": "Software Development Engineer I", "location": "Seattle, Washington, USA",
                       "url": "https://www.amazon.jobs/en/jobs/0/sde-i",
                       "published_at": (NOW - timedelta(days=4)).isoformat()}
    assert "result_limit=100" in seen[0][1]
    assert all(f"category%5B%5D={c}&" in seen[0][1] for c in (
        "software-development", "systems-quality-security-engineering", "data-science"))


# --- Apple --------------------------------------------------------------------

def apple_page(results, total):
    state = {"loaderData": {"search": {"searchResults": results, "totalRecords": total}}}
    data = json.dumps(json.dumps(state))
    return f"<script>window.__staticRouterHydrationData = JSON.parse({data});</script>".encode()


def apple_jobs(n, start=0, when="2026-09-24T00:46:38.691+00:00"):
    return [{"positionId": str(200000000 + i), "postingTitle": "Software Engineer", "postDateInGMT": when,
             "locations": [{"city": "Cupertino", "stateProvince": "California", "countryName": "United States"}]}
            for i in range(start, start + n)]


def test_apple_pages_from_one_and_stops_past_14_days():
    seen = []

    def handler(m, url, b):
        page = int(url.split("page=")[1])
        if "canada-CANC" in url:
            return 200, apple_page(apple_jobs(1, 999), 1), {}
        when = "2026-09-24T00:00:00Z" if page == 1 else "2026-09-01T00:00:00Z"
        return 200, apple_page(apple_jobs(20, page * 20, when), 4574), {}
    jobs = run(board_sync.fetch_apple("apple", client(handler, seen)))
    assert [u.split("?")[1] for _, u, _ in seen] == [
        "sort=newest&location=united-states-USA&page=1", "sort=newest&location=canada-CANC&page=1",
        "sort=newest&location=united-states-USA&page=2"]
    assert len(jobs) == 41
    assert jobs[0] == {"title": "Software Engineer", "location": "Cupertino, California, United States",
                       "url": "https://jobs.apple.com/en-us/details/200000020",
                       "published_at": "2026-09-24T00:00:00Z"}


def test_an_apple_page_without_its_data_is_an_error():
    with pytest.raises(ValueError):
        run(board_sync.fetch_apple("apple", client(lambda *a: (200, b"<html>maintenance</html>", {}))))


# --- tracking, curation, discovery --------------------------------------------------

def _rows():
    with _db.SessionLocal() as db:
        return {c.slug: (c.provider, c.boards, c.name) for c in db.scalars(select(TrackedCompany))}


def test_a_board_is_identified_by_its_url_not_its_slug():
    amat = "https://amat.wd1.myworkdayjobs.com/External"
    with _db.SessionLocal() as db:
        assert board_sync.track_company(db, "workday", "appliedmaterials", "fortune500",
                                        boards=[amat], name="Applied Materials")
        # Simplify later finds the same site under the vendor's id, in other case
        assert not board_sync.track_company(db, "workday", "amat", "simplify",
                                            boards=["https://AMAT.wd1.myworkdayjobs.com/external/"], name="AMAT")
        assert not board_sync.track_company(db, "workday", "amat", "simplify",
                                            boards=["https://amat.wd1.myworkdayjobs.com/University"])
        db.commit()
    assert _rows() == {"appliedmaterials": ("workday", [amat, "https://amat.wd1.myworkdayjobs.com/University"],
                                            "Applied Materials")}


def test_a_parked_slug_is_taken_over_only_by_a_vendor_the_move_check_cannot_probe():
    past = NOW - timedelta(days=1)
    with _db.SessionLocal() as db:
        db.add_all([TrackedCompany(slug="acme", provider="greenhouse", gone_at=past,
                                   next_check_at=NOW + timedelta(days=6)),
                    TrackedCompany(slug="live", provider="greenhouse"),
                    TrackedCompany(slug="park", provider="greenhouse", gone_at=past)])
        db.commit()
        assert board_sync.track_company(db, "workday", "acme", "simplify", boards=[WD], name="Acme")
        # a live Greenhouse "live" is another company: the Workday one is tracked apart
        assert board_sync.track_company(db, "workday", "live", "simplify",
                                        boards=["https://live.wd1.myworkdayjobs.com/x"], name="Live Corp")
        assert not board_sync.track_company(db, "workday", "live", "simplify",  # its host dedupes it
                                            boards=["https://live.wd1.myworkdayjobs.com/y"])
        assert not board_sync.track_company(db, "lever", "park", "simplify")  # the move check's job (T28)
        db.commit()
        acme = db.get(TrackedCompany, "acme")
        assert (acme.provider, acme.boards, acme.name, acme.gone_at, acme.next_check_at) == \
            ("workday", [WD], "Acme", None, None)
    assert _rows()["live"] == ("greenhouse", None, None)
    assert _rows()["live.workday"] == ("workday", ["https://live.wd1.myworkdayjobs.com/x",
                                                   "https://live.wd1.myworkdayjobs.com/y"], "Live Corp")
    assert _rows()["park"] == ("greenhouse", None, None)


def test_the_curated_list_is_valid_and_seeding_it_is_idempotent(monkeypatch):
    monkeypatch.setattr(board_sync, "F500_BOARDS", REAL_F500)
    slugs = [slug for _, slug, _, _ in board_sync.F500_BOARDS]
    assert len(slugs) == len(set(slugs)) == 47
    for provider, slug, name, boards in board_sync.F500_BOARDS:
        assert provider in board_sync.FETCHERS and board_sync._SLUG_OK.fullmatch(slug) and name
        assert bool(boards) == (provider in board_sync.NEEDS_BOARDS), slug
        for board in boards or []:
            jd_adapters.by_name(provider).board(board)  # raises if it is not one
    with _db.SessionLocal() as db:
        board_sync.track_f500(db)
        first = _rows()
        board_sync.track_f500(db)
    assert _rows() == first and len(first) == 47
    assert first["salesforce"][1] == ["https://salesforce.wd12.myworkdayjobs.com/External_Career_Site",
                                      "https://salesforce.wd12.myworkdayjobs.com/Futureforce_NewGradRoles"]


def test_discovery_finds_workday_and_oracle_boards_and_nothing_else():
    text = " ".join([
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA/SWE_JR1",
        "https://nvidia.wd5.myworkdayjobs.com/nvidiaexternalcareersite/job/US-CA/SWE_JR2",  # same site
        "https://wd5.myworkdaysite.com/recruiting/chewy/External/job/Bellevue-WA/SWE_R1",
        "https://wd1.myworkdaysite.com/en-US/recruiting/wf/WellsFargoJobs/job/x",
        "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26013679",
        "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/x/jobs",  # the API, not a site
        "https://nvidia.wd5.myworkdayjobs.com/",
        "https://evil.com/nvidia.wd5.myworkdayjobs.com/x/job/y",
        "https://nvidia.wd5.myworkdayjobs.com.evil.com/x/job/y",
        "https://x.fa.oraclecloud.com.evil.com/hcmUI/CandidateExperience/en/sites/CX/job/1",
        "https://jobs.lever.co/acme/1",
    ])
    assert board_sync.discover_boards(text) == [
        ("workday", "nvidia", "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"),
        ("workday", "chewy", "https://chewy.wd5.myworkdayjobs.com/External"),
        ("workday", "wf", "https://wf.wd1.myworkdayjobs.com/WellsFargoJobs"),
        ("oracle", "egug", "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1"),
    ]
    assert board_sync.discover_slugs("https://jobs.smartrecruiters.com/ServiceNow/744000149338366 "
                                     "https://jobs.smartrecruiters.com/oneclick-ui/company/x") == \
        [("smartrecruiters", "servicenow")]


def test_the_simplify_scout_tracks_boards_with_their_company_names():
    listings = [
        {"active": True, "company_name": "Applied Materials",
         "url": "https://amat.wd1.myworkdayjobs.com/External/job/x/y_R2"},
        {"active": True, "company_name": " Applied Materials ",
         "url": "https://amat.wd1.myworkdayjobs.com/External/job/x/y_R1"},
        {"active": True, "company_name": "American Express",
         "url": "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/1"},
        {"active": False, "company_name": "Old", "url": "https://old.wd1.myworkdayjobs.com/External/job/x/y"},
        {"active": True, "company_name": None, "url": "https://jobs.lever.co/acme/1"},
        {"active": True, "company_name": "ServiceNow",
         "url": "https://jobs.smartrecruiters.com/ServiceNow/744000149338366"},
    ]

    class Resp:
        status_code = 200
        def json(self): return listings

    class Client:
        async def get(self, url): return Resp()
    with _db.SessionLocal() as db:
        assert run(board_sync._scout_github(Client(), db)) == 4
    assert _rows() == {
        "amat": ("workday", ["https://amat.wd1.myworkdayjobs.com/External"], "Applied Materials"),
        "egug": ("oracle", ["https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1"],
                 "American Express"),
        "acme": ("lever", None, None),
        "servicenow": ("smartrecruiters", None, "ServiceNow")}


def test_the_move_check_only_probes_vendors_that_404_unknown_slugs():
    seen = []
    with _db.SessionLocal() as db:
        db.add(TrackedCompany(slug="acme", provider="greenhouse"))
        db.commit()
        company = db.get(TrackedCompany, "acme")
        assert run(board_sync.sync_company_jobs(db, company, client(lambda *a: (404, {}, {}), seen))) == 0
    assert [u.split("/")[2] for _, u, _ in seen] == ["boards-api.greenhouse.io", "api.lever.co", "api.ashbyhq.com"]


def test_board_sync_builds_no_vendor_url_itself():
    """T18: endpoint knowledge lives in jd_adapters only."""
    from pathlib import Path
    src = Path(board_sync.__file__).read_text()
    for host in ("smartrecruiters.com/v1", "jobs.smartrecruiters.com/", "wday/cxs", "hcmRestApi", "api/pcsx",
                 "search.json", "jobs.apple.com/en-us", "api/v1/widget", "api/v2/accounts", "in_iframe",
                 "/sitemap.xml", "/robots.txt"):
        assert host not in src, host


def test_the_feed_names_the_company(monkeypatch):
    with _db.SessionLocal() as db:
        db.add_all([TrackedCompany(slug="appliedmaterials", provider="workday", name="Applied Materials"),
                    TrackedCompany(slug="plain", provider="greenhouse")])
        db.add_all([JobPosting(url="https://a/1", company_slug="appliedmaterials", title="SWE", created_at=NOW),
                    JobPosting(url="https://a/2", company_slug="plain", title="SWE",
                               created_at=NOW - timedelta(hours=1)),
                    JobPosting(url="https://a/3", company_slug="orphan", title="SWE",
                               created_at=NOW - timedelta(hours=2))])
        db.commit()
    jobs = TestClient(app).get("/board").json()["jobs"]
    assert [(j["company_slug"], j["company_name"], j["date_only"]) for j in jobs] == [
        ("appliedmaterials", "Applied Materials", True), ("plain", None, False), ("orphan", None, False)]


def test_workday_lanes_share_the_work_but_never_a_board(monkeypatch):
    for i in range(6):
        _workday_company(slug=f"t{i}", boards=[f"https://t{i}.wd1.myworkdayjobs.com/x"])
    calls, live, peak = [], 0, 0

    async def fetch(slug, client, boards):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        calls.append(slug)
        await REAL_SLEEP(0.01)
        live -= 1
        return []
    monkeypatch.setitem(board_sync.FETCHERS, "workday", fetch)
    monkeypatch.setattr(board_sync, "JITTER", (0, 0))
    run(board_sync._harvest_cycle())
    assert sorted(calls) == [f"t{i}" for i in range(6)]  # each board once
    assert peak == 3  # three at a time


@pytest.mark.parametrize("entry", ["_harvest_cycle", "harvester_loop"])
def test_both_harvest_entry_points_seed_the_curated_boards(monkeypatch, entry):
    monkeypatch.setattr(board_sync, "F500_BOARDS", [("amazon", "amazon", "Amazon", None)])

    async def idle(*a, **k):
        return None
    monkeypatch.setattr(board_sync, "_vendor_worker", idle)
    monkeypatch.setattr(board_sync, "_worker_forever", idle)
    run(getattr(board_sync, entry)())
    assert _rows()["amazon"] == ("amazon", None, "Amazon")  # beside the empty-DB seeds


@pytest.mark.parametrize("location, country, kept", [
    ("TUN - ARIANA", "TN", False),                     # no rule knows "TUN"; the vendor does
    ("SGP Work-at-Home", "SG", False),
    ("3325 Fort George G. Meade MD", "US", True),      # no comma before MD, so no rule reads it
    ("CAN - Toronto Office", "CA", True),
    ("Taipei | Austin, TX", "TW", True),               # any-valid-wins still holds
    ("Tunis, TN", "TN", False),                        # TN is Tunisia here, not Tennessee
    ("Tunis, TN | Nashville, TN", "TN", True),
    (None, "TW", False),
    ("TUN - ARIANA", None, True),                      # no country stated: unknown is still kept
])
def test_a_stated_country_settles_an_unreadable_location(location, country, kept):
    assert board_sync.is_target_location(location, country) is kept


def test_workday_drops_a_job_whose_code_hides_a_foreign_country():
    _workday_company()
    rows = wd_jobs(1, loc="TUN - ARIANA") + wd_jobs(1, 1, loc="3325 Fort George G. Meade MD")
    countries = {"R0": "TN", "R1": "US"}

    def detail(url):
        job = url.rsplit("_", 1)[-1]
        return 200, {"jobPostingInfo": {"location": job, "jobRequisitionLocation": {
            "country": {"alpha2Code": countries[job]}}}}, {}
    assert _sync(workday({"External": workday_site(rows)}, detail)) == 1
    assert list(_postings()) == [f"{WD}/job/Austin/SWE_R1"]


def test_workday_names_a_job_listed_with_no_location():
    # Accenture lists every row with locationsText null (2026-09-28): 531 jobs in
    # India, Mexico, Poland reached the Board with no location shown.
    _workday_company()
    rows = wd_jobs(1, loc=None) + wd_jobs(1, 1, loc="") + wd_jobs(1, 2, loc="   ") + wd_jobs(1, 3, loc=None)
    rows[3].pop("locationsText")
    places = {"R0": ("Pune", "IN"), "R1": ("Mexico City", "MX"), "R2": ("US, NY, New York", "US"),
              "R3": ("Toronto", "CA")}

    def detail(url):
        place, country = places[url.rsplit("_", 1)[-1]]
        return 200, {"jobPostingInfo": {"location": place, "jobRequisitionLocation": {
            "country": {"alpha2Code": country}}}}, {}
    assert _sync(workday({"External": workday_site(rows)}, detail)) == 2
    with _db.SessionLocal() as db:
        stored = {p.url: p.location for p in db.scalars(select(JobPosting))}
    assert stored == {
        f"{WD}/job/Austin/SWE_R2": "US, NY, New York", f"{WD}/job/Austin/SWE_R3": "Toronto"}


def test_chip_and_defense_hardware_roles_stay_off_the_board():
    # every one seen live on the new Workday/Oracle boards (2026-09-24)
    for t in ["Associate Analog Design Engineer", "Digital IC Design Engineer - USB Products",
              "IC Validation Engineer Intern, MS - Summer 2027", "GaN Process Integration Engineer (SM1)",
              "AMS Layout Engineer Intern - BS - 2027 Co-Op", "Hypersonics Design Engineer",
              "FTAP Missile Launcher Design Engineer", "Weapons / Munitions Systems Engineer",
              "Space Suit Design Engineer", "Product Install Engineer - Chemical Analysis (80% Travel)",
              "Power Delivery Engineering Intern", "Radar Research Engineer", "Naval Systems Engineer"]:
        assert board_sync.is_target_role(t) is False, t
    for t in ["Software Engineer, Radar Perception", "Embedded Software Engineer", "Design Engineer",
              "Software Engineer - Installer and Updates", "Systems Engineer", "Firmware Engineer Intern",
              "Modeling and Simulation Software Engineer", "HPC Systems Engineer"]:
        assert board_sync.is_target_role(t) is True, t


@pytest.mark.parametrize("total", ["45", -1, 4.5, True, [1]])
def test_a_malformed_total_is_a_vendor_error_not_our_bug(total):
    page = {"total": total, "jobPostings": wd_jobs(1)}
    with pytest.raises(ValueError):
        run(board_sync.fetch_workday("acme", client(lambda *a: (200, page, {})), [WD]))


def test_a_missing_total_reads_one_page_only():
    # Workday sends total on page 1 only; its absence there must not loop
    seen = []
    jobs = run(board_sync.fetch_workday("acme", client(lambda *a: (200, {"jobPostings": wd_jobs(20)}, {}), seen), [WD]))
    assert len(jobs) == 20 and len(seen) == 1



def test_a_workday_outage_is_never_read_as_a_move_to_another_vendor():
    # "intel" on Greenhouse would be some other company's board
    _workday_company(slug="intel", boards=["https://intel.wd1.myworkdayjobs.com/External"])
    probed = []

    def handler(method, url, body):
        probed.append(url.split("/")[2])
        return (404, {}, {}) if method == "POST" else (200, {"jobs": []}, {})
    assert _sync(handler, slug="intel") == 0
    assert probed == ["intel.wd1.myworkdayjobs.com"]  # no Greenhouse/Lever/Ashby probe
    with _db.SessionLocal() as db:
        company = db.get(TrackedCompany, "intel")
        assert (company.provider, company.gone_at) == ("workday", NOW)  # parked, not moved


def test_an_undated_workday_row_takes_its_date_from_the_detail():
    # 6 of 315 sites send no postedOn (or a location in its place)
    _workday_company()
    rows = wd_jobs(1, posted=None) + wd_jobs(1, 1, posted="Tempe, AZ") + wd_jobs(1, 2, posted=None, title="Recruiter")
    starts, details = {"R0": "2026-09-22", "R1": "2026-08-01"}, []

    def detail(url):
        details.append(url)
        job = url.rsplit("_", 1)[-1]
        return 200, {"jobPostingInfo": {"location": "Austin, TX", "startDate": starts[job]}}, {}
    assert _sync(workday({"External": workday_site(rows)}, detail)) == 1  # R1 is 54 days old
    assert _postings() == {f"{WD}/job/Austin/SWE_R0": ("open", NOW - timedelta(days=2))}
    assert len(details) == 2  # never for the recruiter


@pytest.mark.parametrize("fetch, payload", [
    ("fetch_oracle", oracle_page([{**reqs(1)[0], "PrimaryLocation": "Tunis, TN", "PrimaryLocationCountry": "TN",
                                   "secondaryLocations": []}], 1)),
    ("fetch_smartrecruiters", {"totalFound": 1, "content": [
        {**sr_jobs(1)[0], "location": {"fullLocation": "Ariana, Tunisia", "country": "tn"}}]}),
])
def test_oracle_and_smartrecruiters_countries_settle_the_location(fetch, payload):
    args = [[OR]] if fetch == "fetch_oracle" else []
    jobs = run(getattr(board_sync, fetch)("acme", client(lambda *a: (200, payload, {})), *args))
    assert jobs[0]["country"] == "TN"
    assert board_sync.is_target_location(jobs[0]["location"], jobs[0]["country"]) is False


def test_a_posting_closing_mid_read_makes_the_read_partial():
    # 45 when page 1 was read; one closes before page 2, so R20 shifts onto page 1's edge
    jobs = wd_jobs(45)
    later = jobs[:19] + jobs[20:]

    def handler(method, url, body):
        rows, total = (jobs, 45) if body["offset"] == 0 else (later, 0)
        return 200, {"total": total, "jobPostings": rows[body["offset"]:body["offset"] + 20]}, {}
    read = run(board_sync.fetch_workday("acme", client(handler), [WD]))
    assert isinstance(read, board_sync.Partial) and f"{WD}/job/Austin/SWE_R20" not in {j["url"] for j in read}


def test_an_empty_page_before_the_total_makes_the_read_partial():
    handler = lambda m, u, body: (200, {"total": 45 if body["offset"] == 0 else 0,
                                        "jobPostings": wd_jobs(20) if body["offset"] == 0 else []}, {})
    assert isinstance(run(board_sync.fetch_workday("acme", client(handler), [WD])), board_sync.Partial)


def test_an_unidentifiable_workday_row_is_skipped_and_closes_nothing():
    rows = wd_jobs(2) + [{"bulletFields": ["R170010"]}]  # seen live on Adobe's board
    jobs = run(board_sync.fetch_workday("acme", client(workday({"External": workday_site(rows)})), [WD]))
    assert [j["url"] for j in jobs] == [f"{WD}/job/Austin/SWE_R0", f"{WD}/job/Austin/SWE_R1"]
    assert isinstance(jobs, board_sync.Partial)


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("slow"), httpx.ConnectError("reset")])
def test_a_transient_failure_mid_read_retries_the_page(harness, failure):
    site, calls = workday_site(wd_jobs(25)), []

    def handler(method, url, body):
        calls.append(body["offset"])
        if calls.count(20) == 1 and body["offset"] == 20:
            raise failure  # seen live: one ReadTimeout failed Micron's whole read
        return 200, site(body["offset"]), {}
    assert len(run(board_sync.fetch_workday("acme", client(handler), [WD]))) == 25
    assert calls == [0, 20, 20] and 15 in harness


def test_a_client_error_mid_read_is_not_retried(harness):
    seen = []
    handler = lambda m, u, body: (200, workday_site(wd_jobs(25))(0), {}) if body["offset"] == 0 else (400, {}, {})
    with pytest.raises(httpx.HTTPStatusError):
        run(board_sync.fetch_workday("acme", client(handler, seen), [WD]))
    assert [body["offset"] for _, _, body in seen] == [0, 20] and 15 not in harness  # asked once, no backoff


@pytest.mark.parametrize("build", [
    lambda: jd_adapters.by_name("amazon").job_url("@evil.com/x"),
    lambda: jd_adapters.by_name("workday").job_url(WD, "@evil.com/job/x"),
    lambda: jd_adapters.by_name("workday").job_url(WD, "/../../evil"),
])
def test_vendor_data_cannot_steer_a_job_link_off_its_host(build):
    with pytest.raises(ValueError):
        build()


def test_ids_are_escaped_into_job_links():
    assert jd_adapters.by_name("apple").job_url("../x?y") == "https://jobs.apple.com/en-us/details/..%2Fx%3Fy"
    assert jd_adapters.by_name("oracle").job_url(OR, "1/2") == f"{OR}/job/1%2F2"


def test_apple_data_survives_a_quote_and_paren_in_a_job_text():
    state = {"loaderData": {"search": {"searchResults": [{"postingTitle": 'Say "hi"); now'}], "totalRecords": 1}}}
    page = f"<script>x.__staticRouterHydrationData = JSON.parse({json.dumps(json.dumps(state))});</script>"
    assert jd_adapters.apple_data(page)["search"]["searchResults"][0]["postingTitle"] == 'Say "hi"); now'


def test_a_curated_companys_other_vendor_board_is_not_tracked_twice():
    with _db.SessionLocal() as db:
        board_sync.track_company(db, "eightfold", "paypal", "fortune500", name="PayPal",
                                 boards=["https://paypal.eightfold.ai/careers?domain=paypal.com"])
        # found live by Serper: PayPal's old Workday site lists the same jobs
        assert not board_sync.track_company(db, "workday", "paypal", "serper",
                                            boards=["https://paypal.wd1.myworkdayjobs.com/jobs"])
        db.commit()
    assert set(_rows()) == {"paypal"} and _rows()["paypal"][0] == "eightfold"


def test_a_parked_curated_company_is_never_taken_over():
    # e.g. Workday Inc's sites briefly gone, then a SmartRecruiters link with slug "workday"
    with _db.SessionLocal() as db:
        board_sync.track_company(db, "workday", "workday", "fortune500", name="Workday",
                                 boards=["https://workday.wd5.myworkdayjobs.com/Workday_Jobs"])
        db.get(TrackedCompany, "workday").gone_at = NOW
        assert not board_sync.track_company(db, "smartrecruiters", "workday", "simplify")
        db.commit()
    assert _rows()["workday"][0] == "workday"


# --- T37: Workable ------------------------------------------------------------

def wk_rows(*rows):
    return {"name": "Acme", "jobs": [
        {"title": t, "shortcode": sc, "published_on": day, "city": "", "state": "", "country": "",
         "locations": [{"city": c, "region": r, "country": n, "countryCode": cc, "hidden": False}
                       for c, r, n, cc in spots]} for t, sc, day, spots in rows]}


def test_workable_merges_a_job_listed_once_per_location():
    # live: charlotte-tilbury lists 301 rows for 270 jobs, one row per location
    ny, sf = ("New York", "New York", "United States", "US"), ("San Francisco", "California", "United States", "US")
    ldn = ("London", "England", "United Kingdom", "GB")
    data = wk_rows(("Software Engineer", "AAA1", "2026-09-22", [ny, sf]),
                   ("Software Engineer", "AAA1", "2026-09-22", [ny, sf]),
                   ("Data Engineer", "BBB2", "2026-09-20", [ny]), ("Data Engineer", "BBB2", "2026-09-20", [ldn]))
    seen = []
    jobs = run(board_sync.fetch_workable("acme", client(lambda *a: (200, data, {}), seen)))
    assert seen == [("GET", "https://apply.workable.com/api/v1/widget/accounts/acme", None)]
    assert jobs == [
        {"title": "Software Engineer", "location": "New York, New York, United States | San Francisco, California, "
         "United States", "url": "https://apply.workable.com/acme/j/AAA1/",
         "published_at": (NOW - timedelta(days=2)).isoformat(), "country": "US"},
        {"title": "Data Engineer", "location": "New York, New York, United States | London, England, United Kingdom",
         "url": "https://apply.workable.com/acme/j/BBB2/", "published_at": (NOW - timedelta(days=4)).isoformat(),
         "country": None},  # two countries: the location text decides, any-valid-wins
    ]


def test_an_unknown_workable_account_is_gone_but_workable_is_not_a_move_target():
    assert run(board_sync.fetch_workable("nosuch", client(lambda *a: (404, {}, {})))) is None  # verified live
    # 15 of 16 parked slugs Workable knew were dormant 0-job accounts (2026-09-25)
    assert "workable" not in board_sync.MOVABLE and "workable" in board_sync.DATE_ONLY


def test_a_workable_job_missing_from_its_account_closes():
    with _db.SessionLocal() as db:
        db.add(TrackedCompany(slug="acme", provider="workable"))
        db.commit()
    us = ("Austin", "Texas", "United States", "US")
    both = wk_rows(("Software Engineer", "AAA1", "2026-09-22", [us]), ("Backend Engineer", "BBB2", "2026-09-22", [us]))
    assert _sync(lambda *a: (200, both, {})) == 2
    assert _sync(lambda *a: (200, wk_rows(("Software Engineer", "AAA1", "2026-09-22", [us])), {})) == 1
    assert _postings()["https://apply.workable.com/acme/j/BBB2/"][0] == "closed"


# --- T37: iCIMS ---------------------------------------------------------------

IC = "https://careers-acme.icims.com"


def ic_sitemap(*jobs):
    urls = "".join(f"<url><loc>{IC}/jobs/{jid}/{slug}/job</loc><lastmod>{lm}</lastmod></url>" for jid, slug, lm in jobs)
    return f"<?xml version='1.0'?><urlset><url><loc>{IC}/jobs/intro</loc></url>{urls}</urlset>".encode()


def ic_page(title, day="2026-09-22", where=(("Austin", "TX", "US"),), posted=None):
    posting = {"@context": "http://schema.org", "@type": "JobPosting", "title": title, "description": "<p>Build</p>",
               "datePosted": posted or f"{day}T04:00:00.000Z", "jobLocation": [
                   {"@type": "Place", "address": {"addressLocality": c, "addressRegion": r, "addressCountry": n}}
                   for c, r, n in where]}
    return f'<html><script type="application/ld+json">{json.dumps(posting)}</script></html>'.encode()


def icims(robots=b"User-agent: *\nDisallow: /jobs/login\n", sitemap=b"", pages=None):
    def handler(method, url, body):
        if url.endswith("/robots.txt"):
            return 200, robots, {}
        if url.endswith("/sitemap.xml"):
            return 200, sitemap, {}
        answer = (pages or {}).get(url.split("/jobs/")[1].split("/")[0])
        return answer if isinstance(answer, tuple) else (200, answer, {})
    return handler


def test_icims_reads_only_likely_target_roles_from_their_own_page(harness):
    recent, old = "2026-09-23T10:00:00-04:00", "2026-07-01T10:00:00-04:00"  # the window is 14 + 30 days
    sitemap = ic_sitemap(("1", "software-engineer", recent), ("2", "accountant", recent),
                         ("3", "software-engineer-ii", old), ("4", "backend-developer%2c-platform", recent))
    seen = []
    pages = {"1": ic_page("Software Engineer"),
             "4": ic_page("Backend Developer, Platform", where=(("Pune", "MH", "IN"),))}
    jobs = run(board_sync.fetch_icims("careers-acme", client(icims(sitemap=sitemap, pages=pages), seen), [IC]))
    assert [u for _, u, _ in seen] == [f"{IC}/robots.txt", f"{IC}/sitemap.xml",
                                       f"{IC}/jobs/1/software-engineer/job?in_iframe=1",
                                       f"{IC}/jobs/4/backend-developer%2c-platform/job?in_iframe=1"]
    assert jobs[0] == {"title": "Software Engineer", "location": "Austin, TX, US", "country": "US",
                       "published_at": (NOW - timedelta(days=2)).isoformat(),
                       "url": f"{IC}/jobs/1/software-engineer/job"}
    assert jobs[1] == {"title": "accountant", "location": None, "published_at": None,
                       "url": f"{IC}/jobs/2/accountant/job"}  # seen, never stored
    assert jobs[2]["published_at"] is None  # a target title untouched for 44+ days is not fetched
    assert jobs[3]["country"] == "IN"
    assert 1.0 in harness  # the polite gap before each page


def test_an_icims_portal_that_forbids_us_is_never_fetched():
    seen = []
    handler = icims(robots=b"User-agent: *\nDisallow: /\n",
                    sitemap=ic_sitemap(("1", "software-engineer", "2026-09-23")))
    assert run(board_sync.fetch_icims("careers-acme", client(handler, seen), [IC])) is None  # 3 of 70 live ones
    assert [u for _, u, _ in seen] == [f"{IC}/robots.txt"]


def test_icims_honours_crawl_delay_and_rereads_robots_daily(harness, monkeypatch):
    handler = icims(robots=b"User-agent: *\nCrawl-delay: 7\n",
                    sitemap=ic_sitemap(("1", "software-engineer", "2026-09-23T10:00:00-04:00")),
                    pages={"1": ic_page("Software Engineer")})
    seen = []
    run(board_sync.fetch_icims("careers-acme", client(handler, seen), [IC]))
    assert 7 in harness
    run(board_sync.fetch_icims("careers-acme", client(handler, seen), [IC]))
    assert [u for _, u, _ in seen].count(f"{IC}/robots.txt") == 1  # cached within a day
    monkeypatch.setattr(board_policy, "utcnow", lambda: NOW + timedelta(days=1, minutes=1))
    run(board_sync.fetch_icims("careers-acme", client(handler, seen), [IC]))
    assert [u for _, u, _ in seen].count(f"{IC}/robots.txt") == 2


def test_an_icims_job_that_closed_since_the_sitemap_is_dropped_and_a_page_without_json_ld_is_undated():
    sitemap = ic_sitemap(("1", "software-engineer", "2026-09-23"), ("2", "data-engineer", "2026-09-23"))
    pages = {"1": (410, b"", {}), "2": b"<html>no posting here</html>"}
    jobs = run(board_sync.fetch_icims("careers-acme", client(icims(sitemap=sitemap, pages=pages)), [IC]))
    assert [(j["url"].split("/jobs/")[1], j["published_at"]) for j in jobs] == [("2/data-engineer/job", None)]


def test_icims_ignores_other_hosts_and_pages_in_a_sitemap():
    sitemap = (b"<urlset><url><loc>https://evil.icims.com/jobs/9/software-engineer/job</loc></url>"
               b"<url><loc>" + IC.encode() + b"/jobs/search?pr=0</loc></url></urlset>")
    assert run(board_sync.fetch_icims("careers-acme", client(icims(sitemap=sitemap)), [IC])) == []


def test_icims_detail_is_cached_by_url():
    seen = []
    handler = icims(sitemap=ic_sitemap(("1", "software-engineer", "2026-09-23")),
                    pages={"1": ic_page("Software Engineer")})
    run(board_sync.fetch_icims("careers-acme", client(handler, seen), [IC]))
    run(board_sync.fetch_icims("careers-acme", client(handler, seen), [IC]))
    assert sum("in_iframe" in u for _, u, _ in seen) == 1


def test_an_icims_board_stores_its_target_roles_and_closes_by_absence():
    with _db.SessionLocal() as db:
        db.add(TrackedCompany(slug="careers-acme", provider="icims", boards=[IC]))
        db.commit()
    pages = {"1": ic_page("Software Engineer"), "2": ic_page("Backend Engineer")}
    both = icims(sitemap=ic_sitemap(("1", "software-engineer", "2026-09-23"), ("2", "backend-engineer", "2026-09-23")),
                 pages=pages)
    assert _sync(both, slug="careers-acme") == 2
    one = icims(sitemap=ic_sitemap(("1", "software-engineer", "2026-09-23")), pages=pages)
    assert _sync(one, slug="careers-acme") == 1
    assert _postings()[f"{IC}/jobs/2/backend-engineer/job"][0] == "closed"


def test_t37_discovery_and_serper_sites():
    text = ("https://apply.workable.com/tickpick/j/5840ECEB50/apply https://apply.workable.com/api/v1/widget "
            "https://careers-gdms.icims.com/jobs/71647/junior-full-stack-engineer/job "
            "https://www.icims.com/jobs/1/x/job https://careers-gdms.icims.com/connect")
    assert ("workable", "tickpick") in board_sync.discover_slugs(text)
    assert not any(s == "api" for _, s in board_sync.discover_slugs(text))
    assert board_sync.discover_boards(text) == [("icims", "careers-gdms", "https://careers-gdms.icims.com")]
    assert {"apply.workable.com", "icims.com"} <= set(board_sync.SERPER_SITES)


@pytest.mark.parametrize("body", [b"<html>Service Unavailable</html>",
                                  b"<sitemapindex><sitemap><loc>x</loc></sitemap></sitemapindex>"])
def test_an_icims_sitemap_that_is_not_a_urlset_closes_nothing(body):
    with pytest.raises(ValueError):
        run(board_sync.fetch_icims("careers-acme", client(icims(sitemap=body)), [IC]))
    # a real empty portal is a urlset holding only its intro page, and reads as no jobs
    assert run(board_sync.fetch_icims("careers-acme", client(icims(sitemap=ic_sitemap())), [IC])) == []


def test_a_workable_location_the_employer_hid_is_neither_shown_nor_used():
    data = {"jobs": [{"title": "Software Engineer", "shortcode": "AAA1", "published_on": "2026-09-22", "locations": [
        {"city": "Austin", "region": "Texas", "country": "United States", "countryCode": "US", "hidden": False},
        {"city": "", "region": None, "country": "Germany", "countryCode": "DE", "hidden": True}]}]}
    job, = run(board_sync.fetch_workable("acme", client(lambda *a: (200, data, {}))))
    assert (job["location"], job["country"]) == ("Austin, Texas, United States", "US")


def test_an_icims_page_without_json_ld_is_asked_again_next_time():
    # it may have been a passing error page; the real posting must not be lost until a restart
    seen = []
    handler = icims(sitemap=ic_sitemap(("1", "software-engineer", "2026-09-23")),
                    pages={"1": b"<html>maintenance</html>"})
    run(board_sync.fetch_icims("careers-acme", client(handler, seen), [IC]))
    later = icims(sitemap=ic_sitemap(("1", "software-engineer", "2026-09-23")),
                  pages={"1": ic_page("Software Engineer")})
    job, = run(board_sync.fetch_icims("careers-acme", client(later, seen), [IC]))
    assert job["title"] == "Software Engineer" and job["published_at"] is not None
    assert sum("in_iframe" in u for _, u, _ in seen) == 2


# T41: 21 of 95 live portals send the moment of the request minus 2 years
FAKE = f"{NOW - timedelta(days=730):%Y-%m-%dT%H:%M:%S}.000Z"


def test_a_faked_icims_post_date_is_never_read_as_a_date():
    ic = jd_adapters.by_name("icims")
    for now, fake in [(NOW, NOW - timedelta(days=730)),                       # no Feb 29 in between
                      (datetime(2026, 1, 15), datetime(2024, 1, 15)),          # 731 days: Feb 29 2024 between
                      (NOW, NOW - timedelta(days=730) + timedelta(seconds=1.5)),  # their clock ahead (seen live)
                      (NOW, NOW - timedelta(days=730) - timedelta(minutes=59))]:
        assert ic.faked({"datePosted": f"{fake:%Y-%m-%dT%H:%M:%S.%f}Z"}, now), (now, fake)
    for real in [f"{NOW - timedelta(days=730, hours=2):%Y-%m-%dT%H:%M:%S}Z", "2026-09-22T04:00:00.000Z",
                 "2024-09-24T12:00:00+05:00", None, "", "not a date"]:  # +05:00 is 07:00 UTC, 5 h off
        assert not ic.faked({"datePosted": real}, NOW), real


def _icims_ids(sitemap, pages):
    jobs = run(board_sync.fetch_icims("careers-acme", client(icims(sitemap=sitemap, pages=pages)), [IC]))
    return {j["url"].split("/jobs/")[1].split("/")[0]: j["published_at"] for j in jobs}


def test_a_faked_icims_date_falls_back_to_lastmod_only_for_ids_newer_than_the_portals_old_jobs():
    """A job cannot be edited before it exists, so one untouched for 14 days is
    old, and ids run in posting order: on 74 real portals this rule matched the
    true date at 85% precision; lastmod alone, 58% (edits move it)."""
    fresh, old = (NOW - timedelta(days=2)).isoformat(), (NOW - timedelta(days=14)).isoformat()
    late = "2026-09-22T22:00:00-04:00"  # 02:00 UTC on the 23rd: dated by its own day, like datePosted
    sitemap = ic_sitemap(("5", "accountant", old),                 # untouched for 14 days: an old job
                         ("9", "software-engineer", late),         # a newer id: posted since
                         ("3", "backend-engineer", fresh),         # an older id, edited lately
                         ("4", "data-engineer", fresh),            # an older id with a real date
                         ("8", "frontend-engineer", fresh))        # a newer id with a real date: kept
    pages = {"9": ic_page("Software Engineer", posted=FAKE), "3": ic_page("Backend Engineer", posted=FAKE),
             "4": ic_page("Data Engineer", day="2026-09-23"), "8": ic_page("Frontend Engineer", day="2026-09-23")}
    assert _icims_ids(sitemap, pages) == {"5": None, "9": (NOW - timedelta(days=2)).isoformat(), "3": None,
                                          "4": (NOW - timedelta(days=1)).isoformat(),
                                          "8": (NOW - timedelta(days=1)).isoformat()}
    # a page with no datePosted at all (0 of 1,530 on real portals) is read the same way
    board_sync._ICIMS_POSTINGS.clear()
    undated = {"9": ic_page("Software Engineer", posted=FAKE).replace(f'"datePosted": "{FAKE}", '.encode(), b"")}
    assert b"datePosted" not in undated["9"]
    assert _icims_ids(sitemap, undated)["9"] == (NOW - timedelta(days=2)).isoformat()
    # a sitemap row without lastmod (0 of 25,789 live) cannot be dated by it
    board_sync._ICIMS_POSTINGS.clear()
    no_lastmod = sitemap.replace(f"<loc>{IC}/jobs/9/software-engineer/job</loc><lastmod>{late}</lastmod>".encode(),
                                 f"<loc>{IC}/jobs/9/software-engineer/job</loc>".encode())
    assert no_lastmod != sitemap and _icims_ids(no_lastmod, pages)["9"] is None
    # no job untouched for 14 days, no way to tell new from edited: on 5 real portals so, 33 of 100 were new
    board_sync._ICIMS_POSTINGS.clear()
    assert _icims_ids(ic_sitemap(("9", "software-engineer", fresh)), pages) == {"9": None}


def test_a_faked_icims_job_is_stored_with_its_lastmod_day():
    with _db.SessionLocal() as db:
        db.add(TrackedCompany(slug="careers-acme", provider="icims", boards=[IC]))
        db.commit()
    fresh, old = (NOW - timedelta(days=2)).isoformat(), (NOW - timedelta(days=30)).isoformat()
    handler = icims(sitemap=ic_sitemap(("5", "accountant", old), ("9", "software-engineer", fresh),
                                       ("3", "backend-engineer", fresh)),
                    pages={"9": ic_page("Software Engineer", posted=FAKE), "3": ic_page("Backend Engineer", posted=FAKE)})
    assert _sync(handler, slug="careers-acme") == 1
    assert _postings() == {f"{IC}/jobs/9/software-engineer/job": ("open", NOW - timedelta(days=2))}


# T42: iCIMS writes "UNAVAILABLE" into empty address fields (31 of 95 portals in
# the city, 42 the region, 5 the country; 2,013 of 2,013 spelled exactly so).
NA = "UNAVAILABLE"


def test_icims_placeholder_and_multi_line_address_fields_are_cleaned():
    pages = {"1": ic_page("Software Engineer", where=(("Remote", NA, "US"),)),
             "2": ic_page("Backend Engineer", where=((NA, NA, "US"),)),
             "3": ic_page("Data Engineer", where=((NA, NA, NA),)),                 # Atlassian, GTS...: all of it
             "4": ic_page("Platform Engineer", where=((NA, NA, NA), ("Pune", "MH", "IN"))),
             "5": ic_page("Frontend Engineer",                                     # EMCOR 52752, verbatim
                          where=(("IA-Des Moines\nUS-IA-Des Moines\nUS-IA-Des Moines", NA, "US"),)),
             "6": ic_page("Web Developer", where=(("Norfolk-Norwich\xa0", NA, "UK"),)),
             "7": ic_page("ML Engineer", where=(("London", NA, "GB"), ("Amsterdam", NA, "NL"), (NA, NA, "NL")))}
    day = "2026-09-23"
    sitemap = ic_sitemap(*((i, slug, day) for i, slug in [
        ("1", "software-engineer"), ("2", "backend-engineer"), ("3", "data-engineer"), ("4", "platform-engineer"),
        ("5", "frontend-engineer"), ("6", "web-developer"), ("7", "ml-engineer")]))
    jobs = run(board_sync.fetch_icims("careers-acme", client(icims(sitemap=sitemap, pages=pages)), [IC]))
    got = {j["url"].split("/jobs/")[1].split("/")[0]: (j["location"], j["country"]) for j in jobs}
    assert got == {"1": ("Remote, US", "US"), "2": ("US", "US"), "3": (None, None),
                   "4": ("Pune, MH, IN", "IN"),  # a placeholder country no longer hides the real one
                   "5": ("IA-Des Moines / US-IA-Des Moines, US", "US"), "6": ("Norfolk-Norwich, UK", "UK"),
                   "7": ("London, GB | Amsterdam, NL | NL", "GB")}
    assert board_sync.is_target_location(*got["3"])      # no place at all: kept, as any unknown is
    assert not board_sync.is_target_location(*got["4"])
    # ", NL" next to placeholders read as Newfoundland and let this one in
    assert not board_sync.is_target_location(*got["7"])


def test_a_stored_icims_placeholder_location_is_rewritten_on_the_next_read():
    with _db.SessionLocal() as db:
        db.add(TrackedCompany(slug="careers-acme", provider="icims", boards=[IC]))
        db.add(JobPosting(url=f"{IC}/jobs/2/backend-engineer/job", company_slug="careers-acme", title="Backend Engineer",
                          location=f"{NA}, {NA}, US", status="open", created_at=NOW - timedelta(days=2), updated_at=NOW))
        db.commit()
    handler = icims(sitemap=ic_sitemap(("2", "backend-engineer", "2026-09-23")),
                    pages={"2": ic_page("Backend Engineer", where=((NA, NA, "US"),))})
    assert _sync(handler, slug="careers-acme") == 1
    with _db.SessionLocal() as db:
        assert db.get(JobPosting, f"{IC}/jobs/2/backend-engineer/job").location == "US"


def test_a_job_page_robots_forbids_is_not_fetched():
    seen = []
    handler = icims(robots=b"User-agent: *\nDisallow: /jobs/1/\n",
                    sitemap=ic_sitemap(("1", "software-engineer", "2026-09-23"), ("2", "data-engineer", "2026-09-23")),
                    pages={"1": ic_page("Software Engineer"), "2": ic_page("Data Engineer")})
    jobs = run(board_sync.fetch_icims("careers-acme", client(handler, seen), [IC]))
    assert not any("/jobs/1/" in u and "in_iframe" in u for _, u, _ in seen)
    assert [j["published_at"] is None for j in jobs] == [True, False]  # seen, but never read or stored


# --- T46: first sight and discovery delay ------------------------------------

def gh_board(*jobs):
    """A Greenhouse board: (id, title, first_published) per job."""
    return lambda m, u, b: (200, {"jobs": [{"id": i, "title": t, "location": {"name": "Austin, TX"},
                                            "first_published": p} for i, t, p in jobs]}, {})


def _first_seen():
    with _db.SessionLocal() as db:
        return {p.url.rsplit("/", 1)[1]: p.first_seen_at for p in db.scalars(select(JobPosting))}


def test_a_posting_records_when_we_first_saw_it_and_keeps_it(monkeypatch):
    with _db.SessionLocal() as db:
        db.add(TrackedCompany(slug="acme", provider="greenhouse"))
        db.commit()
    posted = (NOW - timedelta(hours=3)).isoformat()
    at = lambda hours: monkeypatch.setattr(board_policy, "utcnow", lambda: NOW + timedelta(hours=hours))
    assert _sync(gh_board((1, "Software Engineer", posted))) == 1
    assert _first_seen() == {"1": NOW}
    at(1)
    _sync(gh_board((1, "Software Engineer II", posted), (2, "Backend Engineer", posted)))  # retitled; a new one
    assert _first_seen() == {"1": NOW, "2": NOW + timedelta(hours=1)}
    at(2)
    _sync(gh_board((2, "Backend Engineer", posted)))                               # 1 leaves the board...
    at(3)
    _sync(gh_board((1, "Software Engineer II", posted), (2, "Backend Engineer", posted)))  # ...and comes back
    assert _postings()[f"{GH_JOB}1"][0] == "open"
    assert _first_seen() == {"1": NOW, "2": NOW + timedelta(hours=1)}               # first sight, never the latest
    at(4)
    _sync(gh_board((1, "Software Engineer II", (NOW - timedelta(days=30)).isoformat())))  # dated out: deleted
    assert "1" not in _first_seen()
    at(5)
    _sync(gh_board((1, "Software Engineer II", posted)))                           # date corrected: a new sight
    assert _first_seen()["1"] == NOW + timedelta(hours=5)


GH_JOB = "https://job-boards.greenhouse.io/acme/jobs/"


def _seen_row(slug, provider, jid, posted_ago, seen_ago):
    """A stored posting, posted and first seen that many minutes before NOW."""
    with _db.SessionLocal() as db:
        if db.get(TrackedCompany, slug) is None:
            db.add(TrackedCompany(slug=slug, provider=provider))
        db.add(JobPosting(url=f"https://x/{slug}/{jid}", company_slug=slug, title="Software Engineer", status="open",
                          created_at=NOW - timedelta(minutes=posted_ago), updated_at=NOW,
                          first_seen_at=None if seen_ago is None else NOW - timedelta(minutes=seen_ago)))
        db.commit()


def test_discovery_delay_counts_only_jobs_we_were_watching_for():
    """Minutes from posting to first sight, per vendor (nearest-rank p50/p95)."""
    day = 24 * 60
    _seen_row("a", "ashby", 0, 3 * day, 2 * day)    # on the board when we first read it: excluded
    for jid, delay in enumerate([10, 20, 30, 40, 1000], 1):
        _seen_row("a", "ashby", jid, day + delay, day)  # posted after we began watching
    _seen_row("w", "workday", 0, 3 * day, 2 * day)     # watched for 2 days, but date-only: its "posted"
    _seen_row("w", "workday", 1, 60, 0)                # is our own first sight, so no delay to measure
    _seen_row("a", "ashby", 6, day - 60, day)          # re-dated after we saw it (a repost): not a delay
    _seen_row("g", "greenhouse", 0, 30, None)          # stored before T46: no first sight recorded
    _seen_row("g", "greenhouse", 1, 9 * day, 9 * day - 5)  # first seen 9 days ago: outside 7
    _seen_row("g", "greenhouse", 2, 8 * day + 60, 8 * day)
    with _db.SessionLocal() as db:
        assert board_sync.discovery_delays(db, days=7) == {"days": 7, "vendors": {
            "ashby": {"jobs": 5, "p50_minutes": 30, "p95_minutes": 1000, "max_minutes": 1000}}}
        nine = board_sync.discovery_delays(db, days=9)["vendors"]
        assert nine["greenhouse"] == {"jobs": 1, "p50_minutes": 60, "p95_minutes": 60, "max_minutes": 60}
        assert "workday" not in nine


def test_no_measured_jobs_is_an_empty_report():
    with _db.SessionLocal() as db:
        assert board_sync.discovery_delays(db, days=7) == {"days": 7, "vendors": {}}


def test_the_delay_report_is_served_read_only():
    _seen_row("a", "ashby", 0, 3 * 24 * 60, 2 * 24 * 60)
    _seen_row("a", "ashby", 1, 24 * 60 + 15, 24 * 60)
    api = TestClient(app)
    r = api.get("/board/delays")
    assert r.status_code == 200 and r.json() == {"days": 7, "vendors": {
        "ashby": {"jobs": 1, "p50_minutes": 15, "p95_minutes": 15, "max_minutes": 15}}}
    assert [api.get(f"/board/delays?days={d}").status_code for d in (0, 15, 14)] == [422, 422, 200]
