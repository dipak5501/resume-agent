import pytest

from app.schemas.ats import AtsScore
from app.schemas.pipeline import PipelineResult, Report
from app.schemas.selector import ResumeInput
from app.services import jobs


def _result(overall=80, tex="TEX", summary=""):
    a = AtsScore(
        overall=overall, keyword_coverage=1.0, llm_fit=overall,
        required_keywords=[], matched=[], missing=[], rationale="r",
    )
    return PipelineResult(
        pdf_path="/tmp/x.pdf",
        tex=tex,
        report=Report(ats_before=a, ats_after=a, summary=summary),
    )


def _store(monkeypatch, run=None):
    monkeypatch.setattr(jobs, "run_pipeline", run or (lambda jd, rs, **k: _result()))
    return jobs.JobStore()


def test_lifecycle_queued_running_done(monkeypatch):
    store = _store(monkeypatch)
    job = store.create("jd", [ResumeInput(id="r", tex="T")])
    assert job.status == "queued"
    store.run(job.id)
    done = store.get(job.id)
    assert done.status == "done"
    assert done.result.tex == "TEX"


def test_exception_sets_error_status(monkeypatch):
    def boom(jd, rs, **k):
        raise ValueError("kaboom")

    store = _store(monkeypatch, boom)
    job = store.create("jd", [])
    store.run(job.id)
    j = store.get(job.id)
    assert j.status == "error"
    assert "kaboom" in j.error


def test_feedback_increments_and_caps(monkeypatch):
    texs = iter(f"TEX{i}" for i in range(99))  # each round returns a different résumé
    store = _store(monkeypatch, lambda jd, rs, **k: _result(tex=next(texs)))
    job = store.create("jd", [ResumeInput(id="r", tex="T")])
    store.run(job.id)  # done, round 0
    for n in range(1, jobs.OUTER_LOOP_MAX + 1):
        j = store.request_feedback(job.id, "more please")
        assert j.round == n
        store.run(job.id)  # complete the round → done again
    with pytest.raises(jobs.FeedbackLimitReached):
        store.request_feedback(job.id, "more please")


def test_noop_revision_does_not_consume_a_round(monkeypatch):
    """T22 honest accounting: the revision came back byte-identical, so the round
    is handed back and no slip lands on the timeline."""
    store = _store(monkeypatch)  # every run returns the same tex
    job = store.create("jd", [ResumeInput(id="r", tex="T")])
    store.run(job.id)
    assert store.request_feedback(job.id, "change something").round == 1
    store.run(job.id)
    j = store.get(job.id)
    assert j.round == 0  # rolled back
    assert len(j.rounds) == 1  # only the initial round
    assert jobs.NO_CHANGE_NOTE in j.result.report.warnings


def test_failed_revision_keeps_the_last_good_proof(monkeypatch):
    """A network blip mid-revision must not cost the user the proof they already
    have, or a round. The run stays `done` on the previous result and says why."""
    steps = iter([_result(80, "TEX0"), OSError("[Errno 60] Operation timed out")])

    def run(jd, rs, **k):
        step = next(steps)
        if isinstance(step, Exception):
            raise step
        return step

    store = _store(monkeypatch, run)
    job = store.create("jd", [ResumeInput(id="r", tex="T")])
    store.run(job.id)
    store.request_feedback(job.id, "tone down the AI/ML framing")
    store.run(job.id)

    j = store.get(job.id)
    assert j.status == "done"  # not stranded on the error screen
    assert j.result.tex == "TEX0"  # the finished résumé is still reachable
    assert j.round == 0  # the failed round was handed back
    assert len(j.rounds) == 1  # no slip for work that never happened
    assert any("Errno 60" in w for w in j.result.report.warnings)


def test_repeated_revision_failures_keep_one_note(monkeypatch):
    """Retrying after a blip replaces the note rather than stacking copies."""
    store = _store(monkeypatch)
    job = store.create("jd", [ResumeInput(id="r", tex="T")])
    store.run(job.id)  # a good round 0 to fall back to

    def boom(jd, rs, **k):
        raise OSError("boom")

    monkeypatch.setattr(jobs, "run_pipeline", boom)
    for _ in range(3):
        store.request_feedback(job.id, "try again")
        store.run(job.id)

    notes = [w for w in store.get(job.id).result.report.warnings if jobs.REVISION_FAILED in w]
    assert len(notes) == 1


def test_rounds_accumulate_with_deltas(monkeypatch):
    results = iter([
        _result(80, "TEX0", summary="initial tailoring"),
        _result(88, "TEX1", summary="led with platform"),
        _result(84, "TEX2", summary="toned down AI/ML"),
    ])
    store = _store(monkeypatch, lambda jd, rs, **k: next(results))
    job = store.create("jd", [ResumeInput(id="r", tex="T")])
    store.run(job.id)
    for prompt in ("lead with platform", "tone down AI/ML"):
        store.request_feedback(job.id, prompt)
        store.run(job.id)

    rounds = store.get(job.id).rounds
    assert [r.index for r in rounds] == [0, 1, 2]
    assert [r.kind for r in rounds] == ["initial", "revision", "revision"]
    assert [r.ats_overall for r in rounds] == [80, 88, 84]
    assert [r.ats_delta for r in rounds] == [None, 8, -4]  # round 0 has no delta
    assert [r.feedback for r in rounds] == [None, "lead with platform", "tone down AI/ML"]
    assert rounds[2].summary == "toned down AI/ML"


def test_feedback_requires_done_job(monkeypatch):
    store = _store(monkeypatch)
    job = store.create("jd", [])
    with pytest.raises(jobs.JobNotDone):  # still queued
        store.request_feedback(job.id, "x")


def test_get_missing_raises(monkeypatch):
    store = _store(monkeypatch)
    with pytest.raises(jobs.JobNotFound):
        store.get("does-not-exist")


def test_list_returns_summaries_newest_first(monkeypatch):
    store = _store(monkeypatch)
    j1 = store.create("Senior Backend Engineer\nAcme Corp", [ResumeInput(id="r", tex="T")])
    j2 = store.create("  \nFrontend Role at Gizmo", [])  # leading blank line
    summaries = store.list()
    assert [s.id for s in summaries] == [j2.id, j1.id]  # newest first
    assert summaries[1].title == "Senior Backend Engineer"  # first non-empty JD line
    assert summaries[0].title == "Frontend Role at Gizmo"
    assert summaries[1].status == "queued"


def test_list_summary_has_pdf_flag_and_title_fallback(monkeypatch):
    store = _store(monkeypatch)
    job = store.create("", [ResumeInput(id="r", tex="T")])  # empty JD → fallback title
    assert store.list()[0].has_pdf is False
    store.run(job.id)  # produces a result with a pdf_path
    s = store.list()[0]
    assert s.has_pdf is True
    assert s.title == "Untitled run"
