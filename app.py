"""
Flask backend for PDFCompare.

Handles PDF upload, text extraction, diff computation (line-level and
word-level), metadata extraction, deterministic report generation, and
LLM-powered report delegation.  All routes are JSON APIs consumed by the
single-page frontend in static/index.html.
"""

import io
import re
import difflib
import logging
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory
import pdfplumber

import config
from llm import generate_llm_report

# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------

app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024

logger = logging.getLogger(__name__)

# Sentinel character sequence injected between pages during text extraction.
# It is stripped before any user-facing output but allows internal functions
# to map diff blocks back to their source page numbers.
PAGE_MARKER_PREFIX = "\x00PAGE:"


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def extract_text_and_metadata(pdf_bytes: bytes) -> tuple[list[str], dict]:
    """Open a PDF once and return both its text lines and metadata dict.

    Text lines include page-boundary sentinels (PAGE_MARKER_PREFIX + page_no)
    so downstream functions can determine which page a line belongs to.
    Metadata includes standard fields (title, author, dates …) plus page count.
    """
    lines: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            # Insert a sentinel so we know where each page starts
            lines.append(f"{PAGE_MARKER_PREFIX}{page.page_number}")
            text = page.extract_text() or ""
            lines.extend(text.splitlines())

        meta = pdf.metadata or {}
        metadata = {
            "title": meta.get("Title", "") or "",
            "author": meta.get("Author", "") or "",
            "subject": meta.get("Subject", "") or "",
            "creator": meta.get("Creator", "") or "",
            "producer": meta.get("Producer", "") or "",
            "creation_date": meta.get("CreationDate", "") or "",
            "mod_date": meta.get("ModDate", "") or "",
            "page_count": len(pdf.pages),
        }
    return lines, metadata


# ---------------------------------------------------------------------------
# Page-marker helpers
# ---------------------------------------------------------------------------

def _is_page_marker(line: str) -> bool:
    """Return True if *line* is a page-boundary sentinel, not real content."""
    return line.startswith(PAGE_MARKER_PREFIX)


def _page_number_from_marker(line: str) -> int:
    """Extract the integer page number from a page-boundary sentinel."""
    return int(line[len(PAGE_MARKER_PREFIX):])


def _build_page_index(lines: list[str]) -> list[int]:
    """Pre-compute a list that maps every line index to its page number.

    This replaces a previous O(n) backward walk with an O(1) lookup per
    line, significantly improving performance for large documents.
    """
    page_index: list[int] = []
    current_page = 1
    for line in lines:
        if _is_page_marker(line):
            current_page = _page_number_from_marker(line)
        page_index.append(current_page)
    return page_index


# ---------------------------------------------------------------------------
# Ignore rules
# ---------------------------------------------------------------------------

def apply_ignore_rules(lines: list[str], ignore_options: dict) -> list[str]:
    """Filter/transform extracted lines according to user-selected rules.

    Supported options (all optional, default False / empty):
      ignore_whitespace  – collapse runs of whitespace to a single space
      ignore_case        – lowercase every line
      ignore_pattern     – drop lines matching a user-supplied regex
      ignore_headers_footers – drop lines that look like page numbers or
                               common headers/footers

    Page-marker sentinels are always preserved regardless of rules.
    """
    result: list[str] = []
    for line in lines:
        # Never filter out page-boundary sentinels
        if _is_page_marker(line):
            result.append(line)
            continue

        if ignore_options.get("ignore_whitespace"):
            line = " ".join(line.split())

        if ignore_options.get("ignore_case"):
            line = line.lower()

        if ignore_options.get("ignore_pattern"):
            try:
                pattern = ignore_options["ignore_pattern"]
                # Reject very long patterns to mitigate ReDoS risk
                if len(pattern) > 500:
                    pass
                elif re.fullmatch(pattern, line, flags=0):
                    continue
            except (re.error, TimeoutError):
                pass  # invalid regex — skip filtering for this line

        if ignore_options.get("ignore_headers_footers"):
            stripped = line.strip()
            # Bare page numbers like "12", "– 5 –", etc.
            if re.fullmatch(r'[-–—\s]*\d+[-–—\s]*', stripped):
                continue
            # "Page 3" or "Page 3 of 10"
            if re.fullmatch(r'page\s+\d+(\s+of\s+\d+)?', stripped, re.IGNORECASE):
                continue

        result.append(line)
    return result


