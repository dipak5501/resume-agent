"""Board freshness and handoff contracts, exercised through the real API/DB.

conftest redirects all sessions to a fresh database for each test.
"""
import asyncio
import html
import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from app import db
from app.main import app
from app.models import JobPosting, TrackedCompany
from app.schemas.jd import JdSource
from app.services import board_policy, board_sync, jd_fetch

NOW = datetime(2026, 9, 20, 3, 0)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(board_policy, "utcnow", lambda: NOW)


def now():
    return board_policy.utcnow()


def posting(jid, age, *, status="open", title=None, location="Austin, TX", company="acme"):
    """A distinct title per jid unless given: the feed groups same-title openings."""
    with db.SessionLocal() as session:
        if session.get(TrackedCompany, company) is None:
            session.add(TrackedCompany(slug=company, provider="greenhouse"))
        url = f"https://job-boards.greenhouse.io/{company}/jobs/{jid}"
        session.add(JobPosting(url=url, company_slug=company, title=title or f"Software Engineer {jid}",
                               location=location, status=status, created_at=now() - age))
        session.commit()
    return url


def test_feed_filters_age_before_counting_and_paginating():
    recent = posting(1, timedelta(days=2))
    posting(2, timedelta(days=400))
    posting(3, timedelta(days=-1))
    posting(4, timedelta(days=1), status="closed")
    response = TestClient(app).get("/board?limit=1")
    assert response.status_code == 200
    assert [j["url"] for j in response.json()["jobs"]] == [recent]
    assert response.json()["total_pages"] == 1
    assert response.json()["has_more"] is False


def test_a_recent_edit_does_not_make_an_old_posting_eligible(monkeypatch):
    async def payload(*_):
        return {"jobs": [{"id": 1, "title": "Software Engineer",
                          "location": {"name": "Austin, TX"},
                          "updated_at": now().isoformat()}]}
    monkeypatch.setattr(board_sync, "_get_board", payload)
    with db.SessionLocal() as session:
        company = TrackedCompany(slug="acme", provider="greenhouse")
        session.add(company)
        session.commit()
        asyncio.run(board_sync.sync_company_jobs(session, company))
        assert session.query(JobPosting).count() == 0


def test_malformed_success_response_preserves_existing_postings(monkeypatch):
    url = posting(1, timedelta(days=1))
    async def payload(*_):
        return {"message": "unexpected response shape"}
    monkeypatch.setattr(board_sync, "_get_board", payload)
    with db.SessionLocal() as session:
        import pytest
        with pytest.raises(board_sync.BoardVendorError):
            asyncio.run(board_sync.sync_company_jobs(session, session.get(TrackedCompany, "acme")))
        session.rollback()
    with db.SessionLocal() as session:
        assert session.get(JobPosting, url).status == "open"


def test_exact_expiry_count_order_and_cleanup_ignore_last_seen():
    # Last-seen timestamps default to the real current time, but cannot extend age.
    keep = [posting(i, age) for i, age in enumerate([
        timedelta(0), timedelta(days=14, microseconds=-1), timedelta(days=3),
        timedelta(days=3),
    ])]
    remove = [posting(i + 10, age) for i, age in enumerate([
        timedelta(days=14), timedelta(days=14, microseconds=1),
        timedelta(microseconds=-1), timedelta(days=2000),
    ])]
    closed = posting(20, timedelta(days=1), status="closed")
    remove.append(posting(21, timedelta(days=15), status="closed"))
    client = TestClient(app)
    pages = [client.get(f"/board?page={p}&limit=2").json() for p in (1, 2, 3)]
    assert [j["url"] for p in pages for j in p["jobs"]] == [keep[0], keep[2], keep[3], keep[1]]
    assert [p["total_pages"] for p in pages] == [2, 2, 2]
    assert [p["has_more"] for p in pages] == [True, False, False]
    # Fingerprint all non-posting tables, including seeded profile/answer data.
    def other_tables():
        with db.engine.connect() as conn:
            return {table.name: list(conn.execute(select(table)))
                    for table in db.Base.metadata.sorted_tables if table.name != "job_postings"}
    before = other_tables()
    assert board_sync.cleanup_postings() == len(remove)
    assert board_sync.cleanup_postings() == 0
    assert before == other_tables()
    with db.SessionLocal() as session:
        assert {j.url for j in session.query(JobPosting)} == set(keep + [closed])


