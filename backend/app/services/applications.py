"""File a finished tailoring run as an application.

The job store remains the run. Marking applied copies the tailored PDF (and .tex)
into DATA_DIR and records job id + that path, so the dashboard can serve the
résumé later without touching the original file.
"""

import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app import db
from app.core import config
from app.models import Application
from app.schemas.job import ApplicationOut, FiledStatus
from app.schemas.selector import ResumeInput
from app.services import jobs

PID = "default"

SAVED = ("draft", "ready")
FILED = ("applied", "interviewing", "offer", "rejected", "archived")


class InvalidStatus(Exception):
    """A status change the user is not allowed to make."""


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _safe(rel: str) -> Path:
    """Resolve a DATA_DIR-relative path and refuse anything that escapes it."""
    root = config.DATA_DIR.resolve()
    path = (root / rel).resolve()
    if path != root and root not in path.parents:
        raise ValueError("refusing to read outside DATA_DIR")
    return path


def _label(resumes: list[ResumeInput]) -> str | None:
    labels = [r.id for r in resumes if r.id]
    if not labels:
        return None
    return " · ".join(labels)[:240]


def _library_ids(resumes: list[ResumeInput]) -> list[str]:
    return [r.library_id for r in resumes if r.library_id]


def _exists(rel: str | None) -> bool:
    if not rel:
        return False
    try:
        return _safe(rel).is_file()
    except ValueError:
        return False


def _out(row: Application) -> ApplicationOut:
    ids = row.resume_ids if isinstance(row.resume_ids, list) else []
    filed = row.status in FILED
    saved_at = _utc(row.applied_at)
    return ApplicationOut(
        job_id=row.job_id,
        title=row.title,
        company=row.company,
        status=row.status,  # type: ignore[arg-type]
        saved_at=saved_at,
        applied_at=saved_at if filed else None,
        resume_label=row.resume_label,
        resume_ids=[str(i) for i in ids],
        apply_url=row.apply_url,
        has_tex=_exists(row.tex_path),
        has_pdf=_exists(row.pdf_path),
    )


def resume_file(job_id: str, kind: str) -> Path:
    """Absolute path to the archived résumé. Raises FileNotFoundError when missing."""
    with db.SessionLocal() as session:
        row = session.get(Application, job_id)
        if row is None or row.profile_id != PID:
            raise FileNotFoundError(job_id)
        rel = row.pdf_path if kind == "pdf" else row.tex_path
    if not rel:
        raise FileNotFoundError(job_id)
    try:
        path = _safe(rel)
    except ValueError as e:
        raise FileNotFoundError(job_id) from e
    if not path.is_file():
        raise FileNotFoundError(rel)
    return path


def list_bucket(bucket: str) -> list[ApplicationOut]:
    statuses = FILED if bucket == "filed" else SAVED
    with db.SessionLocal() as session:
        rows = session.scalars(
            select(Application)
            .where(Application.profile_id == PID, Application.status.in_(statuses))
            .order_by(Application.applied_at.desc())
        ).all()
        return [_out(r) for r in rows]


def list_applied() -> list[ApplicationOut]:
    return list_bucket("filed")


def open_draft(job_id: str) -> None:
    """Record a run as saved-but-not-applied. The résumé stays on the job until it is ready."""
    job, jd_text, resumes = jobs.store.snapshot(job_id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with db.SessionLocal() as session:
        if session.get(Application, job_id) is not None:
            return
        session.add(Application(
            job_id=job_id,
            profile_id=PID,
            title=job.title or jobs._title(jd_text),
            company=job.company,
            status="draft",
            applied_at=now,
            pdf_path="",
            resume_label=_label(resumes),
            resume_ids=_library_ids(resumes) or None,
            apply_url=job.apply_url,
        ))
        session.commit()


def note_ready(job_id: str) -> None:
    """Copy the current tailored résumé and mark a saved run ready. Filed rows keep their snapshot."""
    job, jd_text, resumes = jobs.store.snapshot(job_id)
    if job.status != "done" or job.result is None or not job_id.isalnum():
        return
    src = Path(job.result.pdf_path)
    if not src.is_file():
        return
    rel_pdf = f"applications/{job_id}/resume.pdf"
    rel_tex = f"applications/{job_id}/resume.tex"
    dest_pdf = _safe(rel_pdf)
    dest_tex = _safe(rel_tex)
    with db.SessionLocal() as session:
        row = session.get(Application, job_id)
        if row is not None and row.status in FILED:
            return
        dest_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest_pdf)
        # A PDF-sourced run's `tex` field is plain text, not a LaTeX source.
        if job.result.tex and job.result.kind != "pdf":
            dest_tex.write_text(job.result.tex)
        label = _label(resumes)
        ids = _library_ids(resumes) or None
        title = job.title or jobs._title(jd_text)
        if row is None:
            session.add(Application(
                job_id=job_id,
                profile_id=PID,
                title=title,
                company=job.company,
                status="ready",
                applied_at=datetime.now(timezone.utc).replace(tzinfo=None),
                pdf_path=rel_pdf,
                tex_path=rel_tex if dest_tex.is_file() else None,
                resume_label=label,
                resume_ids=ids,
                apply_url=job.apply_url,
            ))
        else:
            row.status = "ready"
            row.title = title
            row.company = job.company
            row.pdf_path = rel_pdf
            row.tex_path = rel_tex if dest_tex.is_file() else None
            row.resume_label = label
            row.resume_ids = ids
            row.apply_url = job.apply_url
        session.commit()