# ---------------------------------------------------------------------------
# Diff computation
# ---------------------------------------------------------------------------

def compute_diff(lines_a: list[str], lines_b: list[str]):
    """Compare two line arrays and return (diff_blocks, stats).

    diff_blocks is a list of dicts, each describing a contiguous region:
        tag          – "equal", "insert", "delete", or "replace"
        left_start / left_end   – line range in document A
        right_start / right_end – line range in document B
        left_lines / right_lines – actual text of those lines
        left_page / right_page   – source page number (int or None)
        word_diffs   – (replace blocks only) per-line word-level spans

    stats is a dict with counts: equal, insert, delete, replace.

    Page-marker sentinels are excluded from the diff itself but used to
    determine page numbers for each block.
    """
    # Pre-compute page index for O(1) lookups
    page_index_a = _build_page_index(lines_a)
    page_index_b = _build_page_index(lines_b)

    # Build content-only lists for diffing, keeping original indices for
    # page lookup afterwards
    content_a = [(i, l) for i, l in enumerate(lines_a) if not _is_page_marker(l)]
    content_b = [(i, l) for i, l in enumerate(lines_b) if not _is_page_marker(l)]

    text_a = [l for _, l in content_a]
    text_b = [l for _, l in content_b]

    # autojunk=False avoids SequenceMatcher's heuristic that can ignore
    # frequently repeated lines, producing more accurate diffs on large docs
    matcher = difflib.SequenceMatcher(None, text_a, text_b, autojunk=False)
    opcodes = matcher.get_opcodes()

    diff_blocks: list[dict] = []
    stats = {"equal": 0, "insert": 0, "delete": 0, "replace": 0}

    for tag, i1, i2, j1, j2 in opcodes:
        left_lines_text = text_a[i1:i2]
        right_lines_text = text_b[j1:j2]

        # Word-level diffs give finer granularity inside replace blocks
        word_diffs = None
        if tag == "replace":
            word_diffs = compute_word_diffs(left_lines_text, right_lines_text)

        # Map content indices back to original line indices for page lookup
        left_page = page_index_a[content_a[i1][0]] if i1 < len(content_a) else None
        right_page = page_index_b[content_b[j1][0]] if j1 < len(content_b) else None

        block: dict = {
            "tag": tag,
            "left_start": i1,
            "left_end": i2,
            "right_start": j1,
            "right_end": j2,
            "left_lines": left_lines_text,
            "right_lines": right_lines_text,
            "left_page": left_page,
            "right_page": right_page,
        }
        if word_diffs is not None:
            block["word_diffs"] = word_diffs
        diff_blocks.append(block)

        # Accumulate statistics
        if tag == "equal":
            stats["equal"] += i2 - i1
        elif tag == "insert":
            stats["insert"] += j2 - j1
        elif tag == "delete":
            stats["delete"] += i2 - i1
        elif tag == "replace":
            stats["replace"] += max(i2 - i1, j2 - j1)

    return diff_blocks, stats


def compute_word_diffs(left_lines: list[str], right_lines: list[str]) -> list[dict]:
    """Produce word-level diff spans for each line pair in a replace block.

    Pairs lines positionally (padding with "" when one side is shorter).
    Each result dict contains:
        left_spans  – list of [text, type] where type is "equal" or "delete"
        right_spans – list of [text, type] where type is "equal" or "insert"

    These spans let the frontend highlight individual changed words rather
    than colouring the entire line.
    """
    result: list[dict] = []
    max_len = max(len(left_lines), len(right_lines))

    for i in range(max_len):
        left = left_lines[i] if i < len(left_lines) else ""
        right = right_lines[i] if i < len(right_lines) else ""

        left_words = left.split()
        right_words = right.split()
        sm = difflib.SequenceMatcher(None, left_words, right_words)

        left_spans: list[list] = []
        right_spans: list[list] = []

        for op, a1, a2, b1, b2 in sm.get_opcodes():
            if op == "equal":
                text = " ".join(left_words[a1:a2])
                left_spans.append([text, "equal"])
                right_spans.append([text, "equal"])
            elif op == "delete":
                left_spans.append([" ".join(left_words[a1:a2]), "delete"])
            elif op == "insert":
                right_spans.append([" ".join(right_words[b1:b2]), "insert"])
            elif op == "replace":
                left_spans.append([" ".join(left_words[a1:a2]), "delete"])
                right_spans.append([" ".join(right_words[b1:b2]), "insert"])

        result.append({"left_spans": left_spans, "right_spans": right_spans})
    return result


