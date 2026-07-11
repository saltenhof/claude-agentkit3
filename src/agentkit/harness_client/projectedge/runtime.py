"""Runtime helpers for reading and refreshing local project-edge state."""

from __future__ import annotations

import json
import os
import ssl
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from agentkit.backend.config.loader import load_project_config
from agentkit.backend.control_plane.models import (
    EdgeBundle,
    EdgeFreezeStateView,
    EdgePointer,
    ProjectEdgeSyncRequest,
)
from agentkit.backend.control_plane.ownership import (
    canonical_binding_revocation_reason,
)

# RE-IMPORT the canonical FK-56 operating-mode literal from its SINGLE foundation
# definition (``core_types.operating_mode``). This R-boundary CLASSIFIES the mode
# (``ProjectEdgeResolver`` reads the persisted bundle and decides) but does NOT
# redeclare the type -- there is exactly ONE definition, so no drift (AK2 SSOT).
# Re-exported in ``__all__`` for the named ``operating_mode_resolver`` A-core seam.
from agentkit.backend.core_types.operating_mode import OperatingMode
from agentkit.harness_client.projectedge.client import (
    HttpsJsonTransport,
    LocalEdgePublisher,
    ProjectEdgeClient,
)

if TYPE_CHECKING:
    from collections.abc import Callable

FreshnessClass = Literal["baseline_read", "guarded_read", "mutation"]
#: Tri-state result of resolving the persisted exploration change-frame freeze
#: state (FK-23 §23.4.3, AG3-047):
#:
#: * ``"absent"``  -- no change-frame file persisted yet: the frame is editable
#:   (known, NOT frozen) -- the legitimate pre-freeze worker-draft state
#:   (FK-25 §25.4.2);
#: * ``"frozen"``  -- the persisted frame carries ``frozen: true``;
#: * ``"editable"`` -- the persisted frame exists and carries ``frozen: false``;
#: * ``"unreadable"`` -- the file exists but cannot be read / parsed (an ERROR,
#:   not an absence): the freeze state is UNKNOWN and the guard fails closed.
ChangeFrameFreezeState = Literal["absent", "frozen", "editable", "unreadable"]
_SYNC_LOCK_STALE_AFTER = timedelta(seconds=30)


def read_change_frame_freeze_state(change_frame_path: Path) -> ChangeFrameFreezeState:
    """Resolve the persisted change-frame freeze state from its file (FK-23 §23.4.3).

    The exploration worker / freeze marker materializes
    ``_temp/qa/{story_id}/change_frame.json``; this boundary reader inspects that
    file's ``frozen`` flag so the productive guard-context builder can key the
    change-frame protection on the PERSISTED freeze state (AG3-047). It is the
    R-boundary FS read for the bloodgroup-A ``guard_evaluation`` core (which owns
    the path policy and passes the concrete path in).

    Fail-closed (ZERO DEBT): ONLY an absent file is the legitimate pre-freeze
    editable state (``"absent"``). Anything that is present but whose freeze
    state cannot be read UNAMBIGUOUSLY is an ERROR, returned as ``"unreadable"``
    so the guard blocks the write rather than treating an unknown state as "not
    frozen". That includes: a path that exists but is not a regular file (e.g. a
    directory), garbage / non-object JSON, and a ``frozen`` field that is missing
    or not a real boolean (``{}`` / ``{"frozen": null}`` / ``{"frozen": "true"}``
    must NOT be silently read as editable). Only an explicit ``frozen: false``
    is ``"editable"``; only an explicit ``frozen: true`` is ``"frozen"``.

    Args:
        change_frame_path: Absolute path of the story's ``change_frame.json``.

    Returns:
        The :data:`ChangeFrameFreezeState` tri-state (+ ``"unreadable"`` error
        state).
    """
    if not change_frame_path.exists():
        return "absent"
    if not change_frame_path.is_file():
        # Present but not a regular file (e.g. a directory) -> unknown.
        return "unreadable"
    try:
        payload = _load_json(change_frame_path)
    except (OSError, ValueError, RuntimeError):
        # Present but unreadable/garbage -> unknown freeze state (fail-closed).
        return "unreadable"
    if not isinstance(payload, dict):
        return "unreadable"
    frozen = payload.get("frozen")
    if frozen is True:
        return "frozen"
    if frozen is False:
        return "editable"
    # Present but the freeze flag is missing / not a real bool -> unknown.
    return "unreadable"


