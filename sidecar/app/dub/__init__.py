"""Dub sync: place per-segment audio at SRT timestamps and fit durations.

speedScale clamp (~0.8-1.3) + ffmpeg rubberband time-stretch + absorb residual
into adjacent silence, then mux into the source video. Implemented in Session 6.
"""
