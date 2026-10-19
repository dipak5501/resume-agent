"""Orchestrator: JD + N résumés → best tailored, ATS-scored, quality-gated,
1-page PDF + report. A .tex source is edited as LaTeX and compiled with latexmk.
A PDF source has no .tex: its extracted text is rewritten and laid out on one
page. Neither path invents a LaTeX compile for a PDF.

Services are called module-qualified so tests can mock each one."""

from typing import Callable

from app.core.config import HIRING_AGENT_GATE, INNER_LOOP_MAX, TARGET_ATS
from app.schemas.pipeline import PipelineResult, Report
from app.schemas.selector import ResumeInput
from app.services import ats, hiring_agent, improver, render, selector

_GITHUB_NOTE = (
    "This general-quality score is largely GitHub/experience-driven (T1: ~90% comes from "
    "open-source and production history), so résumé edits can't move it much. It's a gate, "
    "not a dial — see the advice below for the honest levers."
)


def _tex_for(resume_id: str, resumes: list[ResumeInput]) -> str:
    return next(r.tex for r in resumes if r.id == resume_id)


def _pdf_job(prior: PipelineResult | None, resumes: list[ResumeInput]) -> bool:
    if prior is not None:
        return prior.kind == "pdf"
    return any(r.kind == "pdf" for r in resumes)


def _package_pdf(
    *,
    best_pdf,
    best_text: str,
    selection_warning: str | None,
    ats_before,
    best_ats,
    changes: list[str],
    summary: str,
    added: list[str],
    keywords,
    requirements,
    warnings: list[str],
    progress,
) -> PipelineResult:
    progress("running the quality gate")
    hiring = None
    try:
        hiring = hiring_agent.score_resume(best_pdf)
        if hiring.overall < HIRING_AGENT_GATE:
            hiring = hiring.model_copy(update={"note": _GITHUB_NOTE})
    except Exception as e:
        warnings.append(f"quality gate unavailable: {e}")
    progress("packaging the result")
    report = Report(
        selection_warning=selection_warning,
        ats_before=ats_before,
        ats_after=best_ats,
        changes=changes,
        summary=summary,
        added=list(dict.fromkeys(added)),
        hiring_agent=hiring,
        warnings=warnings,
    )
    return PipelineResult(
        pdf_path=best_pdf,
        tex=best_text,
        report=report,
        keywords=keywords,
        requirements=requirements,
        kind="pdf",
    )


