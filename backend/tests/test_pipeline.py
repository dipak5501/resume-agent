import os
from pathlib import Path

import pytest

from app.schemas.ats import AtsScore, JdKeyword, Requirement
from app.schemas.improver import ImproveResult
from app.schemas.pipeline import HiringAgentReport, PipelineResult, Report
from app.schemas.render import Guards, RenderResult
from app.schemas.selector import ResumeInput, Selection
from app.services import ats as ats_mod, pipeline

RESUMES = [ResumeInput(id="r1", tex="TEX1"), ResumeInput(id="r2", tex="TEX2")]
KWS = [JdKeyword(term="Python", required=True)]
REQS = [Requirement(text="BS in Computer Science", priority="must")]


def _ats(overall):
    return AtsScore(
        overall=overall,
        keyword_coverage=0.5,
        llm_fit=overall,
        required_keywords=["Python"],
        matched=["Python"],
        missing=["Rust"],
        rationale="r",
    )


def _render(text="resume text"):
    return RenderResult(
        ok=True,
        pdf_path=Path("/tmp/fake.pdf"),
        page_count=1,
        text=text,
        guards=Guards(compiles=True, extraction_clean=True, single_page=True),
        errors=[],
    )


def _mock(monkeypatch, scores, *, warning=None, hiring=None):
    calls = []
    monkeypatch.setattr(
        pipeline.selector,
        "select_resume",
        lambda jd, rs: Selection(
            picked_id=rs[0].id,
            picked_score=_ats(scores[0]),
            ranked=[{"id": rs[0].id, "score": scores[0]}],
            close=warning is None,
            warning=warning,
            keywords=KWS,
            requirements=REQS,
        ),
    )
    monkeypatch.setattr(pipeline.render, "render_tex", lambda tex, **k: _render())
    it = iter(scores)
    monkeypatch.setattr(pipeline.ats, "score_with_keywords", lambda kws, reqs, text: _ats(next(it)))

    def no_extract(jd):
        raise AssertionError("pipeline must reuse the selector's keywords, never re-extract")

    monkeypatch.setattr(pipeline.ats, "extract_jd_keywords", no_extract)
    monkeypatch.setattr(pipeline.ats, "extract_requirements", no_extract)
    monkeypatch.setattr(
        pipeline.improver,
        "improve",
        lambda tex, jd, ats, feedback=None: ImproveResult(
            tex=tex + "+", changed=True, changes=["change"], added=["Rust"],
            summary="did a thing", compiled=True, single_page=True,
        ),
    )

    def fake_hiring(pdf):
        calls.append(pdf)
        return hiring if hiring is not None else HiringAgentReport(
            overall=85, categories={"production": 25}, advice=["do x"]
        )

    monkeypatch.setattr(pipeline.hiring_agent, "score_resume", fake_hiring)
    return calls


def test_inner_loop_keeps_best_stops_on_plateau_gate_once(monkeypatch):
    # baseline 70; rounds score 80, 85, 85 (3rd is a plateau → discard, stop)
    calls = _mock(monkeypatch, [70, 80, 85, 85])
    r = pipeline.run_pipeline("jd", RESUMES)
    assert r.report.ats_before.overall == 70
    assert r.report.ats_after.overall == 85
    assert len(calls) == 1  # hiring-agent called exactly once
    assert r.report.changes == ["change", "change"]  # only the 2 kept rounds
    assert r.report.added == ["Rust"]  # deduped
    assert r.report.hiring_agent is not None
    assert r.report.selection_warning is None
    assert r.report.warnings == []  # a later-round plateau is the normal stop, not news


def test_first_round_without_gain_says_why(monkeypatch):
    # baseline 91, the only rewrite scores 91 → original kept, and the report says so
    _mock(monkeypatch, [91, 91])
    r = pipeline.run_pipeline("jd", RESUMES)
    assert r.report.changes == []
    assert r.report.warnings == ["the rewrite scored 91, not above your original's 91, so the original was kept"]


