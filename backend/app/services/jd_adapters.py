"""Per-ATS adapters (T10). When a URL's host matches a known ATS, hit its public
JSON API directly (deterministic, no LLM, structured title/location) instead of
scraping. Registry — append new boards over time (this ticket is semi-open).

Each adapter: match(url) -> bool, api_url(url) -> str (pure), parse(data, url) -> JdSource.
The network GET (SSRF-guarded) lives in jd_fetch, so adapters stay pure + testable.
Optional flags (T36): raw = parse() gets the page text, not JSON; api_is_source =
the posting page is built from this same source, so its "not found" is final."""

import html
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote, unquote, urlparse

from app.schemas.jd import JdSource

_BLOCK = re.compile(r"</(?:p|div|li|h[1-6]|tr|ul|ol)>|<br\s*/?>|<li[^>]*>", re.I)


def board_jobs(data, provider: str) -> list[dict]:
    """A missing/malformed list is not evidence that every posting has closed."""
    jobs = data if provider == "lever" else data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list) or any(not isinstance(job, dict) for job in jobs):
        raise ValueError(f"invalid {provider} board: expected a jobs list")
    url_key = {"greenhouse": "absolute_url", "lever": "hostedUrl", "ashby": "jobUrl"}[provider]
    for job in jobs:
        if not any(isinstance(job.get(key), (str, int)) and str(job[key]).strip()
                   for key in ("id", url_key)):
            raise ValueError(f"invalid {provider} board: missing posting identifier")
    return jobs


def _strip_html(s: str) -> str:
    """HTML fragment → readable text: block tags become line breaks, other tags
    drop, entities unescape, blank lines collapse."""
    if not isinstance(s, str):
        raise ValueError("invalid ATS description: expected text")
    # Workday double-escapes some characters ("&amp;#xa;", 5 of 70 postings),
    # which left a literal "&#xa;" in the text instead of a line break.
    s = re.sub(r"&amp;(#x?[0-9a-f]+;)", r"&\1", s, flags=re.I)
    s = _BLOCK.sub("\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return "\n".join(ln.strip() for ln in s.splitlines() if ln.strip()).strip()


def parse_ats_date(value) -> datetime | None:
    """ATS date -> naive UTC, or None when missing/unparseable. Handles ISO strings
    (with or without offset, or date-only as Workday sends) and Lever's epoch ms."""
    if not value:
        return None
    try:
        if str(value).isdigit():
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).replace(tzinfo=None)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        # Naive is assumed to be UTC already; aware is converted and stripped.
        return dt if dt.tzinfo is None else dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None


def object_field(data: dict, key: str) -> dict:
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"invalid ATS {key}: expected an object")
    return value


_LOCALE = re.compile(r"[a-z]{2}-[a-z]{2}", re.I)


def _job_id(url: str, pattern: str) -> str | None:
    m = re.search(pattern, urlparse(url).path)
    return m.group(1) if m else None


