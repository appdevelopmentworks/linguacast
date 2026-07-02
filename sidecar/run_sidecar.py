"""PyInstaller entry point for the packaged sidecar.

Frozen builds cannot use `uvicorn app.main:app` (a module string) — this script
starts uvicorn programmatically with the same --host/--port the Rust core
passes. Local faster-whisper is intentionally NOT bundled; packaged builds use
Groq (cloud) for STT.
"""

from __future__ import annotations

import argparse

import uvicorn

from app.main import app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8756)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
