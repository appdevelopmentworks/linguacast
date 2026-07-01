"""OS/hardware dispatch for the STT backend (CLAUDE.md gotcha #8).

Windows/Linux + NVIDIA -> faster-whisper (CUDA). macOS/Apple Silicon ->
mlx-whisper or whisper.cpp (Metal). All backends share the `transcribe()` shape.
"""

from __future__ import annotations

import platform

from app.stt.base import TranscribeOptions, TranscriptResult


class FasterWhisperBackend:
    name = "faster-whisper"

    def transcribe(self, audio_path: str, options: TranscribeOptions) -> TranscriptResult:
        # Imported lazily so the heavy dependency is only loaded when used.
        from app.stt import faster_whisper_backend as fw

        return fw.transcribe(audio_path, options)


class MacWhisperBackend:
    name = "mlx-whisper/whisper.cpp"

    def transcribe(self, audio_path: str, options: TranscribeOptions) -> TranscriptResult:
        raise NotImplementedError(
            "macOS の STT バックエンド（mlx-whisper / whisper.cpp）はこのビルドでは未実装です。"
        )


def select_backend():
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin" and machine in ("arm64", "aarch64"):
        return MacWhisperBackend()
    return FasterWhisperBackend()
