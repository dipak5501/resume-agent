"""Save-locally: folder rule C, CSV upsert (preserving user columns), path-safety.
LLM extraction is mocked; the base dir is a tmp dir."""

import csv
from pathlib import Path

import pytest

from app.core import config
from app.schemas.ats import AtsScore
from app.schemas.job import Job
from app.schemas.pipeline import PipelineResult, Report
from app.services import local_save


def _ats(overall=88):
    return AtsScore(
        overall=overall, keyword_coverage=0.5, llm_fit=overall,
        required_keywords=["Python"], matched=["Python"], missing=["Rust"], rationale="r",
    )


def _job(pdf: Path, apply_url=None, title=None) -> Job:
    return Job(
        id="j1", status="done", apply_url=apply_url, title=title,
        result=PipelineResult(pdf_path=pdf, tex="TEX", report=Report(ats_before=_ats(60), ats_after=_ats(88))),
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    # Route the base through a symlink so target.resolve() differs from the raw
    # path — reproduces the macOS /var→/private/var case and guards the
    # relative_to() computation against it.
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    base = link / "tailored-resume"
    monkeypatch.setattr(config, "TAILORED_RESUME_DIR", base)
    pdf = tmp_path / "src.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    return base, pdf


def _rows(base):
    return list(csv.DictReader((base / local_save.CSV_NAME).open(newline="", encoding="utf-8")))


def test_slugify_is_path_safe():
    assert local_save.slugify("Adobe Inc.", "x") == "adobe-inc"
    assert local_save.slugify("   ", "unknown") == "unknown"
    assert local_save.slugify("../../etc/", "x") == "etc"  # traversal stripped to safe chars


def test_rule_c_and_idempotent_resave(env, monkeypatch):
    """Rule C for new roles; a re-save of the SAME role (e.g. after a revision)
    overwrites in place — flat or nested — leaving no duplicate/orphan."""
    base, pdf = env
    cp = {"v": ("Adobe", "Senior SWE")}
    monkeypatch.setattr(local_save, "extract_company_position", lambda jd: cp["v"])
    j = _job(pdf)

    # first save → flat
    r1 = local_save.save_local(j, "jd", "Kashif Manzer")
    assert r1["saved_path"] == "tailored-resume/adobe/kashif-manzer_resume.pdf"
    # revision re-save of the SAME role → overwrites the flat file, never nests
    assert local_save.save_local(j, "jd", "Kashif Manzer")["saved_path"] == r1["saved_path"]
    assert not (base / "adobe" / "senior-swe").exists()

    # a genuinely NEW role at the same company → nested (rule C)
    cp["v"] = ("Adobe", "Staff SWE")
    r2 = local_save.save_local(j, "jd", "Kashif Manzer")
    assert r2["saved_path"] == "tailored-resume/adobe/staff-swe/kashif-manzer_resume.pdf"
    # revision re-save of the nested role → overwrites in place
    assert local_save.save_local(j, "jd", "Kashif Manzer")["saved_path"] == r2["saved_path"]

    # exactly two PDFs total — the flat senior role + the nested staff role, no orphans
    assert sorted(str(p.relative_to(base)) for p in base.rglob("*.pdf")) == [
        "adobe/kashif-manzer_resume.pdf",
        "adobe/staff-swe/kashif-manzer_resume.pdf",
    ]


def test_csv_upsert_preserves_user_columns(env, monkeypatch):
    base, pdf = env
    monkeypatch.setattr(local_save, "extract_company_position", lambda jd: ("Google", "SWE"))
    j = _job(pdf, apply_url="https://x/apply")

    local_save.save_local(j, "jd", "Ada")
    rows = _rows(base)
    assert len(rows) == 1
    assert rows[0]["company"] == "google" and rows[0]["ats_score"] == "88"
    assert rows[0]["apply_url"] == "https://x/apply" and rows[0]["status"] == ""

    # user fills status/notes by hand, then a re-save of the same (company, position)
    rows[0]["status"], rows[0]["notes"] = "applied", "referred by X"
    with (base / local_save.CSV_NAME).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=local_save.CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)

    local_save.save_local(j, "jd", "Ada")
    rows2 = _rows(base)
    assert len(rows2) == 1  # upsert, not append
    assert rows2[0]["status"] == "applied" and rows2[0]["notes"] == "referred by X"


def test_traversal_slug_stays_inside_base(env, monkeypatch):
    base, pdf = env
    monkeypatch.setattr(local_save, "extract_company_position", lambda jd: ("../../etc", "..\\evil"))
    r = local_save.save_local(_job(pdf), "jd", "Ada")
    assert r["company"] == "etc" and r["position"] == "evil"
    written = (base / "etc" / "ada_resume.pdf").resolve()
    assert written.exists() and base.resolve() in written.parents


def test_filename_falls_back_without_profile_name(env, monkeypatch):
    base, pdf = env
    monkeypatch.setattr(local_save, "extract_company_position", lambda jd: ("Nvidia", "ML Eng"))
    r = local_save.save_local(_job(pdf), "jd", None)
    assert r["saved_path"] == "tailored-resume/nvidia/resume.pdf"
    assert (base / "nvidia" / "resume.pdf").exists()


def test_endpoint_saves_then_404(tmp_path, monkeypatch):
    """Full HTTP path: POST /jobs (completes via mocked pipeline) → POST save-local."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import jobs

    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    result = _job(pdf).result
    monkeypatch.setattr(jobs, "run_pipeline", lambda jd, rs, **k: result)
    monkeypatch.setattr(config, "TAILORED_RESUME_DIR", tmp_path / "tailored-resume")
    monkeypatch.setattr(local_save, "extract_company_position", lambda jd: ("Stripe", "Backend Engineer"))
    jobs.store._recs.clear()
    client = TestClient(app)

    job_id = client.post(
        "/jobs",
        data={"jd": "Stripe backend role"},
        files={"files": ("r.tex", b"\\documentclass{article}", "text/plain")},
    ).json()["job_id"]

    saved = client.post(f"/jobs/{job_id}/save-local")
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["company"] == "stripe" and body["position"] == "backend-engineer"
    assert (tmp_path / body["saved_path"]).exists()

    assert client.post("/jobs/nope/save-local").status_code == 404


def test_posting_title_wins_over_llm_position(env, monkeypatch):
    """T32: Ashby JD text never names the role, so the LLM returned "" and the
    save landed in unknown-position/. A link JD's posting title is the position."""
    _, pdf = env
    monkeypatch.setattr(local_save, "extract_company_position", lambda jd: ("Atomic", ""))
    r = local_save.save_local(_job(pdf, title="Software Engineer, Backend "), "jd", "Ada")
    assert r["position"] == "software-engineer-backend"
    # a pasted JD (no title) still uses the LLM's answer, or the fallback
    assert local_save.save_local(_job(pdf), "jd", "Ada")["position"] == "unknown-position"
