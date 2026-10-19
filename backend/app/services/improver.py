"""Improver: one tailoring pass over a résumé's LaTeX - AGGRESSIVE by default,
DIRECTED when the caller passes the user's `feedback` (T22).

Product decision: maximize ATS/JD match (target 95%+) — inject every required JD
keyword (including current gaps), rewrite the summary tight, and add a project of
the candidate's own only when a required keyword is still missing (T33). This is the
user's own résumé; they review and own every claim, so the pass reports an `added`
list (what was newly claimed) for transparency instead of refusing to add it.

Still enforced structurally: edits touch the BODY only (preamble/closing reattached
byte-for-byte), and every candidate must compile to ONE page (T2 render_tex),
retried on failure. The improver↔score loop lives in T6, not here.
"""

import re

from pydantic import BaseModel

from app.core.config import IMPROVER_COMPILE_RETRIES, OLLAMA_MODEL, OLLAMA_WRITER_MODEL
from app.schemas.ats import AtsScore
from app.schemas.improver import ImproveResult
from app.services import llm
from app.services.ats import _mentions
from app.services.render import render_plain, render_tex

_BEGIN = r"\begin{document}"
_END = r"\end{document}"


def split_tex(tex: str) -> tuple[str, str, str]:
    """(preamble, body, closing). Preamble includes `\\begin{document}`; closing
    is `\\end{document}`→end; body is between. Pure: preamble+body+closing == tex."""
    bi = tex.find(_BEGIN)
    if bi == -1:
        return "", tex, ""
    b = bi + len(_BEGIN)
    ei = tex.find(_END, b)
    if ei == -1:
        return tex[:b], tex[b:], ""
    return tex[:b], tex[b:ei], tex[ei:]


def reassemble(preamble: str, body: str, closing: str) -> str:
    return preamble + body + closing


_OUTPUT_FMT = (
    "Output EXACTLY this and nothing else:\n"
    "===TEX===\n<the full rewritten LaTeX body>\n===END===\n"
    "===CHANGES===\n"
    '{"summary": "...", "changes": ["..."], "added": ["..."]}\n'
    "===ENDCHANGES===\n"
    # Field meanings live OUTSIDE the JSON: written as the values, gpt-oss shipped
    # the instruction itself as a run's summary.
    "In that JSON: summary is 2-3 short plain-English sentences on what THIS pass did "
    "and why; changes lists what you changed, one per item; added lists each skill, "
    "project or claim you ADDED that was not in the original."
)

_EDIT_SYS = (
    "You are an elite résumé writer optimizing a résumé to score 95%+ on ATS / "
    "JD-match for a specific job. Rewrite the LaTeX body to match the job as closely "
    "as possible. Rules:\n"
    "- Make EVERY keyword in the CURRENTLY MISSING list appear, woven into the skills "
    "list, the experience bullets, and the summary so they read naturally, and keep the "
    "REQUIRED keywords the résumé already has. A keyword written as \"A / B / C\" lists "
    "alternatives: the résumé needs only one, so never add the others. Add NO other "
    "technology or tool the résumé does not already show - not the JD's nice-to-haves, "
    "not the rest of its tech stack.\n"
    "- Where the résumé names a required skill differently from the JD, also use the "
    "JD's word once (e.g. \"PostgreSQL (Postgres)\"): recruiters search the JD's exact words.\n"
    "- NEVER remove degrees, years of experience, job titles, employers, or dates.\n"
    "- PROFESSIONAL SUMMARY: rewrite it to a tight 2–3 lines, 30–40 words MAX, "
    "laser-targeted to this job: lead with the role, years of experience and any degree "
    "it states, then required skills the résumé proves. No soft-skill adjectives or "
    "soft-skill lists anywhere.\n"
    "- PAST JOBS: keep each entry's bullet count and rewrite its existing bullets; never "
    "add new bullets or new numbers to them.\n"
    "- PROJECTS: keep the candidate's real projects, most relevant to this job first, and "
    "follow the NEW PROJECT line in the request. A new project is the candidate's OWN "
    "independent work, not the employer's: never introduce the hiring company's name, its "
    "product, team or system names, its customers, or its partners anywhere in the résumé, "
    "and give it a neutral, descriptive name. Each project has 2–3 bullet points.\n"
    "- Keep \\textbf on technologies as the original does, and bold required keywords in "
    "new text.\n"
    "- Keep it to ONE page. Preserve the LaTeX structure, commands, and environments "
    "so it compiles. Do NOT touch anything outside the body you are given.\n"
    "- This is the user's own résumé; they will review and own every claim.\n"
) + _OUTPUT_FMT

