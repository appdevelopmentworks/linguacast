# linguacast アーキテクチャ設計

version: 0.1 / status: draft

関連: [requirements.md](requirements.md) / [session-plan.md](session-plan.md)

---

## 1. 全体構成

Tauri 2 を器とし、3つの実行主体で構成する。

```
┌─────────────────────────────────────────────────────────┐
│  Tauri 2 アプリ                                          │
│                                                          │
│  ┌────────────────┐        ┌──────────────────────────┐  │
│  │ Next.js + TS    │ invoke │ Rust コア (src-tauri)     │  │
│  │ (WebView UI)    │◄──────►│ - Tauriコマンド           │  │
│  │ - 入力/設定     │        │ - サイドカー起動/監視     │  │
│  │ - 進捗表示      │        │ - 配信HTTPサーバ          │  │
│  │ - QR表示        │        │ - LAN IP解決 / ffmpeg起動 │  │
│  └────────────────┘        └───────────┬──────────────┘  │
│                                          │ spawn / HTTP    │
│                            ┌─────────────▼──────────────┐  │
│                            │ Python FastAPI サイドカー   │  │
│                            │ (uv管理, 重い計算を担当)    │  │
│                            └─────────────┬──────────────┘  │
└──────────────────────────────────────────┼───────────────┘
                                            │ HTTP (localhost)
        ┌───────────────┬───────────────────┼──────────────┐
        ▼               ▼                   ▼              ▼
   Ollama :11434   LM Studio :1234   VOICEVOX :50021   Cloud APIs
                                                     (STT/LLM/TTS)
```

### 責務分担
- **Next.js + TS**: UIのみ。URL入力・プリセットチャンネル一覧・設定・進捗・QR表示。ビジネスロジックは持たない。UIは既存 FFmpeg-UI の操作感に準拠（上部にURL入力ボックス、直下にスニペット一覧様式のプリセットチャンネルリスト）。5章・12章参照。
- **Rust コア**: プロセスのライフサイクル、ファイルシステム、配信HTTPサーバ、LAN IP解決、`ffmpeg`/`yt-dlp` の起動。ネイティブで軽快にやるべき処理。
- **Python サイドカー**: 重いAI計算（Whisper・LLM呼び出し・TTSオーケストレーション・要約・SRT・同期）。`uv` 管理。torch/CUDA は遅延インストール。

## 2. プロセストポロジー

- アプリ起動時、Rustコアがサイドカー（`uvicorn`）を子プロセスとして起動し、`127.0.0.1` の内部ポートで待受。
- サイドカーは各外部エンジン（Ollama / LM Studio / VOICEVOX / クラウド）をHTTPクライアントとして呼ぶ。
- Rustコアは配信用HTTPサーバを別途 `0.0.0.0` で立て、QRダウンロードを担う（サイドカーとは別。LAN公開する唯一の口）。
- 依存の可用性（ffmpeg / yt-dlp / VOICEVOX / Ollama）は起動時＋実行前にヘルスチェック。

## 3. パイプライン詳細

各ステージは独立したモジュールとし、入出力（主にファイル＋メタJSON）で連結する。

1. **ingest**: URL → `yt-dlp` で音声取得。メタ（タイトル/長さ/チャプター）を保存。長さで方式ルーティング。
2. **extract**: `ffmpeg` で 16kHz mono 等に整形。
3. **transcribe**: ローカルWhisperで原語文字起こし（VADフィルタON）→ セグメント＋原語SRT。STTバックエンドはOSで分岐（Windows/NVIDIA: `faster-whisper`+CUDA / macOS Apple Silicon: `mlx-whisper` or `whisper.cpp`+Metal）。
   - フォールバック: クラウドSTT。
4. **translate**: LLMルーターで和訳。チャンク分割＋文脈/用語集引き継ぎ。TranslateGemmaは専用プロンプト、汎用モデルは通常指示。→ 和訳SRT（原語タイムスタンプ維持）。
   - フォールバック: Ollama → LM Studio → クラウドLLM。
5. **summarize**（任意）: 長編を要約 → 日本語ポッドキャスト台本。長さで 1パス / 階層要約 を切替。
6. **synthesize (TTS)**: VOICEVOX で音声化（キャラ選択）。未起動なら警告。
   - フォールバック: クラウドTTS。
