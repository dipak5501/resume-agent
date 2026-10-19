# T1 findings — hiring-agent on Ollama Cloud

Date: 2026-07-20 · Run: `score.py cisco_swe_backend_compile_verified.pdf` · model `gemma4:31b-cloud` (Ollama Cloud) · exit 0.

## TL;DR
- ✅ Runs end-to-end against Ollama Cloud with a **1-block provider patch**.
- ⚠️ **hiring-agent is a quality GATE, not a dial to optimize.** ~90/100 points are GitHub/experience-driven. A solid résumé already maxes `production` + `technical_skills`; the biggest gap (`open_source`, 35) needs real OSS activity that résumé edits cannot create. Only `self_projects` (add live-demo URLs) is meaningfully text-editable (~8 pts).
- ⚠️ Needs `GITHUB_TOKEN` at any volume (60 → 5000 req/hr).
- ✅ Reuse win: it caches a full **JSON-Resume** extraction → our T5 content model, no custom extractor needed.

## 1. Output schema
`EvaluationData` (Pydantic, `models.py`):
- `scores`: `open_source`, `self_projects`, `production`, `technical_skills` — each `{score, max, evidence}`.
- Category maxes (`score.py:80`): **35 / 30 / 25 / 10** = 100.
- `bonus_points {total ≤20, breakdown}`, `deductions {total, reasons}`.
- `key_strengths[1-5]`, `areas_for_improvement[1-5]`.
- **Overall** = Σ min(score,max) + bonus − deductions, capped at 120.

## 2. Score drivers — GitHub/experience dominated (the core question)
Sample result (Kashif backend résumé): **58/100**

| Category | Score | Driver |
|---|---|---|
| open_source | 5/35 | "only personal repos, no external contributions" → **GitHub-locked, résumé edits can't move it** |
| self_projects | 22/30 | docked for "missing live demo/URLs" → **the one résumé-editable lever (~8 pts)** |
| production | 25/25 | maxed from work experience |
| technical_skills | 10/10 | maxed from skills list |
| bonus / deductions | +2 / −6 | LinkedIn+GitHub present / project URLs missing |

Evidence of the split (code + result):
- `_evaluate_resume` scores `résumé_text` **+ appended GitHub text** + blog text.
- 90 of 100 category points are project/experience/GitHub; only 10 (`technical_skills`) is pure résumé wording.
- A decent résumé maxes `production` + `technical_skills` immediately, so realistic headroom from editing text ≈ `self_projects` (add project URLs) only. The 30-pt `open_source` gap is unreachable without real OSS.

**Implication:** do **not** loop the improver to raise this number — little to gain, and the big lever isn't text. Use it **once** as a gate + advice source (`areas_for_improvement` = genuine feedback to show the user).

## 3. Latency
~**77 s** cold, end-to-end (12:53:38 → 12:54:55). Breakdown: section extraction **60 s** (6 LLM calls), GitHub fetch ~3 s, repo classify + top-5 select ~13 s, final eval 1 call. `DEVELOPMENT_MODE=True` caches résumé + GitHub JSON → re-runs skip extraction/fetch (near-instant to the eval call).

## 4. External deps
- **GitHub API**: unauthenticated **60 req/hr**. This one candidate used **11** (9 repos). ≈5 candidates/hr before the code *sleeps* to wait out the reset. Set `GITHUB_TOKEN` → 5000/hr. Required at any real volume.
- **Ollama Cloud**: works via `Client(host="https://ollama.com", headers={"Authorization": "Bearer <key>"})`. `gemma4:31b-cloud` valid. ⚠️ **Correction (T3):** it does **not** honor Ollama's `format` schema enforcement — it returns prose / markdown tables / ```json fences```. hiring-agent still works because `evaluator.py` coaxes JSON via prompt + `extract_json_from_response()` before `json.loads`, *not* by trusting `format`. Callers (T3 `llm.py`, T4/T5) must state the exact JSON shape in the prompt and strip fences when parsing.
- A model name unknown to `prompt.py` maps to provider=OLLAMA and params=None — both handled fine, so `gemma4:31b-cloud` needs no code change.

## 5. Extraction reuse (for T5)
`cache/resumecache_<pdf>.json` = full **JSON-Resume** structure (basics/work/education/awards/skills/projects — confirmed: 3 work, 2 projects, 4 skills). Directly reusable as the improver's editable content model. Caveat: it's PDF→JSON (lossy vs the original `.tex`); T5 edits the `.tex`, but this JSON is ideal for gap analysis + JD matching.

## 6. Integration recommendation
- Call as a **subprocess** (`score.py <pdf>`) from its own venv — isolates its old pins (`ollama==0.5.1`, `pydantic==2.11.7`, `google-generativeai`) from our backend. Venv already set up at `external/hiring-agent/.venv`.
- **Provider patch required (done):** `OllamaProvider.__init__` → authed `Client` from `OLLAMA_HOST` / `OLLAMA_API_KEY`.
- Env to run: `LLM_PROVIDER=ollama`, `DEFAULT_MODEL=gemma4:31b-cloud`, `OLLAMA_HOST=https://ollama.com`, `OLLAMA_API_KEY=…`, `GITHUB_TOKEN=…`.
- Run **once per résumé as a gate** (T6), not per improver iteration. Cache dir makes re-runs idempotent.
- Benign gotcha: `evaluator.py` logs the raw LLM response at `ERROR` level — it's not a failure.

## Artifacts / config
- Patched: `external/hiring-agent/models.py` (`OllamaProvider`).
- Sample PDF: `cisco_swe_backend_compile_verified.pdf` (1 pg, `github.com/KashifManzer`).
- Outputs: `cache/*.json`, `resume_evaluations.csv`, `t1_run.log` (all under gitignored `external/`).
