# Resume Agent

Paste a job description + upload your `.tex` resumes → get a tailored, ATS-scored, 1-page PDF back. A PDF résumé can be uploaded too: it fills empty profile fields and stays in the library. Tailoring still needs a `.tex` source.

Design / board: [`docs/2026-07-20-resume-agent-design.md`](docs/2026-07-20-resume-agent-design.md)

## Stack (first iteration)

- Backend: Python 3.12 + FastAPI, managed by `uv`
- Frontend: Vite + React + TypeScript, managed by `pnpm`
- Deferred (added per ticket): Tectonic (LaTeX), Ollama Cloud wiring, Tailwind/shadcn, Docker

## Run (dev)

Backend:  `uv run --directory backend uvicorn app.main:app --reload`  → http://localhost:8000/health

Frontend: `pnpm -C frontend dev`  → http://localhost:5173
