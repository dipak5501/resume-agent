"""Job API — the stable seam the frontend drives. POST a JD plus résumé .tex
or PDF files, poll status/result, request feedback rounds, download the final PDF."""

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import db
from app.db import get_db
from app.models import Profile, Resume
from app.routers.profile import PID
from app.schemas.job import ApplicationOut, ChatIn, ChatOut, ChatTurn, FitNote, Job, JobAnswer, JobSummary
from app.schemas.selector import ResumeInput
from app.services import answerer, applications, auto_apply, fit, jobs, local_save, storage
from app.services.resume_parse import PDF_NO_TEXT, is_pdf_upload, pdf_text

router = APIRouter()


class FeedbackIn(BaseModel):
    feedback: str


class QuestionIn(BaseModel):
    question: str


def _resume_input(
    name: str,
    data: bytes,
    filename: str | None,
    content_type: str | None,
    library_id: str | None = None,
) -> ResumeInput:
    """A .tex upload stays LaTeX. A PDF becomes its extracted text — the tailor
    rewrites that text and lays out a new page. It is not compiled as LaTeX."""
    if is_pdf_upload(filename, content_type, data):
        text = pdf_text(data)
        if not text:
            raise HTTPException(status_code=400, detail=PDF_NO_TEXT)
        return ResumeInput(id=name, tex=text, library_id=library_id, kind="pdf")
    return ResumeInput(
        id=name,
        tex=data.decode("utf-8", "replace"),
        library_id=library_id,
        kind="tex",
    )


def _resumes_from_library(resume_ids: list[str]) -> list[ResumeInput]:
    """Resolve library résumé ids → ResumeInput. PDF and .tex are both sources."""
    out = []
    with db.SessionLocal() as session:
        for rid in resume_ids:
            r = session.get(Resume, rid)
            if r is None or r.profile_id != PID:
                raise HTTPException(status_code=404, detail=f"résumé not found: {rid}")
            name = r.label or r.filename or r.id
            if r.format == "pdf":
                data = storage.open_resume_file(PID, rid, "source.pdf")
                out.append(_resume_input(name, data, "source.pdf", "application/pdf", library_id=r.id))
            else:
                data = storage.open_resume_file(PID, rid, "source.tex")
                out.append(_resume_input(name, data, r.filename or "source.tex", "text/plain", library_id=r.id))
    return out


@router.post("/jobs")
async def create_job(
    background: BackgroundTasks,
    jd: str = Form(...),
    resume_ids: list[str] = Form(default=[]),
    files: list[UploadFile] = File(default=[]),
    apply_url: str | None = Form(default=None),  # T16: adapter's apply URL (link JDs only)
    title: str | None = Form(default=None),  # T32: adapter's posting title (link JDs only)
    company: str | None = Form(default=None),
) -> dict[str, str]:
    # ad-hoc upload (as today) OR pick from the library — mirrors JD paste-or-link
    if files:
        resumes = []
        for i, f in enumerate(files):
            data = await f.read()
            resumes.append(_resume_input(f.filename or f"resume{i}", data, f.filename, f.content_type))
        if not resumes:
            raise HTTPException(status_code=400, detail="provide resume_ids or files")
    elif resume_ids:
        resumes = _resumes_from_library(resume_ids)
    else:
        raise HTTPException(status_code=400, detail="provide resume_ids or files")
    job = jobs.store.create(
        jd, resumes, apply_url=apply_url or None, title=title or None,
        company=(company or "").strip() or None,
    )
    applications.open_draft(job.id)
    background.add_task(jobs.store.run, job.id)
    return {"job_id": job.id}


@router.get("/jobs")
def list_jobs() -> list[JobSummary]:
    """Recent tailored runs for the extension's picker (T12)."""
    return jobs.store.list()


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> Job:
    try:
        return jobs.store.get(job_id)
    except jobs.JobNotFound:
        raise HTTPException(status_code=404, detail="job not found")


@router.post("/jobs/{job_id}/feedback")
def post_feedback(job_id: str, body: FeedbackIn, background: BackgroundTasks) -> dict:
    try:
        job = jobs.store.request_feedback(job_id, body.feedback)
    except jobs.JobNotFound:
        raise HTTPException(status_code=404, detail="job not found")
    except jobs.JobNotDone:
        raise HTTPException(status_code=409, detail="job is not finished yet")
    except jobs.FeedbackLimitReached:
        raise HTTPException(status_code=429, detail="feedback limit reached")
    background.add_task(jobs.store.run, job_id)
    return {"job_id": job.id, "round": job.round}


