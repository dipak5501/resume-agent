"""PDF + .tex résumé upload: store both, fill blank profile fields, never clobber."""

import pymupdf
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.ats import AtsScore
from app.schemas.pipeline import PipelineResult, Report
from app.services import jobs, storage


def _client():
    return TestClient(app)


def _pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _upload(c, name, body, content_type="application/octet-stream"):
    return c.post("/resumes", files={"file": (name, body, content_type)})


_PARSED = {
    "name": "Ada Lovelace",
    "email": "ada@x.io",
    "phone": "555-0100",
    "location": "London",
    "work_auth": "UK citizen",
    "links": {
        "github": "github.com/ada",
        "linkedin": "linkedin.com/in/ada",
        "portfolio": "ada.dev",
    },
}

_RESUME_TEXT = "Ada Lovelace\nada@x.io\n555-0100\nLondon\nhttps://github.com/ada\nhttps://linkedin.com/in/ada\nhttps://ada.dev\n"


def _mock_llm(monkeypatch, payload=None, seen=None):
    body = payload if payload is not None else _PARSED

    def fake_chat(messages, format=None, **_):
        if seen is not None:
            seen.append(messages[-1]["content"])
        return body

    monkeypatch.setattr("app.services.resume_parse.llm.chat", fake_chat)


