"""Translation backend resolution: Ollama -> LM Studio -> OpenRouter.

Health-checks each tier in order and returns the highest available one. All are
OpenAI-compatible, so the resolved Backend is just base URL + model (+ key for
the cloud tier). The resolved tier is surfaced to the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.translate import client as llm

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_V1 = "http://localhost:11434/v1"
LMSTUDIO_V1 = "http://localhost:1234/v1"
OPENROUTER_V1 = "https://openrouter.ai/api/v1"
GROQ_V1 = "https://api.groq.com/openai/v1"

# Keep the Ollama model resident between per-segment calls (gotcha #6).
OLLAMA_KEEP_ALIVE = "30m"


@dataclass
class Backend:
    tier: str  # "ollama" | "lmstudio" | "openrouter"
    base_url: str
    model: str
    api_key: str | None = None
    keep_alive: str | None = None
    available_models: list[str] = field(default_factory=list)


class NoBackendAvailable(RuntimeError):
    pass


def _pick_model(
    preferred: str | None, available: list[str], require_general: bool = False
) -> str | None:
    """Pick a model on this tier, degrading to what IS available.

    ``require_general`` excludes translation-specialized models (TranslateGemma
    cannot do general tasks like summarization or script writing).
    """

    def is_tgemma(name: str) -> bool:
        return "translategemma" in name.lower()

    if preferred and preferred in available and not (require_general and is_tgemma(preferred)):
        return preferred

    if not require_general:
        # Prefer a translation-specialized model for translation work.
        for m in available:
            if is_tgemma(m):
                return m

    chat_models = [
        m for m in available if "embed" not in m.lower() and not (require_general and is_tgemma(m))
    ]
    return chat_models[0] if chat_models else None


def probe_local() -> dict:
    """Report local tier availability + models (for the UI, no cloud needed)."""
    ollama = llm.health_ollama(OLLAMA_BASE)
    lmstudio = llm.health_openai_models(LMSTUDIO_V1)
    return {
        "ollama": {"available": ollama is not None, "models": ollama or []},
        "lmstudio": {"available": lmstudio is not None, "models": lmstudio or []},
    }


def resolve_backend(
    preferred_model: str | None = None,
    forced_tier: str | None = None,
    openrouter_key: str | None = None,
    openrouter_model: str | None = None,
    require_general: bool = False,
    cloud_provider: str = "openrouter",
    groq_key: str | None = None,
    groq_model: str | None = None,
) -> Backend:
    if forced_tier in (None, "ollama"):
        models = llm.health_ollama(OLLAMA_BASE)
        if models is not None:
            model = _pick_model(preferred_model, models, require_general)
            if model:
                return Backend("ollama", OLLAMA_V1, model, None, OLLAMA_KEEP_ALIVE, models)

    if forced_tier in (None, "lmstudio"):
        models = llm.health_openai_models(LMSTUDIO_V1)
        if models is not None:
            model = _pick_model(preferred_model, models, require_general)
            if model:
                return Backend("lmstudio", LMSTUDIO_V1, model, None, None, models)

    # Cloud tier: user-selected provider; both are OpenAI-compatible, so each
    # is just a base URL + key for the unified client (no per-provider code).
    if forced_tier in (None, "groq") and cloud_provider == "groq" and groq_key and groq_model:
        return Backend("groq", GROQ_V1, groq_model, groq_key, None, [])
    if (
        forced_tier in (None, "openrouter")
        and cloud_provider == "openrouter"
        and openrouter_key
        and openrouter_model
    ):
        return Backend("openrouter", OPENROUTER_V1, openrouter_model, openrouter_key, None, [])

    raise NoBackendAvailable(
        "利用可能な翻訳バックエンドがありません（Ollama / LM Studio が未起動で、"
        "クラウドLLM（OpenRouter / Groq）のキー・モデルも未設定です）。"
    )
