# Resume-Agent — High-Level Design

_Status: high-level board. We build it ticket-by-ticket (see Backlog). Each ticket gets its own focused spec + plan session._
_Last updated: 2026-07-20_

## 1. One line

Paste a job description, upload several of your own `.tex` resumes; the system picks the closest one, tailors it to the JD, scores it honestly (JD/ATS + a quality gate), and hands back a polished 1-page PDF + `.tex`.

## 2. Goal

Given a JD and N candidate resumes, produce the best honestly-achievable, JD-tailored, ATS-readable, single-page resume — and be transparent about what changed, the scores, and any gaps that can't be closed.

## 3. Users & scope

- **MVP: single user, no accounts, stateless.** One request in → result out.
- Not a job board, tracker, or multi-tenant SaaS. See Non-Goals.

## 4. Principles (the honesty rules — non-negotiable)

- **The writer never grades itself.** The improver proposes; a *separate, grounded* scorer scores. (Prevents the "always 95" self-score.)
- **The ATS number is grounded, not vibes.** = keyword coverage measured against the JD + an independent LLM rubric. Target 90–98; never hardcoded.
- **No fabrication.** The improver may only rephrase / reorder / re-emphasize *real* facts. JD keywords it can't honestly add become a "gaps" list shown to the user — not invented.
- **Respect the user's `.tex`.** Edit content only; never touch document class, packages, preamble, or section macros. Their design/format is preserved.
- **Always 1 page.** Enforced as a hard guard; forces trading weak content out for strong JD-aligned content.

## 5. Inputs / outputs

