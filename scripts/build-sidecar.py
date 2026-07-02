#!/usr/bin/env python3
"""Build the sidecar into a single-file binary and place it in src-tauri/binaries.

The packaged sidecar is the cloud/Edge build: faster-whisper and CUDA are
excluded (distributed users transcribe via Groq). Run before `tauri build`:

    uv run --directory sidecar --with pyinstaller python ../scripts/build-sidecar.py

CI does the same. Cross-platform (Windows .exe / macOS+Linux no extension).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIDECAR = ROOT / "sidecar"
OUT_DIR = ROOT / "src-tauri" / "binaries"
BIN_NAME = "linguacast-sidecar.exe" if sys.platform == "win32" else "linguacast-sidecar"

EXCLUDES = [
    "faster_whisper",
    "ctranslate2",
    "torch",
    "onnxruntime",
    "nvidia",
    "transformers",
    "tokenizers",
    "av",
    "numpy",
]


def main() -> None:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SIDECAR / "run_sidecar.py"),
        "--name", "linguacast-sidecar",
        "--onefile", "--noconfirm", "--clean",
        "--distpath", str(SIDECAR / "dist"),
        "--workpath", str(SIDECAR / "build"),
        "--specpath", str(SIDECAR),
        "--paths", str(SIDECAR),
        "--collect-submodules", "app",
        "--collect-all", "uvicorn",
        "--collect-all", "edge_tts",
        "--collect-submodules", "openai",
        "--collect-submodules", "fastapi",
        "--collect-submodules", "starlette",
    ]  # fmt: skip
    for mod in EXCLUDES:
        cmd += ["--exclude-module", mod]

    print("building sidecar:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(SIDECAR))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    src = SIDECAR / "dist" / BIN_NAME
    dst = OUT_DIR / BIN_NAME
    shutil.copy2(src, dst)
    print(f"placed {dst} ({os.path.getsize(dst) / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
