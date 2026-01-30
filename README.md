# PDFCompare

A web application for comparing two PDF documents side by side, highlighting differences, and generating detailed reports on what changed and how it affects the document's meaning.

## Features

- **Drag-and-drop upload** — drop two PDFs onto the browser to compare them
- **Side-by-side diff view** — color-coded line-by-line comparison (green = added, red = removed, yellow = modified)
- **Unified diff view** — standard patch-style output
- **Built-in report** — deterministic Markdown report with statistics, severity rating, and consequence analysis
- **AI-powered report** (optional) — send the diff to an LLM for deeper semantic analysis of changes
- **Export** — download the diff as a `.patch` file and either report as `.md`

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
```

## Running the app

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

For production use with gunicorn:

```bash
gunicorn app:app --bind 0.0.0.0:5000
```

## Usage

1. **Upload PDFs** — drag and drop (or click to browse) a PDF into each drop zone. The left zone is the original document, the right zone is the modified version.
2. **Click Compare** — the app extracts text from both PDFs, computes the diff, and displays results.
3. **Browse results** using the tabs:
   - **Side-by-Side** — two-column highlighted diff with line numbers
   - **Unified Diff** — standard unified diff format
   - **Report** — auto-generated Markdown analysis with statistics, categorized changes, and consequences
   - **AI Report** — LLM-generated analysis (only available when a provider is configured)
4. **Export** — use the buttons above the results to download:
   - `diff.patch` — unified diff file
   - `comparison-report.md` — the built-in report
   - `ai-comparison-report.md` — the LLM report (when available)

## LLM Configuration

The AI report feature is optional. To enable it, expand the **LLM Configuration** panel before running a comparison and select a provider.

### Ollama (local)

Run models locally with [Ollama](https://ollama.com). No API key needed.

| Field    | Value                              |
|----------|------------------------------------|
| Provider | Ollama (local)                     |
| Model    | Any installed model, e.g. `llama3` |
| API Key  | Leave empty                        |
| Endpoint | `http://localhost:11434` (default) |

Make sure Ollama is running (`ollama serve`) and the model is pulled (`ollama pull llama3`).

### OpenAI (ChatGPT)

Uses the [OpenAI API](https://platform.openai.com).

| Field    | Value                                           |
|----------|-------------------------------------------------|
| Provider | OpenAI (ChatGPT)                                |
| Model    | `gpt-4o`, `gpt-4o-mini`, `gpt-3.5-turbo`, etc. |
| API Key  | Your key from platform.openai.com               |
| Endpoint | Leave empty for default                         |

### Google Gemini

Uses the [Gemini API](https://aistudio.google.com).

| Field    | Value                                       |
|----------|---------------------------------------------|
| Provider | Google Gemini                               |
| Model    | `gemini-2.0-flash`, `gemini-1.5-pro`, etc.  |
| API Key  | Your key from aistudio.google.com           |
| Endpoint | Leave empty for default                     |

### Custom / self-hosted endpoints

Use the **Endpoint** field to point at any compatible API server. This works for:

- Remote Ollama instances (e.g. `http://my-server:11434`)
- OpenAI-compatible proxies (e.g. LiteLLM, LocalAI, vLLM with OpenAI-compatible mode)
- Corporate API gateways

## Project structure

```
Pdfcompare/
├── app.py              # Flask backend: PDF extraction, diff, API routes
├── llm.py              # LLM provider abstraction (Ollama, OpenAI, Gemini)
├── requirements.txt    # Python dependencies
└── static/
    └── index.html      # Single-page frontend (HTML + CSS + JS)
```

## How it works

1. **Text extraction** — `pdfplumber` reads each PDF page and extracts text line by line.
2. **Diff computation** — Python's `difflib.SequenceMatcher` compares the two line arrays and produces tagged blocks (equal, insert, delete, replace).
3. **Built-in report** — a deterministic template function walks the diff blocks and generates Markdown with statistics, severity assessment, and consequence analysis.
4. **AI report** — the unified diff and statistics are sent to the selected LLM provider with a system prompt that instructs the model to produce a detailed semantic analysis of the changes.
