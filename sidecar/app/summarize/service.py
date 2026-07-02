"""Summarize/podcast-script orchestration.

Length routing: single-pass when the transcript fits one call; hierarchical
(compress per section -> merge -> script) otherwise. Comprehension/compression
and script generation are separate stages (FR-5). The script format branches on
an LLM speaker-count estimate: narration (monologue) vs host/guest dialogue.
"""

from __future__ import annotations

import json
import os
import re

import srt as srtlib

from app.summarize import chunking, prompts
from app.summarize.chunking import Section, TimedText
from app.translate import client as llm
from app.translate.router import Backend

# Fits one compression/script call comfortably on local ~27B models.
SINGLE_PASS_MAX_CHARS = 20000
# Sample size handed to the speaker classifier.
CLASSIFY_SAMPLE_CHARS = 4000
# Generation can be slow on big local models; give calls room to breathe.
CALL_TIMEOUT = 900.0

NARRATOR = "ナレーター"
_DIALOGUE_LINE = re.compile(r"^(ホスト|ゲスト)\s*[:：]\s*(.+)$")
_TITLE_LINE = re.compile(r"^タイトル\s*[:：]\s*(.+)$")


def load_timed_text(srt_path: str) -> list[TimedText]:
    with open(srt_path, encoding="utf-8") as f:
        subs = list(srtlib.parse(f.read()))
    return [
        TimedText(
            start=s.start.total_seconds(),
            end=s.end.total_seconds(),
            text=" ".join(s.content.split()),
        )
        for s in subs
    ]


def _chat(backend: Backend, messages: list[dict[str, str]], temperature: float) -> str:
    return llm.chat(
        backend.base_url,
        backend.api_key,
        backend.model,
        messages,
        temperature=temperature,
        timeout=CALL_TIMEOUT,
        keep_alive=backend.keep_alive,
    ).strip()


def estimate_format(backend: Backend, items: list[TimedText]) -> str:
    """Return "narration" or "dialogue" from a small classification call."""
    sample = ""
    for t in items:
        sample += t.text + "\n"
        if len(sample) >= CLASSIFY_SAMPLE_CHARS:
            break
    out = _chat(backend, prompts.classify_speakers(sample), temperature=0.0)
    return "dialogue" if "DIALOGUE" in out.upper() else "narration"


def generate_script(
    srt_path: str,
    output_dir: str,
    backend: Backend,
    source_title: str,
    chapters: list[dict] | None = None,
    single_pass_budget: int | None = None,
    progress=None,
) -> dict:
    items = load_timed_text(srt_path)
    if not items:
        raise ValueError("transcript SRT has no segments")

    full_text = " ".join(t.text for t in items)
    budget = single_pass_budget or SINGLE_PASS_MAX_CHARS

    # --- Stage A: comprehension / compression ---
    # Progress: N compression units + merge + classify + script generation.
    if len(full_text) <= budget:
        strategy = "single_pass"
        total_units = 3.0
        notes = _chat(
            backend,
            prompts.compress_section(source_title, full_text),
            temperature=0.3,
        )
        section_count = 1
        done_units = 1.0
    else:
        strategy = "hierarchical"
        sections: list[Section] = chunking.build_sections(items, chapters)
        total_units = len(sections) + 3.0
        section_notes: list[tuple[str, str]] = []
        for si, sec in enumerate(sections):
            note = _chat(
                backend,
                prompts.compress_section(sec.title, sec.text),
                temperature=0.3,
            )
            section_notes.append((sec.title, note))
            if progress is not None:
                progress(si + 1, total_units)
        notes = _chat(backend, prompts.merge_notes(section_notes), temperature=0.3)
        section_count = len(sections)
        done_units = float(section_count) + 1.0
    if progress is not None:
        progress(done_units, total_units)

    # --- Speaker-format estimate + Stage B: script generation ---
    script_format = estimate_format(backend, items)
    if progress is not None:
        progress(done_units + 1.0, total_units)
    if script_format == "dialogue":
        raw = _chat(backend, prompts.dialogue_script(notes, source_title), temperature=0.7)
    else:
        raw = _chat(backend, prompts.narration_script(notes, source_title), temperature=0.7)

    title, lines = _parse_script(raw, script_format, fallback_title=source_title)
    if progress is not None:
        progress(total_units, total_units)

    os.makedirs(output_dir, exist_ok=True)
    txt_path = os.path.join(output_dir, "script.ja.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"タイトル: {title}\n\n")
        for line in lines:
            f.write(f"{line['speaker']}: {line['text']}\n")

    json_path = os.path.join(output_dir, "script.json")
    payload = {
        "title": title,
        "format": script_format,
        "strategy": strategy,
        "section_count": section_count,
        "lines": lines,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return {
        **payload,
        "notes": notes,
        "script_txt_path": txt_path,
        "script_json_path": json_path,
    }


def _parse_script(
    raw: str, script_format: str, fallback_title: str
) -> tuple[str, list[dict[str, str]]]:
    """Parse LLM output into (title, [{speaker, text}]). Tolerant of stray lines."""
    title = fallback_title
    lines: list[dict[str, str]] = []

    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        m = _TITLE_LINE.match(ln)
        if m:
            title = m.group(1).strip()
            continue
        m = _DIALOGUE_LINE.match(ln)
        if m:
            lines.append({"speaker": m.group(1), "text": m.group(2).strip()})
            continue
        # Markdown headings / decorations sneak in from some models — skip.
        if ln.startswith(("#", "---", "```", "**")):
            continue
        if script_format == "narration":
            lines.append({"speaker": NARRATOR, "text": ln})
        elif lines:
            # Continuation of the previous dialogue turn.
            lines[-1]["text"] += " " + ln

    if not lines:
        # Degenerate output: keep the raw text as one narration block.
        lines = [{"speaker": NARRATOR, "text": raw.strip()}]
    return title, lines