- **In:** Job description (text) + 1..N `.tex` resume files.
- **Out:** final **PDF** + edited **`.tex`** + a **report** (scores, change-log, gaps, and — if a score plateaus — a detailed explanation of why).
  - _(Text is still extracted internally for guard #2 and the scorers — just not returned to the user.)_

## 6. Flow

```
User: JD + N .tex resumes
        │
        ▼
[Selector]  LLM picks the .tex closest to the JD.
            If none is close → pick closest + warn user.
        │
        ▼
[Improver]  Edit content in the chosen .tex to fit the JD.
            Preserve format. No fabrication. Keep ≤1 page.
        │
        ▼
[Guards]    compile (latexmk/pdflatex) → extract text clean → ≤1 page.
            Any fail → reject edit / retry.
        │
        ▼
[ATS scorer] INDEPENDENT: JD keyword coverage % + LLM rubric.
        │        (Improver ↔ ATS scorer inner loop, max 3.)
        ▼
[Quality gate] hiring-agent ("hackerrank"). Pass ≥ 80–85.
            NOTE: JD-blind + GitHub-driven. Treat as a gate,
            not a dial. If it won't move, explain WHY in detail
            (e.g. dominated by GitHub profile, thin profile, JD
            mismatch) rather than looping pointlessly.
        │
        ▼
[Return]   PDF + text + .tex + report to user.
        │
        ▼
[Human loop] User requests changes → back to Improver.
            Max 5 rounds.
```

## 7. Components

| Component | Job | Notes |
|---|---|---|
| Selector | Pick JD-closest resume | LLM (Ollama Cloud) |
| Improver | Edit chosen `.tex` content to JD | LLM; content-only edits |
| ATS scorer | Grounded JD-fit score + gaps | keyword coverage + independent LLM rubric |
| Quality gate | General resume quality | hiring-agent repo, JD-blind |
| Render/guards | `.tex`→PDF, text, page check | latexmk (pdflatex) + PyMuPDF |
| Orchestrator | Wire the loops | caps + honest stop |
| UI | Paste JD, upload, show results | minimal |

## 8. Automated guards (run on every produced `.tex`)

1. **compile = validator** — `latexmk` (pdflatex) compiles; fail → reject/retry.
2. **extraction check** — extracted text is clean (catches the LaTeX garbled-glyph ATS trap; both scorers depend on clean text).
3. **≤1 page** — page count = 1, else reject/retry with "trim" instruction.

## 9. Loops

- **Inner (Improver ↔ ATS scorer):** max **3**. Stop early if the score stops improving. This is the **only** optimization loop.
- **Quality gate (hiring-agent):** run **once**, never in a loop. It's a **gate + advice source**, not an optimization target — T1 confirmed ~90/100 of its score is GitHub/experience-driven and unreachable by résumé edits (`findings/T1-hiring-agent.md`). Clear the gate at ≥ 80–85; surface its `areas_for_improvement` in the report as the honest "why the score won't move" explanation, and fold any résumé-editable advice (e.g. add project demo URLs) into the improver's normal pass.
- **Outer (human feedback):** max **5** rounds.

## 10. Locked decisions

- JD-fit scorer = **grounded keyword coverage + independent LLM judge** (no third-party ATS API).
- Resume handling = **edit user's own `.tex` in place**, preserve format, 1 page.
- LaTeX engine = **TeX Live via `latexmk`** — default `pdflatex`, fall back to `lualatex`/`xelatex` for fontspec résumés. **Tectonic dropped**: its XeTeX heap-crashes (SIGABRT in `print_glyph_name`) on `fontawesome5`, a very common résumé package — see `findings/T2-renderer.md`. Local dev = TinyTeX; deploy = `texlive` image (T8).
- Models via **Ollama Cloud** (Llama). Specific model TBD per-ticket.
- Two independent scorers: ATS (JD-fit) + hiring-agent (quality). Both gate.
- **hiring-agent = vendored** into `vendor/hiring-agent/` (MIT, pinned to a commit) so one clone has it and upstream changes can't break us; run as a **subprocess in its own venv**. Local patch: `OllamaProvider` cloud auth. See `vendor/hiring-agent/VENDORING.md`.
- **GITHUB_TOKEN** needed for hiring-agent's GitHub enrichment at volume (unauth 60/hr → 5000/hr); single dev runs work without.
- **Tech stack (locked):**
  - Backend: **Python 3.12**, **FastAPI + uvicorn** (gunicorn workers in prod), **Pydantic v2 + pydantic-settings**, deps via **uv**. Clean layout: `routers / services / schemas / core`.
  - Long jobs: **job-based API** (POST → `job_id`, GET status / SSE). Executor **in-process now**; swap to **Celery/RQ + Redis** later without changing the API contract.
  - Persistence: **deferred**. When needed (~T6) use **SQLAlchemy 2.0 + Alembic**, SQLite → Postgres by config flip.
  - Frontend: **Vite + React + TypeScript + Tailwind + shadcn/ui + TanStack Query**, deps via **pnpm**.
  - Infra: **deferred** for the first iteration — local dev is uv (backend) + pnpm (frontend), no Docker. Docker + docker-compose come later for reproducible builds/deploy.
  - Principle: mature choices + clean seams, implemented at the simplest level that works; scale by swapping a piece, not rewriting.

## 11. Backlog (build order — de-risk first)

- **T1 — Spike: hiring-agent on Ollama Cloud.** Clone repo, get `score.py resume.pdf` working against Ollama Cloud, run on a real resume, document its output format and **what actually drives the score** (GitHub vs resume text). _Highest priority — de-risks §9 quality gate._
- **T2 — LaTeX render + guards.** `.tex` → latexmk/pdflatex → PDF; extract text; enforce clean-extraction + ≤1 page.
- **T3 — JD parse + grounded ATS scorer.** JD → required keywords/skills; score = coverage % + independent LLM rubric → score + gap list.
- **T4 — Selector.** JD + N resumes → closest `.tex`; "none close" fallback + warning.
- **T5 — Improver.** Content-only `.tex` edits to close gaps; preserve format; ≤1 page; no-fabrication; change-log; compile-validate each edit.
- **T6 — Orchestrator + loops.** Wire selector → improver ↔ ATS (cap 3) → quality gate; plateau explanation; package PDF+text+.tex+report; outer human loop (cap 5).
- **T7 — UI.** Paste JD, upload `.tex`, show progress/scores/gaps/report, download PDF+text, feedback box.
- **T8 — Deploy.** Live on server (Student Pack), TeX Live + Python + Ollama Cloud.

## 12. Open decisions (settle inside their ticket)

- **App stack** — **locked**, see §10 Tech stack.
- **Hosting** (which Student Pack option) — T8.
- **Ollama Cloud model** (which Llama) — T1/T5.
- **Docker + docker-compose** — deferred to keep the first iteration lean; add later for reproducible builds/deploy.
- **Redis/Celery worker + Postgres** — deferred; adopt when load/state demands it (the job API + SQLAlchemy seams already allow the swap without a rewrite).

## 13. Non-goals (YAGNI)

- No accounts, auth, multi-tenant, DB/persistence (MVP is stateless).
- No storing "base variants" server-side (user uploads at runtime).
- No design-preservation *engine* — we keep the user's `.tex`, that's it.
- No non-`.tex` resume input for MVP (PDF/DOCX ingest is a later maybe).
