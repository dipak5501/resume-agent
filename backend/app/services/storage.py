"""Résumé file storage seam (T11). Bytes on the filesystem under
DATA_DIR/profiles/<pid>/resumes/<rid>/<kind>; the DB holds only metadata. Local
FS now — swap this one module for S3 later. Functions, not a class hierarchy."""

import shutil
from pathlib import Path

from app.core import config


def _resume_dir(pid: str, rid: str) -> Path:
    return config.DATA_DIR / "profiles" / pid / "resumes" / rid


def save_resume_file(pid: str, rid: str, kind: str, data: bytes) -> str:
    """Write bytes; return the DATA_DIR-relative path (portable, not absolute)."""
    path = _resume_dir(pid, rid) / kind
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path.relative_to(config.DATA_DIR))


def open_resume_file(pid: str, rid: str, kind: str) -> bytes:
    return (_resume_dir(pid, rid) / kind).read_bytes()


def delete_resume_dir(pid: str, rid: str) -> None:
    shutil.rmtree(_resume_dir(pid, rid), ignore_errors=True)