def test_one_card_per_role_counts_its_open_openings():
    # Crane posted JR102640/41/42: one Co-Op, three identical requisitions (2026-09-28).
    day = timedelta(days=1)
    newest = posting(1, day, title="Engineering Co-Op")
    posting(2, day * 2, title="engineering co-op ")      # case and edge spaces are noise
    posting(3, day * 3, title=" ENGINEERING CO-OP")
    posting(4, timedelta(0), title="Engineering Co-Op", status="closed")  # newer, but not on the Board
    posting(5, timedelta(days=20), title="Engineering Co-Op")             # stale
    posting(6, day * 4, title="Engineering Co-Op", location="austin, tx ")
    elsewhere = posting(7, day * 5, title="Engineering Co-Op", location="Plano, TX")
    other = posting(8, day * 6, title="Engineering Co-Op", company="globex")
    level = posting(9, day * 7, title="Engineering Co-Op II")
    unplaced = [posting(10, day * 8, title="Engineering Co-Op", location=None),
                posting(11, day * 9, title="Engineering Co-Op", location=None)]
    # Co-ops are internships, hidden unless the feed is asked to include them.
    body = TestClient(app).get("/board?include_interns=true").json()
    assert [(j["url"], j["openings"]) for j in body["jobs"]] == [
        (newest, 4), (elsewhere, 1), (other, 1), (level, 1), (unplaced[0], 2)]
    assert body["jobs"][0]["title"] == "Engineering Co-Op"  # the shown posting's own text


def test_the_feed_pages_by_card_not_by_posting():
    for i in range(3):
        posting(i, timedelta(days=1, hours=i), title="Engineering Co-Op")
    solo = posting(9, timedelta(days=2))
    client = TestClient(app)
    first, second = (client.get("/board?include_interns=true&limit=1").json(),
                     client.get("/board?include_interns=true&page=2&limit=1").json())
    assert [first["total_pages"], first["has_more"], second["has_more"]] == [2, True, False]
    assert [j["openings"] for j in first["jobs"]] == [3]
    assert [j["url"] for j in second["jobs"]] == [solo]
    assert client.get("/board?include_interns=true&page=3&limit=1").json()["jobs"] == []


def test_priority_hiring_boards_refresh_about_every_minute_and_hide_internships():
    """Boards that already list our roles are due about every minute. The feed
    stays full-time until internships are asked for."""
    full = posting(1, timedelta(days=1), title="Software Engineer")
    posting(2, timedelta(hours=1), title="Software Engineer Intern")
    posting(3, timedelta(hours=2), title="Engineering Co-Op")
    client = TestClient(app)
    body = client.get("/board").json()
    assert [j["url"] for j in body["jobs"]] == [full]
    assert client.get("/board?include_interns=false").json()["jobs"] == body["jobs"]
    assert len(client.get("/board?include_interns=true").json()["jobs"]) == 3

    minute = timedelta(seconds=60)
    assert board_sync.MIN_INTERVAL == minute
    assert board_sync.ACTIVE_CEILING == minute
    for current in (timedelta(minutes=20), timedelta(hours=1), timedelta(hours=2), timedelta(hours=24)):
        for new_jobs, peak in ((3, True), (0, True), (1, False)):
            got = board_sync.next_interval(current, lists_target=True, new_jobs=new_jobs, peak=peak)
            assert got == minute
    assert board_sync.next_interval(
        timedelta(hours=1), lists_target=False, new_jobs=0, peak=True) == timedelta(hours=24)
    assert board_sync.next_interval(
        timedelta(hours=24), lists_target=None, new_jobs=0, peak=False) == timedelta(hours=24)


def test_full_time_help_desk_and_cs_show_and_intern_help_desk_stays_hidden():
    """Help desk and software/CS full-time postings stay on the board.
    A help-desk internship is stored for the toggle and hidden by default."""
    desk = posting(1, timedelta(days=1), title="Business Help Desk")
    swe = posting(2, timedelta(days=2), title="Software Engineer")
    cs = posting(3, timedelta(days=3), title="Computer Science New Grad")
    posting(4, timedelta(hours=1), title="Business Help Desk Intern")
    client = TestClient(app)
    body = client.get("/board").json()
    assert [j["title"] for j in body["jobs"]] == [
        "Business Help Desk", "Software Engineer", "Computer Science New Grad"]
    assert [j["url"] for j in body["jobs"]] == [desk, swe, cs]
    asked = client.get("/board?include_interns=true").json()
    assert [j["title"] for j in asked["jobs"]] == [
        "Business Help Desk Intern", "Business Help Desk", "Software Engineer",
        "Computer Science New Grad"]


