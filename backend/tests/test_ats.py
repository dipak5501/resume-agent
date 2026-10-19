import ast
import os
from pathlib import Path

import pytest

from app.schemas.ats import JdKeyword, Requirement, RequirementVerdict
from app.services import ats

FIXTURES = Path(__file__).parent / "fixtures"


def _kw(term, aliases=(), required=True):
    return JdKeyword(term=term, aliases=list(aliases), required=required)


def _req(text, priority="must"):
    return Requirement(text=text, priority=priority)


def _v(req, verdict, evidence=""):
    return RequirementVerdict(**req.model_dump(), verdict=verdict, evidence=evidence)


# --- keyword_coverage: pure / deterministic --------------------------------


def test_coverage_matched_and_missing():
    kws = [_kw("Python"), _kw("Rust"), _kw("Kafka")]
    pct, matched, missing = ats.keyword_coverage(kws, "I ship Python and Kafka services.")
    assert matched == ["Python", "Kafka"]
    assert missing == ["Rust"]
    assert pct == pytest.approx(2 / 3)


def test_alias_match():
    kws = [_kw("Kubernetes", ["k8s"]), _kw("CI/CD", ["cicd", "ci cd"])]
    pct, matched, missing = ats.keyword_coverage(kws, "Ran k8s in prod with a cicd pipeline.")
    assert matched == ["Kubernetes", "CI/CD"]
    assert missing == []
    assert pct == 1.0


def test_alternatives_keyword_matches_any_option():
    # T32: "AWS, Azure, or GCP" is ONE keyword; the Rivian JD's options were each
    # marked required, so a résumé with AWS was told it was missing Azure.
    grouped = _kw("AWS / Azure / GCP")  # options missing from aliases: the term alone still works
    _, matched, _ = ats.keyword_coverage([grouped], "Deployed on AWS Lambda.")
    assert matched == ["AWS / Azure / GCP"]
    _, _, missing = ats.keyword_coverage([grouped], "Deployed on-prem.")
    assert missing == ["AWS / Azure / GCP"]
    # "CI/CD" has no spaced slash, so it is never split into "CI" and "CD"
    _, _, missing = ats.keyword_coverage([_kw("CI/CD")], "a CD player")
    assert missing == ["CI/CD"]


def test_case_insensitive():
    _, matched, _ = ats.keyword_coverage([_kw("PostgreSQL")], "used POSTGRESQL heavily")
    assert matched == ["PostgreSQL"]


def test_word_boundary_no_substring_false_positive():
    # "Go" must not match inside "Google"; standalone "go" must match.
    _, _, missing = ats.keyword_coverage([_kw("Go")], "I love Google Docs.")
    assert missing == ["Go"]
    _, matched, _ = ats.keyword_coverage([_kw("Go")], "I write Go daily.")
    assert matched == ["Go"]


def test_only_required_counted():
    kws = [_kw("Python", required=True), _kw("Rust", required=False)]
    pct, matched, missing = ats.keyword_coverage(kws, "Python only here.")
    assert pct == 1.0  # Rust is nice-to-have, absent but ignored
    assert missing == []
    assert matched == ["Python"]


def test_no_required_keywords_is_full_coverage():
    pct, matched, missing = ats.keyword_coverage([_kw("x", required=False)], "anything")
    assert (pct, matched, missing) == (1.0, [], [])


# --- score_ats orchestration: blend, gap list, clamp (LLM parts stubbed) ----


def test_blend_gap_and_scale(monkeypatch):
    kws = [_kw("Python"), _kw("Rust")]
    monkeypatch.setattr(ats, "extract_jd_keywords", lambda jd: kws)
    monkeypatch.setattr(ats, "extract_requirements", lambda jd: [_req("Python"), _req("Rust")])
    monkeypatch.setattr(ats, "judge_requirements", lambda reqs, r: [_v(reqs[0], "meets"), _v(reqs[1], "not_met")])
    result = ats.score_ats("jd", "I write Python daily.")
    # coverage 0.5 -> 50; requirements 3/6 -> 50; blend w=0.6: 0.6*50 + 0.4*50 = 50
    assert result.overall == 50
    assert result.llm_fit == 50
    assert result.keyword_coverage == pytest.approx(0.5)
    assert result.matched == ["Python"]
    assert result.missing == ["Rust"]
    assert result.required_keywords == ["Python", "Rust"]
    assert result.rationale == "Shows 1 of 2 requirements; not clearly shown: Rust"


