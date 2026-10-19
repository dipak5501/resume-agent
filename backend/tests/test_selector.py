import os
from pathlib import Path

import pytest

from app.schemas.ats import JdKeyword, Requirement
from app.schemas.selector import ResumeInput
from app.services import selector

FIXTURES = Path(__file__).parent / "fixtures"


# --- tex_to_text: pure / approximate ---------------------------------------


def test_tex_to_text_strips_commands_and_comments():
    tex = (
        r"\documentclass{article}\begin{document}"
        "\n\\textbf{Kubernetes} and %secret comment here\nReact\\end{document}"
    )
    out = selector.tex_to_text(tex)
    assert "Kubernetes" in out
    assert "React" in out
    assert "secret" not in out  # comment dropped
    assert "textbf" not in out  # command name dropped
    assert "\\" not in out  # no backslashes remain


def test_plain_text_keeps_percent():
    """A PDF extract has no TeX commands. '%' must not start a comment."""
    out = selector.tex_to_text("cut latency by 30% using Python")
    assert "30%" in out
    assert "Python" in out


def test_pdf_source_text_is_not_flattened_as_latex():
    raw = r"latency 30% and C:\build"
    assert selector.source_text(ResumeInput(id="p", tex=raw, kind="pdf")) == raw


def test_tex_to_text_drops_preamble():
    tex = r"\usepackage{fontawesome5}\title{PREAMBLEONLY}\begin{document}BODYWORD\end{document}"
    out = selector.tex_to_text(tex)
    assert "BODYWORD" in out
    assert "PREAMBLEONLY" not in out
    assert "fontawesome5" not in out


# --- pick_best: pure -------------------------------------------------------


def test_pick_best_highest():
    sel = selector.pick_best([("a", 30), ("b", 80), ("c", 55)])
    assert sel.picked_id == "b"
    assert sel.close is True
    assert sel.warning is None


def test_pick_best_tie_is_deterministic():
    assert selector.pick_best([("a", 70), ("b", 70)]).picked_id == "a"


def test_pick_best_all_below_threshold_warns():
    sel = selector.pick_best([("a", 20), ("b", 35)])
    assert sel.picked_id == "b"
    assert sel.close is False
    assert sel.warning and "b" in sel.warning


# --- select_resume wiring: one extraction, N fits --------------------------


def test_extract_jd_keywords_called_once(monkeypatch):
    calls = []
    monkeypatch.setattr(
        selector.ats,
        "extract_jd_keywords",
        lambda jd: calls.append(1) or [JdKeyword(term="python", required=True)],
    )
    reqs = [Requirement(text="BS in CS", priority="must")]
    monkeypatch.setattr(selector.ats, "extract_requirements", lambda jd: calls.append(2) or reqs)
    judged = []
    monkeypatch.setattr(selector.ats, "judge_requirements", lambda r, text: judged.append(r) or [])
    resumes = [
        ResumeInput(id="a", tex=r"\begin{document}python\end{document}"),
        ResumeInput(id="b", tex=r"\begin{document}java\end{document}"),
    ]
    sel = selector.select_resume("jd", resumes)
    assert calls == [1, 2]  # keywords + requirements, hoisted out of the per-résumé loop
    assert sel.picked_id == "a"  # 'a' mentions python -> higher coverage
    assert sel.picked_score is not None
    assert judged == [reqs, reqs]  # every résumé judged against the ONE extraction
    assert sel.requirements == reqs  # handed on, frozen for the pipeline


def test_select_resume_empty_raises():
    with pytest.raises(ValueError):
        selector.select_resume("jd", [])


# --- live discrimination (needs real key) ----------------------------------


@pytest.mark.skipif(not os.getenv("OLLAMA_API_KEY"), reason="OLLAMA_API_KEY not set")
def test_live_discriminates_backend_vs_frontend():
    good = ResumeInput(id="good", tex=(FIXTURES / "good.tex").read_text())
    fe = ResumeInput(id="frontend", tex=(FIXTURES / "frontend.tex").read_text())
    backend_jd = (FIXTURES / "jd_sample.txt").read_text()
    frontend_jd = (FIXTURES / "jd_frontend.txt").read_text()
    assert selector.select_resume(backend_jd, [good, fe]).picked_id == "good"
    assert selector.select_resume(frontend_jd, [good, fe]).picked_id == "frontend"
