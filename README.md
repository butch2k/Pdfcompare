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
- **AI-powered report** (optional) — send the diff to an LLM for deeper semantic analysis of changes, with 27 expert domain specialisations
- **AI report PDF export** — export the AI report as a paginated PDF with page numbering and proper formatting
- **Configurable ignore rules** — ignore whitespace, case, headers/footers, or lines matching a custom regex
- **Comparison history** — recent comparisons are persisted in localStorage for quick access, including AI reports, metadata, and unified diffs
- **Rerun AI report** — regenerate the AI report from any history entry without re-uploading files
- **Export** — download the diff as a `.patch` file, either report as `.md`, or the AI report as PDF
- **Accessible UI** — ARIA tabs with keyboard navigation, focus indicators, screen-reader labels, skip links, colorblind-friendly text markers
- **Content Security Policy** — CSP headers protect against XSS attacks
- **Encrypted API key storage** — API keys are encrypted in localStorage using session-based XOR encryption

## Requirements

- Python 3.10 or newer
- pip (comes with Python)
- A web browser (Chrome, Firefox, Edge, Safari)
- (Optional) An LLM provider for AI reports — see [LLM Configuration](#llm-configuration)

## Installation — step by step

These instructions assume you have never used Python before. If you already know Python, skip to the [Quick start](#quick-start) section.

### 1. Install Python

**Windows:**
1. Go to [python.org/downloads](https://www.python.org/downloads/) and download Python 3.10 or newer
2. Run the installer
3. **Important:** check the box that says **"Add Python to PATH"** before clicking Install
4. Click "Install Now"
5. When it finishes, open a Command Prompt (press `Win+R`, type `cmd`, press Enter)
6. Type `python --version` and press Enter — you should see something like `Python 3.12.x`

**macOS:**
1. Open Terminal (press `Cmd+Space`, type "Terminal", press Enter)
2. Install Homebrew if you don't have it: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
3. Run: `brew install python`
4. Verify: `python3 --version`

**Linux (Debian/Ubuntu):**
1. Open a terminal
2. Run: `sudo apt update && sudo apt install python3 python3-pip python3-venv`
3. Verify: `python3 --version`

### 2. Download PDFCompare

```bash
git clone <repo-url>
cd Pdfcompare
```

Or download the ZIP from the repository page and extract it.

### 3. Create a virtual environment

A virtual environment keeps PDFCompare's dependencies separate from other Python projects. Think of it as a private folder where PDFCompare stores the libraries it needs.

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

You'll know it worked when you see `(venv)` at the start of your command line.

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

This downloads and installs everything PDFCompare needs (Flask, pdfplumber, etc.). It may take a minute.

### 5. (Optional) Configure environment variables

```bash
# Copy the example config
cp .env.example .env       # macOS/Linux
copy .env.example .env     # Windows
```

Edit `.env` in any text editor to set your preferences. Everything works out of the box without changes — this step is only needed if you want to pre-configure an LLM provider or change the port.

### 6. Start the app

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser. That's it!

### Quick start

For experienced developers:

```bash
git clone <repo-url> && cd Pdfcompare
python -m venv venv && source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env  # optional
python app.py
```

## Configuration (.env)

Copy `.env.example` to `.env` and edit it. All settings are optional — the app works with defaults out of the box.

| Variable | Default | Description |
|----------|---------|-------------|
| `FLASK_PORT` | `5000` | Port the app listens on |
| `FLASK_DEBUG` | `false` | Enable Flask debug mode |
| `MAX_UPLOAD_MB` | `50` | Maximum upload size per file in megabytes |
| `LLM_PROVIDER` | *(empty)* | Default LLM provider (see [supported providers](#supported-providers)) |
| `LLM_MODEL` | *(empty)* | Default model name (e.g. `llama3`, `gpt-4o`, `gemini-2.0-flash`) |
| `LLM_API_KEY` | *(empty)* | API key for cloud providers (not needed for local providers) |
| `LLM_ENDPOINT` | *(empty)* | Custom endpoint URL override |

When `LLM_*` variables are set, they act as server-side defaults. The frontend UI fields override them — users can still change provider/model/key per session without modifying the `.env`.

## Running the app

**Development:**
```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

**Production (gunicorn):**
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
3. **Select an expert domain** (optional) — choose a domain specialisation from the dropdown to get more targeted AI analysis. "Auto-detect" works well for most documents.
4. **Click Compare** — the app extracts text from both PDFs, computes the diff, and displays results.
5. **Browse results** using the tabs:
   - **Side-by-Side** — two-column highlighted diff with line numbers, word-level highlights, and page-break markers
   - **Unified Diff** — standard unified diff format
   - **PDF Preview** — rendered pages of both PDFs with previous/next navigation
   - **Metadata** — table comparing PDF metadata fields, changed rows highlighted
   - **Report** — auto-generated Markdown analysis with statistics, categorized changes, and consequences
   - **AI Report** — LLM-generated analysis (only available when a provider is configured)
6. **Export** — use the buttons above the results to download:
   - `diff.patch` — unified diff file
   - `comparison-report.md` — the built-in report
   - `ai-comparison-report.md` — the LLM report as Markdown
   - `ai-comparison-report.pdf` — the LLM report as a formatted PDF with page numbering
7. **History** — previous comparisons are saved automatically and listed below the results. Click an entry to reload it (including AI report and metadata), or click × to remove it. You can also rerun the AI report from any history entry.

## LLM Configuration

The AI report feature is optional. Configure it via `.env` (server-side defaults) or via the **LLM Configuration** panel in the UI (per-session overrides).

### Supported providers

| Provider | Value | API Key Required | Notes |
|----------|-------|-----------------|-------|
| Ollama | `ollama` | No | Local. Run `ollama serve` first |
| LM Studio | `lmstudio` | No | Local. Start LM Studio server first |
| Anthropic (Claude) | `anthropic` | Yes | [console.anthropic.com](https://console.anthropic.com) |
| DeepSeek | `deepseek` | Yes | [platform.deepseek.com](https://platform.deepseek.com) |
| Google Gemini | `gemini` | Yes | [aistudio.google.com](https://aistudio.google.com) |
| Groq | `groq` | Yes | [console.groq.com](https://console.groq.com) |
| Kimi (Moonshot) | `kimi` | Yes | [platform.moonshot.cn](https://platform.moonshot.cn) |
| Mistral AI | `mistral` | Yes | [console.mistral.ai](https://console.mistral.ai) |
| OpenAI (ChatGPT) | `openai` | Yes | [platform.openai.com](https://platform.openai.com) |
| Perplexity | `perplexity` | Yes | [perplexity.ai](https://www.perplexity.ai) |

### Example configurations

**Ollama (local, no API key):**
```env
LLM_PROVIDER=ollama
LLM_MODEL=llama3
LLM_ENDPOINT=http://localhost:11434
```
Make sure Ollama is running (`ollama serve`) and the model is pulled (`ollama pull llama3`).

**OpenAI:**
```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_API_KEY=sk-...
```

**Google Gemini:**
```env
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.0-flash
LLM_API_KEY=AI...
```

**Anthropic (Claude):**
```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514
LLM_API_KEY=sk-ant-...
```

### Custom / self-hosted endpoints

Use `LLM_ENDPOINT` to point at any compatible API server:

- Remote Ollama instances (e.g. `http://my-server:11434`)
- OpenAI-compatible proxies (e.g. LiteLLM, LocalAI, vLLM with OpenAI-compatible mode)
- Corporate API gateways

### Expert domains

When configuring a comparison, you can select an expert domain to tailor the AI analysis. Available domains include: Agriculture, Architecture, Aviation, Banking, Construction, Contract Law, Cybersecurity, Education, Energy, Environmental Science, Finance & Accounting, Government, Healthcare, Human Resources, Insurance, Intellectual Property, Legal & Regulatory, Logistics, Manufacturing, Marketing, Mining, Pharmaceuticals, Procurement, Real Estate, Software Engineering, Tax Law, Telecommunications, Transportation — or "Auto-detect" to let the AI determine the domain.

## Project structure

```
Pdfcompare/
├── app.py              # Flask backend: PDF extraction, diff engine, report
│                       #   generation, API routes, CSP headers, metadata sanitisation
├── config.py           # Centralised .env configuration with defaults
├── llm.py              # LLM provider abstraction (10 providers)
│                       #   with SSRF protection on endpoint URLs
├── requirements.txt    # Python dependencies (flask, pdfplumber, etc.)
├── .env.example        # Example environment config template
├── Dockerfile          # Container build (non-root user, gunicorn)
├── .dockerignore       # Docker build exclusions
└── static/
    └── index.html      # Single-page frontend (HTML + CSS + JS)
                        #   Includes pdf.js for client-side PDF rendering,
                        #   html2pdf.js for AI report PDF export,
                        #   ARIA-accessible tabs, drag-and-drop uploads,
                        #   localStorage history, and all diff views
```

## How it works

1. **Text extraction** — `pdfplumber` reads each PDF page and extracts text line by line. Page-boundary sentinels are inserted so diffs can be mapped back to source pages.
2. **Ignore rules** — optional filters (whitespace, case, headers/footers, regex) are applied to the extracted lines before diffing.
3. **Diff computation** — Python's `difflib.SequenceMatcher` (with `autojunk=False` for accuracy on large documents) compares the two line arrays and produces tagged blocks (equal, insert, delete, replace). Replace blocks additionally get word-level diffs for finer highlighting.
4. **Page index** — a pre-computed array maps every line to its page number in O(1), used to annotate diff blocks with page citations.
5. **Metadata extraction** — PDF metadata fields (title, author, dates, etc.) are extracted and sanitised in the same `pdfplumber.open()` call as text, avoiding a redundant parse.
6. **Built-in report** — a deterministic template function walks the diff blocks and generates Markdown with statistics, severity assessment (Low/Medium/High by change percentage), categorised changes with page citations, and consequence analysis.
7. **AI report** — the unified diff and statistics are sent to the selected LLM provider with a system prompt that instructs the model to produce a detailed semantic analysis of the changes. The prompt is truncated at ~80K characters to fit typical context windows. An expert domain can be selected to focus the analysis.
8. **PDF export** — the AI report is rendered from Markdown to HTML, post-processed for proper page breaks (text-block wrapping, list protection), and converted to a paginated PDF using html2pdf.js with page numbering.
9. **PDF preview** — pdf.js renders both PDFs client-side on `<canvas>` elements with page-by-page navigation, independent of the text-based diff.
10. **History** — comparison results (including AI reports, metadata, and unified diffs) are stored in `localStorage`, capped at 20 entries. API keys are encrypted using session-based XOR encryption.

## Security notes

- **Content Security Policy** — CSP headers restrict script and resource origins to prevent XSS attacks.
- **SSRF protection** — user-supplied LLM endpoint URLs are validated against a blocklist of cloud metadata addresses and restricted schemes.
- **PDF metadata sanitisation** — metadata values are stripped of HTML tags and null bytes server-side before reaching the frontend.
- **ReDoS mitigation** — user-supplied regex patterns are rejected if longer than 500 characters and executed with a timeout.
- **XSS prevention** — all user-supplied text is HTML-escaped via a DOM-based `esc()` function before rendering.
- **Encrypted API key storage** — API keys stored in localStorage are encrypted with a session-based XOR key (stored in sessionStorage, lost on tab close).
- **No secrets in responses** — the `/api/config` endpoint exposes only a boolean `has_api_key`, never the key itself.
- **Non-root Docker** — the container runs as an unprivileged `appuser`.
- **CSRF protection** — Origin and Referer headers are validated on API requests.
- **Generic error messages** — server-side exceptions are logged with full tracebacks but only generic messages are returned to the client.
