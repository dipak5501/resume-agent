"""In-memory job store + runner. The job API is the seam (design §10): swap this
for Redis/Celery later without touching the routers. ponytail: single-process,
in-memory, threads/GIL — fine for the MVP."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import OUTER_LOOP_MAX
from app.schemas.job import Job, JobSummary, RoundEntry
from app.schemas.pipeline import PipelineResult
from app.schemas.selector import ResumeInput
from app.services.pipeline import run_pipeline


class JobError(Exception):
    """Base for job-store errors the router maps to HTTP codes."""


class JobNotFound(JobError):
    pass


class JobNotDone(JobError):
    pass


class FeedbackLimitReached(JobError):
    pass


@dataclass
class _Record:
    job: Job
    jd_text: str
    resumes: list[ResumeInput]
    pending_feedback: str | None = None
    prior: PipelineResult | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


NO_CHANGE_NOTE = "no change made - round not counted"
REVISION_FAILED = "revision failed, nothing changed"  # prefix: the cause is appended


def _round_entry(index: int, feedback: str | None, result: PipelineResult, prev: list[RoundEntry]):
    """One slip for the proof-rounds timeline. Delta is vs the previous round, so
    round 0 has none (its before→after lives in the score headline)."""
    overall = result.report.ats_after.overall
    return RoundEntry(
        index=index,
        kind="revision" if feedback else "initial",
        feedback=feedback,
        summary=result.report.summary,
        ats_overall=overall,
        ats_delta=None if not prev else overall - prev[-1].ats_overall,
        changes=result.report.changes,
        added=result.report.added,
    )


def _title(jd_text: str) -> str:
    """First non-empty JD line (trimmed) so the user recognizes the run."""
    for line in jd_text.splitlines():
        if line.strip():
            return line.strip()[:80]
    return "Untitled run"


class JobStore:
    def __init__(self) -> None:
        self._recs: dict[str, _Record] = {}

    def create(
        self, jd_text: str, resumes: list[ResumeInput], apply_url: str | None = None,
        title: str | None = None, company: str | None = None,
    ) -> Job:
        job = Job(id=uuid4().hex, apply_url=apply_url, title=title, company=company)
        self._recs[job.id] = _Record(job=job, jd_text=jd_text, resumes=resumes)
        return job

    def get(self, job_id: str) -> Job:
        rec = self._recs.get(job_id)
        if rec is None:
            raise JobNotFound(job_id)
        return rec.job

    def list(self) -> list[JobSummary]:
        """Recent runs, newest first — the extension's run picker (T12)."""
        return [
            JobSummary(
                id=rec.job.id,
                title=rec.job.title or _title(rec.jd_text),
                status=rec.job.status,
                created_at=rec.created_at,
                has_pdf=rec.job.result is not None,
                company=rec.job.company,
                applied=rec.job.applied,
            )
            for rec in reversed(self._recs.values())
        ]

    def snapshot(self, job_id: str) -> tuple[Job, str, Sequence[ResumeInput]]:
        """(job, jd_text, source résumés) for filing an application."""
        rec = self._recs.get(job_id)
        if rec is None:
            raise JobNotFound(job_id)
        return rec.job, rec.jd_text, rec.resumes

    def grounding(self, job_id: str) -> tuple[str, str]:
        """(jd_text, tailored_tex) for the screening answerer (T13). Empty
        strings when the job is missing or not finished — the caller degrades
        gracefully rather than raising."""
        rec = self._recs.get(job_id)
        if rec is None or rec.job.result is None:
            return "", ""
        return rec.jd_text, rec.job.result.tex

    def request_feedback(self, job_id: str, feedback: str) -> Job:
        """Queue another improve round on a finished job (capped at OUTER_LOOP_MAX)."""
        rec = self._recs.get(job_id)
        if rec is None:
            raise JobNotFound(job_id)
        if rec.job.status != "done":
            raise JobNotDone(job_id)
        if rec.job.round >= OUTER_LOOP_MAX:
            raise FeedbackLimitReached(job_id)
        rec.pending_feedback = feedback
        rec.prior = rec.job.result
        rec.job.round += 1
        rec.job.status = "queued"
        return rec.job

    def run(self, job_id: str) -> None:
        """Execute the pipeline for a queued job. Called from a background task."""
        rec = self._recs[job_id]
        rec.job.status = "running"
        rec.job.progress = []
        feedback = rec.pending_feedback
        try:
            result = run_pipeline(
                rec.jd_text,
                rec.resumes,
                feedback=feedback,
                prior=rec.prior,
                on_progress=rec.job.progress.append,
            )
            # Honest round accounting (T22): a revision that changed nothing costs
            # no round and leaves no slip on the timeline.
            if feedback and rec.prior is not None and result.tex == rec.prior.tex:
                rec.job.round = max(0, rec.job.round - 1)
                result.report.warnings.append(NO_CHANGE_NOTE)
            else:
                rec.job.rounds.append(
                    _round_entry(rec.job.round, feedback, result, rec.job.rounds)
                )
            rec.job.result = result
            rec.job.status = "done"
            rec.prior = result
            rec.pending_feedback = None
            _record_ready(job_id)
        except Exception as e:  # never let a worker thread die silently
            # A failed REVISION must not cost the user the proof they already have
            # (a transient LLM/network blip is the common case). Fall back to the
            # last good result, hand the round back, and say what happened. A first
            # pass has nothing to fall back to, so it still surfaces as an error.
            if feedback and rec.prior is not None:
                rec.job.round = max(0, rec.job.round - 1)
                rec.job.result = rec.prior
                rec.job.status = "done"
                rec.pending_feedback = None
                notes = rec.prior.report.warnings
                notes[:] = [n for n in notes if not n.startswith(REVISION_FAILED)]
                notes.append(f"{REVISION_FAILED}: {e}")
                _record_ready(job_id)
            else:
                rec.job.status = "error"
                rec.job.error = str(e)


def _record_ready(job_id: str) -> None:
    """File the tailored résumé on the saved list. A tracking failure must not fail the run."""
    from app.services import applications

    try:
        applications.note_ready(job_id)
    except Exception:
        import logging
        logging.getLogger(__name__).warning("could not record a ready résumé for %s", job_id)


store = JobStore()  # module-level singleton the routers share