7. **dub**（吹き替えモード時）: 和訳SRTのタイミングに各セグメント音声を配置。`speedScale` + タイムストレッチ + 無音吸収で尺補正 → `ffmpeg` で元動画に多重化。
8. **deliver**: 生成物をローカルHTTP配信 + QRコード化。

## 4. モジュール分割（サイドカー）

```
sidecar/app/
├── main.py            # FastAPIエントリ, ジョブAPI, ヘルスチェック
├── jobs/              # 再開可能ジョブ管理(状態機械, 中間成果物の永続化)
├── stt/               # STTアダプタ(faster-whisper/CUDA, mlx-whisper・whisper.cpp/Metal) + VAD + SRT化
├── translate/
│   ├── router.py      # Ollama→LMStudio→Cloud のフォールバック解決
│   ├── formatter.py   # モデルファミリ別プロンプト(TranslateGemma定型/汎用)
│   ├── chunker.py     # 文脈引き継ぎ付きチャンク分割
│   └── glossary.py    # 用語集の一貫性管理
├── summarize/         # map-reduce / hierarchical / topic-based
├── tts/
│   ├── voicevox.py    # /speakers, /audio_query, /synthesis
│   └── cloud/         # polly.py, google.py 等アダプタ
├── srt/               # parse/format, 和訳SRT生成
├── dub/               # セグメント配置, time-stretch(rubberband), mux
└── delivery/          # QR生成, ファイルトークン解決の補助
```

## 5. IPC / データフロー

- **UI ⇄ Rust**: Tauri `invoke`（ジョブ開始、設定取得/保存、進捗購読、QR取得）。進捗はイベントemitでストリーム。
- **Rust ⇄ サイドカー**: 内部HTTP。ジョブ開始/状態取得。長時間ジョブはジョブID＋ポーリング or SSE。
- **ステージ間**: ファイル（音声/SRT/セグメント音声）＋メタJSON。これにより再開可能性を担保。
- **秘匿情報**: クラウドAPIキーはOSキーチェーン/ユーザー設定に保存。ソース・ログ・URLに載せない。

## 6. フォールバック実装

共通契約: `resolve_backend(stage) → (tier, client)` を各段が持ち、ヘルスチェックで最上位を選ぶ。

- **翻訳/要約**:
  1. Ollama `GET /api/tags` → 必要モデル在庫確認
  2. LM Studio `GET /v1/models`（OpenAI互換）
  3. クラウドLLM（ユーザー設定プロバイダ＋キー）
- **STT**: ローカル faster-whisper 実行可否（GPU/所要時間見積り） → クラウドSTT。
- **TTS**: VOICEVOX `GET /version` 等でヘルスチェック → クラウドTTS。
- 解決した層をジョブメタに記録し、UIに「ローカル/クラウド」表示。ユーザーは設定で強制切替可能。

## 7. 配信レイヤー（QR / 拡張）

- **v0.1: QR + ローカルHTTP**（Rustコア側）
  - `0.0.0.0:<port>` で待受。`GET /download/{token}` が音声を `FileResponse` 相当で返す（rangeサポート = スマホでシーク/ストリーム）。
  - トークンは推測不能・期限付き。LAN内でも保護。
  - LAN IPは Rust `local-ip-address` クレートで取得。QR描画はフロントで `qrcode.react` にURLを渡す。
  - 初回起動時のWindowsファイアウォール許可（プライベート）を案内。
- **拡張1: プライベートRSS** — 生成物を `<enclosure>` にしたRSSを配信し、ポッドキャストアプリで購読。継続視聴・オフラインDL・レジュームをアプリ側に委譲。
- **拡張2: Tailscale** — ポート開放無しで外出先スマホからPCのtailnet IPにアクセス。QR/RSSと併用可。

## 8. 状態管理 / チェックポイント

- ジョブは状態機械（ingest→extract→transcribe→translate→[summarize]→tts→[dub]→deliver）。
- 各ステージ完了時に中間成果物（音声/原語SRT/和訳SRT/セグメント音声）を作業ディレクトリへ保存。
- 失敗時は最後に成功したステージから再開。10hジョブが9h地点で落ちても最初からやり直さない（NFR-4）。
- 作業ディレクトリはジョブID単位。完了後の保持/削除はユーザー設定。

