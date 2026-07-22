"""Process-wide single-writer lock for VectorDB sync (AG3-174 R05 / AC 6).

Uses a project-contained advisory file lock so independent Engine instances
and separate CLI/MCP processes serialise on the same ``(project_id, producer)``
key. Fail-closed when the lock cannot be acquired within the timeout.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class SingleWriterError(Exception):
    """Raised when the single-writer lock cannot be acquired (fail-closed)."""


@dataclass(frozen=True)
class SingleWriterKey:
    """Lock identity."""

    project_id: str
    producer_tool: str


@contextmanager
def single_writer_lock(
    *,
    lock_dir: Path,
    project_id: str,
    producer_tool: str,
    timeout_seconds: float = 30.0,
    poll_seconds: float = 0.05,
) -> Iterator[None]:
    """Acquire an exclusive file lock for ``(project_id, producer_tool)``.

    The lock file is created under ``lock_dir`` which must already sit inside
    the project containment boundary.
    """
    lock_dir.mkdir(parents=True, exist_ok=True)
    safe_project = "".join(c if c.isalnum() or c in "-_" else "_" for c in project_id)
    safe_producer = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in producer_tool
    )
    lock_path = lock_dir / f"vectordb_sync_{safe_project}_{safe_producer}.lock"
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    handle = None
    while True:
        try:
            handle = open(lock_path, "a+b")  # noqa: SIM115
            _lock_exclusive(handle)
            handle.seek(0)
            handle.truncate()
            handle.write(f"{os.getpid()}\n".encode("ascii"))
            handle.flush()
            break
        except OSError:
            if handle is not None:
                with suppress(OSError):
                    handle.close()
                handle = None
            if time.monotonic() >= deadline:
                raise SingleWriterError(
                    f"could not acquire single-writer lock for "
                    f"({project_id!r}, {producer_tool!r}) within "
                    f"{timeout_seconds}s (fail-closed, AC 6 / R05)."
                ) from None
            time.sleep(poll_seconds)
    try:
        yield
    finally:
        if handle is not None:
            try:
                _unlock(handle)
            finally:
                handle.close()


def _lock_exclusive(handle: object) -> None:
    """Platform exclusive lock."""
    if os.name == "nt":
        import msvcrt  # noqa: PLC0415

        # Lock one byte at start of file.
        handle.seek(0)  # type: ignore[attr-defined]
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        except OSError as exc:
            raise OSError("lock busy") from exc
    else:
        import fcntl  # noqa: PLC0415

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]


def _unlock(handle: object) -> None:
    if os.name == "nt":
        import msvcrt  # noqa: PLC0415

        try:
            handle.seek(0)  # type: ignore[attr-defined]
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        except OSError:
            pass
    else:
        import contextlib
        import fcntl  # noqa: PLC0415

        with contextlib.suppress(OSError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


__all__ = [
    "SingleWriterError",
    "SingleWriterKey",
    "single_writer_lock",
]
