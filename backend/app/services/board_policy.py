"""One posting-age policy for ingestion, feed reads and retention (T26)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_

from app.models import JobPosting

MAX_AGE = timedelta(days=14)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_recent(posted_at: datetime, now: datetime | None = None) -> bool:
    now = now if now is not None else utcnow()
    return now - MAX_AGE < posted_at <= now


def eligible_postings(now: datetime | None = None):
    now = now if now is not None else utcnow()
    return (
        JobPosting.status == "open",
        JobPosting.created_at > now - MAX_AGE,
        JobPosting.created_at <= now,
    )


def prune_postings(session, now: datetime | None = None) -> int:
    """Both open and closed postings expire by publication, never last-seen.

    Caller owns the transaction. Company tracking and personal data are untouched.
    Existing stored dates are accepted until re-harvested (user-approved tradeoff).
    """
    now = now if now is not None else utcnow()
    result = session.execute(delete(JobPosting).where(or_(
        JobPosting.created_at <= now - MAX_AGE,
        JobPosting.created_at > now,
    )))
    return result.rowcount