# T22: a human-directed revision is NOT an optimization pass. The person read the
# résumé and said what to change, so their request outranks keyword coverage - and
# the pass must not quietly undo it by re-stuffing what they asked to tone down.
_REVISE_SYS = (
    "You are an elite résumé writer applying a HUMAN'S DIRECTED REVISION to a résumé's "
    "LaTeX body. The user has read this exact résumé and told you what to change. Rules:\n"
    "- The user's request is AUTHORITATIVE. Apply it faithfully and visibly. It takes "
    "precedence over JD-keyword coverage and over any match score - losing keyword "
    "coverage is an acceptable price for doing what they asked.\n"
    "- NEVER re-add, restore, or re-emphasize anything they asked you to remove or tone "
    "down, no matter how strongly the job description calls for it.\n"
    "- This is a revision, not a fresh rewrite: change what the request implies and leave "
    "the rest of the résumé alone.\n"
    "- Do NOT stuff in new keywords. Keep the coverage already there only where it does "
    "not conflict with the request.\n"
    "- Keep it to ONE page. Preserve the LaTeX structure, commands, and environments "
    "so it compiles. Do NOT touch anything outside the body you are given.\n"
    "- This is the user's own résumé; they will review and own every claim.\n"
) + _OUTPUT_FMT


def _parse_edit(resp: str) -> tuple[str, list[str], list[str], str]:
    m = re.search(r"===TEX===\s*(.*?)\s*===END===", resp, re.S)
    if not m:
        raise ValueError("no ===TEX=== block in edit response")
    new_body = m.group(1)
    changes: list[str] = []
    added: list[str] = []
    summary = ""
    cm = re.search(r"===CHANGES===\s*(.*?)\s*(?:===ENDCHANGES===|$)", resp, re.S)
    if cm:
        try:
            data = llm._loads(cm.group(1))
            changes = data.get("changes") or []
            added = data.get("added") or []
            summary = data.get("summary") or ""
        except Exception:
            pass  # sentinels parsed; a malformed changes block just yields empty lists
    return new_body, changes, added, summary


def _edit_body(
    body: str, jd_text: str, ats: AtsScore, error: str | None = None, feedback: str | None = None,
    model: str | None = None,
):
    if feedback:
        user = (
            f"THE USER'S REVISION REQUEST - do exactly this:\n{feedback}\n\n"
            f"JOB DESCRIPTION (context only - it does NOT override the request):\n{jd_text}\n\n"
            f"RÉSUMÉ BODY (LaTeX - revise ONLY this):\n{body}"
        )
    else:
        user = (
            f"JOB DESCRIPTION:\n{jd_text}\n\n"
            f"REQUIRED JD KEYWORDS (keep them covered; \"A / B\" is covered by any one option): "
            f"{ats.required_keywords}\n"
            f"CURRENTLY MISSING — make sure these now appear in the résumé: {ats.missing}\n"
            # T33: an invented project replaced a real, relevant one on every run, and was
            # the whole judge gain (96 -> 92 with the real one back). Only a gap earns one.
            + (f"NEW PROJECT: allowed, only to show {ats.missing} - replace the least relevant project.\n\n"
               if ats.missing else
               "NEW PROJECT: not allowed - every required keyword is covered; keep the real projects.\n\n")
            + f"RÉSUMÉ BODY (LaTeX — rewrite ONLY this):\n{body}\n\n"
            # Page overflow was the #1 failure: this budget took one-page success from 58%
            # to 92% (gpt-oss) and 79% to 92% (gemma), 24 rewrites each, in fewer calls.
            f"LENGTH BUDGET: the body above is {len(body)} characters and fills exactly one "
            f"page. Your rewritten body must be no longer than {len(body)} characters - "
            "replace content, do not add to it."
        )
    if error:
        user += f"\n\nYOUR PREVIOUS ATTEMPT FAILED: {error}\nReturn a corrected version."
    system = _REVISE_SYS if feedback else _EDIT_SYS
    resp = llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=model or OLLAMA_WRITER_MODEL,
    )
    return _parse_edit(resp)


