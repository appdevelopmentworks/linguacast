"""In-memory progress registry for long-running stage calls.

Stage services update it per work unit (segment/block/line); the Rust core
polls ``GET /progress/{task_id}`` while awaiting the main request and emits
percent events to the UI.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_tasks: dict[str, dict] = {}
_TTL_SEC = 3600.0


def update(
    task_id: str | None, stage: str, done: float, total: float, detail: str | None = None
) -> None:
    """Record progress; no-op when the caller did not request tracking.

    ``detail`` names the RESOLVED backend (tier/model/engine) so the UI shows
    what is actually running, not the preferred setting.
    """
    if not task_id:
        return
    now = time.time()
    with _lock:
        _tasks[task_id] = {
            "stage": stage,
            "done": done,
            "total": total,
            "detail": detail,
            "ts": now,
        }
        stale = [k for k, v in _tasks.items() if v["ts"] < now - _TTL_SEC]
        for k in stale:
            del _tasks[k]


def get(task_id: str) -> dict | None:
    with _lock:
        entry = _tasks.get(task_id)
        return dict(entry) if entry else None