def test_invalid_rewrite_reason_is_surfaced(monkeypatch):
    _mock(monkeypatch, [91])
    monkeypatch.setattr(
        pipeline.improver, "improve",
        lambda *a, **k: ImproveResult(tex="TEX1", changed=False, compiled=True, single_page=True,
                                      warnings=["could not produce a valid ≤1-page rewrite; kept the original"]),
    )
    r = pipeline.run_pipeline("jd", RESUMES)
    assert r.report.warnings == ["could not produce a valid ≤1-page rewrite; kept the original"]


def test_inner_loop_capped_at_max(monkeypatch):
    # every round improves → would run forever, but caps at INNER_LOOP_MAX
    _mock(monkeypatch, [10, 20, 30, 40, 50, 60])
    r = pipeline.run_pipeline("jd", RESUMES)
    assert len(r.report.changes) == pipeline.INNER_LOOP_MAX


def test_below_gate_adds_github_note(monkeypatch):
    _mock(
        monkeypatch, [70, 70],
        hiring=HiringAgentReport(overall=50, categories={"production": 25}, advice=["add OSS"]),
    )
    r = pipeline.run_pipeline("jd", RESUMES)
    assert r.report.hiring_agent.overall == 50
    assert r.report.hiring_agent.note  # GitHub-driven explanation attached
    assert "add OSS" in r.report.hiring_agent.advice


def test_gate_failure_is_warned_not_fatal(monkeypatch):
    _mock(monkeypatch, [70, 80, 85, 85])
    monkeypatch.setattr(
        pipeline.hiring_agent, "score_resume",
        lambda pdf: (_ for _ in ()).throw(RuntimeError("no venv")),
    )
    r = pipeline.run_pipeline("jd", RESUMES)
    assert r.report.hiring_agent is None
    assert any("quality gate unavailable" in w for w in r.report.warnings)


def test_selection_warning_propagates(monkeypatch):
    _mock(monkeypatch, [30, 30], warning="no résumé is a strong match")
    r = pipeline.run_pipeline("jd", RESUMES)
    assert r.report.selection_warning == "no résumé is a strong match"


def test_first_pass_summary_is_last_accepted_pass(monkeypatch):
    _mock(monkeypatch, [70, 80, 85, 85])
    monkeypatch.setattr(
        pipeline.improver, "improve",
        _improver(lambda n: ImproveResult(
            tex=f"TEX{n}", changed=True, summary=f"pass {n}", compiled=True, single_page=True,
        )),
    )
    r = pipeline.run_pipeline("jd", RESUMES)
    assert r.report.summary == "pass 1"  # the 3rd pass plateaus and is discarded


# --- T22: a user revision is directed, not optimized -----------------------


def _prior(overall=99, tex="PRIOR"):
    return PipelineResult(
        pdf_path=Path("/tmp/prior.pdf"),
        tex=tex,
        report=Report(ats_before=_ats(60), ats_after=_ats(overall), changes=["earlier"]),
    )


def _improver(make):
    """Record improve() calls and hand each one to `make(call_index)`."""
    calls = []

    def fake(tex, jd, ats, feedback=None):
        calls.append({"tex": tex, "jd": jd, "feedback": feedback})
        return make(len(calls) - 1)

    fake.calls = calls
    return fake


def test_revision_is_kept_even_when_ats_drops(monkeypatch):
    """THE T22 REGRESSION: 'tone down X' lowers keyword coverage. The human asked
    for it, so the edit ships and we report the lower score honestly."""
    _mock(monkeypatch, [92])  # the revised résumé scores BELOW the prior's 99
    monkeypatch.setattr(
        pipeline.improver, "improve",
        _improver(lambda n: ImproveResult(
            tex="REVISED", changed=True, changes=["toned down AI/ML"],
            summary="Led with the platform work.", compiled=True, single_page=True,
        )),
    )
    r = pipeline.run_pipeline("jd", RESUMES, feedback="tone down the AI/ML framing", prior=_prior())
    assert r.tex == "REVISED"  # not discarded by the ATS gate
    assert r.report.ats_after.overall == 92  # scored honestly, drop and all
    assert r.report.changes == ["toned down AI/ML"]
    assert r.report.summary == "Led with the platform work."


