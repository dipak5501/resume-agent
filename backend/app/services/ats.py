"""Grounded JD-fit / ATS scorer: deterministic keyword coverage + an independent
per-requirement judge whose evidence is checked verbatim (T34). The scorer NEVER
edits or grades against the improver (T5) — the writer must not grade its own
homework (design §4)."""

import re

from pydantic import BaseModel

from app.core.config import ATS_COVERAGE_WEIGHT, OLLAMA_EXTRACT_MODEL, OLLAMA_JUDGE_MODEL
from app.schemas.ats import AtsScore, JdKeyword, Requirement, RequirementVerdict
from app.services import llm


def _mentions(text: str, needle: str) -> bool:
    """Case-insensitive, boundary-aware match: 'Go' matches 'write Go' but not
    'Google'; 'k8s' and 'ci/cd' match literally. Boundaries guard only the
    outer edges so terms with symbols (C++, CI/CD) still match."""
    n = needle.strip().lower()
    if not n:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", text.lower()) is not None


def keyword_coverage(
    keywords: list[JdKeyword], resume_text: str
) -> tuple[float, list[str], list[str]]:
    """Pure/deterministic. Coverage over REQUIRED keywords only; a keyword is
    matched if its term or any alias appears in the résumé. An "A / B" term is a
    set of alternatives (extract_jd_keywords), so any one option matches it."""
    required = [k for k in keywords if k.required]
    matched, missing = [], []
    for k in required:
        if any(_mentions(resume_text, t) for t in [*k.term.split(" / "), *k.aliases]):
            matched.append(k.term)
        else:
            missing.append(k.term)
    pct = len(matched) / len(required) if required else 1.0
    return pct, matched, missing


class _JdKeywords(BaseModel):
    keywords: list[JdKeyword]


def extract_jd_keywords(jd_text: str) -> list[JdKeyword]:
    """LLM, structured output. Pulls the JD's skills/tools/keywords, splits
    required vs nice-to-have, and includes common aliases (k8s, cicd, …)."""
    out = llm.chat(
        [
            {
                "role": "system",
                "content": (
                    "Extract the concrete skills, tools, and technologies from a job "
                    "description (not soft skills or generic phrases). For each: the canonical "
                    "term, common aliases/synonyms (Kubernetes->[k8s], CI/CD->[cicd, ci cd]), "
                    "and required=true if the JD lists it as a requirement/must-have, false if "
                    "nice-to-have. Alternatives the JD accepts ('Kafka or Redpanda', 'one of "
                    "AWS, Azure, or GCP') are ONE keyword: term = the options joined with ' / ' "
                    "(AWS / Azure / GCP), aliases = each option on its own plus their aliases. "
                    "Return ONLY a JSON object of exactly this shape, no markdown "
                    'or prose: {"keywords": [{"term": "Kubernetes", "aliases": ["k8s"], '
                    '"required": true}]}'
                ),
            },
            {"role": "user", "content": jd_text},
        ],
        format=_JdKeywords.model_json_schema(),
        model=OLLAMA_EXTRACT_MODEL,
    )
    return _JdKeywords.model_validate(out).keywords


class _Requirements(BaseModel):
    requirements: list[Requirement]


