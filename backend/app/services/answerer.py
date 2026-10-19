"""Screening-question answerer (T13). Mirrors T12's field_map: a question
resolves via cache → heuristic → LLM classify → cache, then branches on the
matched answer-bank entry:

    verbatim  → fill the bank value as-is, NO LLM
    adaptable → LLM tailors the stored template to this JD + tailored résumé
    fresh     → LLM drafts from the tailored résumé + profile (no bank match)

The classification is cached (stable); the prose is regenerated every call
(per-JD, never cached across jobs). Honesty guardrails are the trust boundary —
see the never-invent / never-auto handling below; do NOT simplify them away."""

import hashlib
import re

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.canonical import ANSWER_CANONICAL, ANSWER_CLASSIFY, NEVER_AUTO
from app.core.config import OLLAMA_ANSWER_MODEL
from app.models import Answer, AnswerResolution
from app.schemas.answer import AnswerResult
from app.services import llm
from app.services.selector import tex_to_text

PID = "default"

# The web app is the only caller whose question text the USER typed; the extension
# passes a label scraped from the ATS page. Link-following is gated on this.
WEBAPP_HOST = "webapp"

# A bug in OUR code must never be reported to the user as "the LLM is down".
# These types mean we broke something - a stale call signature, a typo'd
# attribute, a bad import, a tripped assertion - and swallowing them as transport
# failures hid three real defects in this file alone: two tests that kept passing
# after the behaviour they guarded had changed, and monkeypatched stubs whose
# signatures had drifted. Genuine transport/parse failures (network, HTTP, JSON)
# are still caught and degrade gracefully.
_OUR_BUG = (TypeError, AttributeError, NameError, ImportError, AssertionError)

# Deterministic classifier. Never-auto categories first so a demographic /
# background question can never be shadowed by a benign match. Ordered
# most-specific → most-general within each group.
_Q_RULES: list[tuple[str, re.Pattern]] = [
    ("eeo_demographic", re.compile(r"\b(race|ethnicit|gender|\bsex\b|veteran|disab|sexual orientation|pronoun)")),
    ("criminal_background", re.compile(r"crimin|convict|felon|background check|been arrested")),
    ("requires_sponsorship", re.compile(r"sponsor|require.*visa|visa.*require")),
    ("work_authorization", re.compile(r"authoriz(ed|ation)\s*to\s*work|right\s*to\s*work|work permit|legally.*work|eligible to work")),
    ("salary_expectation", re.compile(r"salary|compensation|desired pay|expected (pay|salary|comp)|pay expectation")),
    ("notice_period", re.compile(r"notice period")),
    ("earliest_start_date", re.compile(r"start date|when can you start|available.*start|earliest.*start")),
    ("willing_to_relocate", re.compile(r"relocat")),
    ("preferred_location_remote", re.compile(r"\bremote\b|on-?site|hybrid|location preference")),
    ("years_experience", re.compile(r"years?\s*of\s*experience|years?\s*experience|how many years")),
    ("how_heard_about_us", re.compile(r"how did you hear|where did you hear|hear about (us|this|the)|referr")),
    ("why_leaving", re.compile(r"why.*leav|reason for leaving|leaving your (current|present|last)")),
    ("why_company", re.compile(r"why.*(work (here|for us|at)|join|interested in (us|this|our|working))|this (company|role|position)|our (company|mission|team|product)")),
    ("tell_me_about_yourself", re.compile(r"tell (us|me) about yourself|about yourself|introduce yourself|your background")),
]


_Q_RULE_BY_CANON = dict(_Q_RULES)

# A question asking the applicant to DESCRIBE or EXPLAIN their own work wants
# prose, not a stored fact.
_DESCRIPTIVE = re.compile(
    r"\b(describe|explain|elaborate|walk (us|me) through|tell (us|me) (about|how|why)|"
    r"how (did|do|would) you|what (was|were|is|are) your (role|experience|approach)|"
    r"(give|share) (us |me )?(an |a )?(example|instance)|"
    r"what (did|do) you (build|built|work|do))\b"
)


