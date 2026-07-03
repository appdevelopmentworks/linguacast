"""Unified OpenAI-compatible client + health checks for the three LLM tiers.

Ollama, LM Studio and OpenRouter all speak the OpenAI chat-completions API, so a
single client just swaps base URL + key (CLAUDE.md LLM fallback chain).
"""

from __future__ import annotations

import time

import httpx

DEFAULT_TIMEOUT = 180.0
# Retry transient failures (client-side timeouts, dropped connections, provider
# 429/5xx). A single blip — or a slow first token while a local model loads —
# must not abort a long per-segment translation job.
DEFAULT_RETRIES = 2


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
    retries: int = DEFAULT_RETRIES,
    reasoning_effort: str | None = None,
) -> str:
    from openai import (
        APIConnectionError,
        APITimeoutError,
        BadRequestError,
        InternalServerError,
        OpenAI,
        RateLimitError,
    )

    # max_retries=0: we run our own retry loop so backoff and the retryable set
    # are explicit (the SDK would otherwise double-retry underneath us).
    client = OpenAI(
        base_url=base_url, api_key=api_key or "not-needed", timeout=timeout, max_retries=0
    )
    kwargs: dict = {"model": model, "messages": messages, "temperature": temperature}

    extra_body: dict = {}
    # Ollama keeps the model resident when given keep_alive (CLAUDE.md gotcha #6).
    if keep_alive is not None:
        extra_body["keep_alive"] = keep_alive
    # Disable chain-of-thought on local "thinking" models (e.g. Qwen3 via Ollama).
    # They otherwise emit long hidden reasoning before the answer, making a short
    # per-segment translation 10-100x slower (measured 131s -> 1s on qwen3.6).
    if reasoning_effort is not None:
        extra_body["reasoning_effort"] = reasoning_effort
    if extra_body:
        kwargs["extra_body"] = extra_body
    if extra_headers:
        kwargs["extra_headers"] = extra_headers

    transient = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)
    last_err: Exception | None = None
    dropped_reasoning = False
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except BadRequestError:
            # A provider/model that doesn't support reasoning_effort (e.g. a
            # non-thinking cloud model) rejects it. Drop it once and retry rather
            # than failing the job; re-raise if it still 400s for another reason.
            if not dropped_reasoning and extra_body.get("reasoning_effort") is not None:
                extra_body.pop("reasoning_effort", None)
                dropped_reasoning = True
                continue
            raise
        except transient as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    raise last_err  # unreachable, but keeps type checkers happy
