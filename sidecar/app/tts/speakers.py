"""LLM-based speaker attribution for the audio-only full read.

Labels each transcript segment as speaker 1 or 2 from conversational cues
(question/answer, register, topic hand-off) so the narrator/guest voices
alternate. This is TEXT-based, not audio diarization: good for clear two-person
interviews, approximate on rapid overlap, and it collapses monologues to a
single speaker. Audio diarization (pyannote) would be more accurate but pulls in
torch and only runs in dev builds.

Batched with a rolling context window so speaker 1/2 stay consistent across
chunks. Best-effort: any failure falls back to a single narrator.
"""

from __future__ import annotations

import re

from app.translate import client as llm
from app.translate.router import Backend

NARRATOR = "ナレーター"
GUEST = "ゲスト"

_BATCH = 30
_CONTEXT = 6
_DIGIT_RE = re.compile(r"[12]")

_SYSTEM = (
    "あなたはインタビューや対話の書き起こしから話者を判定します。入力は1行=1発話です。"
    "各発話が話者1と話者2のどちらかを、会話の流れ（質問→回答、聞き手↔話し手、口調）から推定してください。"
    "インタビューでは通常、聞き手（司会・質問側）と答え手が交互に現れます。"
    "話者が1人だけ（モノローグ・ナレーション）なら全て1にします。\n"
    "出力ルール: 入力の順に、1行につき『1』または『2』の数字だけを出力する。"
    "行数は入力の発話数と必ず同じにする。番号・記号・説明は一切書かない。"
)


def label_speakers(texts: list[str], backend: Backend) -> list[str]:
    """Return a speaker role (NARRATOR/GUEST) for each text, aligned by index."""
    roles: list[str] = []
    for start in range(0, len(texts), _BATCH):
        chunk = texts[start : start + _BATCH]

        # Rolling context: a few already-decided lines keep speaker 1/2 stable.
        ctx = [
            f"[確定] 話者{'1' if roles[i] == NARRATOR else '2'}: {texts[i]}"
            for i in range(max(0, start - _CONTEXT), start)
        ]
        user = ""
        if ctx:
            user += (
                "直前までの確定結果（同じ人物の話者番号を一貫させること）:\n"
                + "\n".join(ctx)
                + "\n\n"
            )
        user += (
            f"次の{len(chunk)}発話を順に判定し、1または2を{len(chunk)}行で出力:\n"
            + "\n".join(chunk)
        )

        try:
            out = llm.chat(
                backend.base_url,
                backend.api_key,
                backend.model,
                [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
                temperature=0.0,
                keep_alive=backend.keep_alive,
                reasoning_effort=backend.reasoning_effort,
            )
        except Exception:  # noqa: BLE001 — attribution is best-effort
            roles.extend([NARRATOR] * len(chunk))
            continue

        # One digit per output line, aligned to input order; pad/truncate to fit.
        digits = [m.group(0) for ln in out.splitlines() if (m := _DIGIT_RE.search(ln))]
        roles.extend(
            GUEST if (digits[j] if j < len(digits) else "1") == "2" else NARRATOR
            for j in range(len(chunk))
        )

    return roles
