# CLAUDE.md

Operating guide for Claude Code working on **linguacast**. Read this fully before writing code. Also read `docs/requirements.md`, `docs/architecture.md`, and `docs/session-plan.md`.

## What this project is

A Tauri 2 desktop app that turns foreign-language audio content (podcasts, lectures on YouTube) into Japanese audio. Local-first pipeline with cloud fallbacks for low-spec machines. See `README.md` for the mission.

Pipeline: `yt-dlp -> local Whisper (transcribe + SRT; faster-whisper on CUDA, mlx-whisper/whisper.cpp on Apple Silicon) -> translate/summarize router (Ollama -> LM Studio -> Cloud API) -> VOICEVOX / Cloud TTS -> SRT-timed mux (dub mode) -> QR delivery`.

## Tech stack (pin these)

- Frontend: Tauri 2 + Next.js + TypeScript
- Native/core: Rust (Tauri commands, local IP resolution, ffmpeg orchestration)
- Sidecar: Python + FastAPI, managed with `uv`. Torch/CUDA installed lazily (heavy deps deferred).
- Local STT: OS-dispatched adapter. Windows/NVIDIA: `faster-whisper` (CTranslate2/CUDA), `large-v3`, `float16`/`int8_float16`. macOS/Apple Silicon: `mlx-whisper` (MLX) or `whisper.cpp` (Metal).
- Local LLM: Ollama primary, LM Studio secondary (both expose OpenAI-compatible HTTP)
- Local TTS: VOICEVOX ENGINE (local HTTP on :50021)
- Cloud TTS (fallback): Google Cloud TTS (Neural2) — single provider in v0.1. Needs Google Cloud credentials.
- Media: system `ffmpeg` (audio extraction, pitch-preserving time-stretch, muxing)
- Target OS: cross-platform (Windows + macOS). Same stack as the author's FFmpeg-UI, which already ships for Mac (Apple Silicon/Intel) and Windows. Keep paths and commands OS-agnostic.
- STT backend is OS-dependent (see gotchas): Windows/NVIDIA -> faster-whisper (CUDA); macOS/Apple Silicon -> mlx-whisper (MLX) or whisper.cpp (Metal). CUDA is NVIDIA-only.

## Architecture principles

1. **Local-first, graceful fallback.** Every AI stage has a fallback chain. Never hard-fail because a local engine is missing; degrade to the next tier and tell the user.
2. **Sidecar owns heavy compute.** Whisper, LLM calls, TTS orchestration live in the FastAPI sidecar. Rust/Tauri handles process lifecycle, filesystem, and the delivery HTTP server. TS handles UI only.
3. **Resumable long jobs.** A 10h video must not lose work if it fails at hour 9. Persist per-stage artifacts (audio, transcript SRT, translated SRT, per-segment audio) and support resume.
4. **Clean-room implementation.** Do not copy from other projects; build fresh.

## Directory layout (create in Session 0)

```
linguacast/
├── src-tauri/          # Rust: Tauri commands, delivery server, sidecar spawn
├── src/                # Next.js + TS frontend
├── sidecar/            # Python FastAPI: pipeline stages
│   ├── pyproject.toml  # uv-managed
│   ├── app/
│   │   ├── main.py
│   │   ├── stt/        # faster-whisper wrapper
│   │   ├── translate/  # LLM router + TranslateGemma formatter
│   │   ├── summarize/  # chunking + map-reduce/hierarchical
│   │   ├── tts/        # VOICEVOX client + cloud TTS adapters
│   │   ├── srt/        # SRT parse/format, translated SRT
│   │   ├── dub/        # segment sync, time-stretch, mux
│   │   └── delivery/   # QR + file serving helpers
├── docs/
└── CLAUDE.md
```

## Language policy

- **User-facing UI strings, notifications, docs → Japanese.**
- **Code identifiers, comments, commit messages, config, log messages → English.**
- Output audio/subtitles are Japanese (that is the product).

## Model policy (which Claude model to use)

- Architecture / ambiguous design decisions → Opus-class.
- Routine implementation → Sonnet-class.
- This is guidance for the human operator when selecting models per session; it does not change runtime behavior.

## LLM fallback chain (runtime)

Resolve the translation/summarization backend in this order, health-checking each:

1. **Ollama** (`http://localhost:11434`) — check `GET /api/tags`, confirm required model present.
2. **LM Studio** (`http://localhost:1234/v1`) — OpenAI-compatible; check `GET /v1/models`.
3. **OpenRouter** (`https://openrouter.ai/api/v1`) — OpenAI-compatible cloud gateway. One key, model-agnostic (user picks a model slug like `anthropic/claude-...`, `openai/gpt-...`, `google/gemini-...`). Do NOT build per-provider adapters in v0.1 — OpenRouter covers OpenAI/Anthropic/Gemini/etc. Used when both local options are unavailable or the user opts in for quality.

All three tiers are OpenAI-compatible, so implement ONE client that swaps base URL + key. Key in OS keychain, never in source.

Expose the resolved tier to the UI so the user knows whether they are running local or cloud.

## Critical gotchas (do not rediscover these)

