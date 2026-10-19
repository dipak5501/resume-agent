from pathlib import Path

from app.services.render import render_tex

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_good_resume_passes_all_guards():
    result = render_tex(_read("good.tex"))
    assert result.ok is True
    assert result.page_count == 1
    assert "Kashif Manzer" in result.text
    assert result.guards.compiles
    assert result.guards.single_page
    assert result.guards.extraction_clean
    assert result.pdf_path is not None and result.pdf_path.exists()


def test_two_page_fails_single_page_guard():
    result = render_tex(_read("twopage.tex"))
    assert result.guards.single_page is False
    assert result.ok is False


def test_broken_tex_reports_error_without_crashing():
    result = render_tex(_read("broken.tex"))
    assert result.guards.compiles is False
    assert result.ok is False
    assert result.errors  # non-empty captured latexmk/LaTeX error


def test_expect_anchor_present_and_bogus():
    good = _read("good.tex")
    assert render_tex(good, expect=["Kashif Manzer"]).guards.extraction_clean is True
    assert render_tex(good, expect=["Zxqwv Notaname"]).guards.extraction_clean is False
