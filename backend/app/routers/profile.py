"""Profile + résumé library (T11). Single profile, hardcoded profile_id — the
tenant seam that makes multi-user a later bolt-on. One router covers both."""

from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Profile, Resume
from pydantic import BaseModel

from app.schemas.profile import PROFILE_SCALARS, ProfileIn, ProfileOut, ResumeMeta, ResumeUploaded
from app.services import auto_apply
from app.services import storage
from app.services.resume_parse import fill_empty_profile, resume_kind, stored_name, text_from_upload

router = APIRouter()

PID = "default"  # the only profile for now; auth resolves the real id later


def _resumes(db: Session) -> list[Resume]:
    return list(db.scalars(select(Resume).where(Resume.profile_id == PID).order_by(Resume.created_at)))


def _get_resume(db: Session, rid: str) -> Resume:
    r = db.get(Resume, rid)
    if r is None or r.profile_id != PID:
        raise HTTPException(status_code=404, detail="résumé not found")
    return r


def _profile_out(p: Profile) -> ProfileOut:
    data = {k: getattr(p, k) for k in PROFILE_SCALARS}
    # Columns added to an existing db file come back NULL until the user sets them.
    data["profile_confirmed"] = bool(data.get("profile_confirmed"))
    data["auto_apply"] = bool(data.get("auto_apply"))
    return ProfileOut(id=p.id, links=p.links or {}, **data)


@router.get("/profile")
def get_profile(db: Session = Depends(get_db)) -> ProfileOut:
    return _profile_out(db.get(Profile, PID))


class AutoApplySwitch(BaseModel):
    enabled: bool


@router.put("/profile/auto-apply")
def set_auto_apply(body: AutoApplySwitch) -> dict[str, bool]:
    """The in-app switch. Default off; this is the only way to turn it on."""
    return {"enabled": auto_apply.set_enabled(body.enabled)}


@router.put("/profile")
def update_profile(body: ProfileIn, db: Session = Depends(get_db)) -> ProfileOut:
    p = db.get(Profile, PID)
    for k in PROFILE_SCALARS:
        setattr(p, k, getattr(body, k))
    p.links = body.links.model_dump()
    db.commit()
    return _profile_out(p)


@router.get("/resumes")
def list_resumes(db: Session = Depends(get_db)) -> list[ResumeMeta]:
    return [ResumeMeta.model_validate(r) for r in _resumes(db)]


@router.post("/resumes")
async def upload_resume(
    file: UploadFile = File(...),
    label: str | None = Form(None),
    db: Session = Depends(get_db),
) -> ResumeUploaded:
    kind = resume_kind(file.filename, file.content_type)
    if kind is None:
        raise HTTPException(status_code=400, detail="Upload a .tex or .pdf résumé.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="That file is empty.")
    rid = uuid4().hex
    storage.save_resume_file(PID, rid, stored_name(kind), data)
    r = Resume(
        id=rid, profile_id=PID, label=label, format=kind, filename=file.filename,
        is_default=not _resumes(db),  # first upload becomes the default
    )
    db.add(r)
    filled = fill_empty_profile(db, PID, text_from_upload(data, kind))
    db.commit()
    return ResumeUploaded.model_validate(r).model_copy(update={"filled": filled})


@router.put("/resumes/{rid}/default")
def set_default(rid: str, db: Session = Depends(get_db)) -> ResumeMeta:
    target = _get_resume(db, rid)
    for r in _resumes(db):
        r.is_default = r.id == rid
    db.commit()
    return ResumeMeta.model_validate(target)


@router.delete("/resumes/{rid}")
def delete_resume(rid: str, db: Session = Depends(get_db)) -> dict:
    r = _get_resume(db, rid)
    was_default = r.is_default
    db.delete(r)
    db.commit()
    storage.delete_resume_dir(PID, rid)
    # keep exactly-one-default invariant: promote the newest survivor
    if was_default and (rest := _resumes(db)):
        rest[-1].is_default = True
        db.commit()
    return {"ok": True}
