"""faster-whisper (CTranslate2) backend for Windows/Linux + NVIDIA.

Heavy imports are deferred to call time so the sidecar starts instantly and only
pays the cost when transcription actually runs.
"""

from __future__ import annotations

import os
import sys

from app.stt.base import Segment, TranscribeOptions, TranscriptResult

# huggingface_hub symlinks into its cache by default, which needs Developer Mode
# or admin on Windows (else WinError 1314). Fall back to copies. Must be set
# before huggingface_hub is imported (it reads this at import time).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

# Cache loaded models so we don't reload a multi-GB model per request.
_MODELS: dict[tuple[str, str, str], object] = {}

# Device/compute fallback chain when the caller does not pin one. RTX-class GPUs
# use float16; int8_float16 is a lighter GPU path; CPU int8 is the last resort.
_AUTO_CANDIDATES: list[tuple[str, str]] = [
    ("cuda", "float16"),
    ("cuda", "int8_float16"),
    ("cpu", "int8"),
]


def _prepare_cuda_libs() -> None:
    """Make CTranslate2 find CUDA libs (cuBLAS/cuDNN) shipped as nvidia-*-cu12 wheels.

    CTranslate2 loads these via ``LoadLibrary`` at model-build time, so on Windows
    the DLL directories must be on PATH — ``add_dll_directory`` alone does not
    cover the plain ``LoadLibrary`` CTranslate2 uses. We add every
    ``site-packages/nvidia/*/bin`` directory to both.
    """
    if sys.platform != "win32":
        return
    try:
        import nvidia  # type: ignore
    except Exception:
        # No nvidia wheels present (e.g. CPU-only); nothing to add.
        return

    # `nvidia` is a PEP 420 namespace package (shared by nvidia-*-cu12 wheels),
    # so it has __path__ but no __file__.
    for base in list(getattr(nvidia, "__path__", [])):
        for name in os.listdir(base):
            bindir = os.path.join(base, name, "bin")
            if not os.path.isdir(bindir):
                continue
            try:
                os.add_dll_directory(bindir)
            except OSError:
                pass
            current = os.environ.get("PATH", "")
            if bindir not in current:
                os.environ["PATH"] = bindir + os.pathsep + current


def _load_model(model_size: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    key = (model_size, device, compute_type)
    if key not in _MODELS:
        _MODELS[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _MODELS[key]


def _run(
    audio_path: str, options: TranscribeOptions, device: str, compute_type: str
) -> TranscriptResult:
    model = _load_model(options.model_size, device, compute_type)
    segments_iter, info = model.transcribe(
        audio_path,
        language=options.language,
        task="transcribe",  # gotcha #3: never rely on Whisper's translate task
        vad_filter=options.vad_filter,  # gotcha #2: suppress silence hallucination
        beam_size=5,
    )
    # Consume the generator here so any backend error surfaces inside the try.
    segments = [Segment(start=s.start, end=s.end, text=s.text.strip()) for s in segments_iter]
    return TranscriptResult(
        language=info.language,
        duration=info.duration,
        segments=segments,
        backend="faster-whisper",
        device=device,
        model=options.model_size,
    )


def transcribe(audio_path: str, options: TranscribeOptions) -> TranscriptResult:
    _prepare_cuda_libs()

    if options.device:
        default_ct = "float16" if options.device == "cuda" else "int8"
        candidates = [(options.device, options.compute_type or default_ct)]
    else:
        candidates = _AUTO_CANDIDATES

    last_err: Exception | None = None
    for device, compute_type in candidates:
        try:
            return _run(audio_path, options, device, compute_type)
        except Exception as e:  # noqa: BLE001 — try the next device/compute tier
            last_err = e
            continue

    raise RuntimeError(f"faster-whisper failed on all device tiers: {last_err}")
