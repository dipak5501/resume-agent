"""Read a résumé upload and fill blank profile contact fields from it.

PDF bytes are extracted with PyMuPDF (same library the renderer uses). `.tex`
is decoded and lightly flattened so a preamble contact block is still visible.
The LLM only supplies name, email, phone, location, work authorization, and
github/linkedin/portfolio — voluntary self-ID fields are never inferred.
Only empty profile fields are written, so a later upload cannot clobber edits.
"""

import logging
from pathlib import Path

import pymupdf
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import config
from app.models import Profile
from app.services import llm
from app.services.selector import tex_to_text

log = logging.getLogger(__name__)

# Short fixtures and empty drops must not call the LLM.
MIN_PROFILE_CHARS = 40

PDF_NO_TEXT = "This PDF has no readable text, so it can't be tailored."

_EXT = {".tex": "tex", ".pdf": "pdf"}
_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/x-tex": "tex",
    "text/x-tex": "tex",
}
_CONTACT = ("name", "email", "phone", "location", "work_auth")
_LINKS = ("github", "linkedin", "portfolio")


class ParsedLinks(BaseModel):
    github: str = ""
    linkedin: str = ""
    portfolio: str = ""


class ParsedProfile(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    work_auth: str = ""
    links: ParsedLinks = ParsedLinks()


def resume_kind(filename: str | None, content_type: str | None) -> str | None:
    """`tex` or `pdf` from the extension, else from a known content type."""
    ext = Path(filename or "").suffix.lower()
    if ext in _EXT:
        return _EXT[ext]
    ct = (content_type or "").split(";")[0].strip().lower()
    return _CONTENT_TYPES.get(ct)


def is_pdf_upload(filename: str | None, content_type: str | None, data: bytes) -> bool:
    if resume_kind(filename, content_type) == "pdf":
        return True
    return data[:5] == b"%PDF-"


def stored_name(kind: str) -> str:
    return "source.pdf" if kind == "pdf" else "source.tex"


def pdf_text(data: bytes) -> str:
    """Plain text of a PDF résumé. Empty when the file has no text layer."""
    return _pdf_text(data).strip()


def text_from_upload(data: bytes, kind: str) -> str:
    if kind == "pdf":
        return _pdf_text(data)
    raw = data.decode("utf-8", "replace")
    # tex_to_text drops the preamble, which is where many résumés put contact info.
    plain = tex_to_text(raw)
    return f"{raw[:2000]}\n{plain}".strip()


def _pdf_text(data: bytes) -> str:
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return "\n".join(page.get_text() for page in doc).strip()
    except Exception:
        log.warning("pdf text extraction failed")
        return ""


def _blank(value: object) -> bool:
    return not str(value or "").strip()


def _parse(text: str) -> ParsedProfile | None:
    try:
        out = llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Extract contact details explicitly written in this résumé. "
                        "Use an empty string for anything not stated. Do not guess. "
                        "work_auth is only a work-authorization phrase printed on the résumé. "
                        "links are github, linkedin, and portfolio only. "
                        'Return JSON: {"name":"","email":"","phone":"","location":"",'
                        '"work_auth":"","links":{"github":"","linkedin":"","portfolio":""}}'
                    ),
                },
                {"role": "user", "content": text[:12000]},
            ],
            format=ParsedProfile.model_json_schema(),
            model=config.OLLAMA_EXTRACT_MODEL,
        )
        if not isinstance(out, dict):
            return None
        return ParsedProfile.model_validate(out)
    except Exception as exc:
        log.warning("resume profile parse failed: %s", type(exc).__name__)
        return None


def fill_empty_profile(session: Session, profile_id: str, text: str) -> list[str]:
    """Write résumé contact fields into blank profile columns. Returns names filled."""
    text = (text or "").strip()
    if len(text) < MIN_PROFILE_CHARS:
        return []
    parsed = _parse(text)
    profile = session.get(Profile, profile_id)
    if parsed is None or profile is None:
        return []
    filled: list[str] = []
    for key in _CONTACT:
        incoming = getattr(parsed, key).strip()
        if incoming and _blank(getattr(profile, key)):
            setattr(profile, key, incoming)
            filled.append(key)
    links = dict(profile.links or {})
    links_changed = False
    for key in _LINKS:
        incoming = getattr(parsed.links, key).strip()
        if incoming and _blank(links.get(key)):
            links[key] = incoming
            filled.append(key)
            links_changed = True
    if links_changed:
        profile.links = links
    return filled
