"""Centralised configuration loaded from environment / .env file."""

import os
from dotenv import load_dotenv

load_dotenv()


# ── Flask / App ──────────────────────────────────────────────────────────────

PORT = int(os.getenv("FLASK_PORT", "5000"))
DEBUG = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))

# ── LLM defaults ────────────────────────────────────────────────────────────
# These act as server-side defaults.  The frontend UI fields override them
# when the user fills them in.

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "")