def test_feed_defaults_to_full_time_and_hides_internships():
    """No level on the profile: internships stay out unless the feed is asked."""
    full = posting(1, timedelta(days=1), title="Software Engineer")
    tools = posting(2, timedelta(days=2), title="Software Engineer, Internal Tools")
    cooperative = posting(3, timedelta(days=3), title="Software Engineer, Cooperative AI")
    new_grad = posting(4, timedelta(days=4), title="New Grad Software Engineer")
    posting(5, timedelta(hours=1), title="Software Engineer Intern")
    posting(6, timedelta(hours=2), title="Software Engineering Internship - San Francisco")
    posting(7, timedelta(hours=3), title="Engineering Co-Op")
    posting(8, timedelta(hours=4), title="Flight Software Intern (Summer 2027)")
    client = TestClient(app)
    body = client.get("/board").json()
    assert [j["url"] for j in body["jobs"]] == [full, tools, cooperative, new_grad]
    assert [j["title"] for j in body["jobs"]] == [
        "Software Engineer", "Software Engineer, Internal Tools",
        "Software Engineer, Cooperative AI", "New Grad Software Engineer"]
    assert body["total_pages"] == 1
    assert client.get("/board?include_interns=false").json()["jobs"] == body["jobs"]
    asked = client.get("/board?include_interns=true").json()
    assert len(asked["jobs"]) == 8
    assert asked["jobs"][0]["title"] == "Software Engineer Intern"


@pytest.mark.parametrize("query", ["page=0", "page=-1", "limit=0", "limit=201"])
def test_feed_rejects_invalid_pagination(query):
    assert TestClient(app).get(f"/board?{query}").status_code == 422


@pytest.mark.parametrize("provider", ["greenhouse", "ashby", "lever"])
def test_each_provider_only_ingests_recent_dated_jobs(monkeypatch, provider):
    dates = [NOW, NOW - timedelta(days=14, milliseconds=-1), NOW - timedelta(days=14),
             NOW - timedelta(days=3000), NOW + timedelta(seconds=1), None, "invalid"]
    jobs = []
    for i, date in enumerate(dates):
        date = date.isoformat() + "Z" if isinstance(date, datetime) else date
        url = f"https://jobs.{provider}.com/acme/{i}"
        if provider == "greenhouse":
            jobs.append(dict(id=i, title="Software Engineer", location={"name": "Austin, TX"},
                             first_published=date, updated_at=NOW.isoformat()))
        elif provider == "ashby":
            jobs.append(dict(id=str(i), title="Software Engineer", location="Austin, TX",
                             jobUrl=url, publishedAt=date))
        else:
            epoch = int(datetime.fromisoformat(date).timestamp() * 1000) if date and date != "invalid" else date
            jobs.append(dict(id=str(i), text="Software Engineer", categories={"location": "Austin, TX"},
                             hostedUrl=url, createdAt=epoch))
    async def payload(*_):
        return jobs if provider == "lever" else {"jobs": jobs}
    monkeypatch.setattr(board_sync, "_get_board", payload)
    with db.SessionLocal() as session:
        company = TrackedCompany(slug="acme", provider=provider)
        session.add(company)
        session.commit()
        assert asyncio.run(board_sync.sync_company_jobs(session, company)) == 2
        rows = session.query(JobPosting).all()
        assert len(rows) == 2
        assert all(board_policy.is_recent(row.created_at) for row in rows)


@pytest.mark.parametrize("provider", ["greenhouse", "ashby", "lever"])
@pytest.mark.parametrize("bad", [{}, {"jobs": None}, {"jobs": {}}, {"jobs": [None]}, {"jobs": [{}]}, [{}], "maintenance"])
def test_malformed_boards_never_mean_empty(monkeypatch, provider, bad):
    url = posting(1, timedelta(days=1))
    async def payload(*_):
        return bad
    monkeypatch.setattr(board_sync, "_get_board", payload)
    with db.SessionLocal() as session:
        company = session.get(TrackedCompany, "acme")
        company.provider = provider
        session.commit()
        with pytest.raises(board_sync.BoardVendorError):
            asyncio.run(board_sync.sync_company_jobs(session, company))
    with db.SessionLocal() as session:
        assert session.get(JobPosting, url).status == "open"


