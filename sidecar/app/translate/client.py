"""Unified OpenAI-compatible client + health checks for the three LLM tiers.

Ollama, LM Studio and OpenRouter all speak the OpenAI chat-completions API, so a
single client just swaps base URL + key (CLAUDE.md LLM fallback chain).
"""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = 180.0


def health_ollama(base: str) -> list[str] | None:
    """Return Ollama's model names via GET /api/tags, or None if unreachable."""
    try:
        r = httpx.get(f"{base}/api/tags", timeout=3.0)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return None


def health_openai_models(base_v1: str) -> list[str] | None:
    """Return model ids via GET {base}/v1/models (LM Studio / OpenAI-compatible)."""
    try:
        r = httpx.get(f"{base_v1}/models", timeout=3.0)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]
    except Exception:
        return None


def chat(
    base_url: str,
    api_key: str | None,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    timeout: float = DEFAULT_TIMEOUT,
    keep_alive: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> str:
    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=api_key or "not-needed", timeout=timeout)
    kwargs: dict = {"model": model, "messages": messages, "temperature": temperature}

    # Ollama keeps the model resident when given keep_alive (CLAUDE.md gotcha #6).
    if keep_alive is not None:
        kwargs["extra_body"] = {"keep_alive": keep_alive}
    if extra_headers:
        kwargs["extra_headers"] = extra_headers

    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""