class Workday:
    name = "workday"
    # The posting page is a JS shell over this same API: it answers 200 even for
    # a job that does not exist (verified 2026-09-24), so the API's 404 is final.
    api_is_source = True
    PAGE = 20  # 21 is an HTTP 400
    CAP = 2000  # `total` stops here, and any offset at or past it wraps to page 1
    _HOST = re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com")
    _SITE_HOST = re.compile(r"(wd\d+)\.myworkdaysite\.com")

    def _parts(self, url: str) -> tuple[str, str, str, list[str]] | None:
        """(canonical host, tenant, site, path after the site). Links also come as
        wdN.myworkdaysite.com/[locale/]recruiting/{tenant}/{site}/..., and the
        {tenant}.wdN.myworkdayjobs.com host serves the same API (verified)."""
        p = urlparse(url)
        host = (p.hostname or "").lower()
        segs = [s for s in p.path.split("/") if s]
        if segs and _LOCALE.fullmatch(segs[0]):
            segs = segs[1:]
        if m := self._HOST.fullmatch(host):
            tenant = m.group(1)
        elif (m := self._SITE_HOST.fullmatch(host)) and len(segs) >= 3 and segs[0] == "recruiting":
            tenant, segs = segs[1].lower(), segs[2:]
            host = f"{tenant}.{m.group(1)}.myworkdayjobs.com"
        else:
            return None
        if not segs or segs[0] in ("job", "wday"):
            return None
        return host, tenant, segs[0], segs[1:]

    def match(self, url: str) -> bool:
        parts = self._parts(url)
        return bool(parts and len(parts[3]) >= 2 and parts[3][0] == "job")

    def api_url(self, url: str) -> str:
        host, tenant, site, rest = self._parts(url)
        return f"https://{host}/wday/cxs/{tenant}/{site}/{'/'.join(rest)}"

    def board_of(self, url: str) -> tuple[str, str] | None:
        """(slug, board URL) of any link into a site, or None. Slug = the tenant."""
        parts = self._parts(url)
        if parts is None or not re.fullmatch(r"[A-Za-z0-9_-]+", parts[2]):
            return None
        return parts[1], f"https://{parts[0]}/{parts[2]}"

    def board(self, board_url: str) -> tuple[str, str, str]:
        """(host, tenant, site) of a stored board URL; ValueError when it is not one."""
        parts = self._parts(board_url)
        if parts is None or parts[3] or not re.fullmatch(r"[A-Za-z0-9_-]+", parts[2]):
            raise ValueError(f"not a Workday board: {board_url!r}")
        return parts[0], parts[1], parts[2]

    def list_request(self, board_url: str, offset: int, facets: dict | None = None) -> tuple[str, dict]:
        host, tenant, site = self.board(board_url)
        return (f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                {"appliedFacets": facets or {}, "limit": self.PAGE, "offset": offset, "searchText": ""})

    def job_url(self, board_url: str, external_path: str) -> str:
        """The sitemap's form: no locale, site then /job/... Vendor data is
        checked: a path not starting /job/ is refused, never appended."""
        if not external_path.startswith("/job/"):
            raise ValueError(f"invalid Workday job path: {external_path!r}")
        return board_url.rstrip("/") + external_path

    def parse(self, data: dict, url: str) -> JdSource:
        info = object_field(data, "jobPostingInfo")
        return JdSource(
            text=_strip_html(info.get("jobDescription", "")),
            title=info.get("title"),
            location=info.get("location"),
            source_url=url,
            apply_url=url,  # Workday's posting URL is itself the apply page
            adapter=self.name,
            # A bare calendar date (verified: "Posted Today" -> today's date). Kept
            # as a date, not UTC midnight, which reads as "yesterday" west of UTC.
            posted_at=(d := parse_ats_date(info.get("startDate"))) and d.date(),
        )


class Greenhouse:
    name = "greenhouse"

    def match(self, url: str) -> bool:
        if "greenhouse.io/" not in url:
            return False
        p = urlparse(url)
        if p.path.startswith("/embed/"):
            # the iframe a careers site embeds: embed/job_app?for={board}&token={job id}
            q = parse_qs(p.query)
            return p.path.startswith("/embed/job_app") and "for" in q and "token" in q
        return "/jobs/" in url or "gh_jid=" in url

    def api_url(self, url: str) -> str:
        p = urlparse(url)
        m = re.search(r"/jobs/(\d+)", p.path)
        q = parse_qs(p.query)
        jid = m.group(1) if m else (q.get("gh_jid") or q.get("token") or [""])[0]
        return f"https://boards-api.greenhouse.io/v1/boards/{self._token(url)}/jobs/{jid}"

    def _token(self, url: str) -> str:
        p = urlparse(url)
        if p.path.startswith("/embed/"):
            return parse_qs(p.query)["for"][0]
        return p.path.strip("/").split("/")[0]

    def board_slug(self, url: str) -> str:
        """The slug list_url takes. Lowercase, like every tracked company (T28)."""
        return self._token(url).lower()

    def list_url(self, slug: str) -> str:
        """Every posting on a board (T26). Same API family as api_url - kept here
        so ATS endpoint knowledge lives in ONE module (the T18 drift lesson)."""
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"

    def parse(self, data: dict, url: str) -> JdSource:
        content = data.get("content", "")
        if not isinstance(content, str):
            raise ValueError("invalid Greenhouse content: expected text")
        return JdSource(
            text=_strip_html(html.unescape(content)),  # content is entity-escaped HTML
            title=data.get("title"),
            location=object_field(data, "location").get("name"),
            company=data.get("company_name"),
            source_url=url,
            apply_url=data.get("absolute_url"),
            adapter=self.name,
            posted_at=parse_ats_date(data.get("first_published")),
            # Greenhouse bulk-rewrites this on board-wide edits (T26), so it is
            # "last touched", not proof the posting itself changed.
            updated_at=parse_ats_date(data.get("updated_at")),
        )