def source(url):
    return JdSource(text="Build reliable software and maintain tested APIs. " * 15,
                    title="Software Engineer", source_url=url, apply_url=url + "#apply", adapter="greenhouse")


@pytest.mark.parametrize("state, expected", [("missing", 404), ("closed", 410), ("expired", 410), ("future", 410)])
def test_unavailable_stored_rows_do_not_fetch(monkeypatch, state, expected):
    age = timedelta(days=14 if state == "expired" else -1 if state == "future" else 1)
    url = "https://jobs.lever.co/acme/unknown" if state == "missing" else posting(1, age, status=state if state == "closed" else "open")
    def unexpected(_):
        pytest.fail("unavailable listing must not trigger a network request")
    monkeypatch.setattr(jd_fetch, "fetch_jd_from_url", unexpected)
    assert TestClient(app).post("/board/resolve", json={"url": url}).status_code == expected


def test_successful_handoff_preserves_description_and_apply_url(monkeypatch):
    url = posting(1, timedelta(days=1))
    monkeypatch.setattr(jd_fetch, "fetch_jd_from_url", source)
    response = TestClient(app).post("/board/resolve", json={"url": url})
    assert response.status_code == 200
    assert response.json() == source(url).model_dump()


@pytest.mark.parametrize("failure", ["gone", "timeout", "rate_limit", "server", "bad_json", "short"])
def test_handoff_only_closes_with_confirmed_removal(monkeypatch, failure):
    url = posting(1, timedelta(days=1))
    def fetch(_):
        if failure == "short":
            return source(url).model_copy(update={"text": "careers"})
        if failure == "gone":
            raise jd_fetch.JdUnavailable("This job is no longer available.")
        if failure == "bad_json":
            raise ValueError("bad JSON")
        raise jd_fetch.JdFetchError(failure, status_code={"rate_limit": 429, "server": 500}.get(failure))
    monkeypatch.setattr(jd_fetch, "fetch_jd_from_url", fetch)
    response = TestClient(app).post("/board/resolve", json={"url": url})
    assert response.status_code == (410 if failure == "gone" else 502)
    with db.SessionLocal() as session:
        assert session.get(JobPosting, url).status == ("closed" if failure == "gone" else "open")


def test_expiry_during_slow_handoff_does_not_return_a_jd(monkeypatch):
    url = posting(1, timedelta(days=14, seconds=-1))
    def fetch(_):
        monkeypatch.setattr(board_policy, "utcnow", lambda: NOW + timedelta(seconds=2))
        return source(url)
    monkeypatch.setattr(jd_fetch, "fetch_jd_from_url", fetch)
    assert TestClient(app).post("/board/resolve", json={"url": url}).status_code == 410


def test_cleanup_during_failed_handoff_is_not_a_server_error(monkeypatch):
    url = posting(1, timedelta(days=14, seconds=-1))
    def fetch(_):
        with db.SessionLocal() as session:
            session.execute(delete(JobPosting).where(JobPosting.url == url))
            session.commit()
        raise jd_fetch.JdUnavailable("This job is no longer available.")
    monkeypatch.setattr(jd_fetch, "fetch_jd_from_url", fetch)
    assert TestClient(app).post("/board/resolve", json={"url": url}).status_code == 410


@pytest.mark.parametrize("change, expected", [("closed", 410), ("removed", 404), ("older_date", 410)])
def test_successful_fetch_rechecks_changes_made_during_network_call(monkeypatch, change, expected):
    url = posting(1, timedelta(days=1))
    def fetch(_):
        # A separate worker commits while the route waits for the remote JD.
        with db.SessionLocal() as session:
            if change == "removed":
                session.execute(delete(JobPosting).where(JobPosting.url == url))
            else:
                values = {"status": "closed"} if change == "closed" else {"created_at": NOW - timedelta(days=30)}
                session.execute(update(JobPosting).where(JobPosting.url == url).values(**values))
            session.commit()
        return source(url)
    monkeypatch.setattr(jd_fetch, "fetch_jd_from_url", fetch)
    assert TestClient(app).post("/board/resolve", json={"url": url}).status_code == expected