def test_no_requirements_scores_coverage_alone(monkeypatch):
    """Nothing to judge against: the score is honest coverage, never a made-up fit."""
    monkeypatch.setattr(ats, "extract_jd_keywords", lambda jd: [_kw("Python"), _kw("Rust")])
    monkeypatch.setattr(ats, "extract_requirements", lambda jd: [])
    monkeypatch.setattr(ats.llm, "chat", lambda *a, **k: pytest.fail("no requirements, no judge call"))
    result = ats.score_ats("jd", "Python")
    assert result.overall == 50 and result.llm_fit == 0 and result.requirements == []
    assert "keyword coverage alone" in result.rationale


# --- requirement judge (T34): evidence checked in code, not by another model ---

RESUME = "Holding a BS in CS. Built real-time Go services on AWS. Led multi-cloud deployment on AWS and GCP."


def _judge(monkeypatch, verdicts, reqs=None):
    reqs = reqs or [_req("BS in CS"), _req("Go"), _req("AWS"), _req("Kubernetes", "should")]
    monkeypatch.setattr(ats.llm, "chat", lambda *a, **k: {"verdicts": verdicts})
    return ats.judge_requirements(reqs, RESUME)


def test_judge_keeps_only_quotes_really_in_the_resume(monkeypatch):
    out = _judge(monkeypatch, [
        {"id": 1, "verdict": "meets", "evidence": "Holding a BS in CS"},
        # seen live: two real quotes joined with "..." - each part checked on its own
        {"id": 2, "verdict": "meets", "evidence": "Built real-time Go services ... Led multi-cloud deployment"},
        # an invented quote is not evidence: downgraded, and the quote dropped
        {"id": 3, "verdict": "meets", "evidence": "Deployed Go services on AWS EKS"},
        {"id": 4, "verdict": "not_met", "evidence": ""},
    ])
    assert [(v.verdict, v.evidence) for v in out] == [
        ("meets", "Holding a BS in CS"),
        ("meets", "Built real-time Go services ... Led multi-cloud deployment"),
        ("unclear", ""),
        ("not_met", ""),
    ]


def test_judge_normalizes_what_models_rewrite(monkeypatch):
    # gpt-oss writes U+2011 hyphens, models change case/spacing and add a full stop
    out = _judge(monkeypatch, [{"id": 2, "verdict": "meets", "evidence": "built  REAL\u2011TIME go services."}])
    assert out[1].verdict == "meets"
    # the PDF text of a rewrite carries U+223C for $\sim$; a judge may quote it as "~"
    monkeypatch.setattr(ats.llm, "chat", lambda *a, **k: {"verdicts": [{"id": 1, "verdict": "meets", "evidence": "from ~1 hour to 5 minutes"}]})
    assert ats.judge_requirements([_req("speed")], "Cut time from \u223c1 hour to 5 minutes.")[0].verdict == "meets"
    # a one-word quote must be a whole word of the résumé, not part of one
    monkeypatch.setattr(ats.llm, "chat", lambda *a, **k: {"verdicts": [{"id": 1, "verdict": "meets", "evidence": "Go"}]})
    assert ats.judge_requirements([_req("Go")], "Used Google Docs")[0].verdict == "unclear"