class Lever:
    name = "lever"

    def match(self, url: str) -> bool:
        return "jobs.lever.co/" in url

    def api_url(self, url: str) -> str:
        company, jid = urlparse(url).path.strip("/").split("/")[:2]
        return f"https://api.lever.co/v0/postings/{company}/{jid}"

    def board_slug(self, url: str) -> str:
        # As written: Lever is case-sensitive (Palantir 404s) and 178 boards in a
        # year of Wayback answer only in their own case, e.g. CesiumAstro (T44).
        return urlparse(url).path.strip("/").split("/")[0]

    def list_url(self, slug: str) -> str:
        return f"https://api.lever.co/v0/postings/{slug}?mode=json"

    def parse(self, data: dict, url: str) -> JdSource:
        # descriptionPlain combines opening/body, but excludes the requirements
        # lists and closing text. Some live postings put their entire JD in lists.
        sections = [data.get("descriptionPlain") or _strip_html(data.get("description") or "")]
        lists = data.get("lists")
        if lists is None:
            lists = []
        if not isinstance(lists, list) or any(not isinstance(item, dict) for item in lists):
            raise ValueError("invalid Lever lists: expected a list of sections")
        for item in lists:
            sections.extend([item.get("text") or "", _strip_html(item.get("content") or "")])
        sections.append(data.get("additionalPlain") or _strip_html(data.get("additional") or ""))
        if any(not isinstance(section, str) for section in sections):
            raise ValueError("invalid Lever section: expected text")
        return JdSource(
            text="\n\n".join(section.strip() for section in sections if section.strip()),
            title=data.get("text"),
            location=object_field(data, "categories").get("location"),
            source_url=url,
            apply_url=data.get("hostedUrl"),
            adapter=self.name,
            posted_at=parse_ats_date(data.get("createdAt")),  # Lever exposes no update time
        )


class Ashby:
    name = "ashby"

    def match(self, url: str) -> bool:
        # only the jobs.ashbyhq.com/{org}/{id} form carries a slug; the embedded
        # ?ashby_jid= form has none → let it fall through to generic/paste.
        p = urlparse(url)
        return p.hostname == "jobs.ashbyhq.com" and len(p.path.strip("/").split("/")) >= 2

    def _org_jid(self, url: str) -> tuple[str, str]:
        org, jid = urlparse(url).path.strip("/").split("/")[:2]
        return org, jid

    def api_url(self, url: str) -> str:
        org, _ = self._org_jid(url)
        return self.list_url(org)

    def board_slug(self, url: str) -> str:
        return unquote(self._org_jid(url)[0]).strip().lower()  # "Flock%20Safety" (T44)

    def list_url(self, slug: str) -> str:
        """Ashby has no per-job endpoint - api_url fetches the whole board and
        parse() filters it, so the two are literally the same URL."""
        return f"https://api.ashbyhq.com/posting-api/job-board/{slug}"

    def parse(self, data: dict, url: str) -> JdSource:
        from app.services.jd_fetch import JdFetchError  # local: avoid import cycle

        _, jid = self._org_jid(url)
        jobs = board_jobs(data, self.name)
        # Missing identifiers make absence ambiguous, not a confirmed removal.
        if any(not isinstance(j.get("id"), str) or not j["id"].strip() for j in jobs):
            raise ValueError("invalid Ashby board: missing posting identifier")
        job = next((j for j in jobs if j.get("id") == jid), None)
        if job is None:
            raise JdFetchError("job not found in Ashby board", status_code=404)
        return JdSource(
            text=job.get("descriptionPlain", ""),  # already clean text
            title=job.get("title"),
            location=job.get("location"),
            source_url=url,
            apply_url=job.get("applyUrl") or job.get("jobUrl"),
            adapter=self.name,
            posted_at=parse_ats_date(job.get("publishedAt")),  # Ashby exposes no update time
        )


