"""PDF résumés are a tailoring source. The LLM is mocked; LaTeX is not used."""

from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.ats import AtsScore
from app.schemas.pipeline import HiringAgentReport, PipelineResult, Report
from app.services import improver, jobs, pipeline
from app.services.resume_parse import pdf_text

OLD = "Tailoring needs a .tex source"

RESUME = (
    "Ada Lovelace\n"
    "ada@x.io\n"
    "Engineer at Analytical Engines, 2018-2024\n"
    "Built Python services for the API.\n"
    "Led a team of 4.\n"
    "Skills: Python, mathematics\n"
)


def _resume_pdf(text: str = RESUME) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, 540, 720), text, fontsize=11, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


def _blank_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def _ats(missing: list[str] | None = None) -> AtsScore:
    return AtsScore(
        overall=70, keyword_coverage=0.5, llm_fit=70,
        required_keywords=["Python"], matched=["Python"], missing=missing or [], rationale="r",
    )


def _install_llm(monkeypatch, prompts: list[str]):
    def fake_chat(messages, format=None, **_):
        system = messages[0]["content"]
        if format is not None:
            if "contact details" in system:
                return {
                    "name": "", "email": "", "phone": "", "location": "", "work_auth": "",
                    "links": {"github": "", "linkedin": "", "portfolio": ""},
                }
            if "hiring company" in system:
                return {"names": []}
            if "concrete skills" in system:
                return {"keywords": [{"term": "Python", "aliases": [], "required": True}]}
            if "candidate requirements" in system:
                return {"requirements": []}
            if "recruiter screening" in system:
                return {"verdicts": []}
            raise AssertionError(f"unexpected structured call: {system[:160]}")
        if "uploaded as a PDF" not in system:
            raise AssertionError(f"unexpected text call: {system[:160]}")
        prompts.append(system)
        user = messages[-1]["content"]
        start = user.find("rewrite ONLY this):\n")
        end = user.find("\n\nLENGTH BUDGET")
        if start < 0 or end < 0:
            raise AssertionError("writer prompt did not include the résumé text")
        body = user[start + len("rewrite ONLY this):\n"):end]
        return (
            "===TEXT===\n"
            f"{body}\n"
            "===END===\n"
            "===CHANGES===\n"
            '{"summary": "Kept the wording.", "changes": [], "added": []}\n'
            "===ENDCHANGES===\n"
        )

    monkeypatch.setattr("app.services.llm.chat", fake_chat)


