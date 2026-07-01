"""linguacast FastAPI sidecar entrypoint.

Owns heavy compute (STT, translation, summarization, TTS, dub). The Rust core
spawns this process and health-checks ``GET /health`` before using it.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

SERVICE_NAME = "linguacast-sidecar"
VERSION = "0.1.0"

app = FastAPI(title=SERVICE_NAME, version=VERSION)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe consumed by the Rust core."""
    return HealthResponse(status="ok", service=SERVICE_NAME, version=VERSION)
