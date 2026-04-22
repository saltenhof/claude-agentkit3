"""Runtime helpers for reading and refreshing local project-edge state."""

from __future__ import annotations

import json
import os
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from agentkit.config.loader import load_project_config
from agentkit.control_plane.models import (
    EdgeBundle,
    EdgePointer,
    ProjectEdgeSyncRequest,
)
from agentkit.projectedge.client import (
    HttpsJsonTransport,
    LocalEdgePublisher,
    ProjectEdgeClient,
)

if TYPE_CHECKING:
    from collections.abc import Callable

FreshnessClass = Literal["baseline_read", "guarded_read", "mutation"]
OperatingMode = Literal["ai_augmented", "story_execution", "binding_invalid"]
_SYNC_LOCK_STALE_AFTER = timedelta(seconds=30)


@dataclass(frozen=True)
class ResolvedEdgeState:
    """Resolved local execution state for one hook invocation."""

    operating_mode: OperatingMode
    bundle: EdgeBundle | None
    block_reason: str | None = None
    synced: bool = False


def build_project_edge_client(project_root: Path) -> ProjectEdgeClient:
    """Construct a configured project-edge client from local project config."""
    config = json.loads(
        (
            project_root / ".agentkit" / "config" / "control-plane.json"
        ).read_text(encoding="utf-8"),
    )
    cafile = config.get("ca_file")
    ssl_context = ssl.create_default_context(cafile=cafile) if cafile else None
    return ProjectEdgeClient(
        transport=HttpsJsonTransport(
            base_url=str(config["base_url"]),
            ssl_context=ssl_context,
        ),
        publisher=LocalEdgePublisher(project_root=project_root),
    )


class ProjectEdgeResolver:
    """Resolve operating mode from the locally materialized edge bundle."""

    def __init__(
        self,
        *,
        project_root: Path,
        client_factory: Callable[[Path], ProjectEdgeClient] = build_project_edge_client,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._project_root = project_root
        self._client_factory = client_factory
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    def resolve(
        self,
        *,
        session_id: str | None,
        cwd: str | Path,
        freshness_class: FreshnessClass,
    ) -> ResolvedEdgeState:
        """Resolve current operating mode for the given hook context."""
        bundle = self.load_current_bundle()
        synced = False
        if self._needs_sync(bundle, freshness_class) and session_id:
            bundle = self._bounded_sync(
                session_id=session_id,
                freshness_class=freshness_class,
            )
            synced = bundle is not None

        if bundle is None:
            return ResolvedEdgeState(operating_mode="ai_augmented", bundle=None)

        session = bundle.session
        if session is None:
            return ResolvedEdgeState(
                operating_mode="ai_augmented",
                bundle=bundle,
                synced=synced,
            )

        if session_id is None or session.session_id != session_id:
            return ResolvedEdgeState(
                operating_mode="binding_invalid",
                bundle=bundle,
                block_reason="session_binding_mismatch",
                synced=synced,
            )

        if bundle.lock.status != "ACTIVE":
            return ResolvedEdgeState(
                operating_mode="binding_invalid",
                bundle=bundle,
                block_reason="inactive_story_execution_lock",
                synced=synced,
            )

        if not _cwd_matches_worktree(Path(cwd), session.worktree_roots):
            return ResolvedEdgeState(
                operating_mode="binding_invalid",
                bundle=bundle,
                block_reason="worktree_root_mismatch",
                synced=synced,
            )

        return ResolvedEdgeState(
            operating_mode="story_execution",
            bundle=bundle,
            synced=synced,
        )

    def load_current_bundle(self) -> EdgeBundle | None:
        """Load the current local edge bundle if one is published."""
        pointer = self._load_current_pointer()
        if pointer is None:
            return None
        bundle_root = self._project_root / pointer.bundle_dir
        session_path = bundle_root / "session.json"
        lock_path = bundle_root / "lock.json"
        if not lock_path.is_file():
            return None
        session_payload = _load_json(session_path) if session_path.is_file() else None
        if session_payload is not None and "session_id" not in session_payload:
            session_payload = None
        lock_payload = _load_json(lock_path)
        return EdgeBundle.model_validate(
            {
                "current": pointer.model_dump(mode="json"),
                "session": session_payload,
                "lock": lock_payload,
                "tombstone_worktree_roots": [],
            },
        )

    def _load_current_pointer(self) -> EdgePointer | None:
        current_path = self._project_root / "_temp" / "governance" / "current.json"
        if not current_path.is_file():
            return None
        return EdgePointer.model_validate(_load_json(current_path))

    def _needs_sync(
        self,
        bundle: EdgeBundle | None,
        freshness_class: FreshnessClass,
    ) -> bool:
        if bundle is None:
            return freshness_class != "baseline_read"
        if freshness_class == "baseline_read":
            return False
        return bundle.current.sync_after <= self._now_provider()

    def _bounded_sync(
        self,
        *,
        session_id: str,
        freshness_class: FreshnessClass,
    ) -> EdgeBundle | None:
        lock_path = self._project_root / "_temp" / "governance" / "sync.lock"
        if not _acquire_sync_lock(lock_path, now=self._now_provider()):
            return self.load_current_bundle()
        try:
            project_config = load_project_config(self._project_root)
            client = self._client_factory(self._project_root)
            result = client.sync(
                ProjectEdgeSyncRequest(
                    project_key=project_config.project_key,
                    session_id=session_id,
                    freshness_class=freshness_class,
                ),
            )
            return result.edge_bundle
        except Exception:
            return self.load_current_bundle()
        finally:
            if lock_path.exists():
                lock_path.unlink()


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object in {path}")
    return payload


def _cwd_matches_worktree(cwd: Path, worktree_roots: list[str]) -> bool:
    cwd_resolved = cwd.resolve()
    for root in worktree_roots:
        try:
            root_path = Path(root).resolve()
            cwd_resolved.relative_to(root_path)
            return True
        except ValueError:
            continue
    return False


def _acquire_sync_lock(lock_path: Path, *, now: datetime) -> bool:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            payload = _load_json(lock_path)
            acquired_at = datetime.fromisoformat(str(payload["acquired_at"]))
        except Exception:
            acquired_at = now - _SYNC_LOCK_STALE_AFTER - timedelta(seconds=1)
        if acquired_at + _SYNC_LOCK_STALE_AFTER > now:
            return False
        lock_path.unlink(missing_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"acquired_at": now.isoformat()}, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    return True


__all__ = [
    "FreshnessClass",
    "OperatingMode",
    "ProjectEdgeResolver",
    "ResolvedEdgeState",
    "build_project_edge_client",
]