def test_judge_never_drops_a_requirement(monkeypatch):
    out = _judge(monkeypatch, [
        {"id": "2", "verdict": "Meets!", "evidence": "Built real-time Go services"},  # bad label
        {"id": "x", "verdict": "meets"},  # unusable id
        {"verdict": "meets"},  # no id
    ])
    assert len(out) == 4 and all(v.verdict == "unclear" for v in out)
    monkeypatch.setattr(ats.llm, "chat", lambda *a, **k: {"no": "verdicts"})
    with pytest.raises(ValueError):  # a broken reply is an error, never a silent 50
        ats.judge_requirements([_req("Go")], RESUME)


def test_requirement_score_weights_musts():
    musts_ok = [_v(_req("a"), "meets"), _v(_req("b"), "meets"), _v(_req("c", "should"), "not_met")]
    assert ats.requirement_score(musts_ok) == 86  # 6 of 7
    mixed = [_v(_req("a"), "meets"), _v(_req("b"), "not_met"), _v(_req("c", "should"), "unclear")]
    assert ats.requirement_score(mixed) == 50  # (3 + 0 + 0.5) / 7
    assert ats.requirement_score([]) == 0


def test_extract_requirements_is_tolerant(monkeypatch):
    monkeypatch.setattr(ats.llm, "chat", lambda *a, **k: {"requirements": [
        {"text": " BS in CS ", "priority": "must"},
        {"text": "Kafka", "priority": "nice-to-have"},  # any non-must label is a should
        {"text": "  ", "priority": "must"},  # blank: skipped
        "junk",
    ]})
    assert ats.extract_requirements("jd") == [_req("BS in CS"), _req("Kafka", "should")]
    monkeypatch.setattr(ats.llm, "chat", lambda *a, **k: {})
    with pytest.raises(ValueError):
        ats.extract_requirements("jd")


def _scored(pct, *verdicts):
    base = ats.AtsScore(overall=0, keyword_coverage=pct, llm_fit=0, required_keywords=[], matched=[], missing=[], rationale="")
    return ats._judged(base, list(verdicts))


def test_reconcile_credits_a_quote_both_versions_share():
    """Seen live: the same quote in both versions, judged meets in one and unclear in
    the other. The comparison must measure the rewrite, not the judge's mood."""
    q = "Terraform, Docker, Kubernetes"
    a = _scored(1.0, _v(_req("build tools"), "meets", q), _v(_req("Go"), "meets", "Go"))
    b = _scored(1.0, _v(_req("build tools"), "unclear"), _v(_req("Go"), "meets", "Go"))
    a2, b2 = ats.reconcile(a, f"Tools: {q}. Go.", b, f"Skills: {q}. Go.")
    assert a2 is a  # nothing to lift: the same object back
    assert b2.requirements[0].verdict == "meets" and b2.requirements[0].evidence == q
    assert (b.overall, b2.overall) == (90, 100) and b2.llm_fit == 100  # fit 75 -> 100
    assert "Shows 2 of 2" in b2.rationale
    # the quote really left the rewrite: that is a regression and stays one
    _, b3 = ats.reconcile(a, f"Tools: {q}. Go.", b, "Skills: Go.")
    assert b3 is b
    # different requirement lists (e.g. a job scored before T34): left alone
    other = _scored(1.0, _v(_req("something else"), "unclear"), _v(_req("Go"), "meets", "Go"))
    assert ats.reconcile(a, q, other, q) == (a, other)


def test_ats_does_not_import_improver():
    tree = ast.parse(Path(ats.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported.update(a.name for a in node.names)
    assert not any("improver" in name for name in imported)


# --- live integration (needs real Ollama Cloud key) ------------------------


@pytest.mark.skipif(not os.getenv("OLLAMA_API_KEY"), reason="OLLAMA_API_KEY not set")
def test_live_score_ats():
    jd = (FIXTURES / "jd_sample.txt").read_text()
    resume = (FIXTURES / "resume_sample.txt").read_text()
    result = ats.score_ats(jd, resume)
    assert 0 <= result.overall <= 100
    assert isinstance(result.missing, list)
    assert result.rationale.strip()
    # DevOps JD must surface infra keywords
    terms = " ".join(result.required_keywords).lower()
    assert "kubernetes" in terms or "terraform" in terms
