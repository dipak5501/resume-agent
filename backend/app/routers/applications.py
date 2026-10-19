"""Tracked applications: saved runs and ones the user has filed."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.schemas.job import ApplicationOut, FiledStatus
from app.services import applications

router = APIRouter()


@router.get("/applications")
def list_applications(bucket: Literal["filed", "saved"] = "filed") -> list[ApplicationOut]:
    return applications.list_bucket(bucket)


class StatusIn(BaseModel):
    status: FiledStatus


@router.patch("/applications/{job_id}")
def patch_status(job_id: str, body: StatusIn) -> ApplicationOut:
    try:
        return applications.set_status(job_id, body.status)
    except applications.InvalidStatus:
        raise HTTPException(status_code=409, detail="that status change is not allowed")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="application not found")


@router.get("/applications/{job_id}/pdf")
def get_pdf(job_id: str):
    try:
        path = applications.resume_file(job_id, "pdf")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="résumé not found")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename="resume.pdf",
        content_disposition_type="inline",
    )


@router.get("/applications/{job_id}/tex")
def get_tex(job_id: str):
    try:
        path = applications.resume_file(job_id, "tex")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="résumé not found")
    return FileResponse(path, media_type="text/plain", filename="resume.tex")