def _not_found(what: str):
    from app.services.jd_fetch import JdFetchError  # local: avoid import cycle

    return JdFetchError(f"{what} not found", status_code=404)


class Oracle:
    """Oracle Recruiting Cloud (T36): Oracle, Dell, Texas Instruments."""
    name = "oracle"
    api_is_source = True  # the candidate page is a JS shell over this REST API
    PAGE = 200  # the API's maximum (500 returns 200)
    # pods may hold hyphens: fa-espx-saasfaprod1 (244 of 2,383 Simplify links)
    _HOST = re.compile(r"[a-z0-9-]+\.fa\.(?:[a-z0-9-]+\.)*oraclecloud\.com")
    _PATH = re.compile(r"/hcmUI/CandidateExperience/[^/]+/sites/([A-Za-z0-9_-]+)(?:/job/(\d+))?/?")
    _REST = "hcmRestApi/resources/latest"

    def _parts(self, url: str) -> tuple[str, str, str | None] | None:
        p = urlparse(url)
        host = (p.hostname or "").lower()
        m = self._PATH.fullmatch(p.path)
        return (host, m.group(1), m.group(2)) if self._HOST.fullmatch(host) and m else None

    def match(self, url: str) -> bool:
        return bool((parts := self._parts(url)) and parts[2])

    def api_url(self, url: str) -> str:
        host, site, jid = self._parts(url)
        return (f"https://{host}/{self._REST}/recruitingCEJobRequisitionDetails"
                f"?expand=all&onlyData=true&finder=ById;Id=%22{jid}%22,siteNumber={site}")

    def board_of(self, url: str) -> tuple[str, str] | None:
        """(slug, board URL), or None. Slug = the pod, e.g. "eeho"."""
        parts = self._parts(url)
        if parts is None:
            return None
        return parts[0].split(".")[0], f"https://{parts[0]}/hcmUI/CandidateExperience/en/sites/{parts[1]}"

    def board(self, board_url: str) -> tuple[str, str]:
        parts = self._parts(board_url)
        if parts is None or parts[2]:
            raise ValueError(f"not an Oracle board: {board_url!r}")
        return parts[0], parts[1]

    def list_url(self, board_url: str, offset: int) -> str:
        host, site = self.board(board_url)
        return (f"https://{host}/{self._REST}/recruitingCEJobRequisitions?onlyData=true"
                f"&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={site},"
                f"limit={self.PAGE},offset={offset},sortBy=POSTING_DATES_DESC")

    def job_url(self, board_url: str, jid) -> str:
        return f"{board_url.rstrip('/')}/job/{quote(str(jid), safe='')}"

    def parse(self, data: dict, url: str) -> JdSource:
        items = data.get("items")
        if items == []:  # an unknown or closed id is a 200 with no items (verified)
            raise _not_found("Oracle posting")
        if not isinstance(items, list) or not isinstance(items[0], dict):
            raise ValueError("invalid Oracle posting: expected items")
        job = items[0]
        sections = [job.get(k) or "" for k in (
            "ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")]
        return JdSource(
            text="\n\n".join(t for t in map(_strip_html, sections) if t),
            title=job.get("Title"),
            location=job.get("PrimaryLocation"),
            source_url=url,
            apply_url=url,
            adapter=self.name,
            posted_at=parse_ats_date(job.get("ExternalPostedStartDate")),
        )


