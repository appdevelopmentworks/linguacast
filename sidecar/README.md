# linguacast sidecar

Python + FastAPI sidecar that owns the heavy AI compute for linguacast (STT,
translation, summarization, TTS orchestration, dub sync). Managed with `uv`.

The Rust core spawns this process on a free loopback port and health-checks
`GET /health` before use. Heavy dependencies (torch/CUDA, faster-whisper, etc.)
are deferred and installed lazily in later sessions.

## Run standalone

```bash
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8756
# then: curl http://127.0.0.1:8756/health
```