@dataclass(frozen=True)
class ResolvedEdgeState:
    """Resolved local execution state for one hook invocation."""

    operating_mode: OperatingMode
    bundle: EdgeBundle | None
    block_reason: str | None = None
    new_owner_ref: str | None = None
    synced: bool = False


#: Project-pinned prompt-bundle lock (FK-43/FK-44), the authoritative local
#: source of the bound skill-bundle version surfaced in the version handshake.
_PROMPT_BUNDLE_LOCK_RELPATH = Path(".agentkit") / "config" / "prompt-bundle.lock.json"
_PROJECT_API_TOKEN_ENV = "AGENTKIT_PROJECT_API_TOKEN"


def _read_bound_skill_bundle_version(project_root: Path) -> str | None:
    """Read the bound skill-bundle version from the project prompt-bundle lock.

    The version is the ``X-AK3-Skill-Bundle`` handshake value (FK-91 §91.1a Rule
    11). The lock owned by ``prompt_runtime`` is the SINGLE source of truth; this
    only mirrors it onto the wire. Returns ``None`` when no readable lock is
    present so the core can fail the request closed at mutating endpoints rather
    than the client inventing a bundle version.
    """
    lock_path = project_root / _PROMPT_BUNDLE_LOCK_RELPATH
    if not lock_path.is_file():
        return None
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    bundle_version = payload.get("bundle_version")
    if isinstance(bundle_version, str) and bundle_version:
        return bundle_version
    return None


def read_bound_skill_bundle_version(project_root: Path) -> str | None:
    """Public accessor for the bound skill-bundle version (AG3-130 handshake).

    The operator CLI (``run-phase`` / ``resume``) is a Dev->Core mutation surface
    and must carry the ``X-AK3-Skill-Bundle`` version handshake header (FK-91
    §91.1a Rule 11). It resolves the value from the SAME authoritative
    prompt-bundle lock as the worker edge, never inventing a version; ``None`` when
    no readable lock is present (the core then fails the mutation closed).
    """
    return _read_bound_skill_bundle_version(project_root)


