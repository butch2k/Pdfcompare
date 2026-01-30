import io
import difflib
import logging
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory
import pdfplumber

import config
from llm import generate_llm_report

app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024

logger = logging.getLogger(__name__)


def extract_text(pdf_bytes: bytes) -> list[str]:
    """Extract text from a PDF, returning a list of lines."""
    lines = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines.extend(text.splitlines())
    return lines


def compute_diff(lines_a: list[str], lines_b: list[str]):
    """Return structured diff information."""
    matcher = difflib.SequenceMatcher(None, lines_a, lines_b)
    opcodes = matcher.get_opcodes()

    diff_blocks = []
    stats = {"equal": 0, "insert": 0, "delete": 0, "replace": 0}

    for tag, i1, i2, j1, j2 in opcodes:
        block = {
            "tag": tag,
            "left_start": i1,
            "left_end": i2,
            "right_start": j1,
            "right_end": j2,
            "left_lines": lines_a[i1:i2],
            "right_lines": lines_b[j1:j2],
        }
        diff_blocks.append(block)

        if tag == "equal":
            stats["equal"] += i2 - i1
        elif tag == "insert":
            stats["insert"] += j2 - j1
        elif tag == "delete":
            stats["delete"] += i2 - i1
        elif tag == "replace":
            stats["replace"] += max(i2 - i1, j2 - j1)

    return diff_blocks, stats


def generate_unified_diff(lines_a, lines_b, name_a="original.pdf", name_b="modified.pdf"):
    """Generate a unified diff string."""
    return "\n".join(
        difflib.unified_diff(
            lines_a, lines_b,
            fromfile=name_a, tofile=name_b,
            lineterm=""
        )
    )


def generate_report(diff_blocks, stats, name_a, name_b):
    """Generate a human-readable Markdown report analysing the differences."""
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

    # Severity assessment
    if pct > 30:
        severity = "**High** — The documents differ substantially. This likely represents a major revision affecting the overall meaning and structure of the document."
    elif pct > 10:
        severity = "**Medium** — Notable differences exist. Specific sections have been altered which may affect interpretation of those sections."
    else:
        severity = "**Low** — Minor differences detected. The documents are largely the same with small edits."

    lines.append(f"**Overall severity:** {severity}")
    lines.append("")

    # Categorise changes
    additions = [b for b in diff_blocks if b["tag"] == "insert"]
    deletions = [b for b in diff_blocks if b["tag"] == "delete"]
    modifications = [b for b in diff_blocks if b["tag"] == "replace"]

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
            lines.append(f"{i}. Near line {b['right_start'] + 1}: *\"{preview}\"*")
        if len(additions) > 10:
            lines.append(f"   *(and {len(additions) - 10} more…)*")
        lines.append("")

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
            lines.append(f"{i}. Near line {b['left_start'] + 1}: *\"{preview}\"*")
        if len(deletions) > 10:
            lines.append(f"   *(and {len(deletions) - 10} more…)*")
        lines.append("")

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
            lines.append(f"{i}. Line {b['left_start'] + 1}:")
            lines.append(f"   - **Was:** *\"{old_preview}\"*")
            lines.append(f"   - **Now:** *\"{new_preview}\"*")
        if len(modifications) > 10:
            lines.append(f"   *(and {len(modifications) - 10} more…)*")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## Consequences",
        "",
    ])

    consequences = []
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


def _safe_filename(file_storage) -> str:
    """Return a safe display name for an uploaded file."""
    name = file_storage.filename
    if not name:
        return "unnamed.pdf"
    return name


# ── API Routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/config")
def get_config():
    """Expose non-secret server defaults to the frontend."""
    return jsonify({
        "llm_provider": config.LLM_PROVIDER,
        "llm_model": config.LLM_MODEL,
        "llm_endpoint": config.LLM_ENDPOINT,
        "has_api_key": bool(config.LLM_API_KEY),
    })


@app.route("/api/compare", methods=["POST"])
def compare():
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

    try:
        lines_a = extract_text(bytes_a)
        lines_b = extract_text(bytes_b)
    except Exception:
        logger.exception("PDF text extraction failed")
        return jsonify({"error": "Failed to extract text from one or both PDFs."}), 422

    diff_blocks, stats = compute_diff(lines_a, lines_b)
    unified = generate_unified_diff(lines_a, lines_b, name_a, name_b)
    report = generate_report(diff_blocks, stats, name_a, name_b)

    return jsonify({
        "diff_blocks": diff_blocks,
        "stats": stats,
        "unified_diff": unified,
        "report": report,
        "name_a": name_a,
        "name_b": name_b,
    })


@app.route("/api/llm-report", methods=["POST"])
def llm_report():
    """Generate an LLM-powered analysis report from a previous comparison."""
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

    # Merge: env defaults ← request overrides
    llm_config = {}
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
    return send_from_directory("static", path)


if __name__ == "__main__":
    app.run(debug=config.DEBUG, port=config.PORT)
