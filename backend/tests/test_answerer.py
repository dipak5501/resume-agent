"""T13 — screening answerer + answer bank: question_sig stability, heuristic +
LLM-mocked classify, the cache, the three-tier branch, and the honesty guards
(never-invent, never-auto, no-invented-figures, graceful degradation)."""

import pytest
from fastapi.testclient import TestClient

from app import db
from app.canonical import ANSWER_CANONICAL
from app.main import app
from app.models import Answer, AnswerResolution
from app.routers.profile import PID
from app.services import answerer


def _fill(canonical: str, answer: str, mode: str = "verbatim") -> None:
    """Put a value in a seeded canonical-core row."""
    with db.SessionLocal() as s:
        a = s.query(Answer).filter_by(profile_id=PID, canonical=canonical).one()
        a.answer, a.mode = answer, mode
        s.commit()


def _no_llm(monkeypatch):
    """Guard: any LLM call in this path is a bug (verbatim/never-auto must not call it)."""
    def boom(*a, **k):
        raise AssertionError("LLM must not be called on this path")
    monkeypatch.setattr(answerer.llm, "chat", boom)


# --- question_sig -----------------------------------------------------------


def test_question_sig_is_normalized_stable():
    assert answerer.question_sig("Why this company?") == answerer.question_sig("why   this company")
    assert answerer.question_sig("Desired salary*") == answerer.question_sig("desired salary")
    assert answerer.question_sig("Salary") != answerer.question_sig("Notice period")


# --- seeding ----------------------------------------------------------------


def test_init_db_seeds_core_idempotently():
    with db.SessionLocal() as s:
        n1 = s.query(Answer).count()
    assert n1 == len(ANSWER_CANONICAL)
    db.init_db()  # second run seeds nothing new
    with db.SessionLocal() as s:
        assert s.query(Answer).count() == len(ANSWER_CANONICAL)


# --- heuristic classify -----------------------------------------------------


def test_heuristic_classifies_common_questions():
    h = answerer._heuristic
    assert h("What are your salary expectations?") == "salary_expectation"
    assert h("Are you authorized to work in the US?") == "work_authorization"
    assert h("Will you now or in future require visa sponsorship?") == "requires_sponsorship"
    assert h("Why do you want to work here?") == "why_company"
    assert h("Tell us about yourself") == "tell_me_about_yourself"
    assert h("What is your gender identity?") == "eeo_demographic"
    assert h("Have you ever been convicted of a felony?") == "criminal_background"
    assert h("What is your favorite programming language?") is None  # → LLM lane


# --- resolve: heuristic → LLM (mocked) → cache ------------------------------


def test_resolve_caches_classification(monkeypatch):
    calls = {"n": 0}

    def fake_classify(q):
        calls["n"] += 1
        return "why_company"

    monkeypatch.setattr(answerer, "_llm_classify", fake_classify)
    q = "What excites you about our unusual mission?"  # not heuristic-matchable
    with db.SessionLocal() as s:
        assert answerer.resolve("boards.greenhouse.io", q, s) == "why_company"
    with db.SessionLocal() as s:  # repeat → cache, no second LLM call
        assert answerer.resolve("boards.greenhouse.io", q, s) == "why_company"
    assert calls["n"] == 1
    with db.SessionLocal() as s:
        assert s.query(AnswerResolution).count() == 1


def test_resolve_llm_outage_does_not_poison_cache(monkeypatch):
    def boom(q):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(answerer, "_llm_classify", boom)
    q = "Some bespoke question the heuristic misses"
    with db.SessionLocal() as s:
        assert answerer.resolve("h", q, s) is None
        assert s.query(AnswerResolution).count() == 0  # nothing cached


# --- three-tier branch ------------------------------------------------------


def test_verbatim_fills_bank_value_with_no_llm(monkeypatch):
    _no_llm(monkeypatch)
    _fill("salary_expectation", "$150,000")
    with db.SessionLocal() as s:
        r = answerer.answer("What is your desired salary?", None, "h", s)
    assert r.answer == "$150,000" and r.source == "bank_verbatim" and r.needs_review is False


def test_adaptable_tailors_the_template(monkeypatch):
    _fill("why_company", "I love building developer tools.", mode="adaptable")
    monkeypatch.setattr(answerer, "_llm_answer", lambda q, tmpl, jd, tex, **kw: f"[tailored] {tmpl}")
    with db.SessionLocal() as s:
        r = answerer.answer("Why do you want to work here?", None, "h", s)
    assert r.source == "bank_adapted" and r.needs_review is True and "tailored" in r.answer


