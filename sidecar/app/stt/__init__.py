"""Speech-to-text adapters behind one ``transcribe()`` interface.

OS-dispatched backends (CLAUDE.md gotcha #8):
- Windows/NVIDIA: faster-whisper (CTranslate2/CUDA)
- macOS/Apple Silicon: mlx-whisper (MLX) or whisper.cpp (Metal)

VAD filtering suppresses silence/music hallucination. Implemented in Session 2.
"""
