"""
tick_bus.py — lightweight pub/sub for SSE tick notifications.

Both app.py (subscriber) and scheduler.py (publisher) import from here
to avoid circular imports.
"""
import json
import queue
import threading
from typing import Any

_subscribers: list[queue.Queue] = []
_lock = threading.Lock()


def subscribe() -> "queue.Queue[str]":
    """Register a new SSE listener; returns its queue."""
    q: queue.Queue = queue.Queue(maxsize=32)
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: "queue.Queue[str]") -> None:
    with _lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


def notify_tick(payload: dict[str, Any]) -> None:
    """Called by scheduler after each tick completes."""
    msg = json.dumps(payload)
    with _lock:
        for q in list(_subscribers):
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass  # slow client — skip rather than block
