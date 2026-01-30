"""
LLM provider abstraction for PDF comparison report generation.

Supports three providers — Ollama (local), OpenAI, and Google Gemini — via
stdlib ``urllib`` so no additional HTTP library is needed.  Each provider
function builds the appropriate JSON payload, POSTs it, and returns the
model's Markdown response.

Security: all user-supplied endpoint URLs are validated against a blocklist
of cloud-metadata and internal addresses to prevent SSRF.
"""

import json
import urllib.request
import urllib.error
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# System prompt sent to every LLM provider
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert document analyst. You will receive a unified diff of two PDF documents \
along with summary statistics. Your task is to produce a detailed Markdown report that:

1. Summarises the nature and volume of changes.
2. For each significant change, explain what was added, removed, or modified and \
   what the likely consequence is for the meaning of the document.
3. Assess overall severity (Low / Medium / High) and explain why.
4. Highlight any changes that could alter legal, financial, or contractual obligations.
5. End with a clear recommendation on whether the changes require further review.

Be precise, cite line numbers when possible, and use professional language.\
"""


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


def _validate_endpoint(url: str) -> None:
    """Validate an LLM endpoint URL to block SSRF attempts.

    Raises ValueError if the URL uses a disallowed scheme, points to a
    known cloud-metadata address, or uses an ambiguous 0-prefixed host.
    """
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Endpoint scheme must be http or https, got {parsed.scheme!r}")
    hostname = parsed.hostname or ""
    if hostname in _BLOCKED_HOSTS:
        raise ValueError("This endpoint address is not allowed")
    # Block 0-prefixed IPs (e.g. 0177.0.0.1) and the IPv6 unspecified address
    if hostname.startswith("0") or hostname == "[::]":
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
    _validate_endpoint(url)

    body = json.dumps({
        "model": config.get("model", "llama3"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,  # wait for the full response
    }).encode()

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"]


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
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


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
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())
    return data["candidates"][0]["content"]["parts"][0]["text"]


# Lookup table mapping provider name → call function
_PROVIDERS = {
    "ollama": _call_ollama,
    "openai": _call_openai,
    "gemini": _call_gemini,
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
) -> str:
    """Generate a comparison report using the configured LLM provider.

    Args:
        provider:     One of "ollama", "openai", "gemini".
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

    return call_fn(config, SYSTEM_PROMPT, user_prompt)