class SmartRecruiters:
    """ServiceNow, Western Digital, Arista (T36), via the documented public
    Posting API. Case-insensitive company ids (verified)."""
    name = "smartrecruiters"
    # A closed posting still answers 200, with "active": false (6 of 6 postings
    # Simplify marked inactive, 2026-09-24), so the API's word is final.
    api_is_source = True
    PAGE = 100  # the API's maximum (200 returns 100)
    _API = "https://api.smartrecruiters.com/v1/companies"

    def _parts(self, url: str) -> tuple[str, str] | None:
        p = urlparse(url)
        # ids are numbers, or UUIDs on older postings (the API takes both, verified)
        m = re.fullmatch(r"/([A-Za-z0-9_-]+)/(\d+|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})(?:-[^/]*)?/?", p.path)
        return (m.group(1), m.group(2)) if p.hostname == "jobs.smartrecruiters.com" and m else None

    def match(self, url: str) -> bool:
        return self._parts(url) is not None

    def api_url(self, url: str) -> str:
        company, jid = self._parts(url)
        return f"{self._API}/{company}/postings/{jid}"

    def board_slug(self, url: str) -> str:
        return self._parts(url)[0].lower()

    def list_url(self, slug: str, offset: int = 0) -> str:
        return f"{self._API}/{slug}/postings?limit={self.PAGE}&offset={offset}"

    def job_url(self, company: str, jid: str) -> str:
        return f"https://jobs.smartrecruiters.com/{quote(company, safe='')}/{quote(str(jid), safe='')}"

    def parse(self, data: dict, url: str) -> JdSource:
        if data.get("active") is False:
            raise _not_found("SmartRecruiters posting")
        sections = object_field(object_field(data, "jobAd"), "sections")
        text = [_strip_html(object_field(sections, k).get("text") or "") for k in (
            "jobDescription", "qualifications", "additionalInformation")]
        return JdSource(
            text="\n\n".join(t for t in text if t),
            title=data.get("name"),
            location=object_field(data, "location").get("fullLocation"),
            company=object_field(data, "company").get("name"),
            source_url=url,
            apply_url=data.get("applyUrl") or url,
            adapter=self.name,
            posted_at=parse_ats_date(data.get("releasedDate")),
        )


