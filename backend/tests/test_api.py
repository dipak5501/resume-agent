from itertools import count

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.ats import AtsScore
from app.schemas.pipeline import PipelineResult, Report
from app.services import answerer, jobs


@pytest.fixture
def client(monkeypatch, tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake pdf bytes")
    a = AtsScore(
        overall=80, keyword_coverage=1.0, llm_fit=80,
        required_keywords=[], matched=[], missing=[], rationale="r",
    )
    # A fresh result per run, with a changing tex — a repeat of the same résumé is
    # a no-op revision that hands the round back (T22), which the cap test needs.
    counter = count()

    def run(jd, rs, **k):
        i = next(counter)
        return PipelineResult(
            pdf_path=pdf, tex="TEX" if i == 0 else f"TEX{i}", report=Report(ats_before=a, ats_after=a)
        )

    # BackgroundTasks run before TestClient returns, so the pipeline "completes" instantly.
    monkeypatch.setattr(jobs, "run_pipeline", run)
    jobs.store._recs.clear()
    return TestClient(app)


def _post_job(client):
    return client.post(
        "/jobs",
        data={"jd": "some job description"},
        files={"files": ("good.tex", b"\\documentclass{article}", "text/plain")},
    )


def test_post_get_pdf_flow(client):
    r = _post_job(client)
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    g = client.get(f"/jobs/{job_id}")
    assert g.status_code == 200
    body = g.json()
    assert body["status"] == "done"
    assert body["result"]["tex"] == "TEX"

    p = client.get(f"/jobs/{job_id}/pdf")
    assert p.status_code == 200
    assert p.headers["content-type"] == "application/pdf"
    assert p.content.startswith(b"%PDF")


def test_get_missing_job_404(client):
    assert client.get("/jobs/nope").status_code == 404


def test_apply_url_threads_through_create_and_read(client):
    # T16/T32: link JDs carry the adapter's apply URL and posting title end-to-end.
    r = client.post(
        "/jobs",
        data={"jd": "At Acme, we build things.", "apply_url": "https://jobs.lever.co/acme/789",
              "title": "Software Engineer, Backend"},
        files={"files": ("good.tex", b"\\documentclass{article}", "text/plain")},
    )
    job_id = r.json()["job_id"]
    job = client.get(f"/jobs/{job_id}").json()
    assert job["apply_url"] == "https://jobs.lever.co/acme/789"
    assert job["title"] == "Software Engineer, Backend"
    # the run picker names the run by its role, not the JD's first line
    assert next(j for j in client.get("/jobs").json() if j["id"] == job_id)["title"] == "Software Engineer, Backend"


def test_paste_job_has_null_apply_url(client):
    # No apply_url/title form field (a pasted JD) → null; no regression to paste flows.
    job_id = _post_job(client).json()["job_id"]
    job = client.get(f"/jobs/{job_id}").json()
    assert job["apply_url"] is None and job["title"] is None
    assert next(j for j in client.get("/jobs").json() if j["id"] == job_id)["title"] != ""


def test_cors_allows_extension_origin(client):
    origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    r = client.get("/jobs", headers={"Origin": origin})
    assert r.headers["access-control-allow-origin"] == origin


def test_cors_rejects_random_web_origin(client):
    r = client.get("/jobs", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in r.headers


def test_list_jobs_for_extension_picker(client):
    job_id = _post_job(client).json()["job_id"]
    rows = client.get("/jobs").json()
    assert isinstance(rows, list) and rows[0]["id"] == job_id
    assert rows[0]["title"] == "some job description"
    assert rows[0]["status"] == "done" and rows[0]["has_pdf"] is True


def test_feedback_new_round_then_cap(client):
    job_id = _post_job(client).json()["job_id"]
    for _ in range(jobs.OUTER_LOOP_MAX):
        resp = client.post(f"/jobs/{job_id}/feedback", json={"feedback": "more"})
        assert resp.status_code == 200
    over = client.post(f"/jobs/{job_id}/feedback", json={"feedback": "more"})
    assert over.status_code == 429


# --- T24: application answers on the run ------------------------------------


def test_answer_appends_to_job_log_and_never_costs_a_round(client, monkeypatch):
    """Answering is a separate concern from revising: the log grows, `round` doesn't."""
    monkeypatch.setattr(answerer, "_llm_classify", lambda q: None)
    monkeypatch.setattr(answerer, "_llm_answer", lambda q, tmpl, jd, tex, **kw: f"drafted: {q}")
    job_id = _post_job(client).json()["job_id"]

    r = client.post(f"/jobs/{job_id}/answer", json={"question": "Why are you a fit for this role?"})
    assert r.status_code == 200
    assert r.json()["answer"].startswith("drafted:")
    assert r.json()["needs_review"] is True  # every draft carries the review backstop

    client.post(f"/jobs/{job_id}/answer", json={"question": "Describe a project you're proud of."})
    job = client.get(f"/jobs/{job_id}").json()
    assert [a["question"] for a in job["answers"]] == [
        "Why are you a fit for this role?",
        "Describe a project you're proud of.",
    ]
    assert job["round"] == 0  # answering never consumes a revision round


def test_answer_save_mode_defaults_by_category(client, monkeypatch):
    """Promotion default: a fact is safe verbatim; résumé-grounded prose must stay
    adaptable so it is re-grounded on the next job's résumé."""
    monkeypatch.setattr(answerer, "_llm_answer", lambda q, tmpl, jd, tex, **kw: "drafted")
    job_id = _post_job(client).json()["job_id"]

    fact = client.post(f"/jobs/{job_id}/answer", json={"question": "What is your notice period?"})
    prose = client.post(f"/jobs/{job_id}/answer", json={"question": "Why do you want to work here?"})
    assert fact.json()["save_mode"] == "verbatim"
    assert prose.json()["save_mode"] == "adaptable"


def test_answer_rejects_blank_and_missing_job(client):
    job_id = _post_job(client).json()["job_id"]
    assert client.post(f"/jobs/{job_id}/answer", json={"question": "   "}).status_code == 400
    assert client.post("/jobs/nope/answer", json={"question": "hi"}).status_code == 404
