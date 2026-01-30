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
_PROVIDERS = {
    "ollama": _call_ollama,
    "openai": _call_openai,
    "gemini": _call_gemini,
    "lmstudio": _call_lmstudio,
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

    return call_fn(config, SYSTEM_PROMPT, user_prompt)