def set_status(job_id: str, status: FiledStatus) -> ApplicationOut:
    """Move a filed application among later stages. Draft and ready stay on Mark applied."""
    if status not in FILED:
        raise InvalidStatus(status)
    with db.SessionLocal() as session:
        row = session.get(Application, job_id)
        if row is None or row.profile_id != PID:
            raise FileNotFoundError(job_id)
        if row.status not in FILED:
            raise InvalidStatus(row.status)
        row.status = status
        session.commit()
        session.refresh(row)
        out = _out(row)
    try:
        job = jobs.store.get(job_id)
    except jobs.JobNotFound:
        return out
    job.applied = True
    return out


def mark_applied(job_id: str) -> ApplicationOut:
    """Copy the tailored résumé into DATA_DIR and record the application.

    A second mark keeps the résumé bytes from the first mark — that is the
    file the user applied with. The source PDF is copied, not moved.
    """
    job, jd_text, resumes = jobs.store.snapshot(job_id)
    if job.status != "done" or job.result is None:
        raise jobs.JobNotDone(job_id)
    src = Path(job.result.pdf_path)
    if not src.is_file():
        raise FileNotFoundError(f"tailored PDF not found: {src}")
    if not job_id.isalnum():
        raise jobs.JobNotFound(job_id)

    rel_pdf = f"applications/{job_id}/resume.pdf"
    rel_tex = f"applications/{job_id}/resume.tex"
    dest_pdf = _safe(rel_pdf)
    dest_tex = _safe(rel_tex)
    dest_pdf.parent.mkdir(parents=True, exist_ok=True)
    # Keep the first snapshot. Never replace it, and never delete `src`.
    if not dest_pdf.exists():
        shutil.copyfile(src, dest_pdf)
    if not dest_pdf.is_file() or dest_pdf.stat().st_size == 0:
        raise FileNotFoundError(f"tailored PDF not found: {dest_pdf}")
    if job.result.tex and job.result.kind != "pdf" and not dest_tex.exists():
        dest_tex.write_text(job.result.tex)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with db.SessionLocal() as session:
        row = session.get(Application, job_id)
        if row is None:
            row = Application(
                job_id=job_id,
                profile_id=PID,
                title=job.title or jobs._title(jd_text),
                company=job.company,
                status="applied",
                applied_at=now,
                pdf_path=rel_pdf,
                tex_path=rel_tex if dest_tex.is_file() else None,
                resume_label=_label(resumes),
                resume_ids=_library_ids(resumes) or None,
                apply_url=job.apply_url,
            )
            session.add(row)
        elif row.status in SAVED:
            row.status = "applied"
            row.applied_at = now
            if not row.pdf_path:
                row.pdf_path = rel_pdf
            if not row.tex_path and dest_tex.is_file():
                row.tex_path = rel_tex
            if not row.resume_label:
                row.resume_label = _label(resumes)
            if not row.resume_ids:
                row.resume_ids = _library_ids(resumes) or None
            if not row.apply_url:
                row.apply_url = job.apply_url
        session.commit()
        session.refresh(row)
        out = _out(row)

    job.applied = True
    job.applied_at = out.applied_at
    return out