def test_extremely_large_page_is_a_client_error_not_a_server_error():
    response = TestClient(app).get("/board?page=9223372036854775808")
    assert response.status_code == 422


def test_reharvest_removes_a_legacy_row_when_its_true_date_is_expired(monkeypatch):
    url = posting(1, timedelta(days=1))  # Legacy edit timestamp looked fresh.
    async def payload(*_):
        return {"jobs": [{"id": 1, "title": "Software Engineer", "location": {"name": "Austin, TX"},
                          "first_published": "2019-01-01T00:00:00Z", "updated_at": NOW.isoformat()}]}
    monkeypatch.setattr(board_sync, "_get_board", payload)
    with db.SessionLocal() as session:
        asyncio.run(board_sync.sync_company_jobs(session, session.get(TrackedCompany, "acme")))
    board_sync.cleanup_postings()
    with db.SessionLocal() as session:
        assert session.get(JobPosting, url) is None


@pytest.mark.parametrize("api_status, page_status, gone", [
    (404, 404, True), (410, 404, True), (404, 410, True),
    (404, 503, False), (503, 404, False), (429, 404, False), (403, 403, False),
])
def test_closure_requires_both_ats_and_posting_page_evidence(monkeypatch, api_status, page_status, gone):
    calls = []
    def get(url):
        calls.append(url)
        status = api_status if "api.lever.co" in url else page_status
        raise jd_fetch.JdFetchError("HTTP error", status_code=status)
    monkeypatch.setattr(jd_fetch, "_guarded_get", get)
    with pytest.raises(jd_fetch.JdFetchError) as error:
        jd_fetch.fetch_jd_from_url("https://jobs.lever.co/acme/1")
    assert isinstance(error.value, jd_fetch.JdUnavailable) is gone
    assert len(calls) == 2


def test_unlisted_job_with_live_page_still_resolves(monkeypatch):
    html = (Path(__file__).parent / "fixtures/generic_job.html").read_bytes()
    def get(url):
        if "api.lever.co" in url:
            raise jd_fetch.JdFetchError("unlisted", status_code=404)
        return html
    monkeypatch.setattr(jd_fetch, "_guarded_get", get)
    monkeypatch.setattr(jd_fetch.config, "OLLAMA_API_KEY", None)
    result = jd_fetch.fetch_jd_from_url("https://jobs.lever.co/acme/1")
    assert result.adapter == "generic" and "Kubernetes" in result.text


@pytest.mark.parametrize("payload, gone", [
    ({"jobs": []}, True), ({}, False), ({"jobs": [{}]}, False),
    ({"jobs": [{"id": "", "jobUrl": "https://jobs.ashbyhq.com/acme/unknown"}]}, False),
    ({"jobs": [{"id": " ", "jobUrl": "https://jobs.ashbyhq.com/acme/unknown"}]}, False),
])
def test_ashby_absence_requires_valid_board_then_missing_page(monkeypatch, payload, gone):
    def get(url):
        if "api.ashbyhq.com" in url:
            return json.dumps(payload).encode()
        raise jd_fetch.JdFetchError("missing", status_code=404)
    monkeypatch.setattr(jd_fetch, "_guarded_get", get)
    with pytest.raises(jd_fetch.JdFetchError) as error:
        jd_fetch.fetch_jd_from_url("https://jobs.ashbyhq.com/acme/1")
    assert isinstance(error.value, jd_fetch.JdUnavailable) is gone


@pytest.mark.parametrize("payload", [[], None, {"content": None}, {"location": "unexpected"}])
def test_malformed_single_job_api_uses_safe_fallback(monkeypatch, payload):
    def get(url):
        if "boards-api.greenhouse.io" in url:
            return json.dumps(payload).encode()
        raise jd_fetch.JdFetchError("outage", status_code=503)
    monkeypatch.setattr(jd_fetch, "_guarded_get", get)
    url = posting(1, timedelta(days=1))
    assert TestClient(app).post("/board/resolve", json={"url": url}).status_code == 502


