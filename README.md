# PDFCompare

A web application for comparing two PDF documents side by side, highlighting differences, and generating detailed reports on what changed and how it affects the document's meaning.

## Features

- **Drag-and-drop upload** — drop two PDFs onto the browser to compare them
- **Side-by-side diff view** — color-coded line-by-line comparison (green = added, red = removed, yellow = modified)
- **Word-level highlighting** — individual changed words are highlighted within modified lines for finer granularity
- **Page-aware diff** — diff blocks are annotated with source page numbers; page-break separators appear in the side-by-side view
- **Unified diff view** — standard patch-style output
- **PDF preview** — client-side rendering of both PDFs with page-by-page navigation (via pdf.js)
- **Metadata diff** — side-by-side comparison of PDF metadata fields (title, author, dates, page count, etc.)
- **Built-in report** — deterministic Markdown report with statistics, severity rating, and consequence analysis
- **AI-powered report** (optional) — send the diff to an LLM for deeper semantic analysis of changes
- **Configurable ignore rules** — ignore whitespace, case, headers/footers, or lines matching a custom regex
- **Comparison history** — recent comparisons are persisted in localStorage for quick access
- **Export** — download the diff as a `.patch` file and either report as `.md`
- **Accessible UI** — ARIA tabs with keyboard navigation, focus indicators, screen-reader labels, colorblind-friendly text markers

## Requirements

- Python 3.10+
- pip

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd Pdfcompare

# Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate   # Linux/macOS
# venv\Scripts\activate    # Windows

# Install dependencies
pip install -r requirements.txt

# Create your .env file from the example
cp .env.example .env
# Edit .env to set your configuration
```

## Configuration (.env)

Copy `.env.example` to `.env` and edit it. All settings are optional — the app works with defaults out of the box.

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASK_PORT` | `5000` | Port the app listens on |
| `FLASK_DEBUG` | `false` | Enable Flask debug mode |
| `MAX_UPLOAD_MB` | `50` | Maximum upload size per file in megabytes |
| `LLM_PROVIDER` | *(empty)* | Default LLM provider: `ollama`, `openai`, or `gemini` |
| `LLM_MODEL` | *(empty)* | Default model name (e.g. `llama3`, `gpt-4o`, `gemini-2.0-flash`) |
| `LLM_API_KEY` | *(empty)* | API key for OpenAI or Gemini (not needed for Ollama) |
| `LLM_ENDPOINT` | *(empty)* | Custom endpoint URL override |

When `LLM_*` variables are set, they act as server-side defaults. The frontend UI fields override them — users can still change provider/model/key per session without modifying the `.env`.

## Running the app

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

For production use with gunicorn:

```bash
gunicorn app:app --bind 0.0.0.0:5000 --workers 4 --timeout 300
```

## Docker

Build and run with Docker:

```bash
# Build the image
docker build -t pdfcompare .

# Run with default settings
docker run -p 5000:5000 pdfcompare

# Run with environment variables
docker run -p 5000:5000 \
  -e LLM_PROVIDER=openai \
  -e LLM_MODEL=gpt-4o \
  -e LLM_API_KEY=sk-... \
  pdfcompare

# Or mount a .env file
docker run -p 5000:5000 --env-file .env pdfcompare
```

The Docker image runs as a non-root user (`appuser`) for security.

### Docker Compose

```yaml
services:
  pdfcompare:
    build: .
    ports:
      - "5000:5000"
    env_file:
      - .env
```

```bash
docker compose up
```

## Usage

1. **Upload PDFs** — drag and drop (or click to browse) a PDF into each drop zone. The left zone is the original document, the right zone is the modified version.
2. **Configure ignore rules** (optional) — expand the *Ignore Rules* panel to skip whitespace differences, case changes, headers/footers, or lines matching a regex pattern.
3. **Click Compare** — the app extracts text from both PDFs, computes the diff, and displays results.
4. **Browse results** using the tabs:
   - **Side-by-Side** — two-column highlighted diff with line numbers, word-level highlights, and page-break markers
   - **Unified Diff** — standard unified diff format
   - **PDF Preview** — rendered pages of both PDFs with previous/next navigation
   - **Metadata** — table comparing PDF metadata fields, changed rows highlighted
   - **Report** — auto-generated Markdown analysis with statistics, categorized changes, and consequences
   - **AI Report** — LLM-generated analysis (only available when a provider is configured)