def _run_pdf_pipeline(
    jd_text: str,
    resumes: list[ResumeInput],
    *,
    feedback: str | None = None,
    prior: PipelineResult | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> PipelineResult:
    """Tailor extracted PDF text. Scores and rewrites that text; the page is
    drawn from the text. latexmk is not involved."""
    progress = on_progress or (lambda _s: None)
    warnings: list[str] = []

    if prior is not None:
        picked_text = prior.tex
        selection_warning = prior.report.selection_warning
        keywords, requirements = prior.keywords, prior.requirements
        ats_before = prior.report.ats_after
    else:
        progress("selecting the closest résumé")
        selection = selector.select_resume(jd_text, resumes)
        picked = next(r for r in resumes if r.id == selection.picked_id)
        if picked.kind != "pdf":
            return run_pipeline(
                jd_text, [picked], feedback=feedback, prior=None, on_progress=on_progress,
            )
        picked_text = picked.tex
        selection_warning = selection.warning
        keywords, requirements = selection.keywords, selection.requirements
        progress("scoring the baseline")
        ats_before = ats.score_with_keywords(keywords, requirements, picked_text)

    base = render.render_plain(picked_text)
    if base.pdf_path is None:
        raise RuntimeError(base.errors[0] if base.errors else "could not lay out the PDF text")

    best_text, best_ats, best_pdf = picked_text, ats_before, base.pdf_path
    changes: list[str] = []
    added: list[str] = []
    summary = ""

    for i in range(1 if feedback else INNER_LOOP_MAX):
        progress("applying your revision" if feedback else f"improving (round {i + 1})")
        imp = improver.improve_text(best_text, jd_text, best_ats, feedback=feedback)
        if not imp.changed:
            warnings += imp.warnings
            break
        cand = render.render_plain(imp.tex)
        if not (cand.pdf_path and cand.guards.single_page):
            break
        cand_ats = ats.score_with_keywords(keywords, requirements, imp.tex)
        reread, cand_ats = ats.reconcile(best_ats, best_text, cand_ats, imp.tex)
        if best_ats is ats_before:
            ats_before = reread
        best_ats = reread
        if not feedback and cand_ats.overall <= best_ats.overall:
            if i == 0:
                warnings.append(
                    f"the rewrite scored {cand_ats.overall}, not above your original's "
                    f"{best_ats.overall}, so the original was kept"
                )
            break
        best_text, best_ats, best_pdf = imp.tex, cand_ats, cand.pdf_path
        changes += imp.changes
        added += imp.added
        summary = imp.summary or summary
        if best_ats.overall >= TARGET_ATS:
            break

    return _package_pdf(
        best_pdf=best_pdf,
        best_text=best_text,
        selection_warning=selection_warning,
        ats_before=ats_before,
        best_ats=best_ats,
        changes=changes,
        summary=summary,
        added=added,
        keywords=keywords,
        requirements=requirements,
        warnings=warnings,
        progress=progress,
    )


def run_pipeline(
    jd_text: str,
    resumes: list[ResumeInput],
    *,
    feedback: str | None = None,
    prior: PipelineResult | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> PipelineResult:
    if _pdf_job(prior, resumes):
        return _run_pdf_pipeline(
            jd_text, resumes, feedback=feedback, prior=prior, on_progress=on_progress,
        )
    progress = on_progress or (lambda _s: None)
    warnings: list[str] = []

    # 1. Start point: select (first pass) or the prior round's résumé (feedback).
    if prior is not None:
        picked_tex = prior.tex
        selection_warning = prior.report.selection_warning
        base = render.render_tex(picked_tex)
        ats_before = prior.report.ats_after  # reuse; avoids a redundant LLM re-score
        keywords, requirements = prior.keywords, prior.requirements
    else:
        progress("selecting the closest résumé")
        selection = selector.select_resume(jd_text, resumes)
        picked_tex = _tex_for(selection.picked_id, resumes)
        selection_warning = selection.warning
        # Extracted ONCE (by the selector) and frozen for the whole job, revisions
        # included: every score in the run is measured against the same target.
        keywords, requirements = selection.keywords, selection.requirements
        progress("scoring the baseline")
        base = render.render_tex(picked_tex)
        ats_before = ats.score_with_keywords(keywords, requirements, base.text)

    best_tex, best_ats, best_pdf, best_text = picked_tex, ats_before, base.pdf_path, base.text
    changes: list[str] = []
    added: list[str] = []
    summary = ""

    # 2. Inner loop — the only optimization loop, and only for a FIRST pass: keep a
    #    candidate if it compiles, is ≤1 page, and improves `overall`; stop early on
    #    plateau/target.
    #    A user revision is human-directed, so it runs ONE pass and is accepted when
    #    VALID - the ATS metric never vetoes the person (T22). We still score it
    #    honestly and report the drop when the trade costs coverage.
    for i in range(1 if feedback else INNER_LOOP_MAX):
        progress("applying your revision" if feedback else f"improving (round {i + 1})")
        imp = improver.improve(best_tex, jd_text, best_ats, feedback=feedback)
        if not imp.changed:
            warnings += imp.warnings  # say WHY nothing changed, never a silent 91 -> 91
            break
        cand = render.render_tex(imp.tex)
        if not (cand.guards.compiles and cand.guards.single_page):
            break  # improver validates already; never trust — stop rather than ship junk
        cand_ats = ats.score_with_keywords(keywords, requirements, cand.text)
        # T34: judge flips on text both versions share must not decide the gate
        reread, cand_ats = ats.reconcile(best_ats, best_text, cand_ats, cand.text)
        if best_ats is ats_before:  # still the original: its "before" is re-read too
            ats_before = reread
        best_ats = reread
        if not feedback and cand_ats.overall <= best_ats.overall:
            if i == 0:  # nothing kept at all; later plateaus are the normal stop
                warnings.append(
                    f"the rewrite scored {cand_ats.overall}, not above your original's "
                    f"{best_ats.overall}, so the original was kept"
                )
            break  # plateau / regression — discard this round, keep the best so far
        # accepted: record only what we actually keep, so the report matches the final résumé
        best_tex, best_ats, best_pdf, best_text = imp.tex, cand_ats, cand.pdf_path, cand.text
        changes += imp.changes
        added += imp.added
        # ponytail: last accepted pass's brief - that pass produced the résumé we ship;
        # the full `changes` list still carries every kept pass.
        summary = imp.summary or summary
        if best_ats.overall >= TARGET_ATS:
            break

    # 3. Quality gate — run ONCE, never looped. Gate + advice, not an optimization target.
    progress("running the quality gate")
    hiring = None
    try:
        hiring = hiring_agent.score_resume(best_pdf)
        if hiring.overall < HIRING_AGENT_GATE:
            hiring = hiring.model_copy(update={"note": _GITHUB_NOTE})
    except Exception as e:
        warnings.append(f"quality gate unavailable: {e}")

    # 4. Package.
    progress("packaging the result")
    report = Report(
        selection_warning=selection_warning,
        ats_before=ats_before,
        ats_after=best_ats,
        changes=changes,
        summary=summary,
        added=list(dict.fromkeys(added)),  # dedup, preserve order
        hiring_agent=hiring,
        warnings=warnings,
    )
    return PipelineResult(
        pdf_path=best_pdf, tex=best_tex, report=report, keywords=keywords, requirements=requirements
    )
