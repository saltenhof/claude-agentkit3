"""Lifecycle-owned VectorDB sync task registry (AG3-176 R7 / FK-13 §13.7).

Closure submits story_sync work here and receives a task_id. Status and errors
remain observable; drain/shutdown is explicit. Not a lost daemon fire-and-forget.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)


class SyncTaskStatus(StrEnum):
    """Observable task status."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class SyncTaskRecord:
    """One submitted sync task."""

    task_id: str
    status: SyncTaskStatus
    error: str | None = None
    future: Future[None] | None = field(default=None, repr=False)


class SyncTaskRegistry:
    """Process-local registry with a non-daemon worker pool."""

    def __init__(self, *, max_workers: int = 2) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, SyncTaskRecord] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="agentkit-vectordb-sync",
        )
        self._closed = False

    def submit(self, work: Callable[[], None]) -> str:
        """Queue ``work``; return task_id after successful handoff."""
        with self._lock:
            if self._closed:
                raise RuntimeError("SyncTaskRegistry is shut down")
            task_id = uuid.uuid4().hex
            record = SyncTaskRecord(task_id=task_id, status=SyncTaskStatus.QUEUED)
            self._tasks[task_id] = record

        def _runner() -> None:
            with self._lock:
                rec = self._tasks.get(task_id)
                if rec is not None:
                    rec.status = SyncTaskStatus.RUNNING
            try:
                work()
            except Exception as exc:  # noqa: BLE001 -- record observably
                logger.warning("VectorDB sync task %s failed: %s", task_id, exc)
                with self._lock:
                    rec = self._tasks.get(task_id)
                    if rec is not None:
                        rec.status = SyncTaskStatus.FAILED
                        rec.error = f"{type(exc).__name__}: {exc}"
                return
            with self._lock:
                rec = self._tasks.get(task_id)
                if rec is not None:
                    rec.status = SyncTaskStatus.SUCCEEDED

        future = self._executor.submit(_runner)
        with self._lock:
            self._tasks[task_id].future = future
        return task_id

    def status(self, task_id: str) -> SyncTaskRecord | None:
        with self._lock:
            rec = self._tasks.get(task_id)
            if rec is None:
                return None
            return SyncTaskRecord(
                task_id=rec.task_id,
                status=rec.status,
                error=rec.error,
                future=None,
            )

    def drain(self, *, timeout: float | None = None) -> None:
        """Wait for outstanding tasks (test/shutdown helper)."""
        with self._lock:
            futures = [t.future for t in self._tasks.values() if t.future is not None]
        for fut in futures:
            with contextlib.suppress(Exception):
                fut.result(timeout=timeout)

    def shutdown(self, *, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=not wait)


_GLOBAL_REGISTRY: SyncTaskRegistry | None = None
_GLOBAL_LOCK = threading.Lock()


def get_sync_task_registry() -> SyncTaskRegistry:
    """Return the process-global registry (created on first use)."""
    global _GLOBAL_REGISTRY
    with _GLOBAL_LOCK:
        if _GLOBAL_REGISTRY is None:
            _GLOBAL_REGISTRY = SyncTaskRegistry()
        return _GLOBAL_REGISTRY


def reset_sync_task_registry_for_tests() -> SyncTaskRegistry:
    """Replace the global registry (unit tests only)."""
    global _GLOBAL_REGISTRY
    with _GLOBAL_LOCK:
        if _GLOBAL_REGISTRY is not None:
            _GLOBAL_REGISTRY.shutdown(wait=False)
        _GLOBAL_REGISTRY = SyncTaskRegistry()
        return _GLOBAL_REGISTRY


def run_story_sync_work(project_root: Path) -> None:
    """Productive story_sync body submitted to the registry."""
    from agentkit.backend.vectordb.ingest.engine import IngestEngine
    from agentkit.backend.vectordb.project_binding import bind_project
    from agentkit.backend.vectordb.schema import ensure_story_context_schema
    from agentkit.integration_clients.vectordb import WeaviateStoryAdapter

    binding = bind_project(project_root)
    vdb = binding.config.pipeline.vectordb
    if vdb is None or not vdb.host or vdb.port is None:
        raise RuntimeError("pipeline.vectordb host/port missing for story_sync")
    adapter = WeaviateStoryAdapter.connect(
        host=vdb.host,
        port=int(vdb.port),
        grpc_port=int(vdb.grpc_port) if vdb.grpc_port else None,
    )
    try:
        ensure_story_context_schema(adapter.raw_client)
        engine = IngestEngine(
            adapter,
            lock_dir=binding.project_root / ".agentkit" / "vectordb" / "locks",
        )
        engine.story_sync(binding, full_reindex=False)
    finally:
        adapter.close()


__all__ = [
    "SyncTaskRecord",
    "SyncTaskRegistry",
    "SyncTaskStatus",
    "get_sync_task_registry",
    "reset_sync_task_registry_for_tests",
    "run_story_sync_work",
]
