"""Microsoft Edge TTS adapter — free neural voices, no API key, no install.

The zero-setup fallback for users who have not set up VOICEVOX or a Google
key (needs internet). Output is MP3; we convert to 16-bit mono WAV via ffmpeg
so the concat pipeline is shared with VOICEVOX.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile

DEFAULT_VOICE = "ja-JP-NanamiNeural"
# Alternate voice for the second dialogue role.
GUEST_VOICE = "ja-JP-KeitaNeural"
SAMPLE_RATE = 24000


def available() -> bool:
    try:
        import edge_tts  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


async def _stream_mp3(text: str, voice: str) -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    buf = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf += chunk["data"]
    if not buf:
        raise RuntimeError("Edge TTS returned no audio")
    return buf


def synthesize_text(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """Synthesize one text chunk -> 16-bit mono WAV bytes."""
    mp3 = asyncio.run(_stream_mp3(text, voice))

    src = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    dst_path = src.name + ".wav"
    try:
        src.write(mp3)
        src.close()
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                src.name,
                "-ar",
                str(SAMPLE_RATE),
                "-ac",
                "1",
                "-sample_fmt",
                "s16",
                dst_path,
            ],  # fmt: skip
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg mp3->wav failed: {proc.stderr[-200:]!r}")
        with open(dst_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(src.name)
        if os.path.exists(dst_path):
            os.unlink(dst_path)