def _no_latex(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("PDF tailoring must not compile LaTeX")

    monkeypatch.setattr(pipeline.render, "render_tex", boom)
    monkeypatch.setattr(pipeline.improver, "improve", boom)
    monkeypatch.setattr(
        pipeline.hiring_agent, "score_resume",
        lambda pdf: HiringAgentReport(overall=70, categories={"production": 10}, advice=[]),
    )


@pytest.fixture
def client():
    jobs.store._recs.clear()
    yield TestClient(app)
    jobs.store._recs.clear()


def test_old_rejection_copy_is_gone():
    root = Path(__file__).resolve().parents[2]
    files = list((root / "backend" / "app").rglob("*.py"))
    files += list((root / "frontend" / "src").rglob("*.tsx"))
    blob = "\n".join(path.read_text() for path in files)
    assert OLD not in blob


def test_blank_pdf_does_not_ask_for_tex(client):
    r = client.post(
        "/jobs",
        data={"jd": "Backend engineer building Python services."},
        files={"files": ("blank.pdf", _blank_pdf(), "application/pdf")},
    )
    assert r.status_code == 400
    assert OLD not in r.text
    assert ".tex" not in r.json()["detail"]


def test_pdf_create_job_lays_out_a_page_without_latex(client, monkeypatch):
    prompts: list[str] = []
    _install_llm(monkeypatch, prompts)
    _no_latex(monkeypatch)
    raw = _resume_pdf()
    assert "Python" in pdf_text(raw)

    r = client.post(
        "/jobs",
        data={"jd": "Backend engineer building Python services for an API."},
        files={"files": ("ada.pdf", raw, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert OLD not in r.text
    job_id = r.json()["job_id"]
    body = client.get(f"/jobs/{job_id}").json()
    assert body["status"] == "done", body.get("error")
    assert body["result"]["kind"] == "pdf"
    assert "Python" in body["result"]["tex"]
    assert "documentclass" not in body["result"]["tex"]
    assert "do not add" in prompts[0].lower()

    pdf = client.get(f"/jobs/{job_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    with pymupdf.open(stream=pdf.content, filetype="pdf") as doc:
        assert doc.page_count == 1
        text = doc[0].get_text()
        assert "Python" in text
        assert "Analytical" in text
        creator = (doc.metadata or {}).get("creator") or ""
        assert "latex" not in creator.lower()

    marked = client.post(f"/jobs/{job_id}/applied")
    assert marked.status_code == 200, marked.text
    assert marked.json()["has_pdf"] is True
    assert marked.json()["has_tex"] is False


def test_library_pdf_create_job(client, monkeypatch):
    prompts: list[str] = []
    _install_llm(monkeypatch, prompts)
    _no_latex(monkeypatch)
    saved = client.post(
        "/resumes",
        files={"file": ("ada.pdf", _resume_pdf(), "application/pdf")},
    )
    assert saved.status_code == 200, saved.text
    mid = saved.json()["id"]
    r = client.post(
        "/jobs",
        data={"jd": "Backend engineer building Python services.", "resume_ids": mid},
    )
    assert r.status_code == 200, r.text
    assert OLD not in r.text
    job = client.get(f"/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "done", job.get("error")
    assert job["result"]["kind"] == "pdf"
    assert "Analytical" in job["result"]["tex"]


def test_tex_create_job_still_accepted(client, monkeypatch, tmp_path):
    seen = []
    pdf = tmp_path / "out.pdf"
    pdf.write_bytes(b"%PDF-1.4 tex-run")

    def run(jd, resumes, **k):
        seen.extend(resumes)
        score = _ats()
        return PipelineResult(
            pdf_path=pdf, tex=resumes[0].tex, kind="tex",
            report=Report(ats_before=score, ats_after=score),
        )

    monkeypatch.setattr(jobs, "run_pipeline", run)
    r = client.post(
        "/jobs",
        data={"jd": "Backend engineer building Python services for an API."},
        files={"files": ("good.tex", b"\\documentclass{article} Python", "text/plain")},
    )
    assert r.status_code == 200, r.text
    assert OLD not in r.text
    assert seen[0].kind == "tex"
    assert "documentclass" in seen[0].tex
    job = client.get(f"/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "done"
    assert job["result"]["kind"] == "tex"


def test_pdf_rewrite_rejects_invented_metrics(monkeypatch):
    def fake_chat(messages, format=None, **_):
        if format is not None:
            return {"names": ["Acme"]}
        return (
            "===TEXT===\n"
            "Ada Lovelace\n"
            "Engineer at Acme, 2018-2024\n"
            "Built Python services and raised revenue by 99%.\n"
            "Kubernetes expert. Led a team of 4.\n"
            "===END===\n"
            "===CHANGES===\n"
            '{"summary": "Added a metric.", "changes": ["added Kubernetes"], "added": ["Kubernetes"]}\n'
            "===ENDCHANGES===\n"
        )

    monkeypatch.setattr("app.services.llm.chat", fake_chat)
    result = improver.improve_text(RESUME, "Backend role at Acme. Kubernetes required.", _ats(["Kubernetes"]))
    assert result.changed is False
    assert "99%" not in result.tex
    assert "Kubernetes" not in result.tex
    assert "Acme" not in result.tex
    assert "Python" in result.tex
    assert result.warnings


def test_pdf_rewrite_keeps_a_faithful_rephrase(monkeypatch):
    rewrite = (
        "Ada Lovelace\n"
        "ada@x.io\n"
        "Engineer at Analytical Engines, 2018-2024\n"
        "Led a team of 4.\n"
        "Built Python services for the API.\n"
        "Skills: Python, mathematics\n"
    )

    def fake_chat(messages, format=None, **_):
        if format is not None:
            return {"names": []}
        return (
            "===TEXT===\n"
            f"{rewrite}\n"
            "===END===\n"
            "===CHANGES===\n"
            '{"summary": "Led with the team line.", "changes": ["Reordered the experience."], "added": []}\n'
            "===ENDCHANGES===\n"
        )

    monkeypatch.setattr("app.services.llm.chat", fake_chat)
    result = improver.improve_text(RESUME, "Backend engineer, Python.", _ats())
    assert result.changed is True
    assert result.single_page is True
    assert "Analytical Engines" in result.tex
    assert "99" not in result.tex
    assert result.added == []
