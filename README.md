# linguacast

> 海外の良質な音声コンテンツ（ポッドキャスト・教育動画）を、ローカルAIで日本語に翻訳・音声化し、スマホですぐ聴けるデスクトップアプリ。

## ミッション

英語をはじめとする外国語の壁のせいで、世界に無料で存在する良質な情報にアクセスできない人が数多くいる。その情報格差につけ込む「詐欺的な情報商材・高額スクール」に課金しなくても、一次情報に直接触れて **自走できる** ようにすることが linguacast の目的である。

- 海外の一次情報（ポッドキャスト・講義・カンファレンス動画）を日本語で聴けるようにする
- ローカル完結を基本とし、ランニングコストゼロで使える（非力なマシンの人はクラウドAPIにフォールバック）
- 生成した音声をスマホにワンタップで送り、移動中でも学習できる

## 主要機能

- **動画入力**: YouTube等のURLから音声を取得（yt-dlp）
- **文字起こし**: ローカル Whisper（faster-whisper）を主とし、非力な環境はクラウドSTTにフォールバック
- **翻訳**: ローカルLLM（TranslateGemma / Qwen3.6）で和訳。`Ollama → LM Studio → クラウドLLM API` の3段フォールバック
- **要約 / ポッドキャスト化**: 長編を要約して"日本語ポッドキャスト台本"を生成（任意）
- **SRT出力**: 原語・和訳の字幕を SRT で保存
- **吹き替えモード**: SRTのタイミングに同期させた日本語音声を生成し、元動画に多重化
- **音声合成**: VOICEVOX（キャラクター選択可）でローカル合成。サーバ未起動時は警告。クラウドTTSにもフォールバック
- **QRダウンロード**: 生成した音声をローカルHTTP配信し、QRコードでスマホに即送信

## 技術スタック

- フロント: Tauri 2 + Next.js + TypeScript
- コア/ネイティブ: Rust
- サイドカー: Python + FastAPI（uv管理）
- AI: faster-whisper, Ollama / LM Studio（ローカルLLM）, VOICEVOX ENGINE, 各種クラウドAPI
- メディア: ffmpeg（音声抽出・タイムストレッチ・多重化）

## パイプライン概要

```
URL入力
  → yt-dlp（音声抽出）
  → faster-whisper（文字起こし + SRT）
  → 翻訳/要約ルーター（Ollama → LM Studio → Cloud）
  → VOICEVOX / クラウドTTS（音声合成）
  → SRT同期muxer（吹き替えモード時）
  → QR配信（ローカルHTTP + QRコード）
```

## フォルダ構成

```
linguacast/
├── README.md              ← このファイル
├── CLAUDE.md              ← Claude Code 用の開発ガイド（英語）
└── docs/
    ├── requirements.md    ← 要求定義
    ├── architecture.md    ← アーキテクチャ設計
    ├── session-plan.md    ← Claude Code 実装セッション計画
    └── claude-code-kickoff.md ← Claude Code キックオフ用プロンプト
```

## 開発状況

`planning` → **`docs完成`** → `scaffold`（次） → `implementation`

要求定義・アーキテクチャ・セッション計画まで完了。次は `docs/claude-code-kickoff.md` を Claude Code に渡してスキャフォールド（Session 0）から着手する。

## ドキュメント

- [要求定義 (requirements.md)](docs/requirements.md)
- [アーキテクチャ設計 (architecture.md)](docs/architecture.md)
- [実装セッション計画 (session-plan.md)](docs/session-plan.md)
- [Claude Code キックオフ (claude-code-kickoff.md)](docs/claude-code-kickoff.md)
