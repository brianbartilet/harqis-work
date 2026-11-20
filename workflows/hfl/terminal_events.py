"""Local wakeups; SQLite remains authoritative across frontend processes."""
import threading
import asyncio
from contextlib import contextmanager

_lock = threading.Lock()
_listeners = {}


def notify(identity):
    with _lock:
        for loop, event in _listeners.get(identity, ()):
            if loop is None:
                event.set()
            elif not loop.is_closed():
                loop.call_soon_threadsafe(event.set)


@contextmanager
def subscribe(identity, *, loop=None):
    event = threading.Event() if loop is None else asyncio.Event()
    listener = (loop, event)
    with _lock:
        _listeners.setdefault(identity, set()).add(listener)
    try:
        yield event
    finally:
        with _lock:
            _listeners[identity].discard(listener)
            if not _listeners[identity]:
                del _listeners[identity]