def test_fresh_draft_when_no_match(monkeypatch):
    monkeypatch.setattr(answerer, "_llm_classify", lambda q: None)  # no canonical
    monkeypatch.setattr(answerer, "_llm_answer", lambda q, tmpl, jd, tex, **kw: "A grounded, drafted answer.")
    with db.SessionLocal() as s:
        r = answerer.answer("Describe a project you're proud of.", None, "h", s)
    assert r.source == "llm_fresh" and r.needs_review is True and r.answer


# --- honesty guards ---------------------------------------------------------


def test_never_invents_when_llm_returns_empty(monkeypatch):
    monkeypatch.setattr(answerer, "_llm_classify", lambda q: None)
    monkeypatch.setattr(answerer, "_llm_answer", lambda q, tmpl, jd, tex, **kw: "")  # nothing grounded
    with db.SessionLocal() as s:
        r = answerer.answer("How many years of Fortran do you have?", None, "h", s)
    assert r.answer == "" and r.source == "blank" and r.needs_review is True


def test_never_auto_eeo_left_blank_no_llm(monkeypatch):
    _no_llm(monkeypatch)  # must never reach the LLM
    with db.SessionLocal() as s:
        r = answerer.answer("What is your race/ethnicity?", "job1", "h", s)
    assert r.answer == "" and r.source == "blank" and r.canonical == "eeo_demographic"
    # Assert the REASON, not just blankness. `_no_llm` raises inside llm.chat and
    # `_draft` turns any exception into a blank, so without this the test passed
    # even with the never-auto guard removed entirely - proven by mutation. The
    # two blanks are only distinguishable by their reason.
    assert r.reason == "high-stakes — leave this to yourself"


def test_never_auto_uses_stored_answer_if_present(monkeypatch):
    _no_llm(monkeypatch)
    with db.SessionLocal() as s:  # user explicitly stored a veteran-status answer
        s.add(Answer(profile_id=PID, canonical="eeo_demographic", answer="Decline to state", mode="verbatim"))
        s.commit()
    with db.SessionLocal() as s:
        r = answerer.answer("Are you a protected veteran?", None, "h", s)
    assert r.answer == "Decline to state" and r.source == "bank_verbatim"


def test_salary_with_no_stored_value_replies_without_inventing_a_figure(monkeypatch):
    """Was `test_salary_with_no_stored_value_is_blank`, and it went stale silently:
    "always reply" means an empty bank row now drafts instead of dead-ending, but
    the test kept passing because `_no_llm` made the LLM raise and `_draft` turns
    any exception into a blank. It asserted "we never guess a salary" while
    actually proving "the LLM was down".

    The guarantee that still matters is that no FIGURE is invented, so assert that
    - and assert the reply is not a dead end."""
    seen = {}

    def fake(q, tmpl, jd, tex, **kw):
        seen.update(kw)
        return "I'd rather discuss compensation once we've talked about the role."

    monkeypatch.setattr(answerer, "_llm_answer", fake)
    with db.SessionLocal() as s:
        r = answerer.answer("Desired salary?", None, "h", s)
    assert r.canonical == "salary_expectation"
    assert r.answer and r.source != "blank"  # a reply, not the old dead end
    assert seen.get("unstored_fact") is True  # ...and the prompt forbids a number
    assert r.needs_review is True