def test_pdf_upload_accepted_and_stored(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("short PDF must not call the LLM")

    monkeypatch.setattr("app.services.resume_parse.llm.chat", boom)
    c = _client()
    pdf = _pdf("Hi")
    r = _upload(c, "a.pdf", pdf, "application/pdf")
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["format"] == "pdf"
    assert meta["filename"] == "a.pdf"
    assert meta["filled"] == []
    assert storage.open_resume_file("default", meta["id"], "source.pdf") == pdf


def test_tex_upload_still_accepted(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("short .tex must not call the LLM")

    monkeypatch.setattr("app.services.resume_parse.llm.chat", boom)
    c = _client()
    body = b"\\documentclass{article}"
    r = _upload(c, "a.tex", body, "text/plain")
    assert r.status_code == 200, r.text
    meta = r.json()
    assert meta["format"] == "tex"
    assert meta["filled"] == []
    assert storage.open_resume_file("default", meta["id"], "source.tex") == body


def test_other_extension_rejected():
    r = _upload(_client(), "a.docx", b"not a resume")
    assert r.status_code == 400
    assert ".tex" in r.json()["detail"] and ".pdf" in r.json()["detail"]


def test_pdf_populates_empty_profile(monkeypatch):
    seen = []
    _mock_llm(monkeypatch, seen=seen)
    c = _client()
    r = _upload(c, "ada.pdf", _pdf(_RESUME_TEXT), "application/pdf")
    assert r.status_code == 200, r.text
    assert r.json()["filled"] == [
        "name", "email", "phone", "location", "work_auth", "github", "linkedin", "portfolio",
    ]
    assert "ada@x.io" in seen[0]
    profile = c.get("/profile").json()
    assert profile["name"] == "Ada Lovelace"
    assert profile["email"] == "ada@x.io"
    assert profile["phone"] == "555-0100"
    assert profile["location"] == "London"
    assert profile["work_auth"] == "UK citizen"
    assert profile["links"]["github"] == "github.com/ada"
    assert profile["links"]["linkedin"] == "linkedin.com/in/ada"
    assert profile["links"]["portfolio"] == "ada.dev"


def test_tex_populates_empty_profile(monkeypatch):
    seen = []
    _mock_llm(monkeypatch, seen=seen)
    tex = (
        "\\documentclass{article}\n\\begin{document}\n"
        + _RESUME_TEXT
        + "\\end{document}\n"
    ).encode()
    c = _client()
    r = _upload(c, "ada.tex", tex, "text/plain")
    assert r.status_code == 200, r.text
    assert r.json()["format"] == "tex"
    assert "email" in r.json()["filled"]
    assert "ada@x.io" in seen[0]
    assert c.get("/profile").json()["email"] == "ada@x.io"


def test_upload_does_not_clobber_filled_fields(monkeypatch):
    responses = [
        _PARSED,
        {
            **_PARSED,
            "name": "Someone Else",
            "email": "other@x.io",
            "phone": "999-9999",
            "links": {**_PARSED["links"], "github": "github.com/other", "linkedin": "linkedin.com/in/other"},
        },
    ]

    def fake_chat(messages, format=None, **_):
        return responses.pop(0)

    monkeypatch.setattr("app.services.resume_parse.llm.chat", fake_chat)
    c = _client()
    c.put("/profile", json={"name": "Kept Name", "links": {"github": "github.com/kept"}})
    first = _upload(c, "ada.pdf", _pdf(_RESUME_TEXT), "application/pdf")
    assert first.status_code == 200, first.text
    assert "name" not in first.json()["filled"]
    assert "github" not in first.json()["filled"]
    assert "email" in first.json()["filled"]
    assert "linkedin" in first.json()["filled"]
    profile = c.get("/profile").json()
    assert profile["name"] == "Kept Name"
    assert profile["email"] == "ada@x.io"
    assert profile["links"]["github"] == "github.com/kept"
    assert profile["links"]["linkedin"] == "linkedin.com/in/ada"

    second = _upload(c, "again.pdf", _pdf(_RESUME_TEXT + "\nSecond pass.\n"), "application/pdf")
    assert second.status_code == 200, second.text
    assert second.json()["filled"] == []
    again = c.get("/profile").json()
    assert again["name"] == "Kept Name"
    assert again["email"] == "ada@x.io"
    assert again["phone"] == "555-0100"
    assert again["links"]["github"] == "github.com/kept"
    assert again["links"]["linkedin"] == "linkedin.com/in/ada"


def test_llm_failure_still_stores_resume(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr("app.services.resume_parse.llm.chat", boom)
    c = _client()
    r = _upload(c, "ada.pdf", _pdf(_RESUME_TEXT), "application/pdf")
    assert r.status_code == 200, r.text
    assert r.json()["filled"] == []
    assert r.json()["format"] == "pdf"
    assert c.get("/profile").json()["name"] is None


def _accepting_pipeline(monkeypatch):
    seen = []

    def run(jd, resumes, **k):
        seen.extend(resumes)
        score = AtsScore(
            overall=80, keyword_coverage=1.0, llm_fit=80,
            required_keywords=[], matched=[], missing=[], rationale="r",
        )
        return PipelineResult(
            pdf_path="/tmp/not-read.pdf", tex=resumes[0].tex, kind="pdf",
            report=Report(ats_before=score, ats_after=score),
        )

    monkeypatch.setattr(jobs, "run_pipeline", run)
    jobs.store._recs.clear()
    return seen


def test_pdf_library_resume_is_a_tailoring_source(monkeypatch):
    seen = _accepting_pipeline(monkeypatch)
    c = _client()
    mid = _upload(c, "a.pdf", _pdf("Hi"), "application/pdf").json()["id"]
    r = c.post("/jobs", data={"jd": "a job", "resume_ids": [mid]})
    assert r.status_code == 200, r.text
    assert "Tailoring needs a .tex source" not in r.text
    assert seen[0].kind == "pdf"
    assert seen[0].library_id == mid
    assert "Hi" in seen[0].tex


def test_adhoc_pdf_is_a_tailoring_source(monkeypatch):
    seen = _accepting_pipeline(monkeypatch)
    r = _client().post(
        "/jobs",
        data={"jd": "a job"},
        files={"files": ("a.pdf", _pdf("Hi"), "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert "Tailoring needs a .tex source" not in r.text
    assert seen[0].kind == "pdf"
    assert "Hi" in seen[0].tex


def test_tex_upload_is_still_a_tailoring_source(monkeypatch):
    seen = _accepting_pipeline(monkeypatch)
    body = b"\\documentclass{article} Python"
    r = _client().post(
        "/jobs",
        data={"jd": "a job"},
        files={"files": ("good.tex", body, "text/plain")},
    )
    assert r.status_code == 200, r.text
    assert "Tailoring needs a .tex source" not in r.text
    assert seen[0].kind == "tex"
    assert "documentclass" in seen[0].tex
