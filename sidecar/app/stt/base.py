"""Shared STT types and the transcriber interface.

All backends (faster-whisper on CUDA, mlx-whisper/whisper.cpp on Metal, cloud)
implement the same `transcribe()` shape so the pipeline is backend-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptResult:
    language: str
    duration: float
    segments: list[Segment]
    backend: str
    device: str
    model: str


@dataclass
class TranscribeOptions:
    # large-v3 is the default per CLAUDE.md; overridable for quick smoke tests.
    model_size: str = "large-v3"
    # None = auto-detect the source language. We always transcribe in the source
    # language and translate later via the LLM router (never Whisper's translate).
    language: str | None = None
    # VAD filtering suppresses silence/music hallucination (CLAUDE.md gotcha #2).
    vad_filter: bool = True
    # None = auto (prefer CUDA, fall back to CPU).
    device: str | None = None
    compute_type: str | None = None


class Transcriber(Protocol):
    name: str

    def transcribe(self, audio_path: str, options: TranscribeOptions) -> TranscriptResult: ...