@pytest.mark.parametrize("lists", [{}, False, "", 0])
def test_malformed_empty_lever_sections_are_not_a_complete_jd(monkeypatch, lists):
    def get(url):
        if "api.lever.co" in url:
            return json.dumps({"descriptionPlain": "Intro text. " * 50, "lists": lists}).encode()
        raise jd_fetch.JdFetchError("fallback unavailable", status_code=503)
    monkeypatch.setattr(jd_fetch, "_guarded_get", get)
    with pytest.raises(jd_fetch.JdFetchError):
        jd_fetch.fetch_jd_from_url("https://jobs.lever.co/acme/1")


def test_startup_cleans_before_serving_and_stops_all_workers(monkeypatch):
    import app.main as main
    posting(1, timedelta(days=100))
    events = []
    async def worker():
        events.append("started")
        try:
            await asyncio.Event().wait()
        finally:
            events.append("stopped")
    for name in ("harvester_loop", "scout_loop", "retention_loop"):
        monkeypatch.setattr(main, name, worker)
    with TestClient(app) as client:
        assert client.get("/board").json()["total_pages"] == 0
        with db.SessionLocal() as session:
            assert session.query(JobPosting).count() == 0
    assert events.count("started") == events.count("stopped") == 3


@pytest.mark.parametrize("worker_name", ["harvester_loop", "scout_loop"])
@pytest.mark.parametrize("phase", ["cycle", "sleep"])
def test_lifespan_stops_real_background_loop_during_work_or_sleep(monkeypatch, worker_name, phase, capsys):
    import app.main as main
    entered, stopped = asyncio.Event(), asyncio.Event()
    closed_clients = []

    async def idle():
        await asyncio.Event().wait()

    async def cycle(*_):
        if phase == "cycle":
            entered.set()
            await idle()
        return 0

    async def sleep(_):
        entered.set()
        await idle()

    @asynccontextmanager
    async def client(**_):
        try:
            yield object()  # Scout I/O is replaced by cycle(); no network calls.
        finally:
            closed_clients.append(True)

    for name in ("JSEARCH_API_KEY", "OPENWEBNINJA_API_KEY", "RAPIDAPI_KEY",
                 "JSEARCH_API_URL", "JSEARCH_API_HOST"):
        monkeypatch.delenv(name, raising=False)
    loop = getattr(board_sync, worker_name)
    async def observed_loop():
        try:
            await loop()
        finally:
            stopped.set()

    monkeypatch.setattr(board_sync, "sync_company_jobs", cycle)  # a vendor worker's work (T31)
    monkeypatch.setattr(board_sync, "_scout_github", cycle)
    monkeypatch.setattr(board_sync, "_scout_serper", cycle)
    monkeypatch.setattr(board_sync, "_scout_jsearch", cycle)
    monkeypatch.setattr(board_sync, "_scout_wayback", cycle)
    monkeypatch.setattr(board_sync.httpx, "AsyncClient", client)
    monkeypatch.setattr(board_sync.asyncio, "sleep", sleep)
    for name in ("harvester_loop", "scout_loop", "retention_loop"):
        monkeypatch.setattr(main, name, observed_loop if name == worker_name else idle)

    async def scenario():
        async with main.lifespan(app):
            await entered.wait()
        assert stopped.is_set()
    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    # Every client that was opened is closed: one per vendor worker (T31); the
    # scout opens one per due scout (Simplify, Serper, Wayback). JSearch is
    # not due without a key, so it adds a client only once a key is configured.
    assert len(closed_clients) == {"harvester_loop": len(board_sync._lanes()),
                                   "scout_loop": 1 if phase == "cycle" else 3}[worker_name]
    assert capsys.readouterr().err == ""  # Normal shutdown must not log a bug.


def test_a_closed_terminal_does_not_stop_the_harvester(monkeypatch):
    """2026-10-17: the log reader exited. print() raised BrokenPipeError, the
    handler's traceback.print_exc() raised the same error, and the checker
    exited for good while the API kept serving a frozen board."""

    class Closed:
        def write(self, _data):
            raise BrokenPipeError("closed")

        def flush(self):
            raise BrokenPipeError("closed")

    monkeypatch.setattr(sys, "stdout", Closed())
    monkeypatch.setattr(sys, "stderr", Closed())
    board_sync.guard_stdio()
    print("[board] greenhouse still due")

    passes = {"n": 0}
    sleeps = []

    async def vendor(_provider, _stats, report_every=None):
        passes["n"] += 1
        if passes["n"] == 1:
            raise BrokenPipeError("closed")
        raise asyncio.CancelledError

    async def sleep(seconds):
        sleeps.append(seconds)

    def explode():
        raise BrokenPipeError("stderr closed")

    monkeypatch.setattr(board_sync, "_vendor_worker", vendor)
    monkeypatch.setattr(board_sync.asyncio, "sleep", sleep)
    monkeypatch.setattr(board_sync.traceback, "print_exc", explode)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(board_sync._worker_forever("greenhouse"))
    assert passes["n"] == 2
    assert sleeps == [board_sync.WORKER_IDLE]


