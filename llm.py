"""LLM provider abstraction for PDF comparison report generation."""

import json
import urllib.request
import urllib.error
from urllib.parse import urlparse


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

_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTS = {
    "169.254.169.254",  # AWS metadata
    "metadata.google.internal",  # GCP metadata
    "100.100.100.200",  # Alibaba metadata
}


def _validate_endpoint(url: str) -> None:
    """Block SSRF attempts against cloud metadata and internal services."""
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Endpoint scheme must be http or https, got {parsed.scheme!r}")
    hostname = parsed.hostname or ""
    if hostname in _BLOCKED_HOSTS:
        raise ValueError("This endpoint address is not allowed")
    if hostname.startswith("0") or hostname == "[::]":
        raise ValueError("This endpoint address is not allowed")


def _build_user_prompt(unified_diff: str, stats: dict, name_a: str, name_b: str) -> str:
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


# ── Provider implementations ────────────────────────────────────────────────

def _call_ollama(config: dict, system: str, user: str) -> str:
    """Call a local Ollama server (/api/chat endpoint)."""
    base = config.get("endpoint", "http://localhost:11434").rstrip("/")
    url = base + "/api/chat"
    _validate_endpoint(url)

    body = json.dumps({
        "model": config.get("model", "llama3"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }).encode()

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"]


def _call_openai(config: dict, system: str, user: str) -> str:
    """Call the OpenAI Chat Completions API."""
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
    """Call the Google Gemini (Generative Language) API."""
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


_PROVIDERS = {
    "ollama": _call_ollama,
    "openai": _call_openai,
    "gemini": _call_gemini,
}


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
        provider: One of "ollama", "openai", "gemini".
        config: Dict with keys like "api_key", "model", "endpoint".
        unified_diff: The unified diff text.
        stats: Dict with equal/insert/delete/replace counts.
        name_a: Filename of document A.
        name_b: Filename of document B.

    Returns:
        Markdown report string from the LLM.
    """
    call_fn = _PROVIDERS.get(provider)
    if call_fn is None:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Choose from: {list(_PROVIDERS)}")

    user_prompt = _build_user_prompt(unified_diff, stats, name_a, name_b)

    # Truncate diff if it's very large to stay within context limits
    max_diff_chars = 80_000
    if len(user_prompt) > max_diff_chars:
        user_prompt = user_prompt[:max_diff_chars] + "\n\n[... diff truncated for length ...]\n"

    return call_fn(config, SYSTEM_PROMPT, user_prompt)