def _norm(q: str) -> str:
    """Lowercase, strip required-markers, collapse whitespace — so trivial
    punctuation/spacing churn doesn't thrash the cache or miss a custom match."""
    return " ".join(re.sub(r"[*✱?:]", " ", q.lower()).split())


def _misrouted(question: str, canon: str | None) -> bool:
    """True when a DESCRIPTIVE question landed in a verbatim FACT bucket that its
    own words never asked for.

    Proven live: "Describe your Python development experience" was classified
    `years_experience` — a verbatim category whose answer-bank row is empty — so
    `answer()` refused with "no stored value" and never called the LLM at all.
    The classify vocabulary has no bucket for skills prose, and "…experience" is
    the nearest-looking label, so the model reaches for it.

    Deliberately narrow: it only fires when the category's OWN trigger words are
    absent. "Describe your salary expectations" still resolves to
    `salary_expectation` (the word "salary" is right there), so a question really
    asking for a number is never quietly turned into drafted prose."""
    if not canon or ANSWER_CANONICAL.get(canon) != "verbatim":
        return False
    if not _DESCRIPTIVE.search(_norm(question)):
        return False
    rx = _Q_RULE_BY_CANON.get(canon)
    return rx is None or not rx.search(_norm(question))


def question_sig(question: str) -> str:
    return hashlib.sha256(_norm(question).encode()).hexdigest()[:16]


def _heuristic(question: str) -> str | None:
    hay = _norm(question)
    for canon, rx in _Q_RULES:
        if rx.search(hay):
            return canon
    return None


class _ClassifyOut(BaseModel):
    canonical: str


def _llm_classify(question: str) -> str | None:
    """One LLM call to classify a question into the answer vocab. Returns a
    canonical key, or None for no-match (fresh). Coerces anything off-vocab to
    None. Raises on transport failure — the caller decides whether to cache."""
    vocab = ", ".join(sorted(ANSWER_CLASSIFY))
    messages = [
        {
            "role": "system",
            "content": (
                "You classify a job-application screening QUESTION into a fixed vocabulary. "
                "You only say what the question ASKS — you never answer it. Reply JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Vocabulary: {vocab}\n\nQuestion: {question!r}\n\n"
                'Return {"canonical":"<key>"}. Use "none" if nothing fits.'
            ),
        },
    ]
    resp = llm.chat(messages, format=_ClassifyOut.model_json_schema())
    canon = resp.get("canonical") if isinstance(resp, dict) else None
    if canon in NEVER_AUTO or canon in ANSWER_CANONICAL:
        return canon
    return None  # "none" or anything off-vocab


def resolve(host: str, question: str, session: Session) -> str | None:
    """cache → heuristic → LLM classify → cache. Returns a canonical key or None
    (no match → fresh). An LLM outage is transient: fall back to the heuristic
    result and DON'T cache, so the cache is never poisoned with a wrong 'none'."""
    sig = question_sig(question)
    cached = session.scalar(
        select(AnswerResolution).where(AnswerResolution.host == host, AnswerResolution.question_sig == sig)
    )
    if cached is not None:
        canon = cached.canonical or None
        if not _misrouted(question, canon):
            return canon
        # Cached before the misrouting guard existed, so it would refuse forever.
        # Drop it and re-derive below - otherwise the only cure is hand-deleting
        # rows from the database, which is how this one had to be cleared.
        forget_resolution(question, session, host)

    canon = _heuristic(question)
    if canon is None:
        try:
            canon = _llm_classify(question)
        except _OUR_BUG:
            raise
        except Exception:
            return None  # transient — resolve again next time, cache nothing

    if _misrouted(question, canon):
        canon = None  # cache the CORRECTED verdict, not the misclassification

    session.add(AnswerResolution(host=host, question_sig=sig, canonical=canon or ""))
    session.commit()
    return canon


