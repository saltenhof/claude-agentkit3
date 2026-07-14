"""Bounded thread execution for long-running installer operations."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class BoundedThreadExecutor:
    """Thread executor with a hard cap on running plus queued work."""

    def __init__(self, *, max_workers: int = 2, max_queued: int = 2) -> None:
        self._slots = threading.BoundedSemaphore(max_workers + max_queued)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="third-party-self-test",
        )

    def submit(self, fn: Callable[[], None]) -> Future[None]:
        """Submit work or fail immediately when bounded capacity is exhausted."""
        if not self._slots.acquire(blocking=False):
            raise RuntimeError("third-party self-test capacity exhausted")
        try:
            future = self._executor.submit(fn)
        except RuntimeError:
            self._slots.release()
            raise
        future.add_done_callback(lambda _future: self._slots.release())
        return future


__all__ = ["BoundedThreadExecutor"]
