# Vendored: hiring-agent

- **Source:** https://github.com/interviewstreet/hiring-agent
- **Pinned commit:** `4db86554e622f4fb8e653565bc99fb7df2f6ef93` (also in `.vendored-commit`)
- **License:** MIT (see `LICENSE`, retained)

## Why vendored (not a submodule)
We both depend on this **and** patch it. Vendoring pins it so upstream changes can't
break us, keeps our patch with the code, and gives a single-clone setup. We re-sync
deliberately (diff upstream against this dir), never by surprise.

## Our patches
- `models.py` → `OllamaProvider.__init__`: builds an authed `ollama.Client` from
  `OLLAMA_HOST` / `OLLAMA_API_KEY` (Ollama Cloud). Falls back to the local module
  client when neither is set. Marked with a `ponytail:` comment.
- `score.py` → `__main__`: added a `--json` flag that prints the `EvaluationData` as a
  sentinel-wrapped block (`===EVAL_JSON=== … ===END_EVAL_JSON===`) after the normal
  run, so `backend/app/services/hiring_agent.py` parses it instead of scraping stdout.
- `score.py` → `main`: the résumé and per-résumé GitHub caches are keyed on a sha256 of
  the PDF bytes instead of the PDF basename. We always pass `resume.pdf`, so the basename
  key made every run score one stale cached résumé. The URL-keyed GitHub API cache
  (`github.py`) is unchanged and never expires; clear `cache/` to refresh GitHub data.

## Setup (isolated venv — old deps: ollama 0.5.1, pydantic 2.11.7)
```
uv venv vendor/hiring-agent/.venv --python 3.11
uv pip install --python vendor/hiring-agent/.venv -r vendor/hiring-agent/requirements.txt
```

## Run (as a subprocess, from this dir)
```
LLM_PROVIDER=ollama DEFAULT_MODEL=gemma4:31b-cloud \
OLLAMA_HOST=https://ollama.com OLLAMA_API_KEY=... GITHUB_TOKEN=... \
.venv/bin/python score.py /path/to/resume.pdf
```

- Runtime artifacts (`cache/`, `resume_evaluations.csv`, `*.log`, `.venv/`) are gitignored.
- Behavior + score-driver findings: `../../docs/findings/T1-hiring-agent.md`
