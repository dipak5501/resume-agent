"""Auto-apply stays off until the switch is on, and a bad form is not logged."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.ats import AtsScore
from app.schemas.pipeline import PipelineResult, Report
from app.services import auto_apply, jobs

APPLY = "https://jobs.lever.co/acme/1"


@pytest.fixture
def client(monkeypatch, tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 applied-with-this")
    score = AtsScore(
        overall=80, keyword_coverage=1, llm_fit=80,
        required_keywords=[], matched=[], missing=[], rationale="r",
    )

    def run(jd, rs, **k):
        return PipelineResult(pdf_path=pdf, tex="TEX", report=Report(ats_before=score, ats_after=score))

    monkeypatch.setattr(jobs, "run_pipeline", run)
    jobs.store._recs.clear()
    auto_apply._armed.clear()
    return TestClient(app)


def _job(client, **extra):
    data = {"jd": "Backend Engineer\nBuild APIs.", "apply_url": APPLY, "title": "Backend Engineer", "company": "Acme", **extra}
    created = client.post(
        "/jobs",
        data=data,
        files={"files": ("good.tex", b"\\documentclass{article}", "text/plain")},
    )
    assert created.status_code == 200, created.text
    return created.json()["job_id"]


def test_switch_defaults_off_and_blocks_submit(client):
    assert client.get("/profile").json()["auto_apply"] is False
    job_id = _job(client)
    refused = client.post(f"/jobs/{job_id}/auto-apply/finish", json={"submitted": True})
    assert refused.status_code == 409
    assert client.get("/applications").json() == []
    assert client.post(f"/jobs/{job_id}/auto-apply/arm").status_code == 409


def test_unknown_required_fields_do_not_mark_applied(client):
    assert client.put("/profile/auto-apply", json={"enabled": True}).json()["enabled"] is True
    job_id = _job(client)
    refused = client.post(
        f"/jobs/{job_id}/auto-apply/finish",
        json={"submitted": True, "unknown_required": ["Visa status"]},
    )
    assert refused.status_code == 409
    assert "unknown" in refused.json()["detail"].lower()
    assert client.get("/applications").json() == []
    assert client.get(f"/jobs/{job_id}").json()["applied"] is False


def test_success_marks_applied_and_keeps_the_resume(client):
    client.put("/profile/auto-apply", json={"enabled": True})
    job_id = _job(client)
    armed = client.post(f"/jobs/{job_id}/auto-apply/arm")
    assert armed.status_code == 200
    assert armed.json()["apply_url"] == APPLY
    # a second arm replaces the first — still one run, not a queue
    other = _job(client, apply_url="https://jobs.lever.co/other/2")
    client.post(f"/jobs/{other}/auto-apply/arm")
    assert client.post("/auto-apply/claim", json={"page_url": APPLY}).json()["job_id"] is None
    claimed = client.post("/auto-apply/claim", json={"page_url": "https://jobs.lever.co/other/2"}).json()
    assert claimed["job_id"] == other

    done = client.post(f"/jobs/{other}/auto-apply/finish", json={"submitted": True, "unknown_required": [], "blocked": None})
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "applied"
    assert body["job_id"] == other
    assert body["resume_label"] == "good.tex"
    assert client.get(f"/applications/{other}/pdf").content == b"%PDF-1.4 applied-with-this"
    assert client.get(f"/jobs/{other}").json()["applied"] is True
    assert client.get("/applications").json()[0]["resume_label"] == "good.tex"


def test_failure_does_not_mark_applied(client):
    client.put("/profile/auto-apply", json={"enabled": True})
    job_id = _job(client)
    for body in (
        {"submitted": False},
        {"submitted": True, "blocked": "captcha"},
        {"submitted": True, "blocked": "login"},
    ):
        refused = client.post(f"/jobs/{job_id}/auto-apply/finish", json=body)
        assert refused.status_code == 409, body
        assert client.get("/applications").json() == []
        assert client.get(f"/jobs/{job_id}").json()["applied"] is False
