"""TTS orchestration: script lines -> one Japanese audio file.

Engine resolution (fallback contract): VOICEVOX (local) when healthy, else
Edge TTS (free Microsoft voices, zero setup), else Google Cloud TTS when a
key is configured, else a clear Japanese error. In dialogue scripts each
speaker role gets its own voice (FR-5/FR-8).
"""

from __future__ import annotations

import os

from app.tts import voicevox
from app.tts.cloud import edge_tts_backend, google_tts

# Extra pause when the speaker changes in a dialogue (seconds).
TURN_PAUSE_SEC = 0.55


class TTSUnavailable(RuntimeError):
    pass


def resolve_engine(
    forced: str | None = None,
    google_key: str | None = None,
    voicevox_base: str = voicevox.DEFAULT_BASE,
) -> str:
    if forced in ("voicevox", "edge", "google"):
        return forced
    if voicevox.health(voicevox_base) is not None:
        return "voicevox"
    # Edge TTS: free Microsoft voices, no key/install — beginner-friendly
    # fallback (needs internet).
    if edge_tts_backend.available():
        return "edge"
    if google_key:
        return "google"
    raise TTSUnavailable(
        "利用できる音声合成エンジンがありません。VOICEVOX を起動するか、"
        "インターネット接続（Edge TTS 用）を確認してください。"
    )


def synthesize_lines(
    lines: list[dict],
    output_dir: str,
    engine: str,
    voice_map: dict[str, int] | None = None,
    google_key: str | None = None,
    google_voice_map: dict[str, str] | None = None,
    voicevox_base: str = voicevox.DEFAULT_BASE,
    progress=None,
) -> dict:
    """Synthesize speaker-tagged lines into output_dir/audio.ja.wav.

    ``voice_map`` maps a speaker role (ナレーター/ホスト/ゲスト) to a VOICEVOX
    style id; ``google_voice_map`` maps roles to Google voice names.
    """
    if not lines:
        raise ValueError("no lines to synthesize")

    voice_map = voice_map or {}
    google_voice_map = google_voice_map or {}
    default_style = next(iter(voice_map.values()), 3)  # VOICEVOX: 3 = ずんだもん(ノーマル)

    blobs: list[bytes] = []
    pauses: list[float] = []
    prev_speaker: str | None = None

    for li, line in enumerate(lines):
        if progress is not None:
            progress(li, len(lines))
        speaker = line.get("speaker") or "ナレーター"
        text = (line.get("text") or "").strip()
        if not text:
            continue

        if engine == "voicevox":
            style = voice_map.get(speaker, default_style)
            sentence_blobs = voicevox.synthesize_long_text(text, style, voicevox_base)
        elif engine == "edge":
            voice = (
                edge_tts_backend.GUEST_VOICE
                if speaker == "ゲスト"
                else edge_tts_backend.DEFAULT_VOICE
            )
            sentence_blobs = [edge_tts_backend.synthesize_text(text, voice)]
        else:
            if not google_key:
                raise TTSUnavailable("Google Cloud TTS のキーが未設定です。")
            voice = google_voice_map.get(
                speaker,
                google_tts.GUEST_VOICE if speaker == "ゲスト" else google_tts.DEFAULT_VOICE,
            )
            sentence_blobs = [google_tts.synthesize_text(text, google_key, voice)]

        for i, blob in enumerate(sentence_blobs):
            if blobs:
                is_turn = i == 0 and prev_speaker is not None and speaker != prev_speaker
                pauses.append(TURN_PAUSE_SEC if is_turn else voicevox.LINE_PAUSE_SEC)
            blobs.append(blob)
        prev_speaker = speaker

    audio = _concat_with_pauses(blobs, pauses)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "audio.ja.wav")
    with open(out_path, "wb") as f:
        f.write(audio)

    return {"audio_path": out_path, "line_count": len(lines), "engine": engine}


def _concat_with_pauses(blobs: list[bytes], pauses: list[float]) -> bytes:
    """Concat WAVs with a per-gap pause list (len(pauses) == len(blobs) - 1)."""
    import io
    import wave

    if not blobs:
        raise ValueError("no audio produced")

    frames: list[bytes] = []
    params = None
    for blob in blobs:
        with wave.open(io.BytesIO(blob), "rb") as w:
            if params is None:
                params = w.getparams()
            frames.append(w.readframes(w.getnframes()))

    assert params is not None
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        for i, chunk in enumerate(frames):
            if i > 0:
                pause = pauses[i - 1] if i - 1 < len(pauses) else voicevox.LINE_PAUSE_SEC
                silence = (
                    b"\x00" * int(params.framerate * pause) * params.sampwidth * params.nchannels
                )
                w.writeframes(silence)
            w.writeframes(chunk)
    return out.getvalue()
