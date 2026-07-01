# linguacast 実装セッション計画（Claude Code）

version: 0.1 / status: draft

関連: [requirements.md](requirements.md) / [architecture.md](architecture.md) / [CLAUDE.md](../CLAUDE.md)

各セッションは「目標 / 成果物 / 受け入れ基準」で構成する。原則1セッション＝1つの動く単位。モデル方針は各セッション冒頭に付記（設計判断はOpus級、実装はSonnet級）。

各セッションで最初にやること: `CLAUDE.md` と関連docsを読む → 変更前に方針を確認 → 実装 → 受け入れ基準で自己検証。

---

## Session 0 — スキャフォールド
- **モデル**: Opus級（初期構成の判断が多い）
- **目標**: Tauri 2 + Next.js + FastAPIサイドカーの骨組みを立て、開発ループを回せる状態にする。
- **成果物**:
  - `src-tauri/`, `src/`, `sidecar/` の初期構成（architecture.md 10章）
  - サイドカーをRustコアが起動/監視する疎通（UIからping → サイドカー応答）
  - Lint/format設定（TS: eslint+prettier / Rust: fmt+clippy / Python: ruff）
  - `CLAUDE.md` の Commands セクションを実コマンドで埋める
- **受け入れ基準**: `npm run tauri dev` でUIが起動し、UI→Rust→サイドカーのヘルスチェックが緑になる。

## Session 1 — 動画入力と音声抽出
- **モデル**: Sonnet級
- **目標**: URL入力からローカル音声ファイルまで。
- **成果物**:
  - URL入力UI（FFmpeg-UI準拠: 上部にURLボックス、直下にプリセットチャンネル一覧）
  - プリセットチャンネル表示（初期値=requirements FR-11、カテゴリ分け `▶ラベル` 様式）＋クリックで `yt-dlp` によるチャンネル直近動画一覧
  - `yt-dlp` 連携（音声取得、メタ: タイトル/長さ/チャプター）
  - `ffmpeg` で 16kHz mono 抽出
  - `ffmpeg`/`yt-dlp` の起動時ヘルスチェック＋不足時の日本語案内
- **受け入れ基準**: 任意のYouTube URLから音声とメタが取得でき、長さで方式ルーティングの分岐値が決まる。

## Session 2 — 文字起こしとSRT
- **モデル**: Sonnet級
- **目標**: ローカルWhisperで原語文字起こし＋SRT。
- **成果物**:
  - STTアダプタ（OS分岐: Windows/NVIDIA=`faster-whisper`+CUDA / macOS Apple Silicon=`mlx-whisper` or `whisper.cpp`+Metal、`float16`/`int8_float16`, VADフィルタON、共通 `transcribe()` 背後で切替）
  - セグメント → 原語SRT出力（`srt`/`pysrt`）
  - クラウドSTTフォールバックのインターフェース（実装スタブ可）
- **受け入れ基準**: 数分動画で原語SRTが生成され、無音区間の反復ハルシネーションが出ない。5090で実時間の数倍速で完了（MacはMLX/Metal経由で実用速度）。

## Session 3 — 翻訳ルーター
- **モデル**: Opus級（フォールバック設計とモデル選定）
- **冒頭タスク（重要）**: 翻訳モデルのベンチマーク（requirements 7章）。代表クリップで TranslateGemma 27B / Qwen3.6-27B 等を比較し、翻訳ノードの既定を決める。
- **目標**: 和訳と3段フォールバック。
- **成果物**:
  - `translate/router.py`（Ollama→LM Studio→OpenRouter のヘルスチェック解決、解決層のUI表示。3段ともOpenAI互換の統一クライアントでbase URL＋キー差し替え）
  - `translate/formatter.py`（TranslateGemma定型プロンプト / 汎用モデル指示を1つの `translate()` 背後で切替。**定型の空行2つに注意**）
  - `translate/chunker.py`＋`glossary.py`（文脈/用語一貫性）
  - 和訳SRT（原語タイムスタンプ維持）
  - （任意）ハイブリッド二段翻訳（下訳→自然化）
  - OpenRouter のキー設定＋モデルslug選択（キーはキーチェーン。プロバイダ別実装は不要）
