from datetime import datetime
from pydantic import BaseModel, ConfigDict

class JobPostingOut(BaseModel):
    url: str
    company_slug: str
    company_name: str | None = None  # T36: "Applied Materials", not its Workday id
    date_only: bool = False  # T36: the vendor gives a day, so created_at's time is when we saw it
    openings: int = 1  # same-role requisitions this card stands for (Board feed groups them)
    title: str
    location: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class BoardFeedOut(BaseModel):
    jobs: list[JobPostingOut]
    has_more: bool
    total_pages: int