# ---------------------------------------------------------------------------
# Metadata comparison
# ---------------------------------------------------------------------------

def compare_metadata(meta_a: dict, meta_b: dict) -> list[dict]:
    """Return a list of metadata fields that differ between two documents.

    Each entry is {"field": key, "value_a": str, "value_b": str}.
    """
    diffs: list[dict] = []
    all_keys = sorted(set(list(meta_a.keys()) + list(meta_b.keys())))
    for key in all_keys:
        val_a = str(meta_a.get(key, ""))
        val_b = str(meta_b.get(key, ""))
        if val_a != val_b:
            diffs.append({"field": key, "value_a": val_a, "value_b": val_b})
    return diffs


# ---------------------------------------------------------------------------
# Unified diff generation
# ---------------------------------------------------------------------------

def generate_unified_diff(lines_a, lines_b, name_a="original.pdf", name_b="modified.pdf"):
    """Generate a standard unified-diff string, excluding page-marker sentinels."""
    clean_a = [l for l in lines_a if not _is_page_marker(l)]
    clean_b = [l for l in lines_b if not _is_page_marker(l)]
    return "\n".join(
        difflib.unified_diff(
            clean_a, clean_b,
            fromfile=name_a, tofile=name_b,
            lineterm=""
        )
    )


# ---------------------------------------------------------------------------
# Deterministic report generation
# ---------------------------------------------------------------------------