class _Names(BaseModel):
    names: list[str]


def _employer_names(jd_text: str, ats: AtsScore) -> list[str]:
    """Names the rewrite must not introduce. 8/15 real rewrites titled the new project
    after the employer ("Coco Delivery Platform") or used its partners (DoorDash).
    A separate call because the writer, asked to list them itself, returned none in
    13/27 calls. Required keywords are dropped: MintMCP's JD names Claude and Codex
    as its own tools, and they are also what the résumé must mention."""
    try:
        out = llm.chat(
            [
                {"role": "system", "content": (
                    "From a job description, list the hiring company's name and every product, "
                    "customer, partner or investor name it mentions - proper names only, never "
                    'technologies or skills. Return ONLY JSON: {"names": ["Acme", "AcmeCloud"]}'
                )},
                {"role": "user", "content": jd_text},
            ],
            format=_Names.model_json_schema(),
        )
        names = _Names.model_validate(out).names
    except Exception:
        return []  # best-effort, like jd_fetch's cleanup: the prompt rule still applies
    keys = [t for k in ats.required_keywords for t in k.split(" / ")]
    return [n for n in names if n.strip() and not any(_mentions(n, k) or _mentions(k, n) for k in keys)]


_BARE_AMP = re.compile(r"(?<!\\)&")


def _sanitize(new_body: str, original_body: str) -> str:
    """Fix LaTeX the writer gets wrong, all seen in real rewrites:
    - bare `&` in prose ("Infrastructure & DevOps") and U+202F (narrow no-break
      space) fail to compile, and gpt-oss repeats them on retry. `&` is escaped only
      when the original body had no bare `&`, so a body that tabulates is left alone.
    - `~1 hour` and `40%` compile but silently corrupt the page ("from  1 hour",
      or the rest of the line dropped), so no retry would ever catch them. A `%`
      comment line never follows a digit, so comments are untouched.
    ponytail: only the observed cases; anything else still falls to the retry loop."""
    if not _BARE_AMP.search(original_body):
        new_body = _BARE_AMP.sub(r"\\&", new_body)
    new_body = re.sub(r"(?<!\\)~(?=\d)", r"$\\sim$", new_body)  # ~1 → ∼1
    new_body = re.sub(r"(?<=\d)%", r"\\%", new_body)  # 40% → 40\%
    return new_body.replace("\u202f", " ")


def _baseline(tex: str, **over) -> ImproveResult:
    """Compile-failure fallback: return the original with its real compile/page status."""
    r = render_tex(tex)
    return ImproveResult(
        tex=tex,
        changed=False,
        compiled=r.guards.compiles,
        single_page=r.guards.single_page,
        **over,
    )


def improve(
    tex: str, jd_text: str, ats: AtsScore, feedback: str | None = None
) -> ImproveResult:
    """One tailoring pass. Without `feedback`: the aggressive JD-match rewrite.
    With `feedback`: a directed revision that honors the user's instruction over
    keyword coverage (T22). Either way returns a compile-validated, ≤1-page rewrite
    + an `added` review list - or the untouched original if no candidate compiles
    to one page (never ship a broken/2-page résumé)."""
    preamble, body, closing = split_tex(tex)
    employer = [] if feedback else _employer_names(jd_text, ats)  # a revision may ask for them
    # A page that is already ~96% full fits or overflows on how lines wrap, which no
    # prompt rule controlled: on one real JD + résumé gpt-oss fit 4/10 runs while gemma's
    # own retry loop fit 6/6. So the default model gets a fresh loop before we keep the
    # original. ponytail: worst case doubles writer calls per round (2 x 3 attempts).
    for model in dict.fromkeys((OLLAMA_WRITER_MODEL, OLLAMA_MODEL)):  # dedup: same model runs once
        error: str | None = None  # retry feedback is about THIS model's own attempt
        for _ in range(1 + IMPROVER_COMPILE_RETRIES):
            try:
                new_body, changes, added, summary = _edit_body(body, jd_text, ats, error, feedback, model)
            except Exception as e:
                error = f"could not parse the edit ({e})"
                continue

            # The prompt forbids the employer's names; this catches the misses.
            leaked = [n for n in employer if _mentions(new_body, n) and not _mentions(body, n)]
            if leaked:
                error = f"you introduced the employer's own names ({', '.join(leaked)}); remove every one"
                continue

            new_tex = reassemble(preamble, _sanitize(new_body, body), closing)
            r = render_tex(new_tex)
            if not (r.guards.compiles and r.guards.single_page and r.guards.extraction_clean):
                error = "; ".join(r.errors) or "the rewrite did not compile to one clean page"
                continue

            if not added:  # gpt-oss dropped the "added" key 1/10; never ship a blank review list
                added = [m for m in ats.missing if any(_mentions(new_tex, t) for t in m.split(" / "))]
            return ImproveResult(
                tex=new_tex,
                changed=True,
                # a malformed changes block parses to []; the Result page reads an empty
                # list as "original kept", so a shipped rewrite always says something
                changes=changes or ["Rewrote the résumé for this job (no change list returned)"],
                added=added,
                summary=summary,
                compiled=True,
                single_page=True,
            )

    return _baseline(tex, warnings=["could not produce a valid ≤1-page rewrite; kept the original"])


