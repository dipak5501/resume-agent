"""Save a tailored résumé into the repo for local application tracking (LOCAL-DEV
ONLY — writes on whatever machine runs the backend). Copies job.result.pdf_path to
TAILORED_RESUME_DIR/<company>/[<position>/]<name>_resume.pdf and upserts a row in
applications-tracker.csv. Company/position come from one LLM call on the JD; a
link JD's posting title wins for position (Ashby JD text never names the role)."""

import csv
import re
import shutil
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from app.core import config
from app.schemas.job import Job
from app.services import llm

CSV_NAME = "applications-tracker.csv"
CSV_FIELDS = ["date_applied", "company", "position", "resume_path", "ats_score", "apply_url", "status", "notes"]
_USER_FIELDS = {"status", "notes"}  # user-owned columns; preserved across re-saves


class _CompanyPosition(BaseModel):
    company: str
    position: str


def slugify(text: str, fallback: str) -> str:
    """Path-safe slug: lowercase, non-alphanumerics → single '-', trimmed, capped.
    Only [a-z0-9-] survive, so a slug can never be a path separator or `..`."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-") or fallback


def extract_company_position(jd_text: str) -> tuple[str, str]:
    """One LLM call → (company, position) raw strings (caller slugifies)."""
    out = llm.chat(
        [
            {"role": "system", "content": (
                "From a job description, extract the hiring company's name and the job title. "
                "Use an empty string if the JD does not state one. Return ONLY JSON of exactly "
                'this shape: {"company": "Adobe", "position": "Senior Software Engineer"}'
            )},
            {"role": "user", "content": jd_text[:6000]},
        ],
        format=_CompanyPosition.model_json_schema(),
    )
    cp = _CompanyPosition.model_validate(out)
    return cp.company, cp.position


def _tracked_path(company: str, position: str) -> Path | None:
    """Where this (company, position) was last saved, per the tracker CSV — so a
    re-save (e.g. after a revision round) overwrites in place instead of leaving a
    duplicate. None if this role hasn't been saved yet."""
    path = config.TAILORED_RESUME_DIR / CSV_NAME
    if not path.exists():
        return None
    for r in csv.DictReader(path.open(newline="", encoding="utf-8")):
        if r.get("company") == company and r.get("position") == position and r.get("resume_path"):
            return (config.TAILORED_RESUME_DIR.resolve().parent / r["resume_path"]).resolve()
    return None


def _resolve_target(company: str, position: str, filename: str) -> Path:
    """A re-save of an already-tracked role overwrites in place. Otherwise folder
    rule C: flat per company, nest by position once the flat one exists. Traversal
    guard is belt-and-suspenders (slugs are already [a-z0-9-])."""
    base = config.TAILORED_RESUME_DIR.resolve()
    tracked = _tracked_path(company, position)
    if tracked is not None:
        target = tracked
    else:
        company_dir = base / company
        flat, nested = company_dir / filename, company_dir / position / filename
        target = nested if (flat.exists() or nested.exists()) else flat
    target = target.resolve()
    if base != target and base not in target.parents:
        raise ValueError("refusing to write outside the tailored-resume folder")
    return target


def _upsert_csv(row: dict) -> None:
    """One row per (company, position): update the auto columns, preserve the user's
    status/notes, append when new."""
    path = config.TAILORED_RESUME_DIR / CSV_NAME
    rows = list(csv.DictReader(path.open(newline="", encoding="utf-8"))) if path.exists() else []
    for r in rows:
        if r.get("company") == row["company"] and r.get("position") == row["position"]:
            r.update({k: v for k, v in row.items() if k not in _USER_FIELDS})
            break
    else:
        rows.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)


def save_local(job: Job, jd_text: str, profile_name: str | None) -> dict:
    """Copy the tailored PDF into the repo + upsert the tracker. Returns
    {saved_path, company, position} (saved_path is repo-root-relative)."""
    if job.result is None:
        raise ValueError("run isn't finished yet")
    pdf = Path(job.result.pdf_path)
    if not pdf.exists():
        raise FileNotFoundError(f"tailored PDF not found: {pdf}")

    raw_company, raw_position = extract_company_position(jd_text)
    company = slugify(raw_company, "unknown-company")
    position = slugify(job.title or raw_position, "unknown-position")
    name = slugify(profile_name or "", "")
    filename = f"{name}_resume.pdf" if name else "resume.pdf"

    target = _resolve_target(company, position, filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pdf, target)

    rel = str(target.relative_to(config.TAILORED_RESUME_DIR.resolve().parent))
    _upsert_csv({
        "date_applied": date.today().isoformat(),
        "company": company,
        "position": position,
        "resume_path": rel,
        "ats_score": str(round(job.result.report.ats_after.overall)),
        "apply_url": job.apply_url or "",
        "status": "",
        "notes": "",
    })
    return {"saved_path": rel, "company": company, "position": position}