def forget_resolution(question: str, session: Session, host: str | None = None) -> int:
    """Drop cached classifications for a question (all hosts unless one is given).

    There was no invalidation path at all, so a single misclassification stuck
    forever: the question that shipped this bug would keep refusing on that host
    even after the classifier was fixed. Returns the number of rows removed."""
    stmt = select(AnswerResolution).where(AnswerResolution.question_sig == question_sig(question))
    if host is not None:
        stmt = stmt.where(AnswerResolution.host == host)
    rows = list(session.scalars(stmt))
    for r in rows:
        session.delete(r)
    session.commit()
    return len(rows)


# --- answer bank lookups ----------------------------------------------------


def _bank(session: Session, canonical: str) -> Answer | None:
    return session.scalar(
        select(Answer).where(Answer.profile_id == PID, Answer.canonical == canonical)
    )


def _custom_match(session: Session, question: str) -> Answer | None:
    """A user's custom Q&A whose stored question matches this one (normalized).
    Exact-normalized match only — no embeddings (YAGNI); it grows if real forms
    need fuzzier matching. ponytail: O(n) scan, n = a user's custom entries."""
    want = _norm(question)
    for a in session.scalars(select(Answer).where(Answer.profile_id == PID, Answer.canonical.is_(None))):
        if a.question and _norm(a.question) == want:
            return a
    return None


# --- result builders --------------------------------------------------------


def _verbatim(text: str, canonical: str | None) -> AnswerResult:
    return AnswerResult(answer=text, source="bank_verbatim", needs_review=False, canonical=canonical)


def _blank(reason: str, canonical: str | None) -> AnswerResult:
    # needs_review so a blanked high-stakes / ungroundable field is surfaced, not silently dropped.
    return AnswerResult(answer="", source="blank", needs_review=True, canonical=canonical, reason=reason)


def _draft(question: str, template: str, job_id: str | None, canonical: str | None,
           source: str, session: Session, *, host: str = "", unstored_fact: bool = False) -> AnswerResult:
    """adaptable/fresh LLM path. Grounds on the tailored résumé, plus any page the
    question links to; every result is needs_review (the human-review backstop).
    LLM down → blank + flag, no crash.

    `unstored_fact` marks a verbatim FACT category with nothing in the answer bank
    (salary, notice period). The model is then told to answer honestly and
    non-committally and to invent no specific number or date — a reply, not a
    fabricated one, and not the old dead end."""
    jd, tex = _grounding(job_id, session)
    links = _link_context(question, host)
    try:
        text = _llm_answer(question, template, jd, tex, links=links, unstored_fact=unstored_fact)
    except _OUR_BUG:
        raise  # ours to fix — never dressed up as an outage
    except Exception:
        return _blank("couldn't draft — LLM unavailable", canonical)
    if not text.strip():
        # Nothing on the résumé, the linked pages or the profile supports an
        # answer. Refusing to invent one is correct - but say WHY, because
        # "couldn't ground an answer" left no idea what to do next.
        why = "nothing in your résumé or profile covers this"
        if host == WEBAPP_HOST and _URL_RE.search(question) and not links:
            why = "couldn't read the link, and your résumé doesn't cover this"
        return _blank(f"{why} — write this one yourself", canonical)
    return AnswerResult(answer=text.strip(), source=source, needs_review=True, canonical=canonical)


class _AnswerOut(BaseModel):
    answer: str