_TEXT_OUTPUT = (
    "Output EXACTLY this and nothing else. The résumé must be plain text, not LaTeX "
    "and not markdown:\n"
    "===TEXT===\n<the full rewritten résumé>\n===END===\n"
    "===CHANGES===\n"
    '{"summary": "...", "changes": ["..."], "added": []}\n'
    "===ENDCHANGES===\n"
    "summary is 2-3 short plain-English sentences on what THIS pass did. "
    "changes lists what you rephrased. added must be an empty list — you add nothing."
)

_TEXT_SYS = (
    "You rewrite a résumé that was uploaded as a PDF. You are given its extracted text, "
    "not LaTeX. Return plain text only.\n"
    "Rules:\n"
    "- Use ONLY employers, job titles, dates, schools, skills, tools, projects, and "
    "numbers that already appear in the source. Do not add a job, skill, tool, degree, "
    "or metric that is not written there.\n"
    "- Do not insert a keyword just because the job description asks for it. If it is "
    "not already in the résumé, leave it out.\n"
    "- You may reorder and rephrase so the existing experience faces this job. Prefer "
    "the job's wording only when the résumé already shows that same skill.\n"
    "- Do not invent a project. Do not name the hiring company, its products, or its "
    "customers unless the source already does.\n"
    "- Keep it to one page: stay at or under the source length.\n"
) + _TEXT_OUTPUT

_TEXT_REVISE_SYS = (
    "You apply a HUMAN'S DIRECTED REVISION to a résumé that was uploaded as a PDF. "
    "You are given its extracted text, not LaTeX. Return plain text only.\n"
    "Rules:\n"
    "- The user's request is authoritative. Apply it, and leave the rest alone.\n"
    "- You still may not add an employer, title, skill, tool, degree, or number that "
    "is not already in the source, even if the user asks for one. Say so in the summary "
    "and leave that claim out.\n"
    "- Do not stuff in new keywords. Keep it to one page.\n"
) + _TEXT_OUTPUT


def _parse_plain(resp: str) -> tuple[str, list[str], list[str], str]:
    m = re.search(r"===TEXT===\s*(.*?)\s*===END===", resp, re.S)
    if not m:
        raise ValueError("no ===TEXT=== block in edit response")
    new_text = m.group(1)
    changes: list[str] = []
    added: list[str] = []
    summary = ""
    cm = re.search(r"===CHANGES===\s*(.*?)\s*(?:===ENDCHANGES===|$)", resp, re.S)
    if cm:
        try:
            data = llm._loads(cm.group(1))
            changes = data.get("changes") or []
            added = data.get("added") or []
            summary = data.get("summary") or ""
        except Exception:
            pass
    return new_text, changes, added, summary


