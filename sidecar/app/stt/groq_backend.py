"""Groq Whisper cloud STT — the low-spec-machine fallback (FR-3).

Free tier friendly: audio is compressed to 16 kHz mono Opus (~11 MB/hour) so
long videos fit the 25 MB per-request cap, and very long audio is split into
chunks whose segment timestamps are re-offset on merge.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

import httpx

from app.stt.base import Segment, TranscriptResult

API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3-turbo"
OPUS_BITRATE = "24k"
# Chunk length for very long audio (1h of 24k opus ~= 11 MB, safely under 25 MB).
MAX_CHUNK_SEC = 3600.0


def transcribe(
    audio_path: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    progress=None,
) -> TranscriptResult:
    total = _probe_duration(audio_path)
    chunk_count = max(1, int(total // MAX_CHUNK_SEC) + (1 if total % MAX_CHUNK_SEC > 1 else 0))

    all_segments: list[Segment] = []
    language: str | None = None

    for i in range(chunk_count):
        offset = i * MAX_CHUNK_SEC
        dur = min(MAX_CHUNK_SEC, max(0.0, total - offset)) if total > 0 else None
        ogg_path = _compress(audio_path, offset if chunk_count > 1 else None, dur)
        try:
            with open(ogg_path, "rb") as f:
                resp = httpx.post(
                    API_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": ("audio.ogg", f, "audio/ogg")},
                    data={"model": model, "response_format": "verbose_json"},
                    timeout=600.0,
                )
        finally:
            os.unlink(ogg_path)

        if resp.status_code == 401:
            raise RuntimeError("Groq APIキーが無効です。設定画面でキーを確認してください。")
        if resp.status_code == 429:
            raise RuntimeError(
                "Groq の無料枠レート制限に達しました。しばらく待ってから再実行してください。"
            )
        if resp.status_code != 200:
            raise RuntimeError(f"Groq STT エラー {resp.status_code}: {resp.text[:300]}")

        payload = resp.json()
        language = payload.get("language") or language
        base = offset if chunk_count > 1 else 0.0
        for seg in payload.get("segments", []):
            text = (seg.get("text") or "").strip()
            if text:
                all_segments.append(
                    Segment(start=seg["start"] + base, end=seg["end"] + base, text=text)
                )
        if progress is not None and total > 0:
            progress(min((i + 1) * MAX_CHUNK_SEC, total), total)

    return TranscriptResult(
        language=language or "en",
        duration=total,
        segments=all_segments,
        backend="groq-whisper",
        device="cloud",
        model=model,
    )


def _compress(src: str, start: float | None, dur: float | None) -> str:
    """16 kHz mono Opus keeps an hour of speech near 11 MB with no quality loss
    that matters for ASR."""
    fd, out_path = tempfile.mkstemp(suffix=".ogg")
    os.close(fd)
    cmd = ["ffmpeg", "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", src]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", OPUS_BITRATE, out_path]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        os.unlink(out_path)
        raise RuntimeError(f"ffmpeg opus compression failed: {proc.stderr[-200:]!r}")
    return out_path


def _probe_duration(path: str) -> float:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0