def test_periodic_cleanup_runs_independently_and_recovers_after_error(monkeypatch):
    intervals, sweeps = [], []
    async def sleep(seconds):
        intervals.append(seconds)
        if len(intervals) == 3:
            raise asyncio.CancelledError
    def cleanup():
        sweeps.append(True)
        if len(sweeps) == 1:
            raise RuntimeError("temporary DB failure")
    monkeypatch.setattr(board_sync.asyncio, "sleep", sleep)
    monkeypatch.setattr(board_sync, "cleanup_postings", cleanup)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(board_sync.retention_loop())
    assert intervals == [900, 900, 900]
    assert len(sweeps) == 2


# --- T29: one harvester per DB ------------------------------------------------
# A second server on the same app.db ran a stale harvester that undid provider
# moves. Only the lock holder runs the loops; every process still serves the API.

def _started_loops(monkeypatch):
    import app.main as main
    started = []
    def worker(name):
        async def loop():
            started.append(name)
            await asyncio.Event().wait()
        return loop
    for name in ("harvester_loop", "scout_loop", "retention_loop"):
        monkeypatch.setattr(main, name, worker(name))
    return started


def test_a_second_server_on_the_same_db_runs_no_background_loops(monkeypatch, capsys):
    import app.main as main
    started = _started_loops(monkeypatch)
    held = board_sync.claim_background_lock()
    try:
        async def scenario():
            async with main.lifespan(app):
                await asyncio.sleep(0)
        asyncio.run(scenario())
        assert started == []
        assert "serving the API only" in capsys.readouterr().out
    finally:
        held.close()


def test_the_lock_is_released_on_shutdown_so_a_restart_takes_over(monkeypatch):
    import app.main as main
    started = _started_loops(monkeypatch)
    async def scenario():
        async with main.lifespan(app):
            await asyncio.sleep(0)
    asyncio.run(scenario())
    assert sorted(started) == ["harvester_loop", "retention_loop", "scout_loop"]
    again = board_sync.claim_background_lock()
    assert again is not None
    again.close()


def test_a_lock_held_by_another_os_process_is_respected(tmp_path, monkeypatch):
    """The real failure: two uvicorn processes, not two lifespans in one."""
    import subprocess, sys
    monkeypatch.setattr(board_sync.config, "DATA_DIR", tmp_path)
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl, sys, time; f = open(sys.argv[1], 'w'); "
         "fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); print('held', flush=True); time.sleep(30)",
         str(tmp_path / "background.lock")], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        assert board_sync.claim_background_lock() is None
    finally:
        holder.kill(); holder.wait()
    mine = board_sync.claim_background_lock()   # the kernel released the dead holder's lock
    assert mine is not None
    mine.close()


def test_resolve_returns_the_deal_breaker_screen(monkeypatch):
    """T39 end to end: the real fetch + Greenhouse parse + screen, only the network faked."""
    url = posting(1, timedelta(days=1))
    content = ("<ul><li>3+ years of professional software development experience</li>"
               "<li>Must be a US Citizen.</li><li>This position is not eligible for visa sponsorship.</li>"
               "<li>Active Secret clearance required.</li></ul>" + "<p>Build and run our platform.</p>" * 10)
    payload = {"title": "Software Engineer", "content": html.escape(content), "absolute_url": url}
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda _: json.dumps(payload).encode())
    response = TestClient(app).post("/board/resolve", json={"url": url})
    assert response.status_code == 200
    assert response.json()["screen"] == {
        "min_years": 3.0, "experience": ["3+ years of professional software development experience"],
        "citizenship": ["Must be a US Citizen."],
        "no_sponsorship": ["This position is not eligible for visa sponsorship."],
        "clearance": ["Active Secret clearance required."]}
