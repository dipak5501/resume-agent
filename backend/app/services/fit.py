"""Fit note and grounded chat for one tailored run.

Both may describe only what is already in the résumé. They never tell the
writer to add skills, titles, or numbers. Missing key or a failed model call
falls back to a short non-LLM summary.
"""

import re

from pydantic import BaseModel

from app import db
from app.core import config
from app.models import Profile
from app.schemas.job import FitNote
from app.services import jobs, llm
from app.services.selector import tex_to_text

CONSTRAINT = "Do not invent skills, titles, or numbers that are not in the résumé."

CHAT_SYSTEM = (
    "You answer whether the stored résumé supports this job. "
    "Use only the profile and résumé text in the user message. "
    "Never invent experience, skills, titles, employers, or numbers that are not in that text. "
    "If the résumé does not support a claim, say so."
)

_INVENT = re.compile(r"\b(add|invent|insert|include|claim|you should)\b", re.I)
_OUR_BUG = (TypeError, AttributeError, NameError, ImportError, AssertionError)


class _FitDraft(BaseModel):
    matches: list[str] = []
    thin: list[str] = []


def _clean(items: list[str]) -> list[str]:
    out: list[str] = []
    for raw in items:
        text = " ".join(str(raw).split())
        if not text or _INVENT.search(text):
            continue
        out.append(text[:240])
        if len(out) == 6:
            break
    return out


def _fallback(resume_text: str, jd: str, matched: list[str], missing: list[str]) -> FitNote:
    hay = resume_text.lower()
    matches = [m for m in matched if m and m.lower() in hay][:5]
    if not matches:
        seen: set[str] = set()
        for word in re.findall(r"[A-Za-z][A-Za-z0-9+#.]{2,}", jd):
            key = word.lower()
            if key in seen or key not in hay:
                continue
            seen.add(key)
            matches.append(word)
            if len(matches) == 4:
                break
    thin = [f"Not in the résumé: {m}" for m in missing[:4] if m]
    if not matches:
        matches = ["No overlap to cite from the stored résumé."]
    if not thin:
        thin = ["No keyword gap stood out from the stored résumé."]
    return FitNote(matches=matches, thin=thin, constraint=CONSTRAINT)


def fit_note(job_id: str) -> FitNote:
    job = jobs.store.get(job_id)
    if job.status != "done" or job.result is None:
        raise jobs.JobNotDone(job_id)
    jd, tex = jobs.store.grounding(job_id)
    resume_text = tex_to_text(tex)
    matched = list(job.result.report.ats_after.matched)
    missing = list(job.result.report.ats_after.missing)
    if not config.OLLAMA_API_KEY:
        return _fallback(resume_text, jd, matched, missing)
    try:
        raw = llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Compare the job to the résumé. List overlaps already present (matches) "
                        "and gaps that are absent (thin). Never tell the writer to add skills, "
                        "titles, or numbers that are not in the résumé. Do not invent experience."
                    ),
                },
                {"role": "user", "content": f"Résumé:\n{resume_text[:12000]}\n\nJob:\n{jd[:8000]}"},
            ],
            format=_FitDraft.model_json_schema(),
        )
        draft = _FitDraft.model_validate(raw if isinstance(raw, dict) else {})
        matches = _clean(draft.matches)
        thin = _clean(draft.thin)
        if not matches and not thin:
            return _fallback(resume_text, jd, matched, missing)
        return FitNote(
            matches=matches or ["No overlap to cite from the stored résumé."],
            thin=thin or ["No keyword gap stood out from the stored résumé."],
            constraint=CONSTRAINT,
        )
    except _OUR_BUG:
        raise
    except Exception:
        return _fallback(resume_text, jd, matched, missing)


def _profile_block() -> str:
    with db.SessionLocal() as session:
        profile = session.get(Profile, "default")
    if profile is None:
        return "(no profile)"
    return "\n".join([
        f"name: {profile.name or ''}",
        f"location: {profile.location or ''}",
        f"work_auth: {profile.work_auth or ''}",
        f"target_role: {profile.target_role or ''}",
    ])


def _chat_fallback(message: str, resume_text: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9+#.]{2,}", message)
    hit: list[str] = []
    hay = resume_text.lower()
    for word in words:
        if word.lower() in hay and word not in hit:
            hit.append(word)
        if len(hit) == 5:
            break
    cited = ", ".join(hit) if hit else "nothing in that question"
    return f"Grounded only in the stored résumé. {CONSTRAINT} The résumé mentions {cited}."


def chat(job_id: str, message: str) -> str:
    text = message.strip()
    if not text:
        raise ValueError("message required")
    jobs.store.get(job_id)
    jd, tex = jobs.store.grounding(job_id)
    if not tex.strip():
        raise jobs.JobNotDone(job_id)
    resume_text = tex_to_text(tex)
    if not config.OLLAMA_API_KEY:
        return _chat_fallback(text, resume_text)
    try:
        raw = llm.chat([
            {"role": "system", "content": CHAT_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Profile:\n{_profile_block()}\n\nRésumé:\n{resume_text[:12000]}\n\n"
                    f"Job:\n{jd[:8000]}\n\nQuestion:\n{text}"
                ),
            },
        ])
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    except _OUR_BUG:
        raise
    except Exception:
        pass
    return _chat_fallback(text, resume_text)