5. **Export** — use the buttons above the results to download:
   - `diff.patch` — unified diff file
   - `comparison-report.md` — the built-in report
   - `ai-comparison-report.md` — the LLM report (when available)
6. **History** — previous comparisons are saved automatically and listed below the results. Click an entry to reload it, or click × to remove it.

## LLM Configuration

The AI report feature is optional. Configure it via `.env` (server-side defaults) or via the **LLM Configuration** panel in the UI (per-session overrides).

### Ollama (local)

Run models locally with [Ollama](https://ollama.com). No API key needed.

```env
LLM_PROVIDER=ollama
LLM_MODEL=llama3
LLM_ENDPOINT=http://localhost:11434
```

Make sure Ollama is running (`ollama serve`) and the model is pulled (`ollama pull llama3`).

### OpenAI (ChatGPT)

Uses the [OpenAI API](https://platform.openai.com).

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_API_KEY=sk-...
```

### Google Gemini

Uses the [Gemini API](https://aistudio.google.com).

```env
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.0-flash
LLM_API_KEY=AI...
```

### Custom / self-hosted endpoints

Use `LLM_ENDPOINT` to point at any compatible API server:

- Remote Ollama instances (e.g. `http://my-server:11434`)
- OpenAI-compatible proxies (e.g. LiteLLM, LocalAI, vLLM with OpenAI-compatible mode)
- Corporate API gateways

## Project structure

```
Pdfcompare/
├── app.py              # Flask backend: PDF extraction, diff engine, report
│                       #   generation, and all API routes
├── config.py           # Centralised .env configuration with defaults
├── llm.py              # LLM provider abstraction (Ollama, OpenAI, Gemini)
│                       #   with SSRF protection on endpoint URLs
├── requirements.txt    # Python dependencies (flask, pdfplumber, etc.)
├── .env.example        # Example environment config template
├── Dockerfile          # Container build (non-root user, gunicorn)
├── .dockerignore       # Docker build exclusions
└── static/
    └── index.html      # Single-page frontend (HTML + CSS + JS)
                        #   Includes pdf.js for client-side PDF rendering,
                        #   ARIA-accessible tabs, drag-and-drop uploads,
                        #   localStorage history, and all diff views
```

## How it works

1. **Text extraction** — `pdfplumber` reads each PDF page and extracts text line by line. Page-boundary sentinels are inserted so diffs can be mapped back to source pages.
2. **Ignore rules** — optional filters (whitespace, case, headers/footers, regex) are applied to the extracted lines before diffing.
3. **Diff computation** — Python's `difflib.SequenceMatcher` (with `autojunk=False` for accuracy on large documents) compares the two line arrays and produces tagged blocks (equal, insert, delete, replace). Replace blocks additionally get word-level diffs for finer highlighting.
4. **Page index** — a pre-computed array maps every line to its page number in O(1), used to annotate diff blocks with page citations.
5. **Metadata extraction** — PDF metadata fields (title, author, dates, etc.) are extracted in the same `pdfplumber.open()` call as text, avoiding a redundant parse.
6. **Built-in report** — a deterministic template function walks the diff blocks and generates Markdown with statistics, severity assessment (Low/Medium/High by change percentage), categorised changes with page citations, and consequence analysis.
7. **AI report** — the unified diff and statistics are sent to the selected LLM provider with a system prompt that instructs the model to produce a detailed semantic analysis of the changes. The prompt is truncated at ~80K characters to fit typical context windows.
8. **PDF preview** — pdf.js renders both PDFs client-side on `<canvas>` elements with page-by-page navigation, independent of the text-based diff.
9. **History** — comparison results (minus word-level diffs to save space) are stored in `localStorage`, capped at 20 entries.

## Security notes

- **SSRF protection** — user-supplied LLM endpoint URLs are validated against a blocklist of cloud metadata addresses and restricted schemes.
- **ReDoS mitigation** — user-supplied regex patterns are rejected if longer than 500 characters.
- **XSS prevention** — all user-supplied text is HTML-escaped via a DOM-based `esc()` function before rendering.
- **No secrets in responses** — the `/api/config` endpoint exposes only a boolean `has_api_key`, never the key itself.
- **Non-root Docker** — the container runs as an unprivileged `appuser`.
- **Generic error messages** — server-side exceptions are logged with full tracebacks but only generic messages are returned to the client.
