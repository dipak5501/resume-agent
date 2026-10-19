from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.answer import AnswerResult, Mode
from app.schemas.pipeline import PipelineResult

JobStatus = Literal["queued", "running", "done", "error"]


class RoundEntry(BaseModel):
    """One proof round on the timeline (T22). Informational: the PDF is always the
    latest round - viewing/reverting an old one is a future ticket."""

    index: int  # 0 = the initial tailoring
    kind: Literal["initial", "revision"]
    feedback: str | None = None  # the user's prompt, echoed back on revision rounds
    summary: str = ""  # the improver's 2-3 line brief of what this round did
    ats_overall: int
    ats_delta: int | None = None  # vs the previous round; None for round 0
    changes: list[str] = []
    added: list[str] = []


class JobAnswer(AnswerResult):
    """One drafted application answer on this run's log (T24). Grounded on THIS
    job's tailored résumé, so it stays true to the résumé it accompanies - which
    is why the log lives on the run and not in the cross-job answer bank."""

    question: str
    # Bank mode to default to IF the user promotes this for cross-job reuse:
    # facts are about the person (safe verbatim), prose must stay adaptable so it
    # gets re-grounded on each new job's résumé. Derived from the category.
    save_mode: Mode = "adaptable"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class Job(BaseModel):
    id: str
    status: JobStatus = "queued"
    progress: list[str] = []
    result: PipelineResult | None = None
    error: str | None = None
    round: int = 0  # completed improve rounds (0 = first pass), capped at OUTER_LOOP_MAX
    rounds: list[RoundEntry] = []  # T22: the full round history, oldest first
    apply_url: str | None = None  # T16: the ATS apply form, when the JD came from a link (not a paste)
    title: str | None = None  # T32: the ATS posting title, when the JD came from a link
    company: str | None = None  # hiring company, when the JD came from a link
    applied: bool = False
    applied_at: datetime | None = None
    answers: list[JobAnswer] = []  # T24: application answers drafted for this run, oldest first
    chat: list[ChatTurn] = []  # grounded "does this résumé support this job?" turns


AppStatus = Literal["draft", "ready", "applied", "interviewing", "offer", "rejected", "archived"]
FiledStatus = Literal["applied", "interviewing", "offer", "rejected", "archived"]


class JobSummary(BaseModel):
    """Lightweight row for the extension's run picker (T12) — no result payload."""

    id: str
    title: str  # first non-empty JD line, for the human to recognize the run
    status: JobStatus
    created_at: datetime
    has_pdf: bool  # only done runs have a tailored PDF to attach
    company: str | None = None
    applied: bool = False


class ApplicationOut(BaseModel):
    """One tracked application. The résumé is served by job id; the bytes stay
    on disk under DATA_DIR. `applied_at` is set only once it is filed."""

    job_id: str
    title: str
    company: str | None = None
    status: AppStatus
    saved_at: datetime
    applied_at: datetime | None = None
    resume_label: str | None = None
    resume_ids: list[str] = []
    apply_url: str | None = None
    has_tex: bool = False
    has_pdf: bool = False


class FitNote(BaseModel):
    """What already matches this job, what is thin, and a hard constraint.

    `constraint` is fixed by the server. The model cannot relax it.
    """

    matches: list[str]
    thin: list[str]
    constraint: str


class ChatIn(BaseModel):
    message: str


class ChatOut(BaseModel):
    answer: str
