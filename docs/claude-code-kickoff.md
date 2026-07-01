# Claude Code — Kickoff Prompt

Paste the block below into Claude Code from the `linguacast/` project root to start development. It orients Claude Code to the docs and begins Session 0.

---

```
You are working on `linguacast`, a Tauri 2 desktop app that turns foreign-language
audio content (podcasts/lectures on YouTube) into Japanese audio, local-first with
cloud fallbacks. The mission: help people who can't access foreign-language primary
sources learn directly and become self-reliant, without paying for scammy paid courses.

Before writing any code, read these files in full:
  - CLAUDE.md                      (your operating guide: stack, conventions, gotchas)
  - docs/requirements.md           (what to build: FR/NFR, fallback design)
  - docs/architecture.md           (how it's structured: process topology, pipeline)
  - docs/session-plan.md           (the phased build plan)

Rules of engagement:
  - Follow CLAUDE.md conventions exactly, especially the Language policy
    (Japanese for user-facing UI/notifications, English for code identifiers) and the
    Critical gotchas (TranslateGemma's fixed prompt format with two blank lines,
    Whisper VAD to avoid silence hallucination, VOICEVOX must be health-checked,
    dub-mode duration fitting, keep-alive for local LLMs, delivery server range support).
  - Respect the fallback contract: a missing local engine (Ollama / VOICEVOX / ffmpeg)
    is a warning to the user, never a crash.
  - Long-running work must be resumable (persist per-stage artifacts).
  - Clean-room implementation — do not copy from other projects.

Start with Session 0 (Scaffold) from docs/session-plan.md:
  1. Propose the concrete scaffold: src-tauri/ (Rust), src/ (Next.js + TS),
     sidecar/ (Python FastAPI managed by uv), plus lint/format configs
     (eslint+prettier, cargo fmt+clippy, ruff).
  2. Wire the Rust core to spawn and health-check the FastAPI sidecar, and expose a
     UI -> Rust -> sidecar ping so we can verify the loop.
  3. Fill in the Commands section of CLAUDE.md with the real dev/build/test commands.

Before scaffolding, show me your plan and the exact directory tree you intend to create,
and wait for my confirmation. Ask any clarifying questions now.

Acceptance for Session 0: `npm run tauri dev` launches the UI and the
UI -> Rust -> sidecar health check is green.

Environment note: primary dev on Windows + RTX 5090 (CUDA 12.8), but target cross-platform
(Windows + macOS/Apple Silicon) from the start — keep the STT backend and paths OS-agnostic
per CLAUDE.md. Ollama runs as a resident service. Torch/CUDA in the sidecar should be a
deferred/lazy install (heavy deps).
```

---

## Notes for the operator (Shin)

- 各セッション開始時にこのリポジトリの `CLAUDE.md` と該当docsを Claude Code に読ませてから着手する。
- モデル選択は session-plan.md の各セッション冒頭の付記に従う（設計判断=Opus級、実装=Sonnet級）。
- **Session 3 の冒頭で翻訳モデルのベンチ**（TranslateGemma 27B vs Qwen3.6-27B、requirements 7章）を必ず実施してから翻訳ノードの既定を確定する。
- 依存の事前準備: `ffmpeg`, `yt-dlp`, `VOICEVOX ENGINE`, `Ollama`（`ollama pull translategemma:27b` / 使用するQwen等）。
