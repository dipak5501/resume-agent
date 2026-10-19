"""Answer-bank + screening-answer contract (T13). `/autofill/answer` receives
ONLY the question text + job_id + host — never the user's other filled data or
page HTML (same privacy boundary as T12's /autofill/map)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

Mode = Literal["verbatim", "adaptable"]


class AnswerIn(BaseModel):
    """Answer-bank write. Core rows edit `answer`+`mode`; custom rows also set
    `question`."""

    question: str | None = None
    answer: str = ""
    mode: Mode = "verbatim"


class AnswerOut(BaseModel):
    id: str
    canonical: str | None
    question: str | None
    answer: str
    mode: str
    model_config = ConfigDict(from_attributes=True)


class AnswerRequest(BaseModel):
    """POST /autofill/answer — question + grounding job, nothing else."""

    question: str
    job_id: str | None = None
    host: str = ""


class AnswerResult(BaseModel):
    answer: str = ""  # empty ⇒ nothing to fill; the extension flags it for the user
    source: Literal["bank_verbatim", "bank_adapted", "llm_fresh", "blank"]  # provenance (subsumes mode)
    needs_review: bool  # LLM-produced or high-stakes → the mandatory human-review backstop
    canonical: str | None = None
    reason: str | None = None  # why blank / flagged, shown to the user
