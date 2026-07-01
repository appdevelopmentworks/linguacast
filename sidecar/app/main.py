"""linguacast FastAPI sidecar entrypoint.

Owns heavy compute (STT, translation, summarization, TTS, dub). The Rust core
spawns this process and health-checks ``GET /health`` before using it. Heavy
backends (faster-whisper, etc.) are imported lazily inside handlers so the
process starts instantly.
"""

from __future__ import annotations

import os
import platform

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

SERVICE_NAME = "linguacast-sidecar"
VERSION = "0.1.0"

app = FastAPI(title=SERVICE_NAME, version=VERSION)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe consumed by the Rust core."""
    return HealthResponse(status="ok", service=SERVICE_NAME, version=VERSION)


# --- STT (Session 2) ---


class SttInfo(BaseModel):
    platform: str
    machine: str
    backend: str
    faster_whisper: bool
    cuda_devices: int
    error: str | None = None


@app.get("/stt/info", response_model=SttInfo)
def stt_info() -> SttInfo:
    """Report the selected backend and CUDA availability without loading a model."""
    from app.stt.dispatch import select_backend

    backend = select_backend().name
    fw_available = False
    cuda_devices = 0
    error: str | None = None
    try:
        import ctranslate2  # type: ignore

        cuda_devices = ctranslate2.get_cuda_device_count()
        import faster_whisper  # type: ignore  # noqa: F401

        fw_available = True
    except Exception as e:  # noqa: BLE001
        error = str(e)

    return SttInfo(
        platform=platform.system(),
        machine=platform.machine(),
        backend=backend,
        faster_whisper=fw_available,
        cuda_devices=cuda_devices,
        error=error,
    )


class TranscribeRequest(BaseModel):
    audio_path: str
    output_dir: str | None = None
    language: str | None = None
    model_size: str = "large-v3"
    vad_filter: bool = True
    device: str | None = None
    compute_type: str | None = None


class SegmentModel(BaseModel):
    start: float
    end: float
    text: str


class TranscribeResponse(BaseModel):
    language: str
    duration: float
    backend: str
    device: str
    model: str
    segment_count: int
    srt_path: str | None
    segments: list[SegmentModel]


@app.post("/stt/transcribe", response_model=TranscribeResponse)
def stt_transcribe(req: TranscribeRequest) -> TranscribeResponse:
    """Transcribe an audio file in its source language and write a source SRT.

    Sync endpoint: FastAPI runs it in a threadpool, so a long transcription does
    not block the event loop / health checks.
    """
    from app.srt.writer import write_srt
    from app.stt.base import TranscribeOptions
    from app.stt.dispatch import select_backend

    if not os.path.exists(req.audio_path):
        raise HTTPException(status_code=404, detail=f"audio not found: {req.audio_path}")

    options = TranscribeOptions(
        model_size=req.model_size,
        language=req.language,
        vad_filter=req.vad_filter,
        device=req.device,
        compute_type=req.compute_type,
    )

    try:
        result = select_backend().transcribe(req.audio_path, options)
    except Exception as e:  # noqa: BLE001 — surface a clean error to the caller
        raise HTTPException(status_code=500, detail=str(e)) from e

    srt_path: str | None = None
    if req.output_dir:
        os.makedirs(req.output_dir, exist_ok=True)
        srt_path = os.path.join(req.output_dir, "source.srt")
        write_srt(result.segments, srt_path)

    return TranscribeResponse(
        language=result.language,
        duration=result.duration,
        backend=result.backend,
        device=result.device,
        model=result.model,
        segment_count=len(result.segments),
        srt_path=srt_path,
        segments=[SegmentModel(start=s.start, end=s.end, text=s.text) for s in result.segments],
    )


# --- Translation (Session 3) ---


class TranslateBackendsResponse(BaseModel):
    ollama: dict
    lmstudio: dict


@app.get("/translate/backends", response_model=TranslateBackendsResponse)
def translate_backends() -> TranslateBackendsResponse:
    """Probe local translation tiers for the UI (no cloud key needed)."""
    from app.translate.router import probe_local

    return TranslateBackendsResponse(**probe_local())


class TranslateSrtRequest(BaseModel):
    srt_path: str
    output_dir: str
    model: str | None = None  # preferred model slug/name
    source_lang: str = "en"
    forced_tier: str | None = None  # pin a tier for testing (ollama/lmstudio/openrouter)
    openrouter_key: str | None = None
    openrouter_model: str | None = None


class TranslateSample(BaseModel):
    start: float
    end: float
    src: str
    dst: str


class TranslateSrtResponse(BaseModel):
    tier: str
    model: str
    base_url: str
    segment_count: int
    translated_srt_path: str
    samples: list[TranslateSample]


@app.post("/translate/srt", response_model=TranslateSrtResponse)
def translate_srt_endpoint(req: TranslateSrtRequest) -> TranslateSrtResponse:
    """Translate a source SRT into a Japanese SRT (timestamps preserved)."""
    from app.translate import router as rt
    from app.translate import service

    if not os.path.exists(req.srt_path):
        raise HTTPException(status_code=404, detail=f"SRT not found: {req.srt_path}")

    try:
        backend = rt.resolve_backend(
            preferred_model=req.model,
            forced_tier=req.forced_tier,
            openrouter_key=req.openrouter_key,
            openrouter_model=req.openrouter_model,
        )
    except rt.NoBackendAvailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    try:
        result = service.translate_srt(req.srt_path, req.output_dir, backend, req.source_lang)
    except Exception as e:  # noqa: BLE001 — surface a clean error to the caller
        raise HTTPException(status_code=500, detail=str(e)) from e

    return TranslateSrtResponse(
        tier=backend.tier,
        model=backend.model,
        base_url=backend.base_url,
        segment_count=result["segment_count"],
        translated_srt_path=result["translated_srt_path"],
        samples=[TranslateSample(**s) for s in result["samples"]],
    )