@router.post("/jobs/{job_id}/answer")
def post_answer(job_id: str, body: QuestionIn, session: Session = Depends(get_db)) -> JobAnswer:
    """Draft an answer to an application question (T24), grounded on THIS run's
    tailored résumé, and append it to the run's answers log. Deliberately never
    touches `round` — answering and revising are separate concerns."""
    try:
        job = jobs.store.get(job_id)
    except jobs.JobNotFound:
        raise HTTPException(status_code=404, detail="job not found")
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="ask a question")
    res = answerer.answer(question, job_id, host=answerer.WEBAPP_HOST, session=session)
    entry = JobAnswer(**res.model_dump(), question=question, save_mode=answerer.save_mode(res.canonical))
    job.answers.append(entry)
    return entry


@router.get("/jobs/{job_id}/pdf")
def get_pdf(job_id: str):
    try:
        job = jobs.store.get(job_id)
    except jobs.JobNotFound:
        raise HTTPException(status_code=404, detail="job not found")
    if job.result is None:
        raise HTTPException(status_code=404, detail="no PDF yet")
    # inline so the UI can render it in an <iframe>; the download button's
    # `download` attribute still forces a save client-side.
    return FileResponse(
        job.result.pdf_path,
        media_type="application/pdf",
        filename="resume.pdf",
        content_disposition_type="inline",
    )


@router.post("/jobs/{job_id}/save-local")
def save_local(job_id: str):
    """Copy the tailored PDF into tailored-resume/ + upsert the tracker CSV
    (LOCAL-DEV ONLY). Company/position are extracted from the JD."""
    try:
        job = jobs.store.get(job_id)
    except jobs.JobNotFound:
        raise HTTPException(status_code=404, detail="job not found")
    if job.result is None:
        raise HTTPException(status_code=409, detail="run isn't finished yet")
    jd_text, _ = jobs.store.grounding(job_id)
    with db.SessionLocal() as session:
        p = session.get(Profile, PID)
        name = p.name if p else None
    try:
        return local_save.save_local(job, jd_text, name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/jobs/{job_id}/fit")
def get_fit(job_id: str) -> FitNote:
    try:
        return fit.fit_note(job_id)
    except jobs.JobNotFound:
        raise HTTPException(status_code=404, detail="job not found")
    except jobs.JobNotDone:
        raise HTTPException(status_code=409, detail="résumé is not ready")


@router.post("/jobs/{job_id}/chat")
def post_chat(job_id: str, body: ChatIn) -> ChatOut:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="ask a question")
    try:
        answer = fit.chat(job_id, message)
    except jobs.JobNotFound:
        raise HTTPException(status_code=404, detail="job not found")
    except jobs.JobNotDone:
        raise HTTPException(status_code=409, detail="résumé is not ready")
    except ValueError:
        raise HTTPException(status_code=400, detail="ask a question")
    job = jobs.store.get(job_id)
    job.chat.append(ChatTurn(role="user", content=message))
    job.chat.append(ChatTurn(role="assistant", content=answer))
    return ChatOut(answer=answer)


class AutoApplyFinish(BaseModel):
    submitted: bool = False
    unknown_required: list[str] = []
    blocked: str | None = None


class ClaimIn(BaseModel):
    page_url: str


@router.post("/jobs/{job_id}/auto-apply/arm")
def arm_auto_apply(job_id: str) -> dict[str, str]:
    """Arm one run. The extension submits it; this does not submit by itself."""
    try:
        return auto_apply.arm(job_id)
    except jobs.JobNotFound:
        raise HTTPException(status_code=404, detail="job not found")
    except jobs.JobNotDone:
        raise HTTPException(status_code=409, detail="résumé is not ready")
    except auto_apply.AutoApplyRefused as e:
        raise HTTPException(status_code=409, detail=e.reason)


@router.post("/auto-apply/claim")
def claim_auto_apply(body: ClaimIn) -> dict[str, str | None]:
    return auto_apply.claim(body.page_url)


@router.post("/jobs/{job_id}/auto-apply/finish")
def finish_auto_apply(job_id: str, body: AutoApplyFinish) -> ApplicationOut:
    try:
        return auto_apply.finish(
            job_id,
            submitted=body.submitted,
            unknown_required=body.unknown_required,
            blocked=body.blocked,
        )
    except jobs.JobNotFound:
        raise HTTPException(status_code=404, detail="job not found")
    except jobs.JobNotDone:
        raise HTTPException(status_code=409, detail="résumé is not ready")
    except auto_apply.AutoApplyRefused as e:
        raise HTTPException(status_code=409, detail=e.reason)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="tailored PDF not found")


@router.post("/jobs/{job_id}/applied")
def mark_applied(job_id: str) -> ApplicationOut:
    """Mark a finished run as applied and keep the résumé used for it."""
    try:
        return applications.mark_applied(job_id)
    except jobs.JobNotFound:
        raise HTTPException(status_code=404, detail="job not found")
    except jobs.JobNotDone:
        raise HTTPException(status_code=409, detail="job is not finished yet")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="tailored PDF not found")