## 9. 技術選定と根拠

- **Tauri 2 + Rust**: 軽量ネイティブ、既存スタックとの一貫性、配信サーバやプロセス管理をRustで安全に。
- **Python FastAPI サイドカー（uv）**: Whisper・LLM・TTSのエコシステムがPython中心。`uv` で高速な依存解決、torch/CUDAは遅延導入で初期セットアップを軽く。
- **STTバックエンド（OS分岐）**: Windows/NVIDIAは `faster-whisper`(CTranslate2/CUDA、参照実装より高速・低VRAM)。macOS/Apple Siliconは `mlx-whisper`(MLX)または `whisper.cpp`(Metal)。いずれもVADフィルタでハルシネーション抑制。共通アダプタ背後で切替。
- **Ollama / LM Studio**: OpenAI互換HTTPでローカルLLMを統一的に呼べる。Ollamaは常駐運用と `OLLAMA_KEEP_ALIVE` によるモデル常駐が容易。
- **VOICEVOX**: 無料・ローカル・日本語特化。ローカルHTTP APIがサイドカー構成に合う。キャラ選択は `/speakers`。
- **ffmpeg**: 音声抽出・ピッチ保持タイムストレッチ（rubberband）・多重化の定番。

## 10. ディレクトリ構成（予定 / Session 0で作成）

```
linguacast/
├── src-tauri/          # Rust: コマンド, 配信サーバ, サイドカーspawn
│   ├── src/
│   ├── Cargo.toml
│   └── tauri.conf.json
├── src/                # Next.js + TS フロント
├── sidecar/
│   ├── pyproject.toml  # uv
│   └── app/            # 4章のモジュール構成
├── docs/
├── CLAUDE.md
└── README.md
```

## 11. 主要リスクと対策

- **翻訳品質のばらつき** → Session 3頭でモデルベンチ（requirements 7章）。ハイブリッド二段翻訳を用意。
- **尺同期の破綻** → speedScale単独に頼らず複合補正。極端な伸縮を避ける。
- **依存欠如（ffmpeg/VOICEVOX等）** → 起動時＋実行前ヘルスチェックと明快な日本語案内。
- **長尺の失敗コスト** → 再開可能ジョブ層で吸収。

## 12. UIレイアウト（FFmpeg-UI準拠）

既存 FFmpeg-UI（Next.js + Tauri 2、テンプレート/スニペット一覧UI）の操作感に合わせ、1画面完結の導線とする。

```
┌────────────────────────────────────────┐
│  linguacast                          [⚙ 設定]   │
│                                                │
│  ┌────────────────────────────┐  │
│  │  🔗 URLを入力（YouTube等）→ 翻訳開始      │  │
│  └────────────────────────────┘  │
│  [出力: 全訳/要約]  [字幕のみ/吹き替え]  [▶開始]│
│                                                │
│  ── プリセットチャンネル ──────────────│
│   AI                                           │
│    ▶ Andrej Karpathy                           │
│    ▶ DeepLearning.AI                            │
│   プログラミング / IT                          │
│    ▶ freeCodeCamp                               │
│   投資                                          │
│    ▶ Point72                                    │
│    ▶ The Master Investor Podcast               │
│                                                │
│  ── 進捗 / 生成物 ─────────────────│
│   [転写 → 翻訳 → 合成 → 配信]  ● ● ○ ○         │
│   生成物: episode.mp3  [QR表示]                │
└────────────────────────────────────────┘
```

- 上部: URL入力ボックス（入力・実行でパイプライン開始）。
- 直下: プリセットチャンネル一覧（FFmpeg-UIのスニペット様式、`▶ ラベル`、カテゴリ見出し付き、クリックで直近動画を取得して選択）。
- 下部: 進捗（解決層のローカル/クラウド表示を含む）と生成物 + QR。
- **プリセットの永続化**: カテゴリ＋チャンネルのリストをユーザー設定に保存（初期値はFR-11、設定で追加/削除/並べ替え）。