def build_project_edge_client(project_root: Path) -> ProjectEdgeClient:
    """Construct a configured project-edge client from local project config."""
    project_config = load_project_config(project_root)
    config = json.loads(
        (project_root / ".agentkit" / "config" / "control-plane.json").read_text(encoding="utf-8"),
    )
    cafile = config.get("ca_file")
    ssl_context = ssl.create_default_context(cafile=cafile) if cafile else None
    return ProjectEdgeClient(
        transport=HttpsJsonTransport(
            base_url=str(config["base_url"]),
            ssl_context=ssl_context,
            skill_bundle_version=_read_bound_skill_bundle_version(project_root),
            bearer_token=os.environ.get(_PROJECT_API_TOKEN_ENV),
            project_key=project_config.project_key,
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

        if session.status == "revoked":
            # AG3-142 (SOLL-034 behavior, FK-56 §56.7a/§56.13c): a revoked
            # binding is deterministically ``binding_invalid`` -- NEVER a
            # silent fall-back to ``ai_augmented``. The reason is an attribute
            # of the revoked binding, not a status per cause: a known reason
            # (e.g. ``ownership_transferred``) is surfaced verbatim; a missing
            # (malformed/legacy) reason still fails closed to ``binding_invalid``
            # with a generic reason, never treated as "not revoked".
            reason = canonical_binding_revocation_reason(session.revocation_reason) if session_id == session.session_id else None
            return ResolvedEdgeState(
                operating_mode="binding_invalid",
                bundle=bundle,
                block_reason=reason or "session_binding_mismatch",
                new_owner_ref=(session.new_owner_ref if reason == "ownership_transferred" else None),
                synced=synced,
            )

        if session_id is None or session.session_id != session_id:
            return ResolvedEdgeState(
                operating_mode="binding_invalid",
                bundle=bundle,
                block_reason="session_binding_mismatch",
                synced=synced,
            )

        if bundle.lock is None or bundle.lock.status != "ACTIVE":
            # Fail-closed: a session-bound bundle MUST carry an ACTIVE
            # story_execution lock. A missing lock here (only legitimate for a
            # fast, session-less bundle handled above) means a bound run without
            # an authoritative lock -> binding_invalid, never story_execution.
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

        return _resolve_freeze_or_story_execution(bundle, synced=synced)

    def load_current_bundle(self) -> EdgeBundle | None:
        """Load the current local edge bundle if one is published."""
        pointer = self._load_current_pointer()
        if pointer is None:
            return None
        bundle_root = self._project_root / pointer.bundle_dir
        session_path = bundle_root / "session.json"
        lock_path = bundle_root / "lock.json"
        qa_lock_path = bundle_root / "qa-lock.json"
        session_payload = _load_json(session_path) if session_path.is_file() else None
        if session_payload is not None and "session_id" not in session_payload:
            session_payload = None
        # FAIL-CLOSED (invalid_bound_session_must_not_fall_back_to_free_mode):
        # the presence of a BOUND bundle is decided by the SESSION, never by
        # lock.json. A missing lock.json must NOT early-return None (that would
        # silently downgrade a bound session to ai_augmented/free mode). Set
        # ``lock_payload = None`` when absent and still return an EdgeBundle; the
        # classification then lives in ``resolve()``:
        #   session != None && lock == None -> binding_invalid (corrupt bound run)
        #   session == None && lock == None -> ai_augmented (the intended FAST bundle)
        #   session != None && lock != None -> story_execution (standard)
        lock_payload = _load_json(lock_path) if lock_path.is_file() else None
        qa_lock_payload = _load_json(qa_lock_path) if qa_lock_path.is_file() else None
        freeze_payload, freezes_readable = _load_freeze_projection(bundle_root / "freeze.json")
        return EdgeBundle.model_validate(
            {
                "current": pointer.model_dump(mode="json"),
                "session": session_payload,
                "lock": lock_payload,
                "qa_lock": qa_lock_payload,
                "tombstone_worktree_roots": [],
                "active_freezes": freeze_payload,
                "active_freezes_readable": freezes_readable,
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
                    # FK-91 §91.1a Rule 5 (AG3-140): the bounded sync is a
                    # client caller -- it mints its own op_id (the server no
                    # longer supplies a default).
                    op_id=f"op-{uuid.uuid4().hex}",
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


def _load_freeze_projection(path: Path) -> tuple[list[dict[str, object]], bool]:
    """Load the local freeze projection, preserving unreadable as blocking state."""
    if not path.is_file():
        return [], False
    try:
        payload = _load_json(path)
        raw_freezes = payload.get("active_freezes")
        if payload.get("state_readable") is not True or not isinstance(raw_freezes, list):
            return [], False
        freezes = [EdgeFreezeStateView.model_validate(item) for item in raw_freezes]
    except (OSError, ValueError, RuntimeError):
        return [], False
    return [freeze.model_dump(mode="json") for freeze in freezes], True


def _blocking_freeze_reason(bundle: EdgeBundle) -> str | None:
    """Return the deterministic fail-closed block reason for bundle freezes."""
    if not bundle.active_freezes_readable:
        return "freeze_state_unreadable"
    if not bundle.active_freezes:
        return None
    priorities = {
        "contested_local_writes": 0,
        "remote_branch_diverged_after_takeover": 1,
        "local_stale_or_dirty_takeover_target": 2,
        "reconcile_repair": 3,
        "split_admin_freeze": 4,
        "conflict_freeze": 5,
    }
    return min(
        (freeze.block_reason for freeze in bundle.active_freezes),
        key=lambda reason: priorities[reason],
    )


def _resolve_freeze_or_story_execution(
    bundle: EdgeBundle,
    *,
    synced: bool,
) -> ResolvedEdgeState:
    """Finish resolution with additive freeze blocking before story success."""
    freeze_reason = _blocking_freeze_reason(bundle)
    if freeze_reason is not None:
        return ResolvedEdgeState(
            operating_mode="binding_invalid",
            bundle=bundle,
            block_reason=freeze_reason,
            synced=synced,
        )
    return ResolvedEdgeState(
        operating_mode="story_execution",
        bundle=bundle,
        synced=synced,
    )


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
    "read_bound_skill_bundle_version",
]
