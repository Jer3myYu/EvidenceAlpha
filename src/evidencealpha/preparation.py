"""Cooperative cancellation and deadlines for original-evidence preparation."""

import contextlib
import threading
import time
import typing

_ACTIVE: set[threading.Event] = set()
_LOCK = threading.Lock()


class Stopped(RuntimeError):
    """Preparation stopped before admission to a scorer."""


def noop() -> None:
    """Allow ordinary source readers without a retrieval deadline."""


def cancel_all() -> None:
    """Signal only currently registered preparation operations."""
    with _LOCK:
        for event in _ACTIVE:
            event.set()


@contextlib.contextmanager
def guard(
    deadline: float, cancelled: threading.Event
) -> typing.Iterator[typing.Callable[[], None]]:
    """Register cancellation before any source or context work starts."""

    def check() -> None:
        if cancelled.is_set():
            raise Stopped("reranker_cancelled")
        if time.monotonic() >= deadline:
            raise Stopped("reranker_deadline")

    with _LOCK:
        _ACTIVE.add(cancelled)
    try:
        check()
        yield check
    finally:
        with _LOCK:
            _ACTIVE.discard(cancelled)
