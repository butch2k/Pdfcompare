"""
LLM provider abstraction for PDF comparison report generation.

Supports four providers — Ollama (local), LM Studio (local), OpenAI, and Google Gemini — via
stdlib ``urllib`` so no additional HTTP library is needed.  Each provider
function builds the appropriate JSON payload, POSTs it, and returns the
model's Markdown response.

Security: all user-supplied endpoint URLs are validated against a blocklist
of cloud-metadata and internal addresses to prevent SSRF.
"""

import ipaddress
import json
import socket
import urllib.request
import urllib.error
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# No-redirect HTTP opener to prevent SSRF via redirect
# ---------------------------------------------------------------------------

class _NoRedirectHandler(urllib.request.HTTPErrorProcessor):
    """Treat 3xx redirects as errors to prevent SSRF via redirect."""
    def http_response(self, request, response):
        if 300 <= response.code < 400:
            raise urllib.error.HTTPError(
                request.full_url, response.code,
                "Redirects are not allowed for LLM endpoints",
                response.headers, response,
            )
        return super().http_response(request, response)
    https_response = http_response

_opener = urllib.request.build_opener(_NoRedirectHandler)


# ---------------------------------------------------------------------------
# System prompt sent to every LLM provider
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are a senior expert in {field}. You will receive a unified diff of two PDF documents \
along with summary statistics. Focus exclusively on substantive content changes — additions, \
deletions, and modifications of meaning, provisions, data, or requirements. \
Ignore formatting, layout, whitespace, numbering, punctuation, and stylistic changes entirely.

IMPORTANT: When the same type of change repeats many times (e.g. a year update on every page, \
a copyright notice change, or a recurring header/footer edit), group them into a single mention. \
State what changed, note it occurs throughout the document (e.g. "across all pages" or \
"approximately N occurrences"), and move on. Never list individual line numbers for repetitive \
changes — a representative example with one or two line references is sufficient.

Produce a thorough, in-depth Markdown report. Begin with a header line:

**Expert analysis by: {field} specialist** ({detection_note})

Then structure the report as follows:

1. **Subject Matter & Context**: Identify what these documents are about and provide \
   background context that a reader needs to understand the significance of the changes.
2. **Executive Summary**: A concise overview of the most important substantive changes \
   and their overall impact.
3. **Detailed Change Analysis**: For each significant change, provide:
   - What exactly was added, removed, or modified (quote key phrases).
   - Why this change matters — explain the intent and rationale where possible.
   - The practical consequences for stakeholders, operations, or compliance.
   - Any risks, ambiguities, or gaps introduced by the change.
   - **Implications**: Explain in depth what this change means in practice. \
     Who is affected and how? Does it create new obligations, remove protections, \
     shift liability, change timelines, or alter scope? What are the downstream \
     effects — on processes, on other provisions in the document, on third parties, \
     on enforcement or interpretation? Consider both intended and unintended consequences. \
     If the change is ambiguous, explain the range of possible interpretations and their \
     respective implications.
4. **Cross-Change Impact**: Analyse how multiple changes interact with each other. \
   Do they compound risk, create inconsistencies, or strengthen the document? \
   Identify any cascading effects where one change amplifies or undermines another. \
   Flag any contradictions between changes.
5. **Severity Assessment**: Rate overall severity (Low / Medium / High / Critical) \
   based on how the changes affect obligations, rights, risks, or outcomes in {field}. \
   Justify the rating with specific references to the changes.
6. **Regulatory & Legal Implications**: Highlight any changes that could alter legal, \
   financial, regulatory, or contractual obligations specific to this domain. \
   Explain the compliance impact: could these changes trigger reporting requirements, \
   affect ongoing disputes, require updated disclosures, or conflict with existing \
   regulations or standards? Identify which jurisdictions or parties are most affected.
7. **Recommendations**: Provide specific, actionable recommendations — not just whether \
   to review, but what to review, who should be involved, and what to watch for. \
   Prioritise the recommendations by urgency and impact.

Do NOT report on formatting, whitespace, reordering, renumbering, or cosmetic edits. \
Only analyse changes that affect the substance or meaning of the document. \
Be precise, cite page/line numbers when possible, and use professional language. \
Provide the depth of analysis expected from a seasoned professional in {field}.

CRITICAL FORMATTING RULES — you MUST follow these exactly:
- Use EXACTLY the 7 numbered section headings listed above (Subject Matter & Context, \
  Executive Summary, Detailed Change Analysis, Cross-Change Impact, Severity Assessment, \
  Regulatory & Legal Implications, Recommendations). Do NOT invent your own headings.