def _clean_plain(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u202f", " ").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _normalize_plain(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_latex(text: str) -> bool:
    return re.search(r"\\(?:begin|end|documentclass|section|textbf|item)\b", text) is not None


_NUM = re.compile(r"\d+(?:\.\d+)?%?")


def _invented_numbers(source: str, rewrite: str) -> list[str]:
    """Digit sequences in the rewrite that never appear in the source."""
    src_digits = re.sub(r"\D", "", source)
    bad = []
    for n in set(_NUM.findall(rewrite)):
        raw = n[:-1] if n.endswith("%") else n
        digits = re.sub(r"\D", "", raw)
        if n in source or raw in source or (digits and digits in src_digits):
            continue
        bad.append(n)
    return sorted(bad)


def _edit_plain(
    body: str, jd_text: str, ats: AtsScore, error: str | None = None, feedback: str | None = None,
    model: str | None = None,
):
    if feedback:
        user = (
            f"THE USER'S REVISION REQUEST - do exactly this, without adding facts:\n{feedback}\n\n"
            f"JOB DESCRIPTION (context only - it does NOT override the request):\n{jd_text}\n\n"
            f"RÉSUMÉ TEXT (plain text - revise ONLY this):\n{body}"
        )
        system = _TEXT_REVISE_SYS
    else:
        user = (
            f"JOB DESCRIPTION:\n{jd_text}\n\n"
            f"KEYWORDS THE RÉSUMÉ DOES NOT ALREADY SHOW — do not add these: {ats.missing}\n\n"
            f"RÉSUMÉ TEXT (plain text — rewrite ONLY this):\n{body}\n\n"
            f"LENGTH BUDGET: the text above is {len(body)} characters. "
            f"Your rewrite must be no longer than {len(body)} characters."
        )
        system = _TEXT_SYS
    if error:
        user += f"\n\nYOUR PREVIOUS ATTEMPT FAILED: {error}\nReturn a corrected version."
    resp = llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=model or OLLAMA_WRITER_MODEL,
    )
    if not isinstance(resp, str):
        raise ValueError("edit response was not text")
    return _parse_plain(resp)


def improve_text(
    text: str, jd_text: str, ats: AtsScore, feedback: str | None = None
) -> ImproveResult:
    """One tailoring pass over extracted PDF text. Same accept/reject role as
    `improve`, but the model returns plain text and nothing may be invented.
    A failed pass returns the original wording."""
    original = _clean_plain(text)
    employer = _employer_names(jd_text, ats)
    for model in dict.fromkeys((OLLAMA_WRITER_MODEL, OLLAMA_MODEL)):
        error: str | None = None
        for _ in range(1 + IMPROVER_COMPILE_RETRIES):
            try:
                new_text, changes, added, summary = _edit_plain(
                    original, jd_text, ats, error, feedback, model,
                )
            except Exception as e:
                error = f"could not parse the edit ({e})"
                continue
            new_text = _clean_plain(new_text)
            if not new_text:
                error = "the rewrite was empty"
                continue
            if _looks_like_latex(new_text):
                error = "return plain text, not LaTeX"
                continue
            leaked = [n for n in employer if _mentions(new_text, n) and not _mentions(original, n)]
            if leaked:
                error = f"you introduced the employer's own names ({', '.join(leaked)}); remove every one"
                continue
            invented = _invented_numbers(original, new_text)
            if invented:
                error = (
                    "you added numbers that are not in the source "
                    f"({', '.join(invented[:8])}); remove them"
                )
                continue
            novel = [a for a in added if str(a).strip() and not _mentions(original, str(a))]
            if novel:
                error = (
                    "you added claims that are not in the source "
                    f"({', '.join(str(a) for a in novel[:6])}); remove them"
                )
                continue
            stuffed = []
            for gap in ats.missing:
                for opt in (t.strip() for t in gap.split(" / ") if t.strip()):
                    if _mentions(new_text, opt) and not _mentions(original, opt):
                        stuffed.append(opt)
            if stuffed:
                error = (
                    "you added skills that are not in the source "
                    f"({', '.join(stuffed[:6])}); remove them"
                )
                continue
            if _normalize_plain(new_text) == _normalize_plain(original):
                return ImproveResult(
                    tex=original, changed=False, summary=summary, compiled=True, single_page=True,
                )
            laid = render_plain(new_text)
            if not (laid.pdf_path and laid.guards.single_page):
                error = "the rewrite did not fit on one page; shorten it without dropping jobs that are in the source"
                continue
            return ImproveResult(
                tex=new_text,
                changed=True,
                changes=changes or ["Rewrote the résumé for this job (no change list returned)"],
                added=[],
                summary=summary,
                compiled=True,
                single_page=True,
            )
    return ImproveResult(
        tex=original,
        changed=False,
        compiled=True,
        single_page=True,
        warnings=["could not produce a one-page rewrite from the PDF text; kept the original wording"],
    )
