"""Quality gate: run the vendored hiring-agent on the final PDF as a subprocess
in its own venv (isolates its old pins). It's a GATE + advice source, run ONCE —
never looped: T1 found ~90% of its score is GitHub/experience-driven and
unreachable by résumé edits (findings/T1-hiring-agent.md)."""

import json
import os
import re
import subprocess
from pathlib import Path

from app.core import config
from app.schemas.pipeline import HiringAgentReport


def _parse_eval(stdout: str) -> HiringAgentReport:
    """Extract the sentinel-wrapped EvaluationData JSON (from score.py --json) and
    reduce it to overall + capped category scores + advice."""
    m = re.search(r"===EVAL_JSON===\s*(.*?)\s*===END_EVAL_JSON===", stdout, re.S)
    if not m:
        raise RuntimeError("hiring-agent produced no evaluation JSON")
    data = json.loads(m.group(1))
    if not data:
        raise RuntimeError("hiring-agent returned an empty evaluation")
    cats = {name: min(c["score"], c["max"]) for name, c in data["scores"].items()}
    overall = sum(cats.values()) + data["bonus_points"]["total"] - data["deductions"]["total"]
    return HiringAgentReport(
        overall=max(0.0, min(120.0, overall)),
        categories=cats,
        advice=data.get("areas_for_improvement", []),
    )


def score_resume(pdf_path: Path, *, timeout: int = 600) -> HiringAgentReport:
    venv_py = config.HIRING_AGENT_DIR / ".venv" / "bin" / "python"
    env = {
        **os.environ,
        "LLM_PROVIDER": "ollama",
        "DEFAULT_MODEL": config.OLLAMA_MODEL,
        "OLLAMA_HOST": config.OLLAMA_HOST,
        "OLLAMA_API_KEY": config.OLLAMA_API_KEY or "",
    }
    if config.GITHUB_TOKEN:
        env["GITHUB_TOKEN"] = config.GITHUB_TOKEN
    proc = subprocess.run(
        [str(venv_py), "score.py", str(Path(pdf_path).resolve()), "--json"],
        cwd=config.HIRING_AGENT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    try:
        return _parse_eval(proc.stdout)
    except Exception as e:
        raise RuntimeError(
            f"hiring-agent failed (exit {proc.returncode}): {e}\nstderr: {proc.stderr[-500:]}"
        )
