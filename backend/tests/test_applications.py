"""Marking a run applied, listing those applications, and serving the résumé kept for each."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.ats import AtsScore
from app.schemas.pipeline import PipelineResult, Report
from app.services import jobs


@pytest.fixture
def client(monkeypatch, tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake pdf bytes")
    a = AtsScore(
        overall=80, keyword_coverage=1.0, llm_fit=80,
        required_keywords=[], matched=[], missing=[], rationale="r",
    )

    def run(jd, rs, **k):
        return PipelineResult(pdf_path=pdf, tex="TEX", report=Report(ats_before=a, ats_after=a))

    monkeypatch.setattr(jobs, "run_pipeline", run)
    jobs.store._recs.clear()
    return TestClient(app)


def _post(client, **data):
    body = {"jd": "Senior Backend Engineer\nBuild APIs.", **data}
    return client.post(
        "/jobs",
        data=body,
        files={"files": ("good.tex", b"\\documentclass{article}", "text/plain")},
    )


def test_mark_applied_lists_and_keeps_the_resume(client):
    created = _post(client, title="Backend Engineer", company="Stripe")
    assert created.status_code == 200, created.text
    job_id = created.json()["job_id"]
    assert client.get("/applications").json() == []

    src = Path(jobs.store.get(job_id).result.pdf_path)
    original = src.read_bytes()
    marked = client.post(f"/jobs/{job_id}/applied")
    assert marked.status_code == 200, marked.text
    body = marked.json()
    assert body["job_id"] == job_id
    assert body["title"] == "Backend Engineer"
    assert body["company"] == "Stripe"
    assert body["status"] == "applied"
    assert body["resume_label"] == "good.tex"
    assert body["applied_at"]
    assert src.is_file() and src.read_bytes() == original  # copied, not moved

    rows = client.get("/applications").json()
    assert [r["job_id"] for r in rows] == [job_id]
    assert rows[0]["resume_label"] == "good.tex"

    pdf = client.get(f"/applications/{job_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content == original
    # listing and a second read still resolve the same bytes
    assert client.get("/applications").json()[0]["job_id"] == job_id
    assert client.get(f"/applications/{job_id}/pdf").content == original

    tex = client.get(f"/applications/{job_id}/tex")
    assert tex.status_code == 200 and tex.content == b"TEX"

    job = client.get(f"/jobs/{job_id}").json()
    assert job["applied"] is True and job["applied_at"]
    assert client.get("/jobs").json()[0]["applied"] is True

    # a later change to the run's PDF does not replace the résumé that was filed
    src.write_bytes(b"%PDF-1.4 changed-after-apply")
    again = client.post(f"/jobs/{job_id}/applied")
    assert again.status_code == 200
    assert client.get(f"/applications/{job_id}/pdf").content == original
    assert src.read_bytes().startswith(b"%PDF-1.4 changed")


def test_unmarked_run_is_left_off_the_dashboard(client):
    job_id = _post(client).json()["job_id"]
    assert client.get(f"/jobs/{job_id}").json()["applied"] is False
    assert client.get("/applications").json() == []


def test_mark_records_library_resume_id(client, monkeypatch):
    monkeypatch.setattr("app.services.resume_parse.llm.chat", lambda *a, **k: {})
    up = client.post(
        "/resumes",
        data={"label": "General"},
        files={"file": ("mine.tex", b"TEX", "text/plain")},
    )
    assert up.status_code == 200, up.text
    rid = up.json()["id"]
    created = client.post(
        "/jobs",
        data={"jd": "some job description", "resume_ids": rid, "title": "SWE", "company": "Acme"},
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["job_id"]
    body = client.post(f"/jobs/{job_id}/applied").json()
    assert body["title"] == "SWE"
    assert body["company"] == "Acme"
    assert body["resume_ids"] == [rid]
    assert body["resume_label"] == "General"
    assert client.get(f"/applications/{job_id}/pdf").content.startswith(b"%PDF")


def test_mark_applied_requires_a_finished_run(monkeypatch):
    def boom(jd, rs, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(jobs, "run_pipeline", boom)
    jobs.store._recs.clear()
    c = TestClient(app)
    job_id = c.post(
        "/jobs",
        data={"jd": "some job description"},
        files={"files": ("good.tex", b"\\documentclass{article}", "text/plain")},
    ).json()["job_id"]
    assert c.get(f"/jobs/{job_id}").json()["status"] == "error"
    refused = c.post(f"/jobs/{job_id}/applied")
    assert refused.status_code == 409
    assert c.get("/applications").json() == []


def test_mark_and_resume_missing_are_404(client):
    assert client.post("/jobs/nope/applied").status_code == 404
    assert client.get("/applications/nope/pdf").status_code == 404
    assert client.get("/applications/nope/tex").status_code == 404
