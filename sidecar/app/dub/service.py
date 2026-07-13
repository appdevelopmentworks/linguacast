"""Dub-mode rendering: timing-synced Japanese audio muxed into the video.

Japanese naturally runs ~2x longer than dense English speech, so timing is a
content problem before it is an audio problem. The fit chain, in order:

(0) group contiguous subtitles into sync blocks (more room per block),
(1) shorten over-budget Japanese with the LLM (dubbing-style concise rewrite),
(2) synthesize and measure,
(3) resynthesize with VOICEVOX speedScale clamped to <= 1.3 (gotcha #5),
(4) fine-tune with ffmpeg rubberband (pitch-preserving),
(5) absorb residual overrun into trailing silence,
(6) hard-trim at the next block as the last resort.

Blocks are placed at absolute SRT times, so drift cannot accumulate.
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass

import srt as srtlib

from app.translate import client as llm
from app.translate.router import Backend
from app.tts import voicevox
from app.tts.cloud import edge_tts_backend

SPEED_MAX = 1.3
# Skip resynthesis when the overrun is negligible.
RATE_TOLERANCE = 1.02
# Keep this much real silence before the next block when absorbing.
GAP_MARGIN_SEC = 0.05
TAIL_SEC = 0.5
# Beyond this total speed-up the audio sounds rushed; prefer trimming.
STRETCH_CAP = 1.5
# Merge subtitles separated by less than this into one sync block.
GROUP_MAX_GAP_SEC = 0.5
# Upper bound for one sync block (keeps dub roughly aligned with the video).
GROUP_MAX_SEC = 14.0
# Measured VOICEVOX (zundamon) narration pace on real scripts.
CHARS_PER_SEC = 5.8
# Shorten text when it exceeds the budget by more than this factor.
SHORTEN_TRIGGER = 1.15


@dataclass
class BlockFit:
    index: int
    start_sec: float
    slot_sec: float
    natural_sec: float
    final_sec: float
    method: str  # natural | shortened | speed_scaled | stretched | absorbed | trimmed
    shortened: bool


@dataclass
class _Block:
    start: float
    end: float
    text: str


def render_dub(
    translated_srt_path: str,
    output_dir: str,
    style_id: int,
    video_path: str | None = None,
    voicevox_base: str = voicevox.DEFAULT_BASE,
    rewrite_backend: Backend | None = None,
    progress=None,
    engine: str = "voicevox",
    edge_voice: str | None = None,
) -> dict:
    with open(translated_srt_path, encoding="utf-8") as f:
        subs = list(srtlib.parse(f.read()))
    if not subs:
        raise ValueError("translated SRT has no segments")

    def synth(text: str, speed: float) -> bytes:
        """Engine-agnostic synthesis; speed 1.0 = natural pace."""
        if engine == "edge":
            rate_percent = round((speed - 1.0) * 100)
            return edge_tts_backend.synthesize_text(
                text, edge_voice or edge_tts_backend.DEFAULT_VOICE, rate_percent
            )
        return voicevox.synthesize_text(text, style_id, voicevox_base, speed_scale=speed)

    blocks = _group_blocks(subs)

    # Precompute per-block budgets, then (1) shorten all over-budget blocks in
    # batched LLM calls (one call per ~8 blocks instead of one per block).
    budgets: list[float] = []
    for i, block in enumerate(blocks):
        slot = max(0.1, block.end - block.start)
        next_start = blocks[i + 1].start if i + 1 < len(blocks) else None
        gap = max(0.0, next_start - block.end) if next_start is not None else TAIL_SEC
        budgets.append(slot + max(0.0, gap - GAP_MARGIN_SEC))

    over_budget: dict[int, int] = {}
    for i, block in enumerate(blocks):
        char_budget = int(budgets[i] * CHARS_PER_SEC * SPEED_MAX)
        if rewrite_backend is not None and len(block.text) > char_budget * SHORTEN_TRIGGER:
            over_budget[i] = char_budget
    shortened_map = (
        _batch_shorten(blocks, over_budget, rewrite_backend)
        if over_budget and rewrite_backend is not None
        else {}
    )

    fits: list[BlockFit] = []
    placed: list[tuple[float, bytes]] = []
    framerate = None

    for i, block in enumerate(blocks):
        if progress is not None:
            progress(i, len(blocks))
        slot = max(0.1, block.end - block.start)
        next_start = blocks[i + 1].start if i + 1 < len(blocks) else None
        budget = budgets[i]

        text = shortened_map.get(i, block.text)
        shortened = i in shortened_map

        # (2) synthesize and measure.
        blob = synth(text, 1.0)
        frames, fr = _wav_frames(blob)
        framerate = framerate or fr
        natural = len(frames) / 2 / fr
        duration = natural
        method = "shortened" if shortened else "natural"

        # (3) speed resynthesis, clamped (VOICEVOX speedScale / Edge rate).
        if duration > budget * RATE_TOLERANCE:
            speed = min(SPEED_MAX, duration / budget)
            blob = synth(text, speed)
            frames, fr = _wav_frames(blob)
            duration = len(frames) / 2 / fr
            method = "speed_scaled"

        # (4) rubberband fine-tune for what speedScale could not cover.
        if duration > budget * RATE_TOLERANCE:
            factor = min(STRETCH_CAP / SPEED_MAX, duration / budget)
            stretched = _stretch(blob, factor)
            if stretched is not None:
                frames, fr = _wav_frames(stretched)
                duration = len(frames) / 2 / fr
                method = "stretched"

        # (5) fits the budget only thanks to the trailing gap.
        if method in ("natural", "shortened") and duration > slot:
            method = "absorbed"

        # (6) hard guarantee: never overlap the next block.
        if next_start is not None and duration > (next_start - block.start):
            keep = int((next_start - block.start - 0.01) * fr) * 2
            frames = frames[: max(2, keep)]
            duration = len(frames) / 2 / fr
            method = "trimmed"

        placed.append((block.start, frames))
        fits.append(
            BlockFit(
                index=i + 1,
                start_sec=round(block.start, 3),
                slot_sec=round(slot, 3),
                natural_sec=round(natural, 3),
                final_sec=round(duration, 3),
                method=method,
                shortened=shortened,
            )
        )

    if framerate is None:
        raise ValueError("no synthesizable text in SRT")

    total_sec = blocks[-1].end + TAIL_SEC
    track = bytearray(int(total_sec * framerate) * 2)
    for start, frames in placed:
        off = int(start * framerate) * 2
        track[off : off + len(frames)] = frames

    os.makedirs(output_dir, exist_ok=True)
    wav_path = os.path.join(output_dir, "dub.ja.wav")
    with wave.open(wav_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(bytes(track))

    result: dict = {
        "dubbed_audio_path": wav_path,
        "segment_count": len(fits),
        "engine": engine,
        "fit_summary": _summarize(fits),
        "fits": [f.__dict__ for f in fits],
    }

    if video_path:
        out_video = os.path.join(output_dir, "dubbed.mp4")
        mux_video(video_path, wav_path, out_video)
        result["dubbed_video_path"] = out_video

    return result


def _group_blocks(subs: list) -> list[_Block]:
    """Merge contiguous subtitles into sync blocks (gap < 0.5s, <= 14s each)."""
    blocks: list[_Block] = []
    for sub in subs:
        text = " ".join(sub.content.split())
        if not text:
            continue
        start = sub.start.total_seconds()
        end = sub.end.total_seconds()
        if (
            blocks
            and start - blocks[-1].end < GROUP_MAX_GAP_SEC
            and end - blocks[-1].start <= GROUP_MAX_SEC
        ):
            prev = blocks[-1]
            joined = prev.text + ("" if prev.text.endswith(("。", "！", "？")) else " ") + text
            blocks[-1] = _Block(start=prev.start, end=end, text=joined)
        else:
            blocks.append(_Block(start=start, end=end, text=text))
    return blocks


_BATCH_SIZE = 8
_NUMBERED_LINE = None  # set lazily to avoid importing re at module top twice


def _batch_shorten(
    blocks: list[_Block], over_budget: dict[int, int], backend: Backend
) -> dict[int, str]:
    """Shorten all over-budget blocks with batched LLM calls (best-effort)."""
    import re

    global _NUMBERED_LINE
    if _NUMBERED_LINE is None:
        _NUMBERED_LINE = re.compile(r"^\s*(\d+)\s*[:：.。]\s*(.+)$")

    system = (
        "あなたは吹き替え台本の編集者です。各行の日本語を、意味と重要な情報を保ったまま、"
        "指定の文字数以内に収まる自然な話し言葉に短縮してください。"
        "出力は各行「番号: 短縮文」の形式のみ。説明や注釈は不要です。"
    )

    result: dict[int, str] = {}
    items = list(over_budget.items())
    for chunk_start in range(0, len(items), _BATCH_SIZE):
        chunk = items[chunk_start : chunk_start + _BATCH_SIZE]
        user_lines = [f"{idx + 1}（{budget}文字以内）: {blocks[idx].text}" for idx, budget in chunk]
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n".join(user_lines)},
        ]
        try:
            out = llm.chat(
                backend.base_url,
                backend.api_key,
                backend.model,
                messages,
                temperature=0.2,
                timeout=600.0,
                keep_alive=backend.keep_alive,
                reasoning_effort=backend.reasoning_effort,
            )
        except Exception:  # noqa: BLE001 — shortening is best-effort
            continue
        valid = {idx for idx, _ in chunk}
        for line in out.splitlines():
            m = _NUMBERED_LINE.match(line.strip())
            if not m:
                continue
            idx = int(m.group(1)) - 1
            text = m.group(2).strip()
            if idx in valid and text and len(text) < len(blocks[idx].text):
                result[idx] = text
    return result


def mux_video(video_path: str, ja_wav_path: str, out_path: str) -> None:
    """Mux the Japanese dub as the ONLY audio track (replacing the original).

    A second original-language audio track breaks mobile playback: phone
    browsers ignore the "default" disposition and mix every audio track, so the
    QR-delivered video played the original with the dub faint behind it. Keeping
    a single Japanese track is also the expected output for a dub.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", ja_wav_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-metadata:s:a:0", "language=jpn",
        "-metadata:s:a:0", "title=日本語吹き替え",
        "-shortest",
        out_path,
    ]  # fmt: skip
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed: {proc.stderr[-400:]}")


def _wav_frames(blob: bytes) -> tuple[bytes, int]:
    with wave.open(io.BytesIO(blob), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("expected 16-bit mono WAV from the TTS engine")
        return w.readframes(w.getnframes()), w.getframerate()


def _stretch(blob: bytes, factor: float) -> bytes | None:
    """Pitch-preserving speed-up by `factor` via rubberband (atempo fallback)."""
    if factor <= 1.0:
        return blob
    src = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    dst_path = src.name + ".out.wav"
    try:
        src.write(blob)
        src.close()
        for filt in (f"rubberband=tempo={factor:.4f}", f"atempo={min(factor, 2.0):.4f}"):
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", src.name, "-filter:a", filt, dst_path],
                capture_output=True,
            )
            if proc.returncode == 0:
                with open(dst_path, "rb") as f:
                    return f.read()
        return None
    finally:
        os.unlink(src.name)
        if os.path.exists(dst_path):
            os.unlink(dst_path)


def _summarize(fits: list[BlockFit]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for f in fits:
        summary[f.method] = summary.get(f.method, 0) + 1
    return summary
