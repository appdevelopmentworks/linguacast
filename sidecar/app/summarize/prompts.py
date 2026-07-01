"""Prompts for the summarize pipeline (compress -> merge -> script).

The output language is Japanese (the product); prompt scaffolding text is
Japanese too so local JA-capable models stay in register. Speaker-count
estimation is a separate tiny classification call.
"""

from __future__ import annotations

Messages = list[dict[str, str]]

_COMPRESS_SYSTEM = (
    "あなたは講演・ポッドキャストの内容を正確に要約する専門家です。"
    "指定された文字起こし（原語のまま）を読み、内容を日本語で構造的に圧縮してください。"
    "重要な主張・具体例・数値・固有名詞を落とさないこと。創作や推測はしないこと。"
)


def compress_section(section_title: str, text: str) -> Messages:
    user = (
        f"次の文字起こしセクション「{section_title}」の内容を、日本語の箇条書きノートに圧縮してください。\n"
        "- 重要な論点・主張ごとに1行\n"
        "- 具体例・数値・固有名詞は保持\n"
        "- 800字以内\n\n"
        f"--- 文字起こし ---\n{text}"
    )
    return [
        {"role": "system", "content": _COMPRESS_SYSTEM},
        {"role": "user", "content": user},
    ]


def merge_notes(notes: list[tuple[str, str]]) -> Messages:
    joined = "\n\n".join(f"## {title}\n{body}" for title, body in notes)
    user = (
        "以下は長編コンテンツをセクションごとに圧縮した日本語ノートです。"
        "全体を通した流れが分かるように、重複を整理し、一つの統合ノートにまとめてください。"
        "重要な主張・具体例・数値・固有名詞は保持してください。1600字以内。\n\n"
        f"{joined}"
    )
    return [
        {"role": "system", "content": _COMPRESS_SYSTEM},
        {"role": "user", "content": user},
    ]


def classify_speakers(sample_text: str) -> Messages:
    """Tiny classification: monologue (lecture) vs multi-speaker conversation."""
    user = (
        "次の文字起こしの抜粋を読み、これが「一人の話者による講義・独白」か"
        "「複数話者による対談・インタビュー・パネル」かを判定してください。"
        "往復のやりとり（質問と応答、話者交代の兆候）があるかに注目してください。\n"
        "回答は次のどちらか1語のみ: MONOLOGUE または DIALOGUE\n\n"
        f"--- 抜粋 ---\n{sample_text}"
    )
    return [{"role": "user", "content": user}]


_SCRIPT_SYSTEM = (
    "あなたは日本語ポッドキャストの放送作家です。学習者向けに、原典の内容を正確に、"
    "しかし聞いていて心地よい自然な日本語で伝える台本を書きます。"
    "誇張・創作はせず、原典にある内容だけを使ってください。"
)


def narration_script(notes: str, source_title: str) -> Messages:
    user = (
        f"以下のノートは「{source_title}」の内容を圧縮したものです。"
        "これをもとに、一人のナレーターが語る日本語ポッドキャストの台本を書いてください。\n"
        "- 冒頭: 何についての回か、原典の紹介を1〜2文\n"
        "- 本編: ノートの流れに沿って、話し言葉（です・ます調）で\n"
        "- 結び: 要点の短いまとめ\n"
        "- 見出しや箇条書きは使わず、朗読可能な段落のみ\n"
        "- 1行目に「タイトル: …」を書き、以降は本文のみ\n\n"
        f"--- ノート ---\n{notes}"
    )
    return [
        {"role": "system", "content": _SCRIPT_SYSTEM},
        {"role": "user", "content": user},
    ]


def dialogue_script(notes: str, source_title: str) -> Messages:
    user = (
        f"以下のノートは「{source_title}」の内容を圧縮したものです。"
        "これをもとに、ホストとゲストの対話形式の日本語ポッドキャスト台本を書いてください。\n"
        "- ホストが聞き手として質問・整理し、ゲストが内容を説明する\n"
        "- 各発話は必ず「ホスト: 」または「ゲスト: 」で始める\n"
        "- 話し言葉（です・ます調）。見出し・箇条書き・ト書きは使わない\n"
        "- 1行目に「タイトル: …」を書き、以降は発話行のみ\n\n"
        f"--- ノート ---\n{notes}"
    )
    return [
        {"role": "system", "content": _SCRIPT_SYSTEM},
        {"role": "user", "content": user},
    ]
