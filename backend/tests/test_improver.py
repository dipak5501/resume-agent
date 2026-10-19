import json
import os
from pathlib import Path

import pytest

from app.schemas.ats import AtsScore
from app.services import improver
from app.services.render import render_tex

FIXTURES = Path(__file__).parent / "fixtures"
GOOD = (FIXTURES / "good.tex").read_text()


def _ats(missing=("Rust",), matched=("Python", "Kubernetes")):
    return AtsScore(
        overall=60,
        keyword_coverage=0.6,
        llm_fit=60,
        required_keywords=list(matched) + list(missing),
        matched=list(matched),
        missing=list(missing),
        rationale="x",
    )


# --- split_tex / reassemble: pure, byte-exact ------------------------------


def test_reassemble_roundtrips_byte_identical():
    preamble, body, closing = improver.split_tex(GOOD)
    assert improver.reassemble(preamble, body, closing) == GOOD


def test_split_boundaries():
    preamble, body, closing = improver.split_tex(GOOD)
    assert preamble.endswith(r"\begin{document}")
    assert closing.startswith(r"\end{document}")
    assert r"\begin{document}" not in body and r"\end{document}" not in body


# --- never-worse: no valid candidate → original, changed=False -------------


def test_never_worse_returns_original(monkeypatch):
    monkeypatch.setattr(
        improver,
        "_edit_body",
        # matches _edit_body's real arity/return shape, so the COMPILE guard is what rejects
        # it - a stale stub used to raise inside improve() and pass via the parse-error path
        lambda *a, **k: (r"\undefinedcmd breaks compile", ["x"], ["y"], ""),
    )
    monkeypatch.setattr(improver, "_employer_names", lambda jd, ats: [])  # hermetic: no LLM
    result = improver.improve(GOOD, "jd", _ats())
    assert result.changed is False
    assert result.tex == GOOD
    assert result.compiled is True  # the original does compile
    assert result.single_page is True
    assert result.warnings


def test_default_model_retries_fresh_after_writer_fails(monkeypatch):
    """gpt-oss overflowed a 96%-full page on a real run (4/10 fit); gemma's own
    retry loop fit 6/6, so it gets a fresh try before the original is kept."""
    good_body = improver.split_tex(GOOD)[1]
    calls = []

    def fake(body, jd, ats, error, feedback, model):
        calls.append((model, error))
        ok = model == "default-model"
        return (good_body if ok else r"\undefinedcmd", ["c"], ["a"], "s")

    monkeypatch.setattr(improver, "_employer_names", lambda jd, ats: [])  # hermetic: no LLM
    monkeypatch.setattr(improver, "_edit_body", fake)
    monkeypatch.setattr(improver, "OLLAMA_WRITER_MODEL", "writer-model")
    monkeypatch.setattr(improver, "OLLAMA_MODEL", "default-model")
    result = improver.improve(GOOD, "jd", _ats())
    assert result.changed is True
    assert [m for m, _ in calls] == ["writer-model"] * 3 + ["default-model"]
    assert calls[3][1] is None  # the fallback starts fresh, not with the writer's error

    calls.clear()
    monkeypatch.setattr(improver, "OLLAMA_MODEL", "writer-model")  # same model: no second loop
    assert improver.improve(GOOD, "jd", _ats()).changed is False
    assert len(calls) == 3


def test_review_list_never_silently_empty(monkeypatch):
    """gpt-oss dropped the "added" key 1/10 while writing Tokio/Elixir in: the
    review list then falls back to the gap keywords the rewrite now claims."""
    body = improver.split_tex(GOOD)[1].replace("Python", "Python, Elixir", 1)
    monkeypatch.setattr(improver, "_employer_names", lambda jd, ats: [])  # hermetic: no LLM
    monkeypatch.setattr(improver, "_edit_body", lambda *a, **k: (body, [], [], "s"))
    # GOOD says "scalable" but never "Scala": a substring match would wrongly list it
    result = improver.improve(GOOD, "jd", _ats(missing=("Elixir", "Scala", "Tokio / Elixir")))
    assert result.changed is True
    assert result.added == ["Elixir", "Tokio / Elixir"]  # a grouped term counts on any option
    assert result.changes  # nor a blank change list: the UI reads [] + [] as "original kept"


def test_sanitize_fixes_gpt_oss_latex_breakers():
    # bare & escaped, an existing \& untouched, U+202F (pdflatex rejects it) → space
    out = improver._sanitize("Infrastructure & DevOps, R\\&D, 10 000 users", "clean body")
    assert out == "Infrastructure \\& DevOps, R\\&D, 10 000 users"
    # a body that already tabulates with bare & is never rewritten
    assert improver._sanitize("a & b", "x & y") == "a & b"


def test_aggressive_pass_carries_length_budget_revision_does_not(monkeypatch):
    seen = []
    monkeypatch.setattr(improver.llm, "chat", lambda msgs, **k: seen.append(msgs[1]["content"]) or "===TEX===\nx\n===END===")
    improver._edit_body("B" * 123, "jd", _ats())
    improver._edit_body("B" * 123, "jd", _ats(), feedback="shorter")
    assert "no longer than 123 characters" in seen[0]
    assert "LENGTH BUDGET" not in seen[1]  # a human-directed revision is not length-capped


