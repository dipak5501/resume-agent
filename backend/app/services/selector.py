"""Selector: pick the JD-closest résumé from N candidates. Reuses T3's ATS
scoring (extract the JD's keywords and requirements ONCE, then score each
résumé) and warns when even the best pick is a weak match. All LLM traffic goes
through ats/llm — never call ollama directly (gemma4:31b-cloud ignores `format`;
see T3)."""

import re

from app.core.config import CLOSE_THRESHOLD
from app.schemas.selector import ResumeInput, Selection
from app.services import ats


def tex_to_text(tex: str) -> str:
    """Approximate LaTeX -> plaintext, for SELECTION only (not the real scoring
    text — T6 uses the picked résumé's rendered-PDF text). Drops the preamble,
    comments, and command wrappers while keeping braced content:
    `\\textbf{Kubernetes}` -> `Kubernetes`.

    A string with no LaTeX commands is already plain text (a PDF extract). Leave
    it alone so a trailing % — as in "30%" — is not read as a comment.
    """
    if "\\" not in tex:
        return re.sub(r"\s+", " ", tex).strip()
    m = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", tex, re.S)
    body = m.group(1) if m else tex
    body = re.sub(r"(?<!\\)%.*", "", body)  # line comments (not \%)
    body = re.sub(r"\\(begin|end)\{[^}]*\}", " ", body)  # environment markers
    body = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", body)  # \cmd and \cmd[opt]
    body = re.sub(r"\\[^a-zA-Z]", " ", body)  # escaped specials: \&, \_, \\
    body = re.sub(r"[{}$~^]", " ", body)  # leftover TeX specials/braces
    return re.sub(r"\s+", " ", body).strip()


def pick_best(ranked: list[tuple[str, int]]) -> Selection:
    """Pure argmax over (id, score). Ties resolve to input order (stable sort).
    If the best score is below CLOSE_THRESHOLD, flag `close=False` + a warning
    naming the pick. Requires a non-empty list."""
    ordered = sorted(ranked, key=lambda t: t[1], reverse=True)
    picked_id, best = ordered[0]
    close = best >= CLOSE_THRESHOLD
    warning = None if close else (
        f"No résumé is a strong match for this JD — best is '{picked_id}' at {best}/100 "
        f"(below {CLOSE_THRESHOLD}). Using it anyway; a more relevant résumé would score higher."
    )
    return Selection(
        picked_id=picked_id,
        ranked=[{"id": i, "score": s} for i, s in ordered],
        close=close,
        warning=warning,
    )


def source_text(resume: ResumeInput) -> str:
    """Text to score. A PDF upload is already plain text; the LaTeX flattener
    would treat `%` and braces in that extract as markup."""
    if resume.kind == "pdf":
        return resume.tex.strip()
    return tex_to_text(resume.tex)


def select_resume(jd_text: str, resumes: list[ResumeInput]) -> Selection:
    """Score each résumé against the JD (one keyword + one requirement extraction,
    N judge calls) and pick the closest. Attaches the picked résumé's full AtsScore."""
    if not resumes:
        raise ValueError("select_resume needs at least one résumé")
    keywords = ats.extract_jd_keywords(jd_text)  # hoisted: once, not per résumé
    requirements = ats.extract_requirements(jd_text)
    scores = {r.id: ats.score_with_keywords(keywords, requirements, source_text(r)) for r in resumes}

    selection = pick_best([(r.id, scores[r.id].overall) for r in resumes])
    selection.picked_score = scores[selection.picked_id]
    selection.keywords = keywords
    selection.requirements = requirements
    return selection
