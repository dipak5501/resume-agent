from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import JobPosting, TrackedCompany
from app.schemas.board import BoardFeedOut, JobPostingOut
from app.schemas.jd import JdSource
from app.services import board_policy, board_sync, jd_fetch

router = APIRouter(prefix="/board", tags=["board"])

@router.get("", response_model=BoardFeedOut)
def get_board_feed(
    # Unbounded before: ?limit=100000 returned all 1925 rows in one response, and
    # page=0 produced a negative offset.
    page: int = Query(1, ge=1, le=2**31 - 1),  # also keep SQL OFFSET in integer range
    limit: int = Query(50, ge=1, le=200),
    # The profile has no level. Full-time is the default; internships stay stored
    # and show only when this is asked for.
    include_interns: bool = Query(False),
    db: Session = Depends(get_db),
):
    offset = (page - 1) * limit
    newest_first = (JobPosting.created_at.desc(), JobPosting.url.asc())
    # One card per role: employers post a requisition per opening (Crane's three
    # identical Co-Ops, 2026-09-28), so same company + title + place is one job
    # to the user. The newest posting stands for the group; the rest are counted.
    role = (JobPosting.company_slug, func.lower(func.trim(JobPosting.title)),
            func.lower(func.trim(func.coalesce(JobPosting.location, ""))))  # no place = one place, on any DB
    eligible = board_policy.eligible_postings()
    if not include_interns:
        eligible = (*eligible, ~board_sync.internship_clause())
    cards = (
        select(JobPosting.url,
               func.row_number().over(partition_by=role, order_by=newest_first).label("rank"),
               func.count().over(partition_by=role).label("openings"))
        .where(*eligible)
        .subquery()
    )
    shown = cards.c.rank == 1

    total_count = db.execute(select(func.count()).select_from(cards).where(shown)).scalar()

    rows = db.execute(
        select(JobPosting, cards.c.openings, TrackedCompany.name, TrackedCompany.provider)
        .join(cards, cards.c.url == JobPosting.url)
        .outerjoin(TrackedCompany, JobPosting.company_slug == TrackedCompany.slug)
        .where(shown)
        .order_by(*newest_first)
        .offset(offset)
        .limit(limit)
    ).all()

    has_more = (offset + limit) < total_count
    total_pages = (total_count + limit - 1) // limit

    return BoardFeedOut(
        jobs=[JobPostingOut.model_validate(j).model_copy(update={
            "company_name": name, "date_only": provider in board_sync.DATE_ONLY, "openings": openings})
            for j, openings, name, provider in rows],
        has_more=has_more,
        total_pages=total_pages
    )


class ResolvePostingIn(BaseModel):
    url: str


def _available_posting(db: Session, url: str) -> JobPosting:
    # Bypass the session identity cache: harvest/retention may have committed
    # another version while this request was waiting for a remote description.
    posting = db.get(JobPosting, url, populate_existing=True)
    if posting is None:
        raise HTTPException(404, "This listing is no longer on the Board.")
    if not board_policy.is_recent(posting.created_at):
        raise HTTPException(410, "This listing is outside the Board's 14-day window.")
    if posting.status != "open":
        raise HTTPException(410, "This job is no longer available.")
    return posting


@router.get("/delays")
def get_discovery_delays(days: int = Query(7, ge=1, le=14), db: Session = Depends(get_db)) -> dict:
    """T46: minutes from posting to first sight, per vendor (14 = retention)."""
    return board_sync.discovery_delays(db, days)


@router.post("/resolve", response_model=JdSource)
def resolve_posting(body: ResolvePostingIn, db: Session = Depends(get_db)):
    posting = _available_posting(db, body.url)
    try:
        source = jd_fetch.fetch_jd_from_url(posting.url)
    except jd_fetch.JdUnavailable as e:
        # Retention may delete the row while the network request is in flight.
        db.execute(update(JobPosting).where(JobPosting.url == body.url).values(status="closed"))
        db.commit()
        raise HTTPException(410, str(e)) from e
    except (jd_fetch.JdFetchError, ValueError) as e:
        raise HTTPException(502, "Couldn't check this posting right now. Please retry.") from e
    if len(source.text.strip()) < jd_fetch.config.JD_MIN_CHARS:
        # A 200 containing an empty careers shell is not proof of closure.
        raise HTTPException(502, "Couldn't read a full job description. Retry or paste it below.")
    # Recheck both elapsed age and concurrent changes before handing off the JD.
    _available_posting(db, body.url)
    return source
