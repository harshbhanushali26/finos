"""
FinOS — app-wide constants.
All paths, model names, limits, and defaults live here.
Nothing else should be hardcoded anywhere in the project.
"""

from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "finos.db"

# Ensure data directory exists at import time
DATA_DIR.mkdir(exist_ok=True)

# ── LLM ────────────────────────────────────────────────────────────────────
MODEL_NAME       = "openai/gpt-oss-120b"
MAX_TOKENS       = 1024
GROQ_TEMPERATURE = 0.2   # low — finance responses should be deterministic

# ── Agent ──────────────────────────────────────────────────────────────────
MAX_HISTORY_MESSAGES = 20   # auto-clear conversation after this many turns
MODEL                = "openai/gpt-oss-120b"  # alias — agent/core.py imports MODEL
MAX_TOOL_CALLS       = 5
DEBUG                = False
TOOL_RESULTS_TO_KEEP    = 4
TOOL_RESULT_TRIM_LENGTH = 60

# ── Auth ───────────────────────────────────────────────────────────────────
TOKEN_EXPIRE_DAYS = 7

# ── Defaults ───────────────────────────────────────────────────────────────
DEFAULT_CURRENCY = "INR"

# ── Default categories seeded for every new user ───────────────────────────
DEFAULT_INCOME_CATEGORIES = [
    "Salary", "Freelance", "Bonus", "Interest", "Other"
]

DEFAULT_EXPENSE_CATEGORIES = [
    "Food", "Rent", "Utilities", "Transport", "Entertainment",
    "Health", "Shopping", "Other"
]