def epoch_seconds(value) -> str | None:
    """Eightfold sends epoch SECONDS; parse_ats_date reads bare digits as Lever's
    milliseconds, so hand it an ISO string instead."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


class Eightfold:
    """Microsoft, Qualcomm, PayPal, Lam Research (T36). robots.txt allows /api/pcsx."""
    name = "eightfold"
    api_is_source = True  # a bogus id is an HTTP 404 "Position not found" (verified)
    PAGE = 10  # fixed; `num` is ignored
    _HOST = re.compile(r"[a-z0-9-]+\.eightfold\.ai|apply\.careers\.microsoft\.com")

    def _host(self, url: str) -> str | None:
        host = (urlparse(url).hostname or "").lower()
        return host if self._HOST.fullmatch(host) else None

    def match(self, url: str) -> bool:
        return bool(self._host(url) and _job_id(url, r"^/careers/job/(\d+)/?$"))

    def api_url(self, url: str) -> str:
        # `domain` is not needed for a single position (verified)
        return (f"https://{self._host(url)}/api/pcsx/position_details"
                f"?position_id={_job_id(url, r'^/careers/job/(\d+)/?$')}&hl=en")

    def board(self, board_url: str) -> tuple[str, str]:
        host = self._host(board_url)
        domain = parse_qs(urlparse(board_url).query).get("domain", [""])[0]
        if not host or not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", domain):
            raise ValueError(f"not an Eightfold board: {board_url!r}")
        return host, domain

    def list_url(self, board_url: str, location: str, start: int) -> str:
        host, domain = self.board(board_url)
        return (f"https://{host}/api/pcsx/search?domain={domain}&query="
                f"&location={quote(location)}&start={start}&sort_by=timestamp")

    def job_url(self, board_url: str, jid) -> str:
        return f"https://{self.board(board_url)[0]}/careers/job/{quote(str(jid), safe='')}"

    def parse(self, data: dict, url: str) -> JdSource:
        job = object_field(data, "data")
        if not job:  # a gone position is an HTTP 404 (verified), so this is just malformed
            raise ValueError("invalid Eightfold position: no data")
        locations = job.get("locations") or []
        return JdSource(
            text=_strip_html(job.get("jobDescription") or ""),
            title=job.get("name"),
            location=" | ".join(x for x in locations if isinstance(x, str)) or None,
            source_url=url,
            apply_url=job.get("publicUrl") or url,
            adapter=self.name,
            posted_at=parse_ats_date(epoch_seconds(job.get("postedTs"))),
        )


class Amazon:
    """amazon.jobs (T36). No JSON per job: the page itself is the source, and it
    extracts cleanly (verified: 6k chars) and 404s once a job is gone."""
    name = "amazon"
    api_is_source = True
    raw = True  # parse() gets the page, not JSON
    PAGE = 100  # the maximum; result_limit=500 fails

    def match(self, url: str) -> bool:
        return (urlparse(url).hostname or "") in ("amazon.jobs", "www.amazon.jobs") \
            and bool(_job_id(url, r"^/[a-z-]+/jobs/(\d+)"))

    def api_url(self, url: str) -> str:
        return url

    # Where target roles sit (1,000 newest US "engineer" jobs, 2026-09-24): Software
    # Development held only 241 of 313; security/SRE, ops/platform, data and BI
    # engineers the rest. Repeated category[] ORs (1,759 + 496 + 88 = 2,343 hits).
    CATEGORIES = ("software-development", "systems-quality-security-engineering",
                  "operations-it-support-engineering", "data-science", "business-intelligence",
                  "database-administration")

    def list_url(self, country: str, offset: int) -> str:
        categories = "".join(f"category%5B%5D={c}&" for c in self.CATEGORIES)
        return (f"https://www.amazon.jobs/en/search.json?{categories}"
                f"country={country}&sort=recent&result_limit={self.PAGE}&offset={offset}")

    def job_url(self, job_path: str) -> str:
        # without the leading slash, "@evil.com/x" would make the host evil.com
        if not job_path.startswith("/"):
            raise ValueError(f"invalid Amazon job path: {job_path!r}")
        return "https://www.amazon.jobs" + job_path

    def parse(self, page: str, url: str) -> JdSource:
        import trafilatura

        from app.core import config

        text = (trafilatura.extract(page) or "").strip()
        if len(text) < config.JD_MIN_CHARS:  # e.g. a block page: let generic warn "please paste"
            raise ValueError("Amazon page has no job description")
        meta = trafilatura.extract_metadata(page)  # its <title> is the job title (verified)
        return JdSource(text=text, title=meta.title if meta else None, source_url=url, apply_url=url,
                        adapter=self.name)


def apple_data(page: str) -> dict:
    """Apple's pages carry their data as JSON.parse("...") of the router state."""
    # a whole JS string literal: a lazy ".*?" would stop at a \"); inside a job's text
    m = re.search(r'__staticRouterHydrationData = JSON.parse\(("(?:[^"\\]|\\.)*")\);', page, re.S)
    if not m:
        raise ValueError("invalid Apple page: no router data")
    return object_field(json.loads(json.loads(m.group(1))), "loaderData")


class Apple:
    """jobs.apple.com (T36). No robots.txt (404, verified)."""
    name = "apple"
    api_is_source = True  # a bogus id still returns a 200 page, just without jobsData
    raw = True
    PAGE = 20

    def match(self, url: str) -> bool:
        return urlparse(url).hostname == "jobs.apple.com" and bool(_job_id(url, r"/details/([\w-]+)"))

    def api_url(self, url: str) -> str:
        return url

    def list_url(self, location: str, page: int) -> str:
        return f"https://jobs.apple.com/en-us/search?sort=newest&location={location}&page={page}"

    def job_url(self, position_id: str) -> str:
        return f"https://jobs.apple.com/en-us/details/{quote(str(position_id), safe='')}"

    def parse(self, page: str, url: str) -> JdSource:
        data = apple_data(page)
        if "jobDetails" not in data:  # a bogus id: a 200 page whose data holds only "root" (verified)
            raise _not_found("Apple job")
        job = object_field(object_field(data, "jobDetails"), "jobsData")
        if not job:
            raise ValueError("invalid Apple job: no jobsData")
        parts = [job.get(k) or "" for k in (
            "jobSummary", "description", "minimumQualifications", "preferredQualifications")]
        if any(not isinstance(p, str) for p in parts):
            raise ValueError("invalid Apple job: expected text")
        return JdSource(
            text="\n\n".join(p.strip() for p in parts if p.strip()),
            title=job.get("postingTitle"),
            location=apple_location(job.get("locations")),
            source_url=url,
            apply_url=url,
            adapter=self.name,
            posted_at=parse_ats_date(job.get("postDateInGMT")),
        )


