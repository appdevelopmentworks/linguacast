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


# --- Summarize / podcast script (Session 4) ---


class SummarizeRequest(BaseModel):
    srt_path: str
    output_dir: str
    source_title: str = ""
    chapters: list[dict] | None = None
    model: str | None = None
    forced_tier: str | None = None
    openrouter_key: str | None = None
    openrouter_model: str | None = None
    # Test hook: shrink the single-pass budget to force hierarchical mode.
    single_pass_budget: int | None = None


class ScriptLine(BaseModel):
    speaker: str
    text: str


class SummarizeResponse(BaseModel):
    tier: str
    model: str
    title: str
    format: str  # narration | dialogue
    strategy: str  # single_pass | hierarchical
    section_count: int
    line_count: int
    script_txt_path: str
    script_json_path: str
    lines: list[ScriptLine]


@app.post("/summarize/script", response_model=SummarizeResponse)
def summarize_script(req: SummarizeRequest) -> SummarizeResponse:
    """Compress a transcript and generate a Japanese podcast script."""
    from app.summarize import service as summarize_service
    from app.translate import router as rt

    if not os.path.exists(req.srt_path):
        raise HTTPException(status_code=404, detail=f"SRT not found: {req.srt_path}")

    try:
        # Summarization needs a general model — never TranslateGemma.
        backend = rt.resolve_backend(
            preferred_model=req.model,
            forced_tier=req.forced_tier,
            openrouter_key=req.openrouter_key,
            openrouter_model=req.openrouter_model,
            require_general=True,
        )
    except rt.NoBackendAvailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    try:
        result = summarize_service.generate_script(
            req.srt_path,
            req.output_dir,
            backend,
            source_title=req.source_title or "この動画",
            chapters=req.chapters,
            single_pass_budget=req.single_pass_budget,
        )
    except Exception as e:  # noqa: BLE001 — surface a clean error to the caller
        raise HTTPException(status_code=500, detail=str(e)) from e

    return SummarizeResponse(
        tier=backend.tier,
        model=backend.model,
        title=result["title"],
        format=result["format"],
        strategy=result["strategy"],
        section_count=result["section_count"],
        line_count=len(result["lines"]),
        script_txt_path=result["script_txt_path"],
        script_json_path=result["script_json_path"],
        lines=[ScriptLine(**line) for line in result["lines"]],
    )


# --- TTS (Session 5) ---


class SpeakerStyle(BaseModel):
    id: int
    name: str


class SpeakerInfo(BaseModel):
    name: str
    styles: list[SpeakerStyle]


class TtsStatusResponse(BaseModel):
    voicevox_available: bool
    voicevox_version: str | None
    speakers: list[SpeakerInfo]
    # Japanese guidance shown by the UI when VOICEVOX is down (gotcha #4).
    warning: str | None


@app.get("/tts/status", response_model=TtsStatusResponse)
def tts_status() -> TtsStatusResponse:
    from app.tts import voicevox

    version = voicevox.health()
    if version is None:
        return TtsStatusResponse(
            voicevox_available=False,
            voicevox_version=None,
            speakers=[],
            warning=(
                "VOICEVOX ENGINE が起動していません（http://127.0.0.1:50021）。"
                "VOICEVOX を起動してください。起動しない場合はクラウドTTS"
                "（Google Cloud TTS）へのフォールバックが利用されます。"
            ),
        )
    try:
        speaker_list = voicevox.speakers()
    except Exception:  # noqa: BLE001 — catalogue failure is non-fatal
        speaker_list = []
    return TtsStatusResponse(
        voicevox_available=True,
        voicevox_version=version,
        speakers=[SpeakerInfo(**s) for s in speaker_list],
        warning=None,
    )


class SynthesizeLine(BaseModel):
    speaker: str = "ナレーター"
    text: str