def extract_requirements(jd_text: str) -> list[Requirement]:
    """What a screener checks, in the JD's words: Ashby's AI review and Greenhouse
    Talent Matching grade recruiter-set criteria, not keyword density (T34). Degree
    and years included - the keyword list never sees them, so losing the BS scored 0.
    Citizenship, onsite, hours and soft traits are left out: a résumé cannot honestly
    show them, and once scored, the rewrite invented "as a U.S. citizen" (F-1 user)."""
    out = llm.chat(
        [
            {
                "role": "system",
                "content": (
                    "From a job description, list the candidate requirements a recruiter would "
                    "screen for: qualifications, experience, degrees, years, and skills. One short "
                    "checkable statement each, in the JD's words. priority = must "
                    "(required/basic/minimum), should (preferred/nice-to-have). Skip company "
                    "info, benefits, culture, EEO and legal text, and anything a résumé does not "
                    "show: work authorization, citizenship, visas, clearances, location, onsite "
                    "or remote, schedule, hours, travel, physical demands, and personality or "
                    "soft traits. Return ONLY JSON: "
                    '{"requirements": [{"text": "3+ years building backend services", '
                    '"priority": "must"}]}'
                ),
            },
            {"role": "user", "content": jd_text},
        ],
        format=_Requirements.model_json_schema(),
        model=OLLAMA_EXTRACT_MODEL,
    )
    rows = out.get("requirements") if isinstance(out, dict) else None
    if not isinstance(rows, list):
        raise ValueError("requirement extraction returned no list")
    return [  # "nice-to-have" and other labels count as should
        Requirement(text=r["text"].strip(), priority="must" if r.get("priority") == "must" else "should")
        for r in rows if isinstance(r, dict) and isinstance(r.get("text"), str) and r["text"].strip()
    ]


class _Verdict(BaseModel):
    id: int
    verdict: str
    evidence: str = ""


class _Verdicts(BaseModel):
    verdicts: list[_Verdict]


# ponytail: fixed weights (Ashby/Greenhouse let recruiters set theirs; we cannot see them).
_PRIORITY_WEIGHT = {"must": 3, "should": 1}
_VERDICT_VALUE = {"meets": 1.0, "unclear": 0.5, "not_met": 0.0}


_DASHES = re.compile(r"[\u2010-\u2015\u2212]")


def _norm(s: str) -> str:
    # U+223C: LaTeX's $\sim$ in the PDF text ("from \u223c1 hour"); a quote may use "~"
    s = _DASHES.sub("-", s).replace("\u2019", "'").replace("\u2018", "'").replace("\u223c", "~")
    return re.sub(r"\s+", " ", s).strip(" .;,").lower()


def _grounded(evidence: str, resume_text: str) -> bool:
    """Every part of the quote is in the résumé verbatim. The judge joins two real
    quotes with "..." (seen live), so each part is checked on its own. A substring
    test cannot hallucinate, unlike asking another model."""
    parts = [p for p in (_norm(p) for p in re.split(r"\.\.\.|\u2026", evidence)) if p]
    text = _norm(resume_text)
    return bool(parts) and all(_mentions(text, p) for p in parts)  # word-bounded: "Go" is not "Google"


def judge_requirements(requirements: list[Requirement], resume_text: str) -> list[RequirementVerdict]:
    """Independent judge, one call: meets / unclear / not_met per requirement, with a
    quote. A "meets" whose quote is not really in the résumé becomes "unclear"."""
    if not requirements:
        return []
    listed = "\n".join(f"{i}. [{r.priority}] {r.text}" for i, r in enumerate(requirements, 1))
    out = llm.chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a recruiter screening a résumé against the job's requirements. For "
                    "EACH numbered requirement decide: meets, not_met, or unclear. Judge ONLY what "
                    "the résumé states; never assume. For meets, copy the résumé text that proves "
                    "it VERBATIM as evidence (a short exact quote). Return ONLY JSON: "
                    '{"verdicts": [{"id": 1, "verdict": "meets", "evidence": "exact quote"}]}'
                ),
            },
            {"role": "user", "content": f"REQUIREMENTS:\n{listed}\n\nRÉSUMÉ:\n{resume_text}"},
        ],
        format=_Verdicts.model_json_schema(),
        model=OLLAMA_JUDGE_MODEL,
    )
    rows = out.get("verdicts") if isinstance(out, dict) else None
    if not isinstance(rows, list):
        raise ValueError("requirement judge returned no verdict list")
    by_id = {}
    for v in rows:
        if isinstance(v, dict) and str(v.get("id", "")).strip().isdigit():
            by_id[int(v["id"])] = v
    verdicts = []
    for i, r in enumerate(requirements, 1):
        v = by_id.get(i, {})  # a skipped requirement is unclear, never dropped
        evidence = v.get("evidence") if isinstance(v.get("evidence"), str) else ""
        evidence = evidence.strip() if _grounded(evidence, resume_text) else ""
        verdict = v.get("verdict") if v.get("verdict") in _VERDICT_VALUE else "unclear"
        if verdict == "meets" and not evidence:
            verdict = "unclear"
        verdicts.append(RequirementVerdict(**r.model_dump(), verdict=verdict, evidence=evidence))
    return verdicts


