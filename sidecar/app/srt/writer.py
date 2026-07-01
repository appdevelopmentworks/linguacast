"""Segments -> SRT. The source-language SRT keeps these timestamps; the
translated SRT (later session) reuses them and swaps only the text.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable

import srt as srtlib

from app.stt.base import Segment


def segments_to_srt(segments: Iterable[Segment]) -> str:
    subs = [
        srtlib.Subtitle(
            index=i + 1,
            start=datetime.timedelta(seconds=seg.start),
            end=datetime.timedelta(seconds=seg.end),
            content=seg.text,
        )
        for i, seg in enumerate(segments)
    ]
    return srtlib.compose(subs)


def write_srt(segments: Iterable[Segment], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(segments_to_srt(segments))
