"""Translation orchestration: source SRT -> Japanese SRT.

Per-segment translation preserves the source timestamps (only the text is
swapped). General models get rolling context + glossary for consistency;
TranslateGemma is translated per-segment with its fixed template.
"""

from __future__ import annotations

import hashlib
import json
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


def _warmup(backend: Backend) -> None:
    """Best-effort: load a local model into VRAM before the per-segment loop.

    A large local model can take longer to load than a single segment's timeout,
    which would abort the whole job on segment 0. Paying that cost once here, with
    a generous timeout, keeps the actual translation calls fast. No-op for cloud
    tiers (nothing to warm up) and non-fatal on failure — a real error will
    resurface on the first real segment.
    """
    if backend.tier not in ("ollama", "lmstudio"):
        return
    try:
        llm.chat(
            backend.base_url,
            backend.api_key,
            backend.model,
            [{"role": "user", "content": "ping"}],
            keep_alive=backend.keep_alive,
            timeout=600.0,
            retries=0,
            reasoning_effort=backend.reasoning_effort,
        )
    except Exception:  # noqa: BLE001 — warmup is advisory only
        pass


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
        reasoning_effort=backend.reasoning_effort,
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
        srt_text = f.read()
    subs = list(srtlib.parse(srt_text))

    use_context = not formatter.is_translategemma(backend.model)
    glossary_text = glossary.format_for_prompt() if glossary else None

    # Mid-stage checkpoint (NFR-4): completed segments are persisted per call,
    # so an interrupted translation resumes where it stopped instead of
    # re-translating from segment 0. Keyed to the source SRT content.
    os.makedirs(output_dir, exist_ok=True)
    fingerprint = hashlib.sha1(srt_text.encode("utf-8")).hexdigest()
    done = _load_partial(output_dir, fingerprint)

    # Load a local model once before the loop so segment 0 doesn't time out on a
    # cold VRAM load (only if there is still work left after resuming).
    if len(done) < len(subs):
        _warmup(backend)

    context_pairs: list[tuple[str, str]] = []
    out_subs: list[srtlib.Subtitle] = []
    samples: list[dict] = []

    for i, sub in enumerate(subs):
        src_text = " ".join(sub.content.split())
        if i in done:
            dst = done[i]
        else:
            context = chunker.format_context(context_pairs) if use_context else None
            dst = translate_text(src_text, backend, source_lang, context, glossary_text)
            done[i] = dst
            _save_partial(output_dir, fingerprint, done)

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

    out_path = os.path.join(output_dir, "translated.ja.srt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(srtlib.compose(out_subs))
    _clear_partial(output_dir)

    return {
        "segment_count": len(out_subs),
        "translated_srt_path": out_path,
        "samples": samples,
    }


def _partial_path(output_dir: str) -> str:
    return os.path.join(output_dir, "translated.partial.json")


def _load_partial(output_dir: str, fingerprint: str) -> dict[int, str]:
    try:
        with open(_partial_path(output_dir), encoding="utf-8") as f:
            data = json.load(f)
        if data.get("fingerprint") != fingerprint:
            return {}
        return {int(k): v for k, v in data.get("entries", {}).items()}
    except Exception:  # noqa: BLE001 — a broken checkpoint just means a fresh start
        return {}


def _save_partial(output_dir: str, fingerprint: str, entries: dict[int, str]) -> None:
    payload = {"fingerprint": fingerprint, "entries": {str(k): v for k, v in entries.items()}}
    with open(_partial_path(output_dir), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def _clear_partial(output_dir: str) -> None:
    try:
        os.remove(_partial_path(output_dir))
    except FileNotFoundError:
        pass