- **受け入れ基準**: 原語SRT→和訳SRTが生成でき、Ollama停止時にLM Studio/クラウドへ自動フォールバックし、UIに現在の層が出る。

## Session 4 — 要約 / ポッドキャスト化（任意モード）
- **モデル**: Opus級（要約方式の設計）
- **目標**: 長編を日本語ポッドキャスト台本に。
- **成果物**:
  - チャンク戦略（1パス / 階層要約）を長さで自動ルーティング
  - チャプターマーカーを話題境界に利用
  - 「圧縮」と「台本生成」を分離した多段処理
  - 台本フォーマットの自動分岐（話者一人→ナレーション単体 / 複数→対話形式）。話者数はLLMがtranscriptから推定（正確な帰属は将来の話者分離で）
- **受け入れ基準**: 1時間級動画から破綻のない日本語台本が生成され、独白はナレーション・対談は対話形式で出力され、超長尺でも階層要約で完走する。

## Session 5 — TTS（VOICEVOX ＋ フォールバック）
- **モデル**: Sonnet級
- **目標**: 日本語音声化とキャラ選択。
- **成果物**:
  - `tts/voicevox.py`（`/speakers` 取得、`/audio_query`→`/synthesis`、文単位合成＋連結）
  - **キャラクター選択UI**
  - **VOICEVOX未起動の警告**（実行前ヘルスチェック、日本語で起動を促す、サイレント失敗させない）
  - 対話形式台本では話者ロールごとに異なる音声を割り当て（例: ホスト/ゲストで別キャラ）
  - クラウドTTSアダプタ（Google Cloud TTS Neural2）＋切替
- **受け入れ基準**: 選んだキャラで台本→音声が生成でき、VOICEVOX停止時に警告が出てクラッシュしない。非力想定でクラウドTTSに切替できる。

## Session 6 — 吹き替え同期（Dub）
- **モデル**: Opus級（同期ロジックが肝）
- **目標**: 和訳音声を動画に同期・多重化。
- **成果物**:
  - `dub/` セグメント配置＋尺補正（`speedScale` 0.8〜1.3クランプ ＋ `rubberband` タイムストレッチ ＋ 無音吸収）
  - `ffmpeg` で元動画へ多重化
- **受け入れ基準**: 和訳音声が字幕タイミングに概ね同期し、ドリフトが累積せず、元動画＋日本語トラックの出力が得られる。

## Session 7 — QR配信
- **モデル**: Sonnet級
- **目標**: 生成音声をスマホへ。
- **成果物**:
  - Rustコアの配信HTTPサーバ（`0.0.0.0`, `GET /download/{token}`, rangeサポート）
  - 期限付き推測不能トークン
  - LAN IP解決（`local-ip-address`）＋ フロントで `qrcode.react` によるQR表示
  - Windowsファイアウォール許可の案内
- **受け入れ基準**: QRをスマホで読むと、ブラウザで音声をシーク再生・ダウンロードできる。

## Session 8 — 設定UI・仕上げ
- **モデル**: Sonnet級
- **目標**: 一連の設定と全体の統合。
- **成果物**:
  - 各段のエンジン/モデル/フォールバック設定、出力モード（全訳/要約、字幕/吹き替え）、プリセットチャンネルの追加/削除/並べ替え/カテゴリ編集
  - 再開可能ジョブ層の統合と進捗UIの完成
  - 依存欠如時のガイド整備、法務注意の明示（requirements 9章）
- **受け入れ基準**: requirements 10章の完成条件を満たし、ローカル完走とクラウドフォールバックの両方が通る。

---

## 拡張（v0.1後）
- プライベートRSS配信 / Tailscale外部アクセス
- 話者分離（WhisperX + pyannote）による話者別の声割り当て
- 複数動画の一括バッチ