def apple_location(locations) -> str | None:
    """"Cupertino, California, United States" per location, joined like the
    other vendors' multi-location strings."""
    if not isinstance(locations, list):
        return None
    units = [", ".join(dict.fromkeys(filter(None, (loc.get("city"), loc.get("stateProvince"),
                                                  loc.get("countryName") or loc.get("name")))))
             for loc in locations if isinstance(loc, dict)]
    return " | ".join(u for u in units if u) or None


def places(entries: list, *keys: str) -> tuple[str | None, str | None]:
    """("City, Region, Country | ...", the first entry's ISO country) from a
    vendor's location list; `keys` name the city/region/country/code fields."""
    units, country = [], None
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict):
            units.append(", ".join(v for v in (entry.get(k) for k in keys[:3]) if isinstance(v, str) and v))
            country = country or entry.get(keys[3])
    # dict.fromkeys: Workable repeats a multi-location job's list on every row
    return " | ".join(dict.fromkeys(u for u in units if u)) or None, country if isinstance(country, str) else None


class Workable:
    """apply.workable.com (T37). robots.txt allows all; unknown accounts 404."""
    name = "workable"
    api_is_source = True  # a closed job's API answers 404 (7 of 8 checked) while its page answers 200
    _API = "https://apply.workable.com/api"

    def _parts(self, url: str) -> tuple[str, str] | None:
        p = urlparse(url)
        m = re.fullmatch(r"/([A-Za-z0-9_-]+)/j/([A-Za-z0-9]+)(?:/apply)?/?", p.path)
        return (m.group(1), m.group(2)) if p.hostname == "apply.workable.com" and m else None

    def match(self, url: str) -> bool:
        return self._parts(url) is not None

    def api_url(self, url: str) -> str:
        account, shortcode = self._parts(url)
        return f"{self._API}/v2/accounts/{account}/jobs/{shortcode}"

    def board_slug(self, url: str) -> str:
        # ponytail: lowercased like every slug; accounts ARE case-sensitive
        # (TickPick 404s), but 0 of 123 real accounts use capitals (2026-09-24).
        return self._parts(url)[0].lower()

    def list_url(self, slug: str) -> str:
        """Every job at once; the paged v3 search has the same ones, 10 a page."""
        return f"{self._API}/v1/widget/accounts/{slug}"

    def job_url(self, slug: str, shortcode: str) -> str:
        return f"https://apply.workable.com/{quote(slug, safe='')}/j/{quote(str(shortcode), safe='')}/"

    def parse(self, data: dict, url: str) -> JdSource:
        shown = [p for p in data.get("locations") or [data.get("location")]
                 if isinstance(p, dict) and not p.get("hidden")]  # the employer hid these
        location, _ = places(shown, "city", "region", "country", "countryCode")
        return JdSource(
            text="\n\n".join(t for t in (_strip_html(data.get(k) or "") for k in (
                "description", "requirements", "benefits")) if t),
            title=data.get("title"),
            location=location,
            source_url=url,
            apply_url=self.job_url(*self._parts(url)) + "apply",
            adapter=self.name,
            posted_at=(d := parse_ats_date(data.get("published"))) and d.date(),  # a date only
        )


def job_posting(page: str) -> dict | None:
    """The page's schema.org JobPosting (JSON-LD), or None."""
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            return data
    return None


def _address(address):
    """T42: iCIMS writes "UNAVAILABLE" into empty fields (2,013 of 2,013 so
    spelled, 95 portals), and EMCOR lists places on separate lines in one."""
    if not isinstance(address, dict):
        return address
    return {k: " / ".join(dict.fromkeys(ln.strip() for ln in v.splitlines() if ln.strip())) if isinstance(v, str) else v
            for k, v in address.items() if v != "UNAVAILABLE"}


def posting_places(posting: dict) -> tuple[str | None, str | None]:
    where = posting.get("jobLocation")
    where = where if isinstance(where, list) else [where]
    return places([_address(w.get("address")) for w in where if isinstance(w, dict)],
                  "addressLocality", "addressRegion", "addressCountry", "addressCountry")


