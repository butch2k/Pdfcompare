"""
Centralised configuration loaded from environment variables / .env file.

All settings have sensible defaults so the app runs out of the box.
LLM_* variables act as server-side defaults that the frontend UI can
override on a per-session basis.
"""

import os
from dotenv import load_dotenv

# Load .env file (if present) into os.environ before reading any values
load_dotenv()


# ── Flask / App ──────────────────────────────────────────────────────────────

PORT = int(os.getenv("FLASK_PORT", "5000"))            # HTTP listen port
DEBUG = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))   # Per-file upload cap

# ── LLM defaults ────────────────────────────────────────────────────────────
# These act as server-side defaults.  The frontend UI fields override them
# when the user fills them in.

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "")    # "ollama", "openai", or "gemini"
LLM_MODEL = os.getenv("LLM_MODEL", "")          # e.g. "llama3", "gpt-4o"
LLM_API_KEY = os.getenv("LLM_API_KEY", "")       # Required for openai / gemini
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "")     # Custom endpoint URL override
