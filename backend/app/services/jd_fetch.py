"""Fetch a JD from a URL (T10): dispatch to a matching ATS adapter, else the
generic HTML-extraction path. Every network call goes through the SSRF guard —
this is a real trust boundary (the generic path takes arbitrary user hosts)."""

import ipaddress
import json
import socket
from urllib.parse import urljoin, urlparse

import httpx

from app.core import config
from app.schemas.jd import JdSource
from app.services import jd_adapters, jd_screen, llm

_UA = "Mozilla/5.0 (compatible; resume-agent/1.0; +jd-fetch)"


class JdFetchError(Exception):
    """Bad/blocked URL or unfetchable page — surfaced as 4xx by the router."""

    def __init__(self, message: str, *, status_code: int | None = None, body: bytes = b""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body  # the start of an error response, for gone() below


class JdUnavailable(JdFetchError):
    """Both the ATS and posting-page fallback confirm the posting is gone."""


def _resolve_ips(host: str) -> set[str]:
    try:
        return {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as e:
        raise JdFetchError(f"could not resolve host: {host}") from e


def _check_url(url: str) -> None:
    """Allow only http(s) to a public host. Blocks SSRF into loopback, private,
    link-local (incl. 169.254.169.254 cloud metadata), and reserved ranges."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise JdFetchError("only http(s) URLs are allowed")
    if not p.hostname:
        raise JdFetchError("URL has no host")
    for ip in _resolve_ips(p.hostname):
        addr = ipaddress.ip_address(ip)
        # ponytail: lean on stdlib classification instead of hardcoding CIDRs —
        # covers 127/8, 10/8, 172.16/12, 192.168/16, 169.254/16, ::1, fc00::/7.
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            raise JdFetchError(f"blocked non-public address: {ip}")


def _guarded_get(url: str, *, transport: httpx.BaseTransport | None = None) -> bytes:
    """SSRF-guarded GET with manual redirect handling (re-check every hop),
    a redirect cap, timeout, and a streamed response-size cap.
    `transport` is a test seam. ponytail: no DNS-rebind pin between check and
    connect — add IP-pinned transport if that threat matters."""
    client = httpx.Client(
        follow_redirects=False, timeout=config.JD_FETCH_TIMEOUT,
        headers={"User-Agent": _UA}, transport=transport,
    )
    try:
        for _ in range(config.JD_FETCH_MAX_REDIRECTS + 1):
            _check_url(url)
            with client.stream("GET", url) as resp:
                if resp.is_redirect:
                    loc = resp.headers.get("location")
                    if not loc:
                        raise JdFetchError("redirect without a location")
                    url = urljoin(url, loc)
                    continue
                if resp.status_code >= 400:
                    raise JdFetchError(f"fetch failed: HTTP {resp.status_code}", status_code=resp.status_code,
                                       body=next(resp.iter_bytes(1024), b""))
                total, chunks = 0, []
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > config.JD_FETCH_MAX_BYTES:
                        raise JdFetchError("response too large")
                    chunks.append(chunk)
                return b"".join(chunks)
        raise JdFetchError("too many redirects")
    except httpx.HTTPError as e:
        raise JdFetchError(f"could not fetch URL: {e}") from e
    finally:
        client.close()


def fetch_jd_from_url(url: str) -> JdSource:
    source = _fetch(url.strip())
    source.screen = jd_screen.screen(source.text)  # T39: shown above the JD
    return source


def _fetch(url: str) -> JdSource:
    ats_missing = False
    for adapter in jd_adapters.ADAPTERS:
        if adapter.match(url):
            try:
                body = _guarded_get(adapter.api_url(url))
                if getattr(adapter, "raw", False):
                    return adapter.parse(body.decode("utf-8", "replace"), url)
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError("invalid ATS posting: expected an object")
                return adapter.parse(data, url)
            except (JdFetchError, ValueError) as e:
                # The public API can 404 even when the posting is live — e.g. an
                # UNLISTED/confidential posting (reachable by direct link, absent
                # from the API), an API disabled for that org, or an outage. The
                # posting PAGE still carries the JD, so fall back to scraping it.
                ats_missing = isinstance(e, JdFetchError) and _gone(e)
                if ats_missing and getattr(adapter, "api_is_source", False):
                    # T36: that page is a shell over this same source (Workday
                    # always answers 200), so there is nothing left to scrape.
                    raise JdUnavailable("This job is no longer available.", status_code=410) from e
                break
    try:
        return _generic(url)
    except JdFetchError as e:
        if ats_missing and e.status_code in (404, 410):
            raise JdUnavailable("This job is no longer available.", status_code=410) from e
        raise


def _gone(e: JdFetchError) -> bool:
    """404/410, or Workday's answer for a closed job: a JSON 403 "S22 permission
    denied" (9 of 10 closed postings, 2026-09-24). A CDN's 403 is HTML."""
    return e.status_code in (404, 410) or (e.status_code == 403 and b'"errorCode":"S22"' in e.body)


def _generic(url: str) -> JdSource:
    import trafilatura

    body = _guarded_get(url)
    text = (trafilatura.extract(body.decode("utf-8", "replace")) or "").strip()
    warnings: list[str] = []
    if len(text) >= config.JD_MIN_CHARS and config.OLLAMA_API_KEY:
        text = _llm_cleanup(text) or text
    # Checked AFTER cleanup too: a JS-rendered careers page (e.g. a branded
    # Greenhouse ?gh_jid= link) yields only nav chrome, which the LLM correctly
    # reduces to a one-line "no job description found".
    if len(text) < config.JD_MIN_CHARS:
        warnings.append("Couldn't extract a clear job description from this page — please paste it.")
    return JdSource(text=text, source_url=url, adapter="generic", warnings=warnings)


def _llm_cleanup(text: str) -> str:
    """Best-effort: strip any leftover page boilerplate. Human reviews the JD
    before running, so failures here are non-fatal — fall back to raw extract.
    gemma won't honor `format`, so use sentinels."""
    prompt = (
        "Below is text scraped from a job posting page. Return ONLY the job "
        "description (role, responsibilities, requirements), dropping site "
        "navigation, cookie/legal boilerplate, and 'apply' chrome. Wrap the "
        "result between <<<JD>>> and <<<END>>>.\n\n" + text
    )
    try:
        out = llm.chat([{"role": "user", "content": prompt}])
        m = out.split("<<<JD>>>", 1)
        return m[1].split("<<<END>>>", 1)[0].strip() if len(m) == 2 else ""
    except Exception:
        return ""