1. **TranslateGemma requires a fixed prompt format.** It is NOT a general chat model. Wrap every translation call in this exact single-user-message template (note the TWO blank lines before the text). For EN->JA:

   ```
   You are a professional English (en) to Japanese (ja) translator. Your goal is to accurately convey the meaning and nuances of the original English text while adhering to Japanese grammar, vocabulary, and cultural sensitivities. Produce only the Japanese translation, without any additional explanations or commentary. Please translate the following English text into Japanese:


   {TEXT}
   ```

   General models (Qwen3.6) use normal instruction prompts and can be told to adjust tone. Keep the two prompt styles behind one `translate()` interface that dispatches by model family.

2. **Whisper hallucinates on silence/music.** Use VAD preprocessing (WhisperX-style) or faster-whisper's VAD filter to avoid repeated-phrase artifacts on non-speech regions. Critical for long videos.

3. **Whisper's built-in `translate` task only outputs English.** For Japanese, always `transcribe` in source language, then translate via the LLM router. Never rely on Whisper for JA translation.

4. **VOICEVOX must be running.** The engine is a separate local HTTP service (:50021). Before any TTS, health-check it. If down, surface a clear Japanese warning with a "start VOICEVOX" hint; do not silently fail or crash the pipeline. Character selection is a required feature — fetch speakers from `GET /speakers`.

5. **Dub-mode duration mismatch.** Japanese TTS rarely matches the source segment length. Fit each SRT segment by (a) computing target rate, (b) setting VOICEVOX `speedScale` clamped to ~0.8–1.3, (c) fine-tuning with ffmpeg time-stretch (`rubberband`), (d) absorbing residual overrun into adjacent silence. Do not rely on `speedScale` alone above ~1.4 (sounds rushed).

6. **Keep models resident.** Set `OLLAMA_KEEP_ALIVE` long so models stay in VRAM between segment calls. Reloading a 27B model per chunk destroys throughput.

7. **Delivery server binds `0.0.0.0`** and serves with HTTP range support (seek/stream on mobile). Use unguessable, expiring tokens in download paths even on LAN. First run triggers a Windows Firewall prompt — allow on Private network.

8. **STT backend is platform-dispatched.** Do not hardcode CUDA/faster-whisper. Detect platform: NVIDIA/CUDA available -> faster-whisper; Apple Silicon -> mlx-whisper or whisper.cpp (Metal). Keep both behind one `transcribe()` adapter; a CUDA call will fail on Mac.

9. **Preset channels are quick-access entries, not videos.** The UI shows curated source channels (see requirements FR-11) below the URL box, styled like FFmpeg-UI's snippet list. A channel URL is not a single video: on click, use yt-dlp to list the channel's recent uploads for the user to pick. Presets are user-editable and persisted in user config.

## Commands

Toolchain: Node 24 / npm, Rust 1.96 + `cargo-tauri` 2, `uv` (manages its own
CPython 3.12 — no system Python needed). All commands run from the repo root.

```bash
# --- First-time setup ---
npm install                     # frontend + Tauri CLI deps
uv sync --directory sidecar     # sidecar venv (downloads CPython 3.12 on first run)

# --- Dev (single command) ---
npm run tauri dev               # builds Rust, starts Next.js (:3000), and the Rust
                                # core auto-spawns + health-checks the FastAPI sidecar
                                # on a free loopback port (killed on app exit).

# --- Release build ---
npm run tauri build             # frontend is static-exported to out/, then bundled

# --- Sidecar standalone (isolated testing only; dev does this for you) ---
uv run --directory sidecar uvicorn app.main:app --host 127.0.0.1 --port 8756
# curl http://127.0.0.1:8756/health  ->  {"status":"ok","service":"linguacast-sidecar",...}

# --- Lint / format ---
# TypeScript / frontend (ESLint flat config + Prettier)
npm run lint
npm run format          # prettier --write .
npm run format:check    # prettier --check .
# Rust (src-tauri)
cargo fmt --manifest-path src-tauri/Cargo.toml
cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets
cargo test --manifest-path src-tauri/Cargo.toml --lib   # delivery server tests etc.
# Python (sidecar) — ruff run ephemerally via uvx (not a runtime dep)
uvx ruff check sidecar
uvx ruff format sidecar

# --- App icon (after editing src-tauri/app-icon.png) ---
npm run tauri -- icon src-tauri/app-icon.png

# --- Release build / installer ---
# 1) package the sidecar into a single binary (cloud/Edge build; no
#    faster-whisper — packaged builds transcribe via Groq). Places it in
#    src-tauri/binaries/ (gitignored; CI rebuilds it).
uv run --directory sidecar --with pyinstaller python ../scripts/build-sidecar.py
# 2) build the installers (out/ is static-exported first)
npm run tauri build                     # nsis + msi (Windows) / dmg (macOS)
# artifacts: src-tauri/target/release/bundle/{nsis,msi,dmg}/
# CI: push a tag (git tag v0.1.0 && git push origin v0.1.0) -> .github/workflows/release.yml
```

## Guardrails

- Never commit API keys or `.env`. Cloud credentials live in OS keychain / user config, not source.
- `ffmpeg` and `yt-dlp` are external runtime dependencies — detect them at startup and warn if missing; do not bundle without checking licensing.
- Respect the fallback contract: a missing local engine is a warning, not a crash.
- Long-running work goes through the resumable-job layer, not ad-hoc scripts.
