"""Model-family-aware prompt building (CLAUDE.md gotcha #1).

TranslateGemma is NOT a general chat model: every call must use its exact fixed
single-user-message template (note the TWO blank lines before the text). General
models (Qwen3.6, Gemma 4, cloud) take normal instruction prompts and can be told
to adjust tone / use context and a glossary. Both sit behind one `translate()`.
"""

from __future__ import annotations

_LANG_NAMES = {
    "en": "English",
    "ja": "Japanese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "zh": "Chinese",
    "ko": "Korean",
    "pt": "Portuguese",
    "it": "Italian",
    "ru": "Russian",
}


def language_name(code: str) -> str:
    return _LANG_NAMES.get(code, code)


def is_translategemma(model: str) -> bool:
    return "translategemma" in model.lower()


def translategemma_prompt(text: str, source_lang: str = "en", target_lang: str = "ja") -> str:
    """TranslateGemma's required fixed template. The two blank lines (``\\n\\n\\n``)
    before the text are load-bearing — do not "clean them up"."""
    src = language_name(source_lang)
    tgt = language_name(target_lang)
    return (
        f"You are a professional {src} ({source_lang}) to {tgt} ({target_lang}) translator. "
        f"Your goal is to accurately convey the meaning and nuances of the original {src} "
        f"text while adhering to {tgt} grammar, vocabulary, and cultural sensitivities. "
        f"Produce only the {tgt} translation, without any additional explanations or "
        f"commentary. Please translate the following {src} text into {tgt}:\n\n\n{text}"
    )


def general_messages(
    text: str,
    source_lang: str = "en",
    target_lang: str = "ja",
    context: str | None = None,
    glossary_text: str | None = None,
    tone: str | None = None,
) -> list[dict[str, str]]:
    """Instruction-style messages for general chat models."""
    src = language_name(source_lang)
    tgt = language_name(target_lang)
    system = (
        f"You are a professional {src}-to-{tgt} translator specializing in natural, fluent "
        f"{tgt} suitable for podcast narration. Translate faithfully while making it sound "
        f"natural in {tgt}. Output ONLY the {tgt} translation — no notes, labels, quotes, "
        f"or the original text."
    )
    if tone:
        system += f" Desired tone: {tone}."

    parts: list[str] = []
    if glossary_text:
        parts.append(f"Use these term translations consistently:\n{glossary_text}")
    if context:
        parts.append(
            "Preceding context (already translated — for consistency only, "
            f"do NOT re-translate it):\n{context}"
        )
    parts.append(f"Translate the following {src} text into {tgt}:\n\n{text}")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
