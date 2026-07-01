"""Cloud STT fallback interface (stub for v0.1).

The fallback contract: when local Whisper is unavailable or too slow, the
pipeline switches to a cloud STT provider. The provider/credentials wiring lands
in a later session; for now this raises a clear, actionable Japanese error.
"""

from __future__ import annotations

from app.stt.base import TranscribeOptions, TranscriptResult


class CloudSTTNotConfigured(RuntimeError):
    pass


class CloudSTTBackend:
    name = "cloud-stt"

    def transcribe(self, audio_path: str, options: TranscribeOptions) -> TranscriptResult:
        raise CloudSTTNotConfigured(
            "クラウドSTTは未設定です。設定でプロバイダとAPIキーを登録してください。"
        )
