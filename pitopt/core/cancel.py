"""
Cooperative cancellation (PRD F-RUN-4).

A long computation checks a token at points where stopping is safe and
raises `Cancelled` there; nothing is killed from outside, so no thread dies
holding a half-written file. The caller decides what to do with the partial
work — the UI discards it and leaves the previous result untouched.
"""
from __future__ import annotations

import threading


class Cancelled(Exception):
    """The user stopped the computation."""


class CancelToken:
    def __init__(self) -> None:
        self._stop = threading.Event()

    def cancel(self) -> None:
        self._stop.set()

    @property
    def cancelled(self) -> bool:
        return self._stop.is_set()

    def check(self) -> None:
        """Raise `Cancelled` if a stop was requested. Call it where the state is consistent."""
        if self._stop.is_set():
            raise Cancelled()