def test_graceful_degradation_verbatim_still_fills_when_llm_down(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(answerer.llm, "chat", boom)
    _fill("work_authorization", "US citizen")
    with db.SessionLocal() as s:
        r = answerer.answer("Are you authorized to work in the US?", None, "h", s)
    assert r.answer == "US citizen"  # verbatim path never needed the LLM


def test_graceful_degradation_llm_field_flags_couldnt_draft(monkeypatch):
    monkeypatch.setattr(answerer, "_llm_classify", lambda q: None)

    def boom(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(answerer.llm, "chat", boom)
    with db.SessionLocal() as s:
        r = answerer.answer("Anything else to add?", "job1", "h", s)
    assert r.answer == "" and r.needs_review is True and "couldn't draft" in (r.reason or "")


# --- custom Q&A -------------------------------------------------------------


def test_custom_verbatim_entry_matches_by_question(monkeypatch):
    _no_llm(monkeypatch)  # a matched verbatim custom entry needs no LLM
    with db.SessionLocal() as s:
        s.add(Answer(profile_id=PID, canonical=None, question="Do you have a security clearance?",
                     answer="Yes — active Secret.", mode="verbatim"))
        s.commit()
    with db.SessionLocal() as s:
        r = answerer.answer("Do you have a security clearance?", None, "h", s)
    assert r.answer == "Yes — active Secret." and r.source == "bank_verbatim"


# --- CRUD + endpoint + privacy ----------------------------------------------


def test_answers_crud_and_seed_visible():
    c = TestClient(app)
    rows = c.get("/answers").json()
    assert len(rows) == len(ANSWER_CANONICAL)
    assert {r["canonical"] for r in rows} == set(ANSWER_CANONICAL)

    core = next(r for r in rows if r["canonical"] == "notice_period")
    up = c.put(f"/answers/{core['id']}", json={"answer": "2 weeks", "mode": "verbatim"})
    assert up.status_code == 200 and up.json()["answer"] == "2 weeks"
    assert c.delete(f"/answers/{core['id']}").status_code == 400  # core can't be deleted

    made = c.post("/answers", json={"question": "Preferred pronouns?", "answer": "they/them", "mode": "verbatim"})
    cid = made.json()["id"]
    assert made.status_code == 200 and made.json()["canonical"] is None
    assert c.post("/answers", json={"question": "  "}).status_code == 400  # custom needs a question
    assert c.delete(f"/answers/{cid}").status_code == 200


def test_autofill_answer_endpoint(monkeypatch):
    _fill("years_experience", "7 years")
    c = TestClient(app)
    r = c.post("/autofill/answer", json={"question": "How many years of experience?", "host": "h"})
    assert r.status_code == 200 and r.json()["answer"] == "7 years"


def test_answer_request_is_question_only():
    # Privacy: the request model carries ONLY question + job_id + host.
    from app.schemas.answer import AnswerRequest
    assert set(AnswerRequest.model_fields) == {"question", "job_id", "host"}


# --- T24: the adapt path re-grounds instead of preserving --------------------


def test_adapt_prompt_regrounds_on_current_resume_and_drops_unsupported(monkeypatch):
    """A saved template is a STYLE guide, not a fact carrier: résumés are
    re-tailored per job, so a claim template-A asserted may be absent from the
    résumé this recruiter reads. The prompt must say DROP it, not preserve it."""
    seen = {}

    def fake_chat(messages, format=None, **_):
        seen["prompt"] = messages[1]["content"]
        return {"answer": "drafted"}

    monkeypatch.setattr(answerer.llm, "chat", fake_chat)
    answerer._llm_answer("Why us?", "I led a 40-person platform team.", "JD TEXT", "RESUME TEX")

    prompt = seen["prompt"]
    assert "RESUME TEX" in prompt  # re-grounded on THIS job's tailored résumé
    assert "DROP any template claim it does not support" in prompt
    assert "preserve every fact" not in prompt.lower()


def test_answer_sees_sections_past_the_preamble(monkeypatch):
    """Raw LaTeX cut at 6000 chars lost Projects/Achievements behind a ~1.4k preamble
    on real résumés. The prompt must carry plain résumé text, down to the last section."""
    seen = {}

    def fake_chat(messages, format=None, **_):
        seen["prompt"] = messages[1]["content"]
        return {"answer": "drafted"}

    tex = (
        "\\documentclass{article}\n" + "\\usepackage{enumitem}\n" * 300
        + "\\begin{document}\n\\section{Experience}\n" + "\\textbf{Shipped} services. " * 150
        + "\\section{Selected Projects}\n\\textbf{OmniAgent} governance platform\n\\end{document}\n"
    )
    monkeypatch.setattr(answerer.llm, "chat", fake_chat)
    answerer._llm_answer("Describe a project you built.", "", "JD", tex)

    assert "OmniAgent" in seen["prompt"]
    assert "\\usepackage" not in seen["prompt"]


def test_save_mode_defaults_by_category():
    assert answerer.save_mode("notice_period") == "verbatim"  # a fact about the person
    assert answerer.save_mode("why_company") == "adaptable"  # résumé-grounded prose
    assert answerer.save_mode(None) == "adaptable"  # fresh draft → never frozen
    assert answerer.save_mode("eeo_demographic") == "verbatim"  # never LLM-rewritten


def test_behavioral_questions_are_answered_not_refused(monkeypatch):
    """The never-invent guard is aimed at FACT lookups (certs, years, employers).
    A 'describe a project you led' question must draft from the résumé's real
    projects — refusing those made the answerer useless for the most common
    application questions."""
    seen = {}

    def fake_chat(messages, format=None, **_):
        seen["system"] = messages[0]["content"]
        return {"answer": "drafted"}

    monkeypatch.setattr(answerer.llm, "chat", fake_chat)
    answerer._llm_answer("Describe a project you led.", "", "JD", "RESUME")

    system = seen["system"]
    assert "DESCRIBE or EXPLAIN" in system and "do not refuse" in system
    # the fact-lookup guard is still the trust boundary — it must stay narrow, not vanish
    assert "never invent experience, numbers" in system
    assert "empty answer ONLY when" in system


# --- always reply: the misrouting that made it refuse -----------------------


def test_descriptive_question_is_not_routed_to_a_verbatim_fact_bucket():
    """Proven live from the user's own cache: 'Describe your Python development
    experience' resolved to `years_experience` (verbatim, empty bank row) and so
    refused without ever calling the LLM."""
    assert answerer._misrouted("Describe your Python development experience", "years_experience") is True
    assert answerer._misrouted("Tell us about how you built your last service", "years_experience") is True
    assert answerer._misrouted("Explain your approach to testing", "salary_expectation") is True


def test_misrouting_guard_is_narrow_and_never_hides_a_real_fact_question():
    """A question that really does ask for the fact keeps its category, so a salary
    question is never quietly turned into drafted prose."""
    # the category's own trigger word is present -> keep it
    assert answerer._misrouted("Describe your salary expectations", "salary_expectation") is False
    assert answerer._misrouted("How many years of experience do you have?", "years_experience") is False
    # not descriptive at all -> keep it
    assert answerer._misrouted("Expected salary?", "salary_expectation") is False
    # adaptable categories are prose already, nothing to rescue
    assert answerer._misrouted("Tell us about yourself", "tell_me_about_yourself") is False
    assert answerer._misrouted("Describe why you want to work here", "why_company") is False
    assert answerer._misrouted("anything", None) is False


def test_resolve_caches_the_corrected_verdict_not_the_misclassification(monkeypatch):
    monkeypatch.setattr(answerer, "_llm_classify", lambda q: "years_experience")
    q = "Describe your Python development experience"
    with db.SessionLocal() as s:
        answerer.forget_resolution(q, s)
        assert answerer.resolve("webapp", q, s) is None
        row = s.query(AnswerResolution).filter_by(question_sig=answerer.question_sig(q)).one()
        assert row.canonical == ""  # the corrected verdict is what gets cached
        answerer.forget_resolution(q, s)


def test_descriptive_question_now_drafts_instead_of_refusing(monkeypatch):
    monkeypatch.setattr(answerer, "_llm_classify", lambda q: "years_experience")
    monkeypatch.setattr(answerer, "_llm_answer", lambda q, tmpl, jd, tex, **kw: "I have shipped Python services since 2021.")
    q = "Describe your Python development experience"
    with db.SessionLocal() as s:
        answerer.forget_resolution(q, s)
        r = answerer.answer(q, None, "webapp", s)
        answerer.forget_resolution(q, s)
    assert r.source == "llm_fresh" and r.answer and r.needs_review is True


# --- always reply: an empty bank row is no longer terminal ------------------


def test_empty_verbatim_bank_row_drafts_instead_of_dead_ending(monkeypatch):
    """8 of the 12 seeded bank rows ship empty, so this dead end was the common
    case, not an edge case."""
    seen = {}

    def fake(q, tmpl, jd, tex, **kw):
        seen.update(kw)
        return "I'm flexible and happy to discuss what's fair for the role."

    monkeypatch.setattr(answerer, "_llm_answer", fake)
    _fill("salary_expectation", "")  # explicitly empty
    with db.SessionLocal() as s:
        r = answerer.answer("What are your salary expectations?", None, "h", s)
    assert r.answer  # a reply, not a refusal
    assert seen.get("unstored_fact") is True  # told not to invent a figure


def test_unstored_fact_prompt_forbids_inventing_a_number(monkeypatch):
    captured = {}
    monkeypatch.setattr(answerer.llm, "chat", lambda m, format=None, **_: captured.update(p=m[1]["content"]) or {"answer": "x"})
    answerer._llm_answer("Desired salary?", "", "JD", "TEX", unstored_fact=True)
    assert "invent NO specific number, date or amount" in captured["p"]
    # ...but a fact the résumé DOES support must still be stated plainly, or
    # "how many years of experience" would be answered evasively for no reason.
    assert "state it plainly" in captured["p"]


# --- always reply: use the profile we already stored ------------------------


def test_work_authorization_answers_from_profile(monkeypatch):
    """The answerer never loaded Profile, so this refused while work_eligible sat
    in the database."""
    _no_llm(monkeypatch)  # must be answered from stored data, no LLM
    _fill("work_authorization", "")  # nothing banked
    from app.models import Profile
    with db.SessionLocal() as s:
        p = s.get(Profile, PID) or Profile(id=PID)
        p.work_eligible = "yes"
        s.add(p)
        s.commit()
        r = answerer.answer("Are you authorized to work in the US?", None, "h", s)
    assert r.answer == "Yes" and r.source == "bank_verbatim"


def test_profile_fallback_returns_nothing_when_unset():
    from app.models import Profile
    with db.SessionLocal() as s:
        p = s.get(Profile, PID) or Profile(id=PID)
        p.work_eligible, p.needs_sponsorship, p.location = "", "", ""
        s.add(p)
        s.commit()
        assert answerer._from_profile(s, "work_authorization") == ""
        assert answerer._from_profile(s, "requires_sponsorship") == ""
        assert answerer._from_profile(s, None) == ""
        assert answerer._from_profile(s, "why_company") == ""  # not a profile fact


# --- always reply: a question that carries a link ---------------------------


def test_link_in_question_is_fetched_and_grounded(monkeypatch):
    """'tell about my this project https://github.com/...' refused because the
    résumé says nothing about that repo and the answerer cannot browse."""
    monkeypatch.setattr(answerer, "_URL_RE", answerer._URL_RE)  # explicit: same regex
    import app.services.jd_fetch as jd_fetch
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda url, **k: b"<html><body><article><p>" + b"resume-agent tailors a LaTeX resume to a job description. " * 6 + b"</p></article></body></html>")
    q = "tell about my project https://github.com/KashifManzer/resume-agent"
    ctx = answerer._link_context(q, "webapp")
    assert "resume-agent" in ctx
    assert "https://github.com/KashifManzer/resume-agent" in ctx
    # An ATS page supplies the field LABEL, so a URL sitting in a label must NOT
    # make us fetch anything - the page would be choosing our network targets.
    assert answerer._link_context(q, "job-boards.greenhouse.io") == ""


def test_link_context_is_best_effort_and_never_raises(monkeypatch):
    import app.services.jd_fetch as jd_fetch

    def boom(url, **k):
        raise RuntimeError("blocked by the SSRF guard")

    monkeypatch.setattr(jd_fetch, "_guarded_get", boom)
    assert answerer._link_context("see https://10.0.0.1/internal", "webapp") == ""
    assert answerer._link_context("no links here", "webapp") == ""


def test_blank_reason_explains_itself(monkeypatch):
    """The old 'couldn't ground an answer' told the user nothing about what to do."""
    monkeypatch.setattr(answerer, "_llm_classify", lambda q: None)
    monkeypatch.setattr(answerer, "_llm_answer", lambda q, tmpl, jd, tex, **kw: "")
    import app.services.jd_fetch as jd_fetch
    monkeypatch.setattr(jd_fetch, "_guarded_get", lambda url, **k: (_ for _ in ()).throw(RuntimeError("nope")))
    with db.SessionLocal() as s:
        r = answerer.answer("tell me about https://example.com/thing", None, "webapp", s)
    assert r.answer == "" and "couldn't read the link" in r.reason
    # from an ATS page we never tried the link, so we must not claim we did
    with db.SessionLocal() as s:
        r2 = answerer.answer("tell me about https://example.com/thing", None, "greenhouse.io", s)
    assert "couldn't read the link" not in (r2.reason or "")
    assert "nothing in your résumé or profile covers this" in (r2.reason or "")


# --- the carve-out stays put ------------------------------------------------


def test_never_auto_still_refuses_after_the_always_reply_change(monkeypatch):
    """EEO / criminal-background are never LLM-answered - 'always reply' does not
    extend to a legal self-identification."""
    _no_llm(monkeypatch)
    with db.SessionLocal() as s:
        for q in ("What is your gender?", "Have you ever been convicted of a felony?"):
            r = answerer.answer(q, None, "h", s)
            assert r.answer == "" and r.source == "blank"
            assert "yourself" in (r.reason or "")


# --- cache invalidation -----------------------------------------------------


def test_forget_resolution_clears_the_cache():
    q = "Describe your Python development experience"
    with db.SessionLocal() as s:
        s.add(AnswerResolution(host="webapp", question_sig=answerer.question_sig(q), canonical="years_experience"))
        s.add(AnswerResolution(host="other", question_sig=answerer.question_sig(q), canonical="years_experience"))
        s.commit()
        assert answerer.forget_resolution(q, s, host="webapp") == 1
        assert answerer.forget_resolution(q, s) == 1  # the remaining host
        assert answerer.forget_resolution(q, s) == 0


def test_a_poisoned_cache_row_self_heals(monkeypatch):
    """Found by a lean-implementation review: `forget_resolution` had no production
    caller because `resolve` trusted the cache blindly, so the misrouting guard only
    applied to NEW questions. A row cached before the fix kept refusing forever -
    the only cure was deleting rows from the database by hand."""
    monkeypatch.setattr(answerer, "_llm_classify", lambda q: None)
    q = "Describe your Python development experience"
    with db.SessionLocal() as s:
        answerer.forget_resolution(q, s)
        # a row poisoned by the OLD classifier
        s.add(AnswerResolution(host="webapp", question_sig=answerer.question_sig(q),
                               canonical="years_experience"))
        s.commit()
        assert answerer.resolve("webapp", q, s) is None  # healed, not refused
        row = s.query(AnswerResolution).filter_by(question_sig=answerer.question_sig(q)).one()
        assert row.canonical == ""  # and re-cached correctly
        answerer.forget_resolution(q, s)


def test_a_correctly_cached_row_is_left_alone(monkeypatch):
    """The self-heal must not invalidate good cache entries on every lookup."""
    def boom(q):
        raise AssertionError("must not re-classify a healthy cache row")
    monkeypatch.setattr(answerer, "_llm_classify", boom)
    q = "What are your salary expectations?"
    with db.SessionLocal() as s:
        answerer.forget_resolution(q, s)
        s.add(AnswerResolution(host="webapp", question_sig=answerer.question_sig(q),
                               canonical="salary_expectation"))
        s.commit()
        assert answerer.resolve("webapp", q, s) == "salary_expectation"
        answerer.forget_resolution(q, s)


# --- our bugs surface; their outages degrade --------------------------------


def test_a_stale_stub_signature_surfaces_instead_of_faking_an_outage(monkeypatch):
    """`_draft` used to catch bare Exception, so a monkeypatched stub whose
    signature had drifted came back as "couldn't draft — LLM unavailable". That
    masked real defects three separate times: two tests kept passing after the
    behaviour they guarded had changed, and stub drift went unnoticed."""
    monkeypatch.setattr(answerer, "_llm_classify", lambda q: None)
    monkeypatch.setattr(answerer, "_llm_answer", lambda q: "wrong arity")  # stale stub
    with db.SessionLocal() as s:
        with pytest.raises(TypeError):
            answerer.answer("Describe a project you led.", None, "h", s)


def test_no_llm_guard_is_now_real_on_the_draft_path(monkeypatch):
    """`_no_llm` raises AssertionError to prove a path must not call the LLM. That
    was being swallowed into a blank, which is exactly why the never-auto test
    passed with its guard removed."""
    monkeypatch.setattr(answerer, "_llm_classify", lambda q: None)
    _no_llm(monkeypatch)
    with db.SessionLocal() as s:
        with pytest.raises(AssertionError):
            answerer.answer("Describe a project you led.", None, "h", s)


def test_a_real_outage_still_degrades_gracefully(monkeypatch):
    """The point is to stop masking OUR bugs, not to start crashing on THEIRS."""
    monkeypatch.setattr(answerer, "_llm_classify", lambda q: None)

    def down(*a, **k):
        raise ConnectionError("ollama unreachable")

    monkeypatch.setattr(answerer, "_llm_answer", down)
    with db.SessionLocal() as s:
        r = answerer.answer("Describe a project you led.", None, "h", s)
    assert r.answer == "" and r.source == "blank"
    assert r.reason == "couldn't draft — LLM unavailable"
