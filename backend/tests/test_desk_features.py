"""Saved vs applied lists, later status edits, fit notes, and grounded chat."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.main import app
from app.schemas.ats import AtsScore
from app.schemas.pipeline import PipelineResult, Report
from app.services import fit, jobs


@pytest.fixture
def client(monkeypatch, tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 desk")
    score = AtsScore(
        overall=70, keyword_coverage=0.5, llm_fit=70,
        required_keywords=["Python"], matched=["Python"], missing=["Rust"], rationale="r",
    )

    def run(jd, rs, **k):
        return PipelineResult(
            pdf_path=pdf,
            tex="Built Python services for the API.",
            report=Report(ats_before=score, ats_after=score),
        )

    monkeypatch.setattr(jobs, "run_pipeline", run)
    jobs.store._recs.clear()
    return TestClient(app)


def _post(client, **data):
    body = {"jd": "Backend Engineer\nPython APIs.", **data}
    return client.post(
        "/jobs",
        data=body,
        files={"files": ("good.tex", b"\\documentclass{article} Python", "text/plain")},
    )


def test_saved_list_is_separate_from_applied_and_stages_move(client, monkeypatch):
    real_run = jobs.JobStore.run
    monkeypatch.setattr(jobs.store, "run", lambda job_id: None)
    created = _post(client, title="Backend Engineer", company="Stripe")
    job_id = created.json()["job_id"]
    saved = client.get("/applications?bucket=saved").json()
    assert saved[0]["status"] == "draft"
    assert saved[0]["job_id"] == job_id
    assert client.get("/applications").json() == []
    assert client.patch(f"/applications/{job_id}", json={"status": "interviewing"}).status_code == 409

    real_run(jobs.store, job_id)
    ready = client.get("/applications?bucket=saved").json()
    assert ready[0]["status"] == "ready"
    assert ready[0]["has_pdf"] is True
    assert client.get("/applications").json() == []

    marked = client.post(f"/jobs/{job_id}/applied")
    assert marked.status_code == 200
    assert marked.json()["status"] == "applied"
    assert marked.json()["resume_label"] == "good.tex"
    assert client.get("/applications?bucket=saved").json() == []
    filed = client.get("/applications").json()
    assert filed[0]["job_id"] == job_id
    assert client.get(f"/applications/{job_id}/pdf").content.startswith(b"%PDF")

    for status in ("interviewing", "offer", "rejected", "archived"):
        edited = client.patch(f"/applications/{job_id}", json={"status": status})
        assert edited.status_code == 200, edited.text
        assert edited.json()["status"] == status
        assert edited.json()["has_pdf"] is True
    assert client.get("/applications?bucket=saved").json() == []
    assert client.get("/applications").json()[0]["status"] == "archived"


def test_fit_note_degrades_without_a_key_and_keeps_the_constraint(client, monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_API_KEY", None)
    monkeypatch.setattr(fit.llm, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no llm")))
    job_id = _post(client).json()["job_id"]
    note = client.get(f"/jobs/{job_id}/fit")
    assert note.status_code == 200, note.text
    body = note.json()
    assert body["constraint"] == fit.CONSTRAINT
    assert any("Python" in item for item in body["matches"])
    assert all("add " not in item.lower() for item in body["matches"] + body["thin"])


def test_fit_note_drops_invented_advice(client, monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_API_KEY", "present")
    monkeypatch.setattr(fit.llm, "chat", lambda *a, **k: {
        "matches": ["Add Go to the résumé", "Python on the résumé"],
        "thin": ["Not in the résumé: Rust"],
    })
    job_id = _post(client).json()["job_id"]
    body = client.get(f"/jobs/{job_id}/fit").json()
    assert body["constraint"] == fit.CONSTRAINT
    assert "Python on the résumé" in body["matches"]
    assert all("Add Go" not in item for item in body["matches"])


def test_chat_refuses_without_inputs_and_returns_a_grounded_answer(client, monkeypatch):
    seen: dict = {}

    def fake(messages, **k):
        seen["system"] = messages[0]["content"]
        return "The résumé lists Python services."

    monkeypatch.setattr(config, "OLLAMA_API_KEY", "present")
    monkeypatch.setattr(fit.llm, "chat", fake)
    assert client.post("/jobs/missing/chat", json={"message": "Does this match?"}).status_code == 404
    job_id = _post(client).json()["job_id"]
    assert client.post(f"/jobs/{job_id}/chat", json={"message": "   "}).status_code == 400
    answered = client.post(f"/jobs/{job_id}/chat", json={"message": "Does the résumé support this job?"})
    assert answered.status_code == 200, answered.text
    assert answered.json()["answer"] == "The résumé lists Python services."
    assert "Never invent" in seen["system"]

    def empty_tex(jd, rs, **k):
        score = AtsScore(
            overall=1, keyword_coverage=0, llm_fit=1,
            required_keywords=[], matched=[], missing=[], rationale="r",
        )
        return PipelineResult(pdf_path=Path(jobs.store.get(job_id).result.pdf_path), tex="", report=Report(ats_before=score, ats_after=score))

    monkeypatch.setattr(jobs, "run_pipeline", empty_tex)
    blank_id = _post(client).json()["job_id"]
    assert client.post(f"/jobs/{blank_id}/chat", json={"message": "hello"}).status_code == 409
