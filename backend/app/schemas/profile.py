from datetime import datetime

from pydantic import BaseModel


class Links(BaseModel):
    github: str | None = None
    linkedin: str | None = None
    portfolio: str | None = None


class ProfileIn(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    work_auth: str | None = None
    # T17 — assisted screening self-ID (all voluntary/optional)
    work_eligible: str | None = None
    needs_sponsorship: str | None = None
    gender: str | None = None
    race: str | None = None
    disability: str | None = None
    veteran: str | None = None
    target_role: str | None = None
    profile_confirmed: bool = False
    auto_apply: bool = False
    links: Links = Links()


# scalar (non-links) profile columns, shared by the get/put mapping below
PROFILE_SCALARS = (
    "name", "email", "phone", "location", "work_auth",
    "work_eligible", "needs_sponsorship", "gender", "race", "disability", "veteran",
    "target_role", "profile_confirmed", "auto_apply",
)


class ProfileOut(ProfileIn):
    id: str


class ResumeMeta(BaseModel):
    id: str
    label: str | None
    format: str
    filename: str | None
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ResumeUploaded(ResumeMeta):
    """POST /resumes only. `filled` is the profile fields this upload wrote."""

    filled: list[str] = []
