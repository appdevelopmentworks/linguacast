"""Section splitting for long transcripts.

Chapters (from yt-dlp metadata) are the preferred topic boundaries; otherwise
we split on size. Sections feed the hierarchical compress -> merge -> script
pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TimedText:
    start: float
    end: float
    text: str


@dataclass
class Section:
    title: str
    start: float
    end: float
    text: str


# A section that comfortably fits one compression call for ~27B local models.
SECTION_MAX_CHARS = 12000
# Below this, neighbouring chapter sections get merged (avoids tiny fragments).
SECTION_MIN_CHARS = 1500


def build_sections(
    items: list[TimedText],
    chapters: list[dict] | None = None,
) -> list[Section]:
    """Group timed segments into topic sections."""
    if chapters:
        sections = _sections_from_chapters(items, chapters)
    else:
        sections = _sections_by_size(items)
    # Oversized sections (single huge chapter) get re-split by size.
    result: list[Section] = []
    for sec in sections:
        if len(sec.text) > SECTION_MAX_CHARS * 1.5:
            result.extend(_resplit(sec, items))
        else:
            result.append(sec)
    return result


def _sections_from_chapters(items: list[TimedText], chapters: list[dict]) -> list[Section]:
    sections: list[Section] = []
    for ch in chapters:
        start = float(ch.get("start", 0.0))
        end = float(ch.get("end", 0.0))
        title = str(ch.get("title", "")) or f"{int(start // 60)}分〜"
        text = " ".join(t.text for t in items if t.start >= start and t.start < end)
        if text.strip():
            sections.append(Section(title=title, start=start, end=end, text=text))

    # Merge undersized neighbours so every section is worth a call.
    merged: list[Section] = []
    for sec in sections:
        if merged and len(merged[-1].text) < SECTION_MIN_CHARS:
            prev = merged[-1]
            merged[-1] = Section(
                title=prev.title,
                start=prev.start,
                end=sec.end,
                text=f"{prev.text} {sec.text}",
            )
        else:
            merged.append(sec)
    return merged


def _sections_by_size(items: list[TimedText]) -> list[Section]:
    sections: list[Section] = []
    buf: list[TimedText] = []
    size = 0
    for t in items:
        buf.append(t)
        size += len(t.text)
        if size >= SECTION_MAX_CHARS:
            sections.append(_pack(buf, len(sections)))
            buf, size = [], 0
    if buf:
        sections.append(_pack(buf, len(sections)))
    return sections


def _resplit(sec: Section, items: list[TimedText]) -> list[Section]:
    inside = [t for t in items if sec.start <= t.start < sec.end]
    parts = _sections_by_size(inside)
    for i, p in enumerate(parts):
        p.title = f"{sec.title} ({i + 1})"
    return parts


def _pack(buf: list[TimedText], index: int) -> Section:
    start = buf[0].start
    return Section(
        title=f"セクション{index + 1}",
        start=start,
        end=buf[-1].end,
        text=" ".join(t.text for t in buf),
    )
