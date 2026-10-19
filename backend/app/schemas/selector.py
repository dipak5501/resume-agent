from typing import Literal

from pydantic import BaseModel

from app.schemas.ats import AtsScore, JdKeyword, Requirement


class ResumeInput(BaseModel):
    id: str
    tex: str  # LaTeX source, or the extracted plain text when kind is "pdf"
    library_id: str | None = None  # set when this source came from the résumé library
    kind: Literal["tex", "pdf"] = "tex"


class Selection(BaseModel):
    picked_id: str
    picked_score: AtsScore | None = None
    ranked: list[dict]  # [{id, score}], highest first
    close: bool
    warning: str | None = None  # set when the best pick is below CLOSE_THRESHOLD
    keywords: list[JdKeyword] = []  # the JD extraction every later score reuses
    requirements: list[Requirement] = []  # T34: what the judge checks, extracted with them
