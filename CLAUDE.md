# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PDFCompare is a web application for comparing two PDF documents side-by-side. Flask backend (Python) with a single-page vanilla JS frontend. Optional LLM integration for semantic analysis reports.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server (port 5000)
python app.py

# Run production server
gunicorn app:app --bind 0.0.0.0:5000 --workers 4 --timeout 300

# Docker
docker build -t pdfcompare .
docker run -p 5000:5000 --env-file .env pdfcompare
```

No test suite exists. Testing is manual via browser at http://localhost:5000.

## Architecture

**Backend (Python/Flask):**
- `app.py` — All API routes and core processing logic. PDF extraction via pdfplumber, line-level diff via `difflib.SequenceMatcher`, word-level sub-diffs for replace blocks, report generation.
- `llm.py` — LLM provider abstraction (Ollama, LM Studio, OpenAI, Gemini) with SSRF protection and prompt truncation.
- `config.py` — Loads environment variables with defaults (port, debug, max upload size, LLM settings).

**Frontend:**
- `static/index.html` — Entire UI in one file (HTML + CSS + JS). Drag-drop upload, tabbed results (side-by-side diff, unified diff, PDF preview via pdf.js, metadata, reports), localStorage history (last 20 comparisons), ARIA accessibility.

**API endpoints:**
- `GET /` — Serves the frontend
- `GET /api/config` — Returns LLM server defaults (never exposes API keys)
- `POST /api/compare` — Main comparison: accepts two PDFs + ignore rule options, returns JSON with diffs, stats, report
- `POST /api/llm-report` — Generates AI analysis report via configured LLM provider

**Processing pipeline in `/api/compare`:**
1. Extract text lines + page markers + metadata from each PDF (single pdfplumber pass)
2. Apply ignore rules (whitespace, case, regex patterns, header/footer removal)
3. Line-level diff with page index mapping (O(1) page lookup via `_build_page_index()`)
4. Word-level diffs within replace blocks
5. Metadata comparison, unified diff generation, deterministic Markdown report

## Key Design Decisions

- Page boundaries tracked via sentinel strings (`PAGE_MARKER_PREFIX`) inserted into text arrays, enabling page-aware diff output
- Word diffs are nested SequenceMatcher calls on individual replace-block line pairs, producing `[text, type]` span arrays for frontend highlighting
- Frontend uses DOM-based `esc()` function for XSS prevention rather than a template engine
- ReDoS mitigation: regex patterns from users are rejected if >500 characters
- LLM endpoint validation blocks metadata service addresses (SSRF protection)
- Docker runs as non-root `appuser`

## Configuration

Environment variables (see `.env.example`): `FLASK_PORT`, `FLASK_DEBUG`, `MAX_UPLOAD_MB`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_ENDPOINT`. The frontend can override LLM settings per-session.

## Tool Usage

Always use Context7 MCP when needing library/API documentation, code generation, setup or configuration steps without the user having to explicitly ask.