def _llm_answer(question: str, template: str, jd: str, tex: str, *,
                links: str = "", unstored_fact: bool = False) -> str:
    """Draft or tailor one answer. Honesty is baked into the prompt: assert only
    facts present in the résumé/profile; unknown factual question → empty."""
    # Adapt path (T24 hardening): a saved template is a STYLE guide, not a set of
    # facts to preserve. Résumés are re-tailored per job, so a claim that was true
    # of résumé A may be absent from the résumé this recruiter reads — drop it
    # rather than assert something the page in their hand doesn't support.
    task = (
        "Re-ground the applicant's saved template on THIS role and THIS résumé. Keep its style, "
        "voice and intent, but assert ONLY claims the résumé below supports: DROP any template "
        f"claim it does not support, and never invent new credentials.\nTemplate: {template!r}"
        if template.strip()
        else "Draft an answer grounded ONLY on the résumé below."
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You draft an applicant's answer to a job screening question. Assert ONLY facts "
                "present in the résumé/job description provided — never invent experience, numbers, "
                "employers or credentials. A question asking the applicant to DESCRIBE or EXPLAIN "
                "their own work — a project, how they approached something, a challenge, what they "
                "built — is answered from the real projects and roles on the résumé: draw on those, "
                "do not refuse. Return an empty answer ONLY when the question asks for a specific "
                "fact the résumé does not contain, or the résumé holds nothing relevant to it. "
                'First person, concise, no preamble. Reply JSON only.'
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question: {question!r}\n\n{task}\n\n"
                + (
                    "This asks for a personal fact the applicant has NOT stored (a figure, a date, "
                    "a preference). Do NOT return empty — answer it. If the résumé below genuinely "
                    "supports the answer (for example years of experience, which follows from the "
                    "dates on it), state it plainly. If it does NOT, give a brief, honest, "
                    "non-committal reply and invent NO specific number, date or amount — something "
                    "they can send as-is or edit.\n\n"
                    if unstored_fact
                    else ""
                )
                # Plain text, not raw LaTeX: the preamble + markup pushed Projects and
                # Achievements past the 6000-char cap, so the model never saw them.
                + f"--- Job description ---\n{jd[:6000]}\n\n--- Tailored résumé ---\n{tex_to_text(tex)[:6000]}\n\n"
                + (f"{links}\n\n" if links else "")
                + 'Return {"answer":"<text or empty>"}'
            ),
        },
    ]
    resp = llm.chat(messages, format=_AnswerOut.model_json_schema(), model=OLLAMA_ANSWER_MODEL)
    return resp.get("answer", "") if isinstance(resp, dict) else ""


def _grounding(job_id: str | None, session: Session) -> tuple[str, str]:
    """(jd_text, résumé_tex) to draft from. Prefer the selected run's tailored
    résumé; with no run (or a gone one), fall back to the default library résumé
    so free-text questions still draft from the user's real experience."""
    if job_id:
        from app.services.jobs import store  # local import avoids a router import cycle
        jd, tex = store.grounding(job_id)
        if tex:
            return jd, tex
    return "", _default_resume_tex(session)


_URL_RE = re.compile(r"https?://[^\s<>\"')]+")


def _link_context(question: str, host: str) -> str:
    """Page text for any URL the question itself carries, so a question like
    "tell me about my project https://github.com/… " can actually be answered
    instead of refused for want of grounding.

    Reuses `jd_fetch._guarded_get`, which already blocks SSRF into loopback /
    private / link-local space and re-checks every redirect hop. Best-effort:
    any failure returns "" and the caller drafts from the résumé alone."""
    # ONLY for questions the user typed in the web app. The extension passes the
    # field LABEL scraped from the ATS page, so honouring links there would let a
    # page trigger an outbound request from the user's machine just by naming a
    # URL in a label. The SSRF guard blocks internal targets; this blocks the
    # page from choosing targets at all.
    if host != WEBAPP_HOST:
        return ""
    urls = _URL_RE.findall(question)[:2]  # a question cites one or two links, not twenty
    if not urls:
        return ""
    import trafilatura

    from app.services.jd_fetch import _guarded_get

    out: list[str] = []
    for url in urls:
        try:
            body = _guarded_get(url).decode("utf-8", "replace")
            text = (trafilatura.extract(body) or "").strip()
            if text:
                out.append(f"--- Page at {url} ---\n{text[:6000]}")
        except Exception:
            # Deliberately broad, unlike the LLM paths above: this parses an
            # arbitrary web page the user linked. Re-raising here would let one
            # malformed page fail the whole answer request instead of the answer
            # simply being drafted without that page.
            continue
    return "\n\n".join(out)


