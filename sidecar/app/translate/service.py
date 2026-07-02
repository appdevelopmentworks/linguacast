"""Translation orchestration: source SRT -> Japanese SRT.

Per-segment translation preserves the source timestamps (only the text is
swapped). General models get rolling context + glossary for consistency;
TranslateGemma is translated per-segment with its fixed template.
"""

from __future__ import annotations

import os

import srt as srtlib

from app.translate import chunker, formatter
from app.translate import client as llm
from app.translate.glossary import Glossary
from app.translate.router import Backend

_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://linguacast.local",
    "X-Title": "linguacast",
}


def _headers_for(backend: Backend) -> dict[str, str] | None:
    return _OPENROUTER_HEADERS if backend.tier == "openrouter" else None


def translate_text(
    text: str,
    backend: Backend,
    source_lang: str = "en",
    context: str | None = None,
    glossary_text: str | None = None,
) -> str:
    if formatter.is_translategemma(backend.model):
        # Fixed template only — TranslateGemma is not instructable.
        messages = [{"role": "user", "content": formatter.translategemma_prompt(text, source_lang)}]
    else:
        messages = formatter.general_messages(
            text, source_lang, context=context, glossary_text=glossary_text
        )

    out = llm.chat(
        backend.base_url,
        backend.api_key,
        backend.model,
        messages,
        keep_alive=backend.keep_alive,
        extra_headers=_headers_for(backend),
    )
    return out.strip()


def translate_srt(
    srt_path: str,
    output_dir: str,
    backend: Backend,
    source_lang: str = "en",
    glossary: Glossary | None = None,
    progress=None,
) -> dict:
    with open(srt_path, encoding="utf-8") as f:
        subs = list(srtlib.parse(f.read()))

    use_context = not formatter.is_translategemma(backend.model)
    glossary_text = glossary.format_for_prompt() if glossary else None

    context_pairs: list[tuple[str, str]] = []
    out_subs: list[srtlib.Subtitle] = []
    samples: list[dict] = []

    for i, sub in enumerate(subs):
        src_text = " ".join(sub.content.split())
        context = chunker.format_context(context_pairs) if use_context else None
        dst = translate_text(src_text, backend, source_lang, context, glossary_text)

        out_subs.append(srtlib.Subtitle(index=i + 1, start=sub.start, end=sub.end, content=dst))
        if progress is not None:
            progress(i + 1, len(subs))
        if use_context:
            context_pairs.append((src_text, dst))
        if len(samples) < 5:
            samples.append(
                {
                    "start": sub.start.total_seconds(),
                    "end": sub.end.total_seconds(),
                    "src": src_text,
                    "dst": dst,
                }
            )

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "translated.ja.srt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(srtlib.compose(out_subs))

    return {
        "segment_count": len(out_subs),
        "translated_srt_path": out_path,
        "samples": samples,
    }
