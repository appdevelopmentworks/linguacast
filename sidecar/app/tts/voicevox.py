"""VOICEVOX ENGINE client (local HTTP :50021).

Health-check before any synthesis (CLAUDE.md gotcha #4): a down engine is a
clear Japanese warning, never a silent failure. Long text is synthesized
sentence-by-sentence and concatenated (FR-8).
"""

from __future__ import annotations

import io
import re
import wave

import httpx

DEFAULT_BASE = "http://127.0.0.1:50021"
# Sentence-level synthesis keeps VOICEVOX stable on long inputs.
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?])\s*")
# Pause inserted between lines (seconds of silence).
LINE_PAUSE_SEC = 0.35


def health(base: str = DEFAULT_BASE) -> str | None:
    """Return the engine version, or None when the engine is down."""
    try:
        r = httpx.get(f"{base}/version", timeout=3.0)
        r.raise_for_status()
        return r.json() if isinstance(r.json(), str) else str(r.json())
    except Exception:
        return None


def speakers(base: str = DEFAULT_BASE) -> list[dict]:
    """Speaker/style catalogue for the character-selection UI (FR-8)."""
    r = httpx.get(f"{base}/speakers", timeout=10.0)
    r.raise_for_status()
    result = []
    for sp in r.json():
        result.append(
            {
                "name": sp["name"],
                "styles": [{"id": st["id"], "name": st["name"]} for st in sp.get("styles", [])],
            }
        )
    return result


def synthesize_text(
    text: str,
    style_id: int,
    base: str = DEFAULT_BASE,
    speed_scale: float = 1.0,
) -> bytes:
    """Synthesize one text chunk -> WAV bytes (audio_query -> synthesis)."""
    with httpx.Client(base_url=base, timeout=120.0) as client:
        q = client.post("/audio_query", params={"text": text, "speaker": style_id})
        q.raise_for_status()
        query = q.json()
        if speed_scale != 1.0:
            query["speedScale"] = speed_scale
        s = client.post("/synthesis", params={"speaker": style_id}, json=query)
        s.raise_for_status()
        return s.content


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def synthesize_long_text(
    text: str,
    style_id: int,
    base: str = DEFAULT_BASE,
    speed_scale: float = 1.0,
) -> list[bytes]:
    """Sentence-split synthesis; returns one WAV blob per sentence."""
    return [
        synthesize_text(sentence, style_id, base, speed_scale) for sentence in split_sentences(text)
    ]


def concat_wavs(blobs: list[bytes], pause_sec: float = LINE_PAUSE_SEC) -> bytes:
    """Concatenate WAV blobs (same format) with a short silence between them."""
    if not blobs:
        raise ValueError("no audio to concatenate")

    frames: list[bytes] = []
    params = None
    for blob in blobs:
        with wave.open(io.BytesIO(blob), "rb") as w:
            if params is None:
                params = w.getparams()
            frames.append(w.readframes(w.getnframes()))

    assert params is not None
    silence = b"\x00" * int(params.framerate * pause_sec) * params.sampwidth * params.nchannels

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        for i, chunk in enumerate(frames):
            if i > 0 and pause_sec > 0:
                w.writeframes(silence)
            w.writeframes(chunk)
    return out.getvalue()