def requirement_score(verdicts: list[RequirementVerdict]) -> int:
    """Pure 0-100: weighted share of requirements the résumé shows."""
    total = sum(_PRIORITY_WEIGHT[v.priority] for v in verdicts)
    got = sum(_PRIORITY_WEIGHT[v.priority] * _VERDICT_VALUE[v.verdict] for v in verdicts)
    return round(100 * got / total) if total else 0


def _judged(score: AtsScore, verdicts: list[RequirementVerdict]) -> AtsScore:
    """`score` with its requirement part (fit, overall, rationale) set from `verdicts`."""
    fit = requirement_score(verdicts)
    if verdicts:
        overall = round(ATS_COVERAGE_WEIGHT * score.keyword_coverage * 100 + (1 - ATS_COVERAGE_WEIGHT) * fit)
        unclear = [v.text for v in verdicts if v.verdict != "meets"]
        rationale = f"Shows {len(verdicts) - len(unclear)} of {len(verdicts)} requirements" + (
            f"; not clearly shown: {'; '.join(unclear)}" if unclear else ""
        )
    else:  # nothing to judge against: say so, never invent a fit
        overall = round(score.keyword_coverage * 100)
        rationale = "No requirements found in the job description; the score is keyword coverage alone."
    return score.model_copy(update={
        "overall": max(0, min(100, overall)), "llm_fit": fit, "rationale": rationale, "requirements": verdicts,
    })


def score_with_keywords(
    keywords: list[JdKeyword], requirements: list[Requirement], resume_text: str
) -> AtsScore:
    """Blend grounded coverage + the requirement judge, against a target extracted
    ONCE per job. Lets the selector score N résumés against the same target.
    `missing` is the keyword gap list that drives T5 and the report."""
    pct, matched, missing = keyword_coverage(keywords, resume_text)
    base = AtsScore(
        overall=0, keyword_coverage=pct, llm_fit=0, required_keywords=[k.term for k in keywords if k.required],
        matched=matched, missing=missing, rationale="",
    )
    return _judged(base, judge_requirements(requirements, resume_text))


def reconcile(a: AtsScore, a_text: str, b: AtsScore, b_text: str) -> tuple[AtsScore, AtsScore]:
    """Two versions of one résumé, judged against the same requirements. The judge
    sometimes flips a verdict on text both share (seen: SpaceX, the same quote in
    both, meets -> unclear), so a rewrite looked 100 -> 99. A "meets" quote from one
    version that is verbatim in the other counts for both: the comparison then
    measures what the rewrite changed, and every "meets" still quotes its own text."""
    if [v.text for v in a.requirements] != [v.text for v in b.requirements]:
        return a, b

    def lift(x: AtsScore, x_text: str, y: AtsScore) -> AtsScore:
        vs = [
            yv if xv.verdict != "meets" and yv.verdict == "meets" and _grounded(yv.evidence, x_text) else xv
            for xv, yv in zip(x.requirements, y.requirements)
        ]
        return x if vs == x.requirements else _judged(x, vs)

    return lift(a, a_text, b), lift(b, b_text, a)


def score_ats(jd_text: str, resume_text: str) -> AtsScore:
    """Orchestrate: extract the JD target -> score. The single-résumé entry point."""
    return score_with_keywords(extract_jd_keywords(jd_text), extract_requirements(jd_text), resume_text)
