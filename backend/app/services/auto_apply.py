"""One selected run, and only when the user turned Auto-apply on.

The extension fills the form and submits it. This module arms that single run
and, after a submit the extension reports as accepted, logs it with the résumé
already stored. A blocked page or an unknown required field is not logged.
There is one arm slot — never a queue of jobs.
"""

from urllib.parse import urlparse

from app import db
from app.models import Profile
from app.schemas.job import ApplicationOut
from app.services import applications, jobs

PID = "default"
_armed: dict[str, str] = {}


class AutoApplyRefused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def enabled() -> bool:
    with db.SessionLocal() as session:
        profile = session.get(Profile, PID)
        return bool(profile and profile.auto_apply)


def set_enabled(on: bool) -> bool:
    with db.SessionLocal() as session:
        profile = session.get(Profile, PID)
        if profile is None:
            raise AutoApplyRefused("No profile.")
        profile.auto_apply = bool(on)
        session.commit()
        return bool(profile.auto_apply)


def _same_application(page_url: str, apply_url: str | None) -> bool:
    if not apply_url:
        return False
    try:
        page = urlparse(page_url)
        apply = urlparse(apply_url)
    except ValueError:
        return False
    if page.scheme not in ("http", "https") or page.netloc.lower() != apply.netloc.lower():
        return False
    left = page.path.rstrip("/") or "/"
    right = apply.path.rstrip("/") or "/"
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def _ready_job(job_id: str):
    job = jobs.store.get(job_id)
    if job.status != "done" or job.result is None:
        raise jobs.JobNotDone(job_id)
    if not job.apply_url:
        raise AutoApplyRefused("This run has no apply link.")
    return job


def arm(job_id: str) -> dict[str, str]:
    if not enabled():
        raise AutoApplyRefused("Auto-apply is off.")
    job = _ready_job(job_id)
    _armed[PID] = job_id
    return {"job_id": job_id, "apply_url": job.apply_url or ""}


def claim(page_url: str) -> dict[str, str | None]:
    """Hand the armed run to the page that matches its apply link, once."""
    job_id = _armed.get(PID)
    if not job_id or not enabled():
        return {"job_id": None, "apply_url": None}
    try:
        job = jobs.store.get(job_id)
    except jobs.JobNotFound:
        _armed.pop(PID, None)
        return {"job_id": None, "apply_url": None}
    if not _same_application(page_url, job.apply_url):
        return {"job_id": None, "apply_url": None}
    _armed.pop(PID, None)
    return {"job_id": job_id, "apply_url": job.apply_url}


def finish(
    job_id: str,
    *,
    submitted: bool,
    unknown_required: list[str],
    blocked: str | None,
) -> ApplicationOut:
    if _armed.get(PID) == job_id:
        _armed.pop(PID, None)
    if not enabled():
        raise AutoApplyRefused("Auto-apply is off.")
    if blocked:
        raise AutoApplyRefused("Left unsubmitted. This page could not be filled reliably.")
    if any(item.strip() for item in unknown_required):
        raise AutoApplyRefused("Left unsubmitted. A required field is unknown.")
    if not submitted:
        raise AutoApplyRefused("Left unsubmitted.")
    _ready_job(job_id)
    return applications.mark_applied(job_id)
