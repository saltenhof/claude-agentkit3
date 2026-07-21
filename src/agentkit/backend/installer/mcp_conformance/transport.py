"""Bounded stdio line pumps for MCP conformance (AG3-164).

Blutgruppe T: stream I/O only. Uses binary pipes so ``read(n)`` returns
available data without waiting for a full buffer. stdout is capacity-bounded
and UTF-8-strict; stderr is drain-only with a fixed tail buffer.
"""

from __future__ import annotations

import contextlib
import queue
import threading
from typing import IO, Final

from agentkit.backend.installer.mcp_conformance.types import (
    MAX_FRAME_BYTES,
    MAX_PENDING_STDOUT_MESSAGES,
    STDERR_DETAIL_CHARS,
    McpConformanceReason,
    TransportError,
)

_READ_CHUNK: Final = 4096


class StdoutLinePump:
    """Single-threaded binary stdout reader with frame and pending-message limits."""

    def __init__(self, stream: IO[bytes], *, name: str = "mcp-stdout") -> None:
        self._stream = stream
        self._queue: queue.Queue[str | None | TransportError] = queue.Queue(
            maxsize=MAX_PENDING_STDOUT_MESSAGES
        )
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._started = False
        self._overflow = False

    def start(self) -> None:
        self._started = True
        self._thread.start()

    def _run(self) -> None:
        buffer = bytearray()
        try:
            while True:
                try:
                    chunk = self._stream.read(_READ_CHUNK)
                except (OSError, ValueError) as exc:
                    self._safe_put(
                        TransportError(
                            McpConformanceReason.PROCESS_EXITED,
                            f"stdout reader failed: {exc}.",
                        )
                    )
                    return
                if not chunk:
                    if buffer and not self._overflow:
                        self._emit_line(bytes(buffer))
                    self._safe_put(None)
                    return
                if self._overflow:
                    continue
                buffer.extend(chunk)
                while True:
                    nl = buffer.find(b"\n")
                    if nl < 0:
                        if len(buffer) > MAX_FRAME_BYTES:
                            self._safe_put(
                                TransportError(
                                    McpConformanceReason.PROTOCOL_ERROR,
                                    f"MCP stdout frame exceeds {MAX_FRAME_BYTES} bytes.",
                                )
                            )
                            self._overflow = True
                            buffer.clear()
                        break
                    line = bytes(buffer[: nl + 1])
                    del buffer[: nl + 1]
                    if not self._emit_line(line):
                        buffer.clear()
                        break
        except BaseException as exc:  # noqa: BLE001 — surface to consumer
            self._safe_put(
                TransportError(
                    McpConformanceReason.PROTOCOL_ERROR,
                    f"stdout pump internal fault: {exc}.",
                )
            )

    def _emit_line(self, line: bytes) -> bool:
        if len(line) > MAX_FRAME_BYTES:
            self._safe_put(
                TransportError(
                    McpConformanceReason.PROTOCOL_ERROR,
                    f"MCP stdout frame exceeds {MAX_FRAME_BYTES} bytes.",
                )
            )
            self._overflow = True
            return False
        # Strict UTF-8: invalid wire bytes are protocol errors (no U+FFFD repair).
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            self._safe_put(
                TransportError(
                    McpConformanceReason.PROTOCOL_ERROR,
                    f"MCP stdout is not valid UTF-8: {exc}.",
                )
            )
            self._overflow = True
            return False
        return self._safe_put(text)

    def _safe_put(self, item: str | None | TransportError) -> bool:
        if self._overflow and not isinstance(item, TransportError) and item is not None:
            return False
        try:
            self._queue.put(item, timeout=0.05)
            return True
        except queue.Full:
            self._overflow = True
            with self._queue.mutex:
                self._queue.queue.clear()
            with contextlib.suppress(queue.Full):
                self._queue.put_nowait(
                    TransportError(
                        McpConformanceReason.PROTOCOL_ERROR,
                        f"MCP stdout pending-message capacity "
                        f"({MAX_PENDING_STDOUT_MESSAGES}) exceeded.",
                    )
                )
            return False

    def readline(self, *, timeout: float) -> str | None:
        """Return one line, ``None`` on EOF; empty string = no line yet."""
        if timeout <= 0:
            raise TransportError(McpConformanceReason.TIMEOUT, "readline timeout exhausted")
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return ""
        if item is None:
            return None
        if isinstance(item, TransportError):
            raise item
        return item

    def join(self, *, timeout: float) -> None:
        if self._started and timeout > 0:
            self._thread.join(timeout=timeout)


class StderrDrainPump:
    """Drain-only binary stderr reader with a fixed-size **tail** buffer.

    Large single writes keep their trailing ``STDERR_DETAIL_CHARS`` bytes rather
    than being dropped wholesale when the ring overflows.
    """

    def __init__(self, stream: IO[bytes], *, name: str = "mcp-stderr") -> None:
        self._stream = stream
        self._tail = bytearray()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._started = False

    def start(self) -> None:
        self._started = True
        self._thread.start()

    def _run(self) -> None:
        try:
            while True:
                try:
                    chunk = self._stream.read(_READ_CHUNK)
                except (OSError, ValueError):
                    return
                if not chunk:
                    return
                with self._lock:
                    self._tail.extend(chunk)
                    if len(self._tail) > STDERR_DETAIL_CHARS:
                        # Keep only the trailing detail bytes.
                        self._tail[:] = self._tail[-STDERR_DETAIL_CHARS:]
        except BaseException:  # noqa: BLE001
            return

    def retained_text(self) -> str:
        with self._lock:
            raw = bytes(self._tail)
        # Best-effort for diagnostics only; may replace if stderr is binary noise.
        return raw.decode("utf-8", errors="replace").strip().replace("\r\n", "\n")

    def join(self, *, timeout: float) -> None:
        if self._started and timeout > 0:
            self._thread.join(timeout=timeout)


__all__ = ["StderrDrainPump", "StdoutLinePump"]