class ICIMS:
    """{portal}.icims.com (T37). robots.txt is per portal and 3 of 70 active ones
    forbid us, so the harvester reads each one's before fetching anything."""
    name = "icims"
    raw = True
    api_is_source = True  # a closed job's page answers 410 (5 of 6 checked)
    _HOST = re.compile(r"(?!www\.)([a-z0-9-]+)\.icims\.com")
    # Most links have no title slug: /jobs/{id}/job (125 of 130 active in Simplify)
    _JOB = re.compile(r"/jobs/(\d+)(?:/([^/]+))?/job/?")

    def _parts(self, url: str) -> tuple[str, str | None, str | None] | None:
        """(host, job id, title slug) of a link into a portal's /jobs/ pages."""
        p = urlparse(url)
        host = (p.hostname or "").lower()
        if not self._HOST.fullmatch(host) or not p.path.startswith("/jobs/"):
            return None
        m = self._JOB.fullmatch(p.path)
        return host, m and m.group(1), m and m.group(2)

    def match(self, url: str) -> bool:
        return bool((parts := self._parts(url)) and parts[1])

    def api_url(self, url: str) -> str:
        """The job itself; the bare URL is a 652 KB shell with no JSON-LD."""
        host, jid, slug = self._parts(url)
        return f"https://{host}/jobs/{jid}/{slug + '/' if slug else ''}job?in_iframe=1"

    def board_of(self, url: str) -> tuple[str, str] | None:
        """(slug, board URL) of a link into a portal's jobs; slug = the host label."""
        parts = self._parts(url)
        return (parts[0].split(".")[0], f"https://{parts[0]}") if parts else None

    def board(self, board_url: str) -> str:
        host = (urlparse(board_url).hostname or "").lower()
        if not self._HOST.fullmatch(host) or board_url.rstrip("/") != f"https://{host}":
            raise ValueError(f"not an iCIMS board: {board_url!r}")
        return f"https://{host}"

    def robots_url(self, board_url: str) -> str:
        return f"{self.board(board_url)}/robots.txt"

    def sitemap_url(self, board_url: str) -> str:
        return f"{self.board(board_url)}/sitemap.xml"

    def slug_title(self, url: str) -> str:
        """The title in a job link: it gave the same role verdict as the page's
        own title on 134 of 134 jobs (14 portals), so it picks what to fetch."""
        return unquote(self._parts(url)[2] or "").replace("-", " ")

    def job_id(self, url: str) -> int:
        return int(self._parts(url)[1])

    def faked(self, posting: dict, now: datetime) -> bool:
        """T41: 21 of 95 live portals send the moment of the request minus 2 years
        as datePosted (456 of 456 jobs within 1.5 s; one job read 02:17 and 03:42
        at those times). 730 or 731 days, as a Feb 29 falls between."""
        posted = parse_ats_date(posting.get("datePosted"))
        return bool(posted) and any(abs(now - posted - timedelta(days=d)) < timedelta(hours=1) for d in (730, 731))

    def parse(self, page: str, url: str) -> JdSource:
        posting = job_posting(page)
        if posting is None:
            raise ValueError("iCIMS page has no JobPosting")
        location, _ = posting_places(posting)
        return JdSource(
            text=_strip_html(posting.get("description") or ""),
            title=posting.get("title"),
            location=location,
            source_url=url,
            apply_url=url,
            adapter=self.name,
            posted_at=None if self.faked(posting, datetime.now(timezone.utc).replace(tzinfo=None))
            else (d := parse_ats_date(posting.get("datePosted"))) and d.date(),  # a date only
        )


ADAPTERS = [Workday(), Greenhouse(), Lever(), Ashby(), Oracle(), SmartRecruiters(), Eightfold(),
            Amazon(), Apple(), Workable(), ICIMS()]


def by_name(name: str):
    """A bare next() raises StopIteration, which inside a coroutine surfaces as an
    opaque "RuntimeError: coroutine raised StopIteration"."""
    try:
        return next(a for a in ADAPTERS if a.name == name)
    except StopIteration:
        raise LookupError(f"no ATS adapter named {name!r}") from None
