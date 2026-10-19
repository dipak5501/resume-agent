import html
import re
import subprocess
import tempfile
from pathlib import Path

import pymupdf

from app.core.config import LATEXMK_BIN, LATEX_ENGINE
from app.schemas.render import Guards, RenderResult

MIN_TEXT_CHARS = 200  # LaTeX text layer below this ⇒ extraction almost certainly broke
MAX_BAD_RATIO = 0.01  # replacement/control-char share above this ⇒ garbled glyphs


def _compile_error(work: Path, proc: subprocess.CompletedProcess) -> str:
    """latexmk's stderr is terse; the real LaTeX error lives in resume.log
    (lines starting with '!'). Prefer those, fall back to captured output."""
    log = work / "resume.log"
    if log.exists():
        bangs = [ln for ln in log.read_text(errors="replace").splitlines() if ln.startswith("!")]
        if bangs:
            return "\n".join(bangs)
    return (proc.stderr or proc.stdout or "latexmk failed").strip()


def render_tex(
    tex: str,
    *,
    expect: list[str] | None = None,
    outdir: Path | None = None,
) -> RenderResult:
    """Compile `tex` with latexmk and run the three guards (compiles / clean
    extraction / single page). Never raises on a guard failure — every failure
    is reported in the returned RenderResult so callers can accept/reject/retry.
    """
    # ponytail: mkdtemp leaks when outdir is None; the OS reaps it. T6 passes a
    # job workdir when it needs to keep the PDF.
    work = Path(outdir) if outdir is not None else Path(tempfile.mkdtemp(prefix="render-"))
    work.mkdir(parents=True, exist_ok=True)
    tex_path = work / "resume.tex"
    tex_path.write_text(tex)

    proc = subprocess.run(
        [
            LATEXMK_BIN,
            f"-{LATEX_ENGINE}",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={work}",
            str(tex_path),
        ],
        capture_output=True,
        text=True,
    )
    pdf_path = work / "resume.pdf"
    compiles = proc.returncode == 0 and pdf_path.exists()

    if not compiles:
        return RenderResult(
            ok=False,
            pdf_path=None,
            page_count=None,
            text="",
            guards=Guards(compiles=False, extraction_clean=False, single_page=False),
            errors=[_compile_error(work, proc)],
        )

    with pymupdf.open(pdf_path) as doc:
        page_count = doc.page_count
        text = "\n".join(page.get_text() for page in doc)

    bad = sum(1 for c in text if c == "�" or (ord(c) < 32 and c not in "\t\n\r\f"))
    ratio = bad / len(text) if text else 1.0
    extraction_clean = (
        len(text) >= MIN_TEXT_CHARS
        and ratio < MAX_BAD_RATIO
        and all(anchor in text for anchor in (expect or []))
    )
    single_page = page_count == 1

    return RenderResult(
        ok=compiles and extraction_clean and single_page,
        pdf_path=pdf_path,
        page_count=page_count,
        text=text,
        guards=Guards(
            compiles=compiles,
            extraction_clean=extraction_clean,
            single_page=single_page,
        ),
        errors=[],
    )


# A PDF résumé has no .tex source. Base-14 Helvetica (what insert_textbox uses
# without a font file) replaces bullets and dashes with "?", so embed a sans
# face that keeps the text layer searchable. macOS Arial, then common Linux faces.
_SANS_FONTS = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
_PAGE = (612, 792)  # US Letter
_BOX = pymupdf.Rect(46, 40, 566, 752)
_FONT_SIZES = (10.5, 10, 9.5, 9, 8.5, 8, 7.5, 7)


def _sans_font() -> str | None:
    for path in _SANS_FONTS:
        if Path(path).is_file():
            return path
    return None


def _layout_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = "".join(ch if ch == "\n" or ord(ch) >= 32 else " " for ch in text)
    text = re.sub(r"[ ]{2,}", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _anchor(text: str) -> str:
    words = re.findall(r"[A-Za-z]{4,}", text)
    if words:
        return words[0]
    return re.sub(r"\s+", " ", text).strip()[:20]


def _from_pdf(pdf_path: Path, source: str) -> RenderResult:
    with pymupdf.open(pdf_path) as doc:
        page_count = doc.page_count
        extracted = "\n".join(page.get_text() for page in doc).replace("\xa0", " ")
    anchor = _anchor(source)
    extraction_clean = bool(anchor) and anchor.lower() in extracted.lower()
    single_page = page_count == 1
    return RenderResult(
        ok=single_page and extraction_clean,
        pdf_path=pdf_path,
        page_count=page_count,
        text=extracted,
        guards=Guards(compiles=True, extraction_clean=extraction_clean, single_page=single_page),
        errors=[] if single_page and extraction_clean else ["the text did not fit on one readable page"],
    )


def _fail(reason: str) -> RenderResult:
    return RenderResult(
        ok=False,
        pdf_path=None,
        page_count=None,
        text="",
        guards=Guards(compiles=False, extraction_clean=False, single_page=False),
        errors=[reason],
    )


def _write_textbox(text: str, work: Path, fontfile: str) -> RenderResult | None:
    for size in _FONT_SIZES:
        doc = pymupdf.open()
        page = doc.new_page(width=_PAGE[0], height=_PAGE[1])
        spare = page.insert_textbox(
            _BOX, text, fontsize=size, fontname="resume", fontfile=fontfile, align=0,
        )
        if spare < 0:
            doc.close()
            continue
        pdf_path = work / "resume.pdf"
        doc.set_metadata({"title": "Resume", "creator": "Resume Agent"})
        doc.save(pdf_path)
        doc.close()
        return _from_pdf(pdf_path, text)
    return None


def _write_htmlbox(text: str, work: Path) -> RenderResult:
    """Last resort when no sans font file is installed. Scales to one page."""
    paragraphs = []
    for para in re.split(r"\n\s*\n", text):
        lines = "<br/>".join(html.escape(line) for line in para.split("\n"))
        paragraphs.append(f"<p>{lines}</p>")
    css = "body {font-family: sans-serif; font-size: 10pt; line-height: 1.25; margin: 0;} p {margin: 0 0 6pt 0;}"
    doc = pymupdf.open()
    page = doc.new_page(width=_PAGE[0], height=_PAGE[1])
    spare, _scale = page.insert_htmlbox(_BOX, "".join(paragraphs), css=css, scale_low=0)
    if spare < 0:
        doc.close()
        return _fail("the text did not fit on one page")
    pdf_path = work / "resume.pdf"
    doc.set_metadata({"title": "Resume", "creator": "Resume Agent"})
    doc.save(pdf_path)
    doc.close()
    return _from_pdf(pdf_path, text)


def render_plain(text: str, *, outdir: Path | None = None) -> RenderResult:
    """Lay plain résumé text on a single page. Does not call latexmk — a PDF
    upload has no LaTeX source, and this PDF is not a LaTeX compile."""
    cleaned = _layout_text(text)
    if not cleaned:
        return _fail("no text to lay out")
    work = Path(outdir) if outdir is not None else Path(tempfile.mkdtemp(prefix="render-plain-"))
    work.mkdir(parents=True, exist_ok=True)
    font = _sans_font()
    if font is not None:
        fitted = _write_textbox(cleaned, work, font)
        if fitted is not None and fitted.ok:
            return fitted
    return _write_htmlbox(cleaned, work)
