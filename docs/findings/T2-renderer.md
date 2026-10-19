# T2 findings — renderer: Tectonic dropped → TeX Live (latexmk/pdflatex)

Date: 2026-07-20

## Decision
Render `.tex` → PDF with **TeX Live via `latexmk`** (default `pdflatex`; `lualatex`/`xelatex` for fontspec résumés). **Tectonic is dropped.**

## Why Tectonic failed
Tectonic 0.16.9 (macOS arm64) **SIGABRTs (exit 134)** compiling any doc that loads `fontawesome5` — an extremely common résumé package (contact-line icons). Even a *dead* `\usepackage{fontawesome5}` with no `\fa` icons trips it (our sample résumé imports but never uses it, yet still crashed).

Heap corruption inside Tectonic's XeTeX engine (from `~/Library/Logs/DiagnosticReports/tectonic-*.ips`):
```
abort → ___BUG_IN_CLIENT_OF_LIBMALLOC_POINTER_BEING_FREED_WAS_NOT_ALLOCATED
      → print_glyph_name → conv_toks → expand
```
Compiled-binary bug — not patchable from our side.

Reproduced:
- `\documentclass{article}\begin{document}Hello\end{document}` → Tectonic **OK**.
- `\documentclass{article}\usepackage{fontawesome5}\begin{document}\faGithub\end{document}` → Tectonic **exit 134**.

## Why latexmk/pdflatex works
`pdflatex` uses fontawesome5's Type1 fonts (not the OTF path that crashes XeTeX). Verified:
- minimal fontawesome5 doc → `pdflatex` exit 0, PDF produced.
- the real résumé (`good.tex`) → `latexmk -pdf` exit 0, **1 page**, name extracts clean.

## Setup notes
- Machine has **TinyTeX** (`~/Library/TinyTeX`). It was outdated → `tlmgr update --self` fixed it, then `tlmgr install fontawesome5 fullpage preprint titlesec enumitem fancyhdr tabularx babel-english`. (A cosmetic fmtutil `language.dat.lua` warning appears during install — non-fatal.)
- Local dev renderer: `latexmk -pdf` (pdflatex) via TinyTeX.
- Engine policy: default `pdflatex`; fall back to `lualatex`/`xelatex` for résumés that `\usepackage{fontspec}` (real TeX Live xetex/lualatex handle OTF fine — only Tectonic's xetex is buggy).
- Missing packages for arbitrary user résumés: `tlmgr install` on demand (works now) or pre-seed a common set; deploy uses a `texlive` image (T8).

## Change-list for the in-progress T2 code (Tectonic → latexmk)
- `app/core/config.py`: `TECTONIC_BIN` → `LATEXMK_BIN` (default `"latexmk"`); add `LATEX_ENGINE` (default `"pdflatex"`).
- `app/services/render.py`: replace the subprocess with
  `[LATEXMK_BIN, f"-{LATEX_ENGINE}", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={work}", str(tex_path)]`.
  Keep the guards (compiles / clean-extract / ≤1 page) and `RenderResult` exactly as-is.
- `tests/test_render.py`: comment wording only ("Tectonic" → "latexmk").
- Optional: lualatex fallback when the first pass fails and the tex loads `fontspec`.