def test_new_project_only_when_a_required_keyword_is_missing(monkeypatch):
    """T33: the rewrite swapped a real, relevant project for an invented one on every
    run, and that swap was the whole judge gain. Code, not the model, decides."""
    seen = []
    monkeypatch.setattr(improver.llm, "chat", lambda msgs, **k: seen.append(msgs[1]["content"]) or "===TEX===\nx\n===END===")
    improver._edit_body("B", "jd", _ats(missing=()))
    improver._edit_body("B", "jd", _ats(missing=("Apache Flink",)))
    improver._edit_body("B", "jd", _ats(missing=("Apache Flink",)), feedback="shorter")
    assert "NEW PROJECT: not allowed" in seen[0]
    assert "NEW PROJECT: allowed, only to show ['Apache Flink']" in seen[1]
    assert "NEW PROJECT" not in seen[2]  # a revision does only what the user asked


def test_sanitize_fixes_silent_corruption_but_keeps_comments():
    body = "%-----EXPERIENCE-----\n\\resumeItem{from ~1 hour, up 40% and 92\\% AUC, by ~30\\%}"
    assert improver._sanitize(body, "") == (
        "%-----EXPERIENCE-----\n\\resumeItem{from $\\sim$1 hour, up 40\\% and 92\\% AUC, by $\\sim$30\\%}"
    )
    assert improver._sanitize("Fig.~A and \\~{}", "") == "Fig.~A and \\~{}"  # ~ before a non-digit stays


# --- live: aggressive rewrite closes gaps and stays valid ------------------


@pytest.mark.skipif(not os.getenv("OLLAMA_API_KEY"), reason="OLLAMA_API_KEY not set")
def test_live_aggressive_rewrite_closes_gaps():
    from app.services.ats import score_ats

    jd = (FIXTURES / "jd_missingskill.txt").read_text()  # demands Rust / Elixir (absent)
    ats = score_ats(jd, render_tex(GOOD).text)
    result = improver.improve(GOOD, jd, ats)

    assert result.compiled is True
    assert result.single_page is True
    assert result.changed is True
    assert result.changes  # a change-log rode along
    assert result.added  # it reports what it newly claimed
    # preamble byte-identical (structural format-respect held)
    assert improver.split_tex(result.tex)[0] == improver.split_tex(GOOD)[0]
    # a previously-missing keyword now appears in the résumé
    tex_lower = result.tex.lower()
    assert any(m.lower() in tex_lower for m in ats.missing)


def test_output_format_puts_no_instruction_inside_json_values():
    """T32: gpt-oss shipped the old in-value instruction ("2-3 short sentences, plain
    English: ...") as a run's summary. Every skeleton value must be a bare "..."."""
    skeleton = next(ln for ln in improver._OUTPUT_FMT.splitlines() if ln.startswith("{"))
    assert json.loads(skeleton) == {"summary": "...", "changes": ["..."], "added": ["..."]}


def test_rewrite_naming_the_employer_is_retried(monkeypatch):
    """T32: 8/15 real rewrites titled the new project after the employer ("Coco
    Delivery Platform") or used its partners (DoorDash). A rewrite that newly names
    one is retried; a name the original already had is fine."""
    good = improver.split_tex(GOOD)[1]
    leak = good.replace("Python", "Python, DoorDash", 1)
    outs = iter([(leak, [], ["x"], ""), (good, [], ["x"], "")])
    errors = []

    def fake(body, jd, ats, error, feedback, model):
        errors.append(error)
        return next(outs)

    monkeypatch.setattr(improver, "_employer_names", lambda jd, ats: ["Coco", "DoorDash", "Python"])
    monkeypatch.setattr(improver, "_edit_body", fake)
    result = improver.improve(GOOD, "jd", _ats())
    assert result.changed is True and "DoorDash" not in result.tex  # the clean retry shipped
    # "Python" was already on the résumé (think: a former employer), so it is no leak
    assert errors[0] is None and "DoorDash" in errors[1] and "Python" not in errors[1]

    # a user's revision may ask for the name, and is never checked
    monkeypatch.setattr(improver, "_employer_names", lambda jd, ats: pytest.fail("revision checked"))
    monkeypatch.setattr(improver, "_edit_body", lambda *a, **k: (leak, [], ["x"], ""))
    assert improver.improve(GOOD, "jd", _ats(), feedback="mention DoorDash").changed is True


def test_employer_names_never_block_a_required_keyword(monkeypatch):
    """MintMCP's JD names Claude and Codex as its own tools; both are required
    keywords the rewrite must add, so the guard must not reject them."""
    monkeypatch.setattr(improver.llm, "chat", lambda *a, **k: {"names": ["MintMCP", "Codex", "Claude Code", "AWS", " "]})
    assert improver._employer_names("jd", _ats(missing=("Codex",), matched=("Claude", "AWS / Azure"))) == ["MintMCP"]
    monkeypatch.setattr(improver.llm, "chat", lambda *a, **k: 1 / 0)
    assert improver._employer_names("jd", _ats()) == []  # best-effort: an LLM failure never blocks the rewrite