class SynthesizeRequest(BaseModel):
    output_dir: str
    lines: list[SynthesizeLine] | None = None
    # Alternative input: a script.json produced by /summarize/script.
    script_json_path: str | None = None
    # Speaker role -> VOICEVOX style id (e.g. {"ナレーター": 3, "ホスト": 3, "ゲスト": 2}).
    voice_map: dict[str, int] | None = None
    engine: str | None = None  # auto (None) | voicevox | google
    google_key: str | None = None


class SynthesizeResponse(BaseModel):
    engine: str
    audio_path: str
    line_count: int


@app.post("/tts/synthesize", response_model=SynthesizeResponse)
def tts_synthesize(req: SynthesizeRequest) -> SynthesizeResponse:
    """Synthesize a speaker-tagged script into one Japanese WAV."""
    import json as jsonlib

    from app.tts import service as tts_service

    lines: list[dict]
    if req.lines:
        lines = [line.model_dump() for line in req.lines]
    elif req.script_json_path:
        if not os.path.exists(req.script_json_path):
            raise HTTPException(status_code=404, detail=f"script not found: {req.script_json_path}")
        with open(req.script_json_path, encoding="utf-8") as f:
            lines = jsonlib.load(f)["lines"]
    else:
        raise HTTPException(status_code=422, detail="either lines or script_json_path is required")

    try:
        engine = tts_service.resolve_engine(req.engine, req.google_key)
    except tts_service.TTSUnavailable as e:
        # 503 + Japanese guidance: the fallback contract, not a crash.
        raise HTTPException(status_code=503, detail=str(e)) from e

    try:
        result = tts_service.synthesize_lines(
            lines,
            req.output_dir,
            engine,
            voice_map=req.voice_map,
            google_key=req.google_key,
        )
    except Exception as e:  # noqa: BLE001 — surface a clean error to the caller
        raise HTTPException(status_code=500, detail=str(e)) from e

    return SynthesizeResponse(**result)


# --- Dub mode (Session 6) ---


class DubRequest(BaseModel):
    translated_srt_path: str
    output_dir: str
    style_id: int = 3
    video_path: str | None = None


class SegmentFitModel(BaseModel):
    index: int
    start_sec: float
    slot_sec: float
    natural_sec: float
    final_sec: float
    method: str
    shortened: bool


class DubResponse(BaseModel):
    dubbed_audio_path: str
    dubbed_video_path: str | None = None
    segment_count: int
    fit_summary: dict[str, int]
    fits: list[SegmentFitModel]


@app.post("/dub/render", response_model=DubResponse)
def dub_render(req: DubRequest) -> DubResponse:
    """Render a timing-synced Japanese dub track and mux it into the video."""
    from app.dub import service as dub_service
    from app.translate import router as rt
    from app.tts import voicevox

    if not os.path.exists(req.translated_srt_path):
        raise HTTPException(status_code=404, detail=f"SRT not found: {req.translated_srt_path}")
    if req.video_path and not os.path.exists(req.video_path):
        raise HTTPException(status_code=404, detail=f"video not found: {req.video_path}")

    # Dub mode is VOICEVOX-only in v0.1 (speedScale is part of the fit chain).
    if voicevox.health() is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "VOICEVOX ENGINE が起動していません（http://127.0.0.1:50021）。"
                "吹き替え生成には VOICEVOX が必要です。起動してから再実行してください。"
            ),
        )

    # Concise-rewrite backend is best-effort: without one the fit chain still
    # runs (speedScale/stretch/trim), quality just degrades on dense speech.
    try:
        rewrite_backend = rt.resolve_backend(require_general=True)
    except rt.NoBackendAvailable:
        rewrite_backend = None

    try:
        result = dub_service.render_dub(
            req.translated_srt_path,
            req.output_dir,
            req.style_id,
            video_path=req.video_path,
            rewrite_backend=rewrite_backend,
        )
    except Exception as e:  # noqa: BLE001 — surface a clean error to the caller
        raise HTTPException(status_code=500, detail=str(e)) from e

    return DubResponse(**result)
