import os
import io
import json
import difflib
import tempfile
from datetime import datetime

from flask import Flask, request, jsonify, send_from_directory, send_file
import pdfplumber

app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

UPLOAD_DIR = tempfile.mkdtemp(prefix="pdfcompare_")


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


# ── API Routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/compare", methods=["POST"])
def compare():
    if "pdf_a" not in request.files or "pdf_b" not in request.files:
        return jsonify({"error": "Two PDF files are required (pdf_a and pdf_b)."}), 400

    pdf_a = request.files["pdf_a"]
    pdf_b = request.files["pdf_b"]

    if not pdf_a.filename.lower().endswith(".pdf") or not pdf_b.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Both files must be PDFs."}), 400

    bytes_a = pdf_a.read()
    bytes_b = pdf_b.read()

    try:
        lines_a = extract_text(bytes_a)
        lines_b = extract_text(bytes_b)
    except Exception as e:
        return jsonify({"error": f"Failed to extract text: {e}"}), 422

    diff_blocks, stats = compute_diff(lines_a, lines_b)
    unified = generate_unified_diff(lines_a, lines_b, pdf_a.filename, pdf_b.filename)
    report = generate_report(diff_blocks, stats, pdf_a.filename, pdf_b.filename)

    return jsonify({
        "diff_blocks": diff_blocks,
        "stats": stats,
        "unified_diff": unified,
        "report": report,
        "name_a": pdf_a.filename,
        "name_b": pdf_b.filename,
    })


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("static", path)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