def test_revision_runs_exactly_one_directed_pass(monkeypatch):
    """One human request → one pass. No autonomous re-optimization on top of it,
    and the feedback arrives first-class rather than stapled onto the JD."""
    _mock(monkeypatch, [99, 99, 99])
    fake = _improver(lambda n: ImproveResult(
        tex=f"REV{n}", changed=True, compiled=True, single_page=True,
    ))
    monkeypatch.setattr(pipeline.improver, "improve", fake)
    r = pipeline.run_pipeline("jd", RESUMES, feedback="lead with platform", prior=_prior())
    assert len(fake.calls) == 1
    assert fake.calls[0]["feedback"] == "lead with platform"
    assert fake.calls[0]["jd"] == "jd"  # the JD is not polluted with the request
    assert r.tex == "REV0"


def test_revision_falls_back_to_prior_when_no_valid_candidate(monkeypatch):
    _mock(monkeypatch, [99])
    monkeypatch.setattr(
        pipeline.improver, "improve",
        _improver(lambda n: ImproveResult(
            tex="PRIOR", changed=False, compiled=True, single_page=True,
        )),
    )
    r = pipeline.run_pipeline("jd", RESUMES, feedback="do something", prior=_prior())
    assert r.tex == "PRIOR"
    assert r.report.ats_after.overall == 99  # the prior's score, untouched


def test_keywords_extracted_once_and_frozen_across_rounds(monkeypatch):
    """The selector's extraction is the ONLY one: baseline, every inner round and a
    later revision all score against the same keywords AND requirements (T34);
    `_mock` fails loudly on any re-extract."""
    _mock(monkeypatch, [70])  # the spy below owns scoring
    seen = []
    scores = iter([70, 80, 90, 95, 97])

    def spy(kws, reqs, text):
        seen.append((kws, reqs))
        return _ats(next(scores))

    monkeypatch.setattr(pipeline.ats, "score_with_keywords", spy)
    first = pipeline.run_pipeline("jd", RESUMES)
    assert first.keywords == KWS and first.requirements == REQS
    pipeline.run_pipeline("jd", RESUMES, feedback="shorter summary", prior=first)
    assert seen and all(s == (KWS, REQS) for s in seen)


def test_a_judge_flip_on_shared_text_is_not_a_gain(monkeypatch):
    """T34: the original is judged "unclear" on a quote the rewrite also has, and the
    rewrite "meets" on it. That is the judge disagreeing with itself, not an
    improvement: after reconcile both meet, so the rewrite is not kept."""
    from app.schemas.ats import RequirementVerdict

    def scored(verdict, evidence):
        v = RequirementVerdict(text="BS in Computer Science", priority="must", verdict=verdict, evidence=evidence)
        return ats_mod._judged(_ats(0), [v])

    _mock(monkeypatch, [0])
    monkeypatch.setattr(pipeline.render, "render_tex", lambda tex, **k: _render("Holding a BS in Computer Science"))
    judged = iter([scored("unclear", ""), scored("meets", "Holding a BS in Computer Science")])
    monkeypatch.setattr(pipeline.ats, "score_with_keywords", lambda kws, reqs, text: next(judged))
    r = pipeline.run_pipeline("jd", RESUMES)
    assert r.tex == "TEX1"  # the original, not the rewrite
    assert r.report.ats_before.overall == r.report.ats_after.overall == 70
    assert r.report.ats_before.requirements[0].verdict == "meets"  # re-read, with its own quote
    assert "not above your original" in r.report.warnings[0]


# --- live end-to-end (real select→render→score↔improve→gate; slow) ----------

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.skipif(not os.getenv("OLLAMA_API_KEY"), reason="OLLAMA_API_KEY not set")
def test_live_e2e_completes():
    good = ResumeInput(id="good", tex=(FIXTURES / "good.tex").read_text())
    jd = (FIXTURES / "jd_sample.txt").read_text()
    result = pipeline.run_pipeline(jd, [good])
    assert result.pdf_path.exists()  # a real PDF was produced
    assert result.tex.strip()
    # the optimization loop never makes the score worse
    assert result.report.ats_after.overall >= result.report.ats_before.overall
    # report is populated (hiring_agent may be None if the gate can't run)
    assert result.report.ats_before and result.report.ats_after