def _from_profile(session: Session, canonical: str | None) -> str:
    """A fact the user already gave us on their Profile. The answerer never read
    `Profile` at all, so `work_authorization` refused with "no stored value"
    while `work_auth='F1'`, `work_eligible='yes'` and `needs_sponsorship='no'`
    sat in the database unread. Only the user's own stored words are returned —
    nothing is inferred from them."""
    if canonical is None:
        return ""
    from app.models import Profile

    p = session.get(Profile, PID)
    if p is None:
        return ""
    yn = {"yes": "Yes", "no": "No"}
    if canonical == "work_authorization":
        if (p.work_eligible or "").lower() in yn:
            return yn[(p.work_eligible or "").lower()]
        return (p.work_auth or "").strip()
    if canonical == "requires_sponsorship":
        return yn.get((p.needs_sponsorship or "").lower(), "")
    if canonical == "preferred_location_remote":
        return (p.location or "").strip()
    return ""


def _default_resume_tex(session: Session) -> str:
    from app.models import Resume
    from app.services import storage

    r = session.scalar(select(Resume).where(Resume.profile_id == PID, Resume.is_default.is_(True))) \
        or session.scalar(select(Resume).where(Resume.profile_id == PID))
    if r is None:
        return ""
    try:
        if r.format == "pdf":
            from app.services.resume_parse import text_from_upload

            return text_from_upload(storage.open_resume_file(PID, r.id, "source.pdf"), "pdf")
        return storage.open_resume_file(PID, r.id, "source.tex").decode("utf-8", "replace")
    except Exception:
        return ""


# --- the resolver's public entrypoint ---------------------------------------


def save_mode(canonical: str | None) -> str:
    """Bank mode to default to when promoting an answer for cross-job reuse (T24):
    facts about the person are safe verbatim; anything else is résumé-grounded
    prose, which must stay adaptable so it is re-grounded per job. A never-auto
    answer is verbatim too — an LLM must never rewrite a demographic answer."""
    return "verbatim" if canonical in NEVER_AUTO else ANSWER_CANONICAL.get(canonical or "", "adaptable")


def answer(question: str, job_id: str | None, host: str, session: Session) -> AnswerResult:
    """Resolve one screening question to a fillable answer + provenance."""
    # A user's explicit custom entry is the strongest signal — honor it first.
    custom = _custom_match(session, question)
    if custom is not None:
        if custom.mode == "verbatim" and custom.answer.strip():
            return _verbatim(custom.answer, None)
        # An empty custom entry used to dead-end here. Draft instead — the user
        # asked a question, so answer it (their blank row is not an answer).
        return _draft(question, custom.answer, job_id, None,
                      source="bank_adapted" if custom.answer.strip() else "llm_fresh",
                      session=session, host=host)

    canonical = resolve(host, question, session)

    # Hard rule: never-auto categories are NEVER LLM-answered.
    if canonical in NEVER_AUTO:
        a = _bank(session, canonical)
        if a is not None and a.answer.strip():
            return _verbatim(a.answer, canonical)
        return _blank("high-stakes — leave this to yourself", canonical)

    if canonical in ANSWER_CANONICAL:
        a = _bank(session, canonical)
        mode = a.mode if a is not None else ANSWER_CANONICAL[canonical]
        template = a.answer.strip() if a is not None else ""
        if mode == "verbatim":
            if template:
                return _verbatim(template, canonical)
            # Nothing banked. Before drafting, use what the user already told us on
            # their Profile — work authorization and sponsorship live there and were
            # never read, so this refused while the answer sat in the database.
            stored = _from_profile(session, canonical)
            if stored:
                return _verbatim(stored, canonical)
            # Still nothing: reply anyway. `unstored_fact` tells the model to be
            # honest and non-committal rather than invent a salary figure. Eight of
            # the twelve bank rows ship empty, so this dead end was the common case.
            return _draft(question, "", job_id, canonical, source="llm_fresh",
                          session=session, host=host, unstored_fact=True)
        # adaptable: tailor the template, or draft fresh when the template is empty.
        return _draft(question, template, job_id, canonical,
                      source="bank_adapted" if template else "llm_fresh", session=session, host=host)

    # No match → fresh draft grounded on the tailored résumé.
    return _draft(question, "", job_id, None, source="llm_fresh", session=session, host=host)
