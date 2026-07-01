"""Context carry-over and long-segment splitting for subtitle translation.

Subtitles are translated segment-by-segment to preserve the 1:1 timestamp
mapping. For general (chat) models we carry a small rolling context of already
translated pairs so wording stays consistent across segments; TranslateGemma is
translated per-segment without context (it is not a chat model).
"""

from __future__ import annotations

import re

# How many preceding (source -> target) pairs to include as context.
CONTEXT_WINDOW = 2


def format_context(pairs: list[tuple[str, str]]) -> str | None:
    """Render the last CONTEXT_WINDOW translated pairs as prompt context."""
    recent = pairs[-CONTEXT_WINDOW:]
    if not recent:
        return None
    return "\n".join(f"- {src} -> {dst}" for src, dst in recent)


def split_long_text(text: str, max_chars: int = 1200) -> list[str]:
    """Split an unusually long segment on sentence boundaries so it fits a call.

    Most SRT segments are short; this only triggers on outliers.
    """
    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current.strip())
    return chunks or [text]