def generate_report(diff_blocks, stats, name_a, name_b):
    """Build a human-readable Markdown report from diff results.

    The report includes:
      - Summary statistics table
      - Severity assessment (Low / Medium / High) based on change percentage
      - Categorised change listings (additions, deletions, modifications)
        with page citations and text previews
      - Consequence analysis describing potential impacts
    """
    total_lines = stats["equal"] + stats["delete"] + stats["replace"]
    changed = stats["insert"] + stats["delete"] + stats["replace"]
    pct = (changed / total_lines * 100) if total_lines else 0

    lines = [
        f"# PDF Comparison Report",
        f"",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"**Document A:** {name_a}",
        f"**Document B:** {name_b}",
        f"",
        f"---",
        f"",
        f"## Summary Statistics",
        f"",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Unchanged lines | {stats['equal']} |",
        f"| Inserted lines | {stats['insert']} |",
        f"| Deleted lines | {stats['delete']} |",
        f"| Modified lines | {stats['replace']} |",
        f"| **Total changed** | **{changed}** |",
        f"| Change percentage | {pct:.1f}% |",
        f"",
        f"---",
        f"",
        f"## Impact Analysis",
        f"",
    ]

    if changed == 0:
        lines.append("The two documents are **identical** in textual content. No differences found.")
        return "\n".join(lines)

    # Severity thresholds: >30% = High, >10% = Medium, else Low
    if pct > 30:
        severity = "**High** — The documents differ substantially. This likely represents a major revision affecting the overall meaning and structure of the document."
    elif pct > 10:
        severity = "**Medium** — Notable differences exist. Specific sections have been altered which may affect interpretation of those sections."
    else:
        severity = "**Low** — Minor differences detected. The documents are largely the same with small edits."

    lines.append(f"**Overall severity:** {severity}")
    lines.append("")

    # Categorise diff blocks by change type
    additions = [b for b in diff_blocks if b["tag"] == "insert"]
    deletions = [b for b in diff_blocks if b["tag"] == "delete"]
    modifications = [b for b in diff_blocks if b["tag"] == "replace"]

    def _page_label(block, side="right"):
        """Format a ' (page N)' suffix if the block has page info."""
        pg = block.get(f"{side}_page")
        return f" (page {pg})" if pg else ""

    # --- New content ---
    if additions:
        lines.append(f"### New Content ({len(additions)} section(s) added)")
        lines.append("")
        lines.append("New content was introduced in Document B that does not appear in Document A. "
                      "This may represent additional clauses, information, or context that changes "
                      "the scope or meaning of the document.")
        lines.append("")
        for i, b in enumerate(additions[:10], 1):
            preview = " ".join(b["right_lines"][:3])
            if len(preview) > 200:
                preview = preview[:200] + "…"
            lines.append(f"{i}. Near line {b['right_start'] + 1}{_page_label(b, 'right')}: *\"{preview}\"*")
        if len(additions) > 10:
            lines.append(f"   *(and {len(additions) - 10} more…)*")
        lines.append("")

    # --- Removed content ---
    if deletions:
        lines.append(f"### Removed Content ({len(deletions)} section(s) deleted)")
        lines.append("")
        lines.append("Content present in Document A has been removed in Document B. "
                      "Removed text may eliminate obligations, rights, definitions, or "
                      "qualifications that previously applied.")
        lines.append("")
        for i, b in enumerate(deletions[:10], 1):
            preview = " ".join(b["left_lines"][:3])
            if len(preview) > 200:
                preview = preview[:200] + "…"
            lines.append(f"{i}. Near line {b['left_start'] + 1}{_page_label(b, 'left')}: *\"{preview}\"*")
        if len(deletions) > 10:
            lines.append(f"   *(and {len(deletions) - 10} more…)*")
        lines.append("")

    # --- Modified content ---
    if modifications:
        lines.append(f"### Modified Content ({len(modifications)} section(s) changed)")
        lines.append("")
        lines.append("Existing text was altered between the two versions. Modifications can "
                      "change meaning, adjust figures, update references, or shift the tone "
                      "of the document.")
        lines.append("")
        for i, b in enumerate(modifications[:10], 1):
            old_preview = " ".join(b["left_lines"][:2])
            new_preview = " ".join(b["right_lines"][:2])
            if len(old_preview) > 150:
                old_preview = old_preview[:150] + "…"
            if len(new_preview) > 150:
                new_preview = new_preview[:150] + "…"
            lines.append(f"{i}. Line {b['left_start'] + 1}{_page_label(b, 'left')}:")
            lines.append(f"   - **Was:** *\"{old_preview}\"*")
            lines.append(f"   - **Now:** *\"{new_preview}\"*")
        if len(modifications) > 10:
            lines.append(f"   *(and {len(modifications) - 10} more…)*")
        lines.append("")

    # --- Consequences ---
    lines.extend([
        "---",
        "",
        "## Consequences",
        "",
    ])

    consequences: list[str] = []
    if deletions:
        consequences.append("- **Removed content** may eliminate previously established terms, "
                            "conditions, or information. Reviewers should verify that no critical "
                            "clauses were unintentionally dropped.")
    if additions:
        consequences.append("- **Added content** introduces new information or requirements. "
                            "Stakeholders should review these additions for compliance and "
                            "alignment with expectations.")
    if modifications:
        consequences.append("- **Modified sections** could alter the interpretation of existing "
                            "provisions. A careful line-by-line review of changed sections is "
                            "recommended to assess whether the intent has shifted.")

    if pct > 30:
        consequences.append("- Given the **high volume of changes**, a full re-review of "
                            "Document B is advisable rather than relying on a delta review alone.")

    lines.extend(consequences)
    lines.append("")
    lines.append("---")
    lines.append("*Report generated by PDFCompare.*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_filename(file_storage) -> str:
    """Return a safe display name for an uploaded file.

    Falls back to 'unnamed.pdf' if the browser did not send a filename.
    """
    name = file_storage.filename
    if not name:
        return "unnamed.pdf"
    return name


# ===========================================================================
# API Routes
# ===========================================================================

@app.route("/")
def index():
    """Serve the single-page frontend."""
    return send_from_directory("static", "index.html")


@app.route("/api/config")
def get_config():
    """Expose non-secret server defaults to the frontend.

    Returns the configured LLM provider, model, and endpoint (but never
    the API key itself — only a boolean indicating whether one is set).
    """
    return jsonify({
        "llm_provider": config.LLM_PROVIDER,
        "llm_model": config.LLM_MODEL,
        "llm_endpoint": config.LLM_ENDPOINT,
        "has_api_key": bool(config.LLM_API_KEY),
    })


@app.route("/api/compare", methods=["POST"])
def compare():
    """Main comparison endpoint.

    Expects a multipart/form-data POST with:
      pdf_a, pdf_b           – the two PDF files
      ignore_whitespace      – "true" to collapse whitespace
      ignore_case            – "true" to lowercase before diffing
      ignore_headers_footers – "true" to strip page-number lines
      ignore_pattern         – regex; matching lines are dropped

    Returns JSON with diff_blocks, stats, unified_diff, report,
    metadata_a/b, and metadata_diff.
    """
    if "pdf_a" not in request.files or "pdf_b" not in request.files:
        return jsonify({"error": "Two PDF files are required (pdf_a and pdf_b)."}), 400

    pdf_a = request.files["pdf_a"]
    pdf_b = request.files["pdf_b"]

    name_a = _safe_filename(pdf_a)
    name_b = _safe_filename(pdf_b)

    if not name_a.lower().endswith(".pdf") or not name_b.lower().endswith(".pdf"):
        return jsonify({"error": "Both files must be PDFs."}), 400

    bytes_a = pdf_a.read()
    bytes_b = pdf_b.read()

    # Parse ignore options from form data
    ignore_options = {
        "ignore_whitespace": request.form.get("ignore_whitespace") == "true",
        "ignore_case": request.form.get("ignore_case") == "true",
        "ignore_headers_footers": request.form.get("ignore_headers_footers") == "true",
        "ignore_pattern": request.form.get("ignore_pattern", ""),
    }

    try:
        # Single-pass extraction: text + metadata from one pdfplumber.open()
        lines_a, meta_a = extract_text_and_metadata(bytes_a)
        lines_b, meta_b = extract_text_and_metadata(bytes_b)
    except Exception:
        logger.exception("PDF text extraction failed")
        return jsonify({"error": "Failed to extract text from one or both PDFs."}), 422

    # Apply user-selected ignore rules before diffing
    filtered_a = apply_ignore_rules(lines_a, ignore_options)
    filtered_b = apply_ignore_rules(lines_b, ignore_options)

    diff_blocks, stats = compute_diff(filtered_a, filtered_b)
    unified = generate_unified_diff(filtered_a, filtered_b, name_a, name_b)
    report = generate_report(diff_blocks, stats, name_a, name_b)
    metadata_diff = compare_metadata(meta_a, meta_b)

    return jsonify({
        "diff_blocks": diff_blocks,
        "stats": stats,
        "unified_diff": unified,
        "report": report,
        "name_a": name_a,
        "name_b": name_b,
        "metadata_a": meta_a,
        "metadata_b": meta_b,
        "metadata_diff": metadata_diff,
    })


@app.route("/api/llm-report", methods=["POST"])
def llm_report():
    """Generate an LLM-powered analysis report from a previous comparison.

    Expects a JSON body with: provider, unified_diff, stats, name_a, name_b,
    and an optional config dict (model, api_key, endpoint).

    Server-side .env defaults are used as a base; request fields override them.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON body required."}), 400

    required = ["provider", "unified_diff", "stats", "name_a", "name_b"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    provider = data["provider"] or config.LLM_PROVIDER
    if not provider:
        return jsonify({"error": "No LLM provider specified."}), 400

    # Merge: .env defaults ← request overrides
    llm_config: dict = {}
    if config.LLM_MODEL:
        llm_config["model"] = config.LLM_MODEL
    if config.LLM_API_KEY:
        llm_config["api_key"] = config.LLM_API_KEY
    if config.LLM_ENDPOINT:
        llm_config["endpoint"] = config.LLM_ENDPOINT
    llm_config.update(data.get("config", {}))

    try:
        report = generate_llm_report(
            provider=provider,
            config=llm_config,
            unified_diff=data["unified_diff"],
            stats=data["stats"],
            name_a=data["name_a"],
            name_b=data["name_b"],
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("LLM report generation failed")
        return jsonify({"error": "LLM request failed. Check provider settings and try again."}), 502

    return jsonify({"report": report})


@app.route("/<path:path>")
def static_files(path):
    """Catch-all route to serve static assets (CSS, JS, images, etc.)."""
    return send_from_directory("static", path)


# ---------------------------------------------------------------------------
# Dev server entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=config.DEBUG, port=config.PORT)
