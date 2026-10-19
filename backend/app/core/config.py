import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env (if present) so a locally-stored OLLAMA_API_KEY and friends
# are picked up without exporting them by hand. Real environment variables win
# (override defaults to False), so a deploy's injected env still takes precedence.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# Persistence (T11). Structure in SQLite; résumé bytes on disk under DATA_DIR.
# ponytail: SQLite is single-writer — flip DATABASE_URL to Postgres at scale
# (SQLAlchemy makes it a URL change, not a rewrite).
DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).resolve().parents[2] / "data")))
DB_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}")

# Repo root + the local "Save locally" folder: the tailored PDF is copied here for
# local application tracking (LOCAL-DEV ONLY — writes on whatever runs the backend).
# Env-overridable so tests point it at a tmp dir.
REPO_ROOT = Path(__file__).resolve().parents[3]
TAILORED_RESUME_DIR = Path(os.environ.get("TAILORED_RESUME_DIR", str(REPO_ROOT / "tailored-resume")))

def _ensure_latex_on_path() -> None:
    """TinyTeX lives outside the default PATH. latexmk looks up pdflatex by name,
    so the bin directory has to be on PATH, not only LATEXMK_BIN."""
    if shutil.which("latexmk") and shutil.which("pdflatex"):
        return
    bin_dir = Path.home() / "Library" / "TinyTeX" / "bin" / "universal-darwin"
    if (bin_dir / "latexmk").is_file() and (bin_dir / "pdflatex").is_file():
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


_ensure_latex_on_path()

# LaTeX toolchain; override via env for Docker/deploy where it lives elsewhere.
LATEXMK_BIN = os.environ.get("LATEXMK_BIN", "latexmk")
LATEX_ENGINE = os.environ.get("LATEX_ENGINE", "pdflatex")  # -lualatex/-xelatex for fontspec

# Ollama Cloud (shared LLM client). OLLAMA_API_KEY is required for any LLM call.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "https://ollama.com")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:31b-cloud")  # everything not routed below
# Per-task models. Writer is gpt-oss: with improver's length budget it matched gemma
# (92% one-page success each over 24 rewrites, same score; the shipped path measured 42/48);
# without the budget it failed 42%. Judge stays gemma: as the old 0-100 judge it repeated within
# ~3 points while gpt-oss/nemotron swung 13-16; as the T34 requirement judge its verdicts were
# identical over 3 runs on the same text (flips across rewrites are handled by ats.reconcile).
OLLAMA_WRITER_MODEL = os.environ.get("OLLAMA_WRITER_MODEL", "gpt-oss:120b")  # improver
OLLAMA_JUDGE_MODEL = os.environ.get("OLLAMA_JUDGE_MODEL", OLLAMA_MODEL)  # ATS requirement judge (T34)
OLLAMA_EXTRACT_MODEL = os.environ.get("OLLAMA_EXTRACT_MODEL", OLLAMA_MODEL)  # JD keywords + requirements (T34)
OLLAMA_ANSWER_MODEL = os.environ.get("OLLAMA_ANSWER_MODEL", OLLAMA_MODEL)  # screening answers

# ATS blend: weight on grounded keyword coverage vs the requirement judge (T34).
ATS_COVERAGE_WEIGHT = float(os.environ.get("ATS_COVERAGE_WEIGHT", "0.6"))

# Selector: best score below this (0-100) → pick closest but warn "none close".
CLOSE_THRESHOLD = int(os.environ.get("CLOSE_THRESHOLD", "40"))

# Improver: retries when an edit fails to compile / exceeds one page.
IMPROVER_COMPILE_RETRIES = int(os.environ.get("IMPROVER_COMPILE_RETRIES", "2"))

# Orchestrator loops + quality gate (design §9).
INNER_LOOP_MAX = int(os.environ.get("INNER_LOOP_MAX", "3"))  # improver ↔ ATS, the only optimization loop
OUTER_LOOP_MAX = int(os.environ.get("OUTER_LOOP_MAX", "5"))  # user-feedback rounds
TARGET_ATS = int(os.environ.get("TARGET_ATS", "95"))  # inner loop stops early at/above this
HIRING_AGENT_GATE = float(os.environ.get("HIRING_AGENT_GATE", "80"))  # gate + advice, never looped
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # hiring-agent GitHub enrichment (60→5000 req/hr)
HIRING_AGENT_DIR = Path(
    os.environ.get("HIRING_AGENT_DIR", str(Path(__file__).resolve().parents[3] / "vendor" / "hiring-agent"))
)

# JD-from-URL fetch (T10): guards on fetching arbitrary user-supplied links.
JD_FETCH_TIMEOUT = float(os.environ.get("JD_FETCH_TIMEOUT", "10"))  # per-request seconds
# Ashby has no per-job endpoint, so resolving one posting reads its whole board.
JD_FETCH_MAX_BYTES = int(os.environ.get("JD_FETCH_MAX_BYTES", str(64 * 1024 * 1024)))  # 64MB (Ashby/bjakcareer board is 33.6MB)
JD_FETCH_MAX_REDIRECTS = int(os.environ.get("JD_FETCH_MAX_REDIRECTS", "3"))
JD_MIN_CHARS = int(os.environ.get("JD_MIN_CHARS", "200"))  # generic extraction below this → warn