- Start the report with the "Expert analysis by" header line as specified.
- NEVER list more than 3 line/page references for any single change. For repetitive \
  changes, write "e.g. lines 1-5" and state the total count. Do NOT enumerate every occurrence.
- Do NOT wrap your response in markdown code fences (```). Output plain Markdown directly.\
"""


def _detect_field(unified_diff: str) -> str:
    """Detect the professional domain from a sample of the diff content.

    Uses simple keyword matching on the first ~2000 characters to identify the
    document's field. Falls back to "document analysis" if no field is detected.
    """
    sample = unified_diff[:2000].lower()

    field_keywords = [
        ("tax law and international taxation", ["tax", "globe", "pillar two", "oecd", "beps", "minimum tax", "jurisdict"]),
        ("legal and regulatory compliance", ["compliance", "regulation", "statute", "legislation", "ordinance", "enact"]),
        ("contract law", ["contract", "agreement", "clause", "party", "indemnif", "liability", "breach", "termination"]),
        ("finance and accounting", ["financial", "revenue", "audit", "balance sheet", "fiscal", "gaap", "ifrs"]),
        ("healthcare and medical sciences", ["patient", "clinical", "diagnosis", "treatment", "medical", "pharma", "dosage"]),
        ("software engineering", ["api", "endpoint", "function", "database", "deploy", "server", "bug", "release"]),
        ("insurance", ["policy", "premium", "claim", "underwriting", "coverage", "insured", "deductible"]),
        ("intellectual property", ["patent", "trademark", "copyright", "infringement", "intellectual property", "licensing"]),
        ("human resources", ["employee", "compensation", "benefits", "hiring", "termination", "workforce", "payroll"]),
        ("environmental science and policy", ["emission", "carbon", "climate", "environmental", "pollution", "sustainability"]),
        ("education", ["curriculum", "student", "assessment", "syllabus", "academic", "grading"]),
        ("real estate", ["property", "lease", "tenant", "mortgage", "zoning", "escrow"]),
    ]

    best_field = "document analysis"
    best_count = 0
    for field, keywords in field_keywords:
        count = sum(1 for kw in keywords if kw in sample)
        if count > best_count:
            best_count = count
            best_field = field

    # Require at least 2 keyword hits to claim a specific field
    if best_count < 2:
        return "document analysis"
    return best_field


def _build_system_prompt(unified_diff: str, expert_field: str = "") -> str:
    """Build a system prompt tailored to the document's professional domain."""
    if expert_field:
        field = expert_field
        detection_note = "manually selected"
    else:
        field = _detect_field(unified_diff)
        detection_note = "auto-detected" if field != "document analysis" else "general"
    return _SYSTEM_PROMPT_TEMPLATE.format(field=field, detection_note=detection_note)


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------

# Only http and https schemes are allowed for LLM endpoints
_ALLOWED_SCHEMES = {"http", "https"}

# Known cloud-provider metadata endpoints that must never be reached
_BLOCKED_HOSTS = {
    "169.254.169.254",          # AWS EC2 instance metadata
    "metadata.google.internal", # GCP metadata server
    "100.100.100.200",          # Alibaba Cloud metadata
}


def _safe_llm_request(req, timeout=300):
    """Execute an LLM HTTP request, sanitizing errors to avoid leaking API keys."""
    try:
        return _opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise ValueError(f"LLM request failed with HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise ValueError(f"LLM request failed: {e.reason}") from None


def _extract_response(data, *keys):
    """Walk nested dict keys, raising ValueError if any key is missing."""
    current = data
    for key in keys:
        if isinstance(current, list):
            if not isinstance(key, int) or key >= len(current):
                raise ValueError("Unexpected LLM response format")
            current = current[key]
        elif isinstance(current, dict):
            if key not in current:
                raise ValueError("Unexpected LLM response format")
            current = current[key]
        else:
            raise ValueError("Unexpected LLM response format")
    if not isinstance(current, str):
        raise ValueError("Unexpected LLM response format")
    return current


def _validate_endpoint(url: str, *, allow_local: bool = False) -> None:
    """Validate an LLM endpoint URL to block SSRF attempts.

    Resolves the hostname to an IP and rejects private/loopback addresses,
    known cloud-metadata endpoints, and ambiguous schemes.

    If *allow_local* is True, loopback and private addresses are permitted
    (used for providers like Ollama that run on the local machine).
    """
    parsed = urlparse(url)
    if parsed.fragment:
        raise ValueError("Fragment identifiers are not allowed in LLM endpoint URLs")
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Endpoint scheme must be http or https, got {parsed.scheme!r}")
    hostname = parsed.hostname or ""
    if hostname in _BLOCKED_HOSTS:
        raise ValueError("This endpoint address is not allowed")
    # Block 0-prefixed IPs and IPv6 unspecified address
    if hostname.startswith("0") or hostname == "[::]":
        raise ValueError("This endpoint address is not allowed")

    # Resolve hostname and check all resulting IPs against private ranges
    try:
        infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {hostname}")

    for family, _, _, _, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_reserved or ip.is_link_local:
            raise ValueError("This endpoint address is not allowed")
        if not allow_local and (ip.is_private or ip.is_loopback):
            raise ValueError("This endpoint address is not allowed")


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_user_prompt(unified_diff: str, stats: dict, name_a: str, name_b: str) -> str:
    """Assemble the user-role message sent to the LLM.

    Includes document names, change statistics, and the full unified diff
    wrapped in a fenced code block.
    """
    return (
        f"## Documents\n"
        f"- **Document A:** {name_a}\n"
        f"- **Document B:** {name_b}\n\n"
        f"## Change Statistics\n"
        f"- Unchanged lines: {stats['equal']}\n"
        f"- Inserted lines: {stats['insert']}\n"
        f"- Deleted lines: {stats['delete']}\n"
        f"- Modified lines: {stats['replace']}\n\n"
        f"## Unified Diff\n```\n{unified_diff}\n```\n"
    )


# ===========================================================================
# Provider implementations
# ===========================================================================

def _call_ollama(config: dict, system: str, user: str) -> str:
    """Call a local Ollama server using the /api/chat endpoint.

    Ollama does not require an API key.  The endpoint defaults to
    http://localhost:11434 but can be overridden via config["endpoint"].
    """
    base = config.get("endpoint", "http://localhost:11434").rstrip("/")
    url = base + "/api/chat"
    _validate_endpoint(url, allow_local=True)

    body = json.dumps({
        "model": config.get("model", "llama3"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,  # wait for the full response
    }).encode()

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with _safe_llm_request(req) as resp:
        data = json.loads(resp.read())
    return _extract_response(data, "message", "content")


def _call_openai(config: dict, system: str, user: str) -> str:
    """Call the OpenAI Chat Completions API (or any compatible endpoint).

    Requires config["api_key"].  Defaults to the official OpenAI endpoint
    but can target any OpenAI-compatible server via config["endpoint"].
    """
    api_key = config.get("api_key", "")
    url = config.get("endpoint", "https://api.openai.com/v1/chat/completions")
    _validate_endpoint(url)

    body = json.dumps({
        "model": config.get("model", "gpt-4o"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode()

    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with _safe_llm_request(req) as resp:
        data = json.loads(resp.read())
    return _extract_response(data, "choices", 0, "message", "content")


def _call_gemini(config: dict, system: str, user: str) -> str:
    """Call the Google Gemini (Generative Language) API.

    Authenticates via the ``x-goog-api-key`` header (not a URL query param)
    to avoid leaking the key in logs or referer headers.
    """
    api_key = config.get("api_key", "")
    model = config.get("model", "gemini-2.0-flash")
    url = config.get(
        "endpoint",
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    )
    _validate_endpoint(url)

    body = json.dumps({
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user}]}],
    }).encode()

    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    })
    with _safe_llm_request(req) as resp:
        data = json.loads(resp.read())
    return _extract_response(data, "candidates", 0, "content", "parts", 0, "text")


def _call_lmstudio(config: dict, system: str, user: str) -> str:
    """Call a local LM Studio server using its OpenAI-compatible API.

    LM Studio does not require an API key.  The endpoint defaults to
    http://localhost:1234/v1/chat/completions but can be overridden via
    config["endpoint"].
    """
    url = config.get("endpoint", "http://localhost:1234/v1/chat/completions")
    _validate_endpoint(url, allow_local=True)

    body = json.dumps({
        "model": config.get("model", "default"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode()

    # API key is optional — LM Studio ignores it, but some compatible
    # servers may require one, so include it when provided.
    headers = {"Content-Type": "application/json"}
    api_key = config.get("api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=body, headers=headers)
    with _safe_llm_request(req) as resp:
        data = json.loads(resp.read())
    return _extract_response(data, "choices", 0, "message", "content")


# Lookup table mapping provider name → call function
def _call_anthropic(config: dict, system: str, user: str) -> str:
    """Call the Anthropic Messages API for Claude models."""
    api_key = config.get("api_key", "")
    url = config.get("endpoint", "https://api.anthropic.com/v1/messages")
    _validate_endpoint(url)

    body = json.dumps({
        "model": config.get("model", "claude-sonnet-4-20250514"),
        "max_tokens": 8192,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()

    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    })
    with _safe_llm_request(req) as resp:
        data = json.loads(resp.read())
    return _extract_response(data, "content", 0, "text")


def _call_mistral(config: dict, system: str, user: str) -> str:
    """Call the Mistral AI Chat API (OpenAI-compatible)."""
    api_key = config.get("api_key", "")
    url = config.get("endpoint", "https://api.mistral.ai/v1/chat/completions")
    _validate_endpoint(url)

    body = json.dumps({
        "model": config.get("model", "mistral-large-latest"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode()

    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with _safe_llm_request(req) as resp:
        data = json.loads(resp.read())
    return _extract_response(data, "choices", 0, "message", "content")


def _call_groq(config: dict, system: str, user: str) -> str:
    """Call the Groq API (OpenAI-compatible, fast inference)."""
    api_key = config.get("api_key", "")
    url = config.get("endpoint", "https://api.groq.com/openai/v1/chat/completions")
    _validate_endpoint(url)

    body = json.dumps({
        "model": config.get("model", "llama-3.3-70b-versatile"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode()

    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with _safe_llm_request(req) as resp:
        data = json.loads(resp.read())
    return _extract_response(data, "choices", 0, "message", "content")


def _call_deepseek(config: dict, system: str, user: str) -> str:
    """Call the DeepSeek API (OpenAI-compatible)."""
    api_key = config.get("api_key", "")
    url = config.get("endpoint", "https://api.deepseek.com/chat/completions")
    _validate_endpoint(url)

    body = json.dumps({
        "model": config.get("model", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode()

    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with _safe_llm_request(req) as resp:
        data = json.loads(resp.read())
    return _extract_response(data, "choices", 0, "message", "content")


def _call_kimi(config: dict, system: str, user: str) -> str:
    """Call the Moonshot Kimi API (OpenAI-compatible)."""
    api_key = config.get("api_key", "")
    url = config.get("endpoint", "https://api.moonshot.cn/v1/chat/completions")
    _validate_endpoint(url)

    body = json.dumps({
        "model": config.get("model", "moonshot-v1-auto"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode()

    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with _safe_llm_request(req) as resp:
        data = json.loads(resp.read())
    return _extract_response(data, "choices", 0, "message", "content")


def _call_perplexity(config: dict, system: str, user: str) -> str:
    """Call the Perplexity API (OpenAI-compatible)."""
    api_key = config.get("api_key", "")
    url = config.get("endpoint", "https://api.perplexity.ai/chat/completions")
    _validate_endpoint(url)

    body = json.dumps({
        "model": config.get("model", "sonar-pro"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode()

    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with _safe_llm_request(req) as resp:
        data = json.loads(resp.read())
    return _extract_response(data, "choices", 0, "message", "content")


_PROVIDERS = {
    "ollama": _call_ollama,
    "openai": _call_openai,
    "gemini": _call_gemini,
    "lmstudio": _call_lmstudio,
    "anthropic": _call_anthropic,
    "mistral": _call_mistral,
    "groq": _call_groq,
    "deepseek": _call_deepseek,
    "kimi": _call_kimi,
    "perplexity": _call_perplexity,
}


# ===========================================================================
# Public API
# ===========================================================================

def generate_llm_report(
    provider: str,
    config: dict,
    unified_diff: str,
    stats: dict,
    name_a: str,
    name_b: str,
    expert_field: str = "",
) -> str:
    """Generate a comparison report using the configured LLM provider.

    Args:
        provider:     One of "ollama", "lmstudio", "openai", "gemini".
        config:       Dict with optional keys "api_key", "model", "endpoint".
        unified_diff: The unified diff text to analyse.
        stats:        Dict with equal/insert/delete/replace counts.
        name_a:       Filename of document A.
        name_b:       Filename of document B.

    Returns:
        Markdown report string produced by the LLM.

    Raises:
        ValueError: If the provider name is unknown.
    """
    call_fn = _PROVIDERS.get(provider)
    if call_fn is None:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Choose from: {list(_PROVIDERS)}")

    user_prompt = _build_user_prompt(unified_diff, stats, name_a, name_b)

    # Truncate the prompt if it exceeds ~80 K chars to stay within typical
    # LLM context windows and avoid excessive token costs
    max_diff_chars = 80_000
    if len(user_prompt) > max_diff_chars:
        user_prompt = user_prompt[:max_diff_chars] + "\n\n[... diff truncated for length ...]\n"

    system_prompt = _build_system_prompt(unified_diff, expert_field)
    return call_fn(config, system_prompt, user_prompt)
