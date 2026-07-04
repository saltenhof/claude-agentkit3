"""Unit tests wiring object-mutation claims into the control-plane runtime
(AG3-141): reads never touch the object-claim port (SOLL-048/053/055); a busy
object surfaces the K4 deterministic 409 + Retry-After shape and releases the
op_id claim it never got to use (no orphan).

DI-injected fakes only (no I/O, no database) -- the atomic Postgres acquire
semantics are proven separately in the integration suite against the real
fixture (K5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from agentkit.backend.control_plane import object_claims as oc
from agentkit.backend.control_plane.models import (
    ClosureCompleteRequest,
    PhaseMutationRequest,
)
from agentkit.backend.control_plane.records import ControlPlaneOperationRecord
from agentkit.backend.control_plane.repository import ObjectMutationClaimRepository
from agentkit.backend.control_plane.runtime import ControlPlaneRuntimeService

_NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


class _ObjectClaimSpyRaisesOnUse:
    """A port that raises if ANY method is called -- proves a code path never
    touches the object-claim mechanism at all (reads-lock-free proof)."""

    def acquire_claim(self, **_kwargs: object) -> bool:
        raise AssertionError("a read path must never acquire an object claim")

    def release_claim(self, *_args: object, **_kwargs: object) -> bool:
        raise AssertionError("a read path must never release an object claim")


@dataclass
class _FakeObjectClaimPort:
    """In-memory object-claim port for wiring tests (mirrors the productive
    cross-scope fairness contract; op_id-scoped release)."""

    held: dict[tuple[str, str, str], str] = field(default_factory=dict)
    released: list[tuple[str, str, str, str]] = field(default_factory=list)

    def acquire_claim(
        self,
        *,
        project_key: str,
        serialization_scope: str,
        scope_key: str,
        op_id: str,
        backend_instance_id: str,
        instance_incarnation: int,
        acquired_at: datetime,
    ) -> bool:
        del backend_instance_id, instance_incarnation, acquired_at
        conflicting = "story" if serialization_scope == "project" else "project"
        if any(
            k[0] == project_key and k[1] == conflicting and v != op_id
            for k, v in self.held.items()
        ):
            return False
        key = (project_key, serialization_scope, scope_key)
        existing = self.held.get(key)
        if existing is not None:
            return existing == op_id
        self.held[key] = op_id
        return True

    def release_claim(
        self, project_key: str, serialization_scope: str, scope_key: str, op_id: str
    ) -> bool:
        key = (project_key, serialization_scope, scope_key)
        self.released.append((project_key, serialization_scope, scope_key, op_id))
        if self.held.get(key) != op_id:
            return False
        del self.held[key]
        return True


@dataclass
class _MinimalControlPlaneRepo:
    """Just enough of ``ControlPlaneRuntimeRepository`` for start_phase's
    pre-dispatch path (replay check, repair lock, op_id claim) -- the object
    claim itself is the seam under test, so dispatch is never reached on the
    busy path.
    """

    operations: dict[str, ControlPlaneOperationRecord] = field(default_factory=dict)
    released_ops: list[str] = field(default_factory=list)

    def load_operation(self, op_id: str) -> ControlPlaneOperationRecord | None:
        return self.operations.get(op_id)

    def has_open_repair_for_story(self, project_key: str, story_id: str) -> bool:
        del project_key, story_id
        return False

    def has_committed_story_exit_operation_for_run(
        self, project_key: str, story_id: str, run_id: str
    ) -> bool:
        del project_key, story_id, run_id
        return False

    def has_committed_operation_for_run(
        self, project_key: str, story_id: str, run_id: str
    ) -> bool:
        del project_key, story_id, run_id
        return False

    def load_binding(self, session_id: str) -> None:
        del session_id
        return None

    def load_story_context(self, project_key: str, story_id: str) -> None:
        del project_key, story_id
        return None

    def claim_operation(self, record: ControlPlaneOperationRecord) -> bool:
        if record.op_id in self.operations:
            return False
        self.operations[record.op_id] = record
        return True

    def release_operation(
        self, op_id: str, *, owner_token: str, owner_claimed_at: str | None
    ) -> None:
        del owner_token, owner_claimed_at
        self.released_ops.append(op_id)
        self.operations.pop(op_id, None)


def _request(*, story_id: str = "AG3-100", op_id: str = "op-1") -> PhaseMutationRequest:
    return PhaseMutationRequest(
        project_key="tenant-a",
        story_id=story_id,
        session_id="sess-1",
        op_id=op_id,
        principal_type="orchestrator",
        worktree_roots=["T:/worktrees/x"],
    )


# ---------------------------------------------------------------------------
# Reads never take locks (SOLL-048/053/055, Scope item 6)
# ---------------------------------------------------------------------------


def test_get_operation_never_touches_the_object_claim_port() -> None:
    repo = _MinimalControlPlaneRepo()
    repo.operations["op-done"] = ControlPlaneOperationRecord(
        op_id="op-done",
        project_key="tenant-a",
        story_id="AG3-100",
        run_id="run-1",
        session_id="sess-1",
        operation_kind="phase_start",
        phase="setup",
        status="committed",
        response_payload={
            "status": "committed",
            "op_id": "op-done",
            "operation_kind": "phase_start",
            "run_id": "run-1",
            "phase": "setup",
            "edge_bundle": {
                "current": {
                    "project_key": "tenant-a",
                    "export_version": "v1",
                    "operating_mode": "ai_augmented",
                    "bundle_dir": "d",
                    "sync_after": _NOW.isoformat(),
                    "freshness_class": "mutation",
                    "generated_at": _NOW.isoformat(),
                },
            },
        },
        created_at=_NOW,
        updated_at=_NOW,
    )
    service = ControlPlaneRuntimeService(
        repository=repo,  # type: ignore[arg-type]
        object_claim_repository=_ObjectClaimSpyRaisesOnUse(),  # type: ignore[arg-type]
    )

    result = service.get_operation("op-done")

    assert result is not None
    assert result.status == "replayed"


def test_sync_project_edge_never_touches_the_object_claim_port() -> None:
    from agentkit.backend.control_plane.models import ProjectEdgeSyncRequest

    repo = _MinimalControlPlaneRepo()
    service = ControlPlaneRuntimeService(
        repository=repo,  # type: ignore[arg-type]
        object_claim_repository=_ObjectClaimSpyRaisesOnUse(),  # type: ignore[arg-type]
    )

    result = service.sync_project_edge(
        ProjectEdgeSyncRequest(
            project_key="tenant-a", session_id="sess-1", op_id="op-sync-1"
        )
    )

    assert result.status == "synced"


# ---------------------------------------------------------------------------
# K4 busy-object wait contract (IMPL-016): 409 + Retry-After, no wait
# ---------------------------------------------------------------------------


def test_start_phase_busy_object_returns_the_pinned_409_retry_after_shape() -> None:
    """A foreign op_id already holds the story's object claim: start_phase must
    release the op_id claim it just won (never dispatched) and surface the
    deterministic K4 wait contract -- never a blocking wait, never a stored op.
    """
    object_claim_port = _FakeObjectClaimPort()
    object_claim_port.held[("tenant-a", "story", "AG3-100")] = "op-foreign-holder"
    repo = _MinimalControlPlaneRepo()
    service = ControlPlaneRuntimeService(
        repository=repo,  # type: ignore[arg-type]
        object_claim_repository=ObjectMutationClaimRepository(
            acquire_claim=object_claim_port.acquire_claim,
            release_claim=object_claim_port.release_claim,
        ),
    )

    result = service.start_phase(
        run_id="run-1", phase="setup", request=_request(op_id="op-mine")
    )

    assert result.status == "rejected"
    assert result.error_code == oc.ERROR_CODE_OBJECT_CLAIM_CONFLICT
    assert result.retry_after_seconds == oc.OBJECT_CLAIM_RETRY_AFTER_SECONDS
    assert result.edge_bundle is None
    assert result.phase_dispatch is not None
    assert result.phase_dispatch.dispatched is False
    #: NO operation is stored for a busy attempt -- a retry re-evaluates fresh.
    assert "op-mine" not in repo.operations
    #: The op_id claim THIS caller won (before discovering the object was
    #: busy) is released -- never dispatched, never stranded.
    assert repo.released_ops == ["op-mine"]
    #: The foreign holder's object claim is untouched.
    assert object_claim_port.held == {("tenant-a", "story", "AG3-100"): "op-foreign-holder"}


def test_start_phase_free_object_is_acquired_before_dispatch_absent_context() -> None:
    """A free object is acquired (SOLL-054) before the dispatch attempt; with
    no story context resolvable, the dispatcher returns ``None`` and the
    existing fail-closed setup-admission path applies (unrelated to K4) -- but
    the object claim must have been released either way (never stranded).
    """
    object_claim_port = _FakeObjectClaimPort()
    repo = _MinimalControlPlaneRepo()
    service = ControlPlaneRuntimeService(
        repository=repo,  # type: ignore[arg-type]
        object_claim_repository=ObjectMutationClaimRepository(
            acquire_claim=object_claim_port.acquire_claim,
            release_claim=object_claim_port.release_claim,
        ),
    )

    result = service.start_phase(
        run_id="run-1", phase="setup", request=_request(op_id="op-mine")
    )

    assert result.status == "rejected"
    assert result.error_code is None  # NOT the K4 busy-object shape
    assert result.retry_after_seconds is None
    #: The claim was acquired then released -- never left held.
    assert object_claim_port.held == {}
    assert ("tenant-a", "story", "AG3-100", "op-mine") in object_claim_port.released


# ---------------------------------------------------------------------------
# Codex-R1 (BLOCKER): the release lifecycle is fail-CLOSED on success/handled
# paths -- a release failure on complete/fail/closure SURFACES (raises), never
# swallowed while the API returns ``committed`` with the object still held.
# ---------------------------------------------------------------------------


@dataclass
class _ReleaseRaisesPort:
    """An object-claim port that ACQUIRES fine but whose RELEASE always raises.

    Proves the runtime never swallows a release failure on a success/handled
    return path (the fail-OPEN gap): a swallowed release on complete/fail/
    closure would leave the story blocked with NO ``claimed`` op row for
    ``admin_abort`` to target.
    """

    release_attempts: list[tuple[str, str, str, str]] = field(default_factory=list)

    def acquire_claim(self, **_kwargs: object) -> bool:
        return True

    def release_claim(
        self, project_key: str, serialization_scope: str, scope_key: str, op_id: str
    ) -> bool:
        self.release_attempts.append(
            (project_key, serialization_scope, scope_key, op_id)
        )
        raise RuntimeError("simulated object-claim release failure (DB unavailable)")


@dataclass
class _MutatePhaseRepo:
    """Minimal control-plane repo that lets ``_mutate_phase`` reach a SUCCESSFUL
    commit (fresh op, fast story, commit succeeds)."""

    committed: list[str] = field(default_factory=list)

    def load_operation(self, op_id: str) -> None:
        del op_id
        return None

    def load_story_context(self, project_key: str, story_id: str) -> None:
        del project_key, story_id
        return None

    def load_binding(self, session_id: str) -> None:
        del session_id
        return None

    def commit_operation_with_side_effects(
        self,
        record: ControlPlaneOperationRecord,
        *,
        binding_to_save: object,
        binding_to_delete: object,
        locks: object,
        events: object,
    ) -> None:
        del binding_to_save, binding_to_delete, locks, events
        self.committed.append(record.op_id)


@pytest.mark.parametrize("operation_kind", ["phase_complete", "phase_fail"])
def test_complete_or_fail_release_failure_surfaces_never_returns_committed(
    operation_kind: str,
) -> None:
    repo = _MutatePhaseRepo()
    port = _ReleaseRaisesPort()
    service = ControlPlaneRuntimeService(
        repository=repo,  # type: ignore[arg-type]
        object_claim_repository=ObjectMutationClaimRepository(
            acquire_claim=port.acquire_claim,
            release_claim=port.release_claim,
        ),
    )

    with pytest.raises(RuntimeError, match="release failure"):
        service._mutate_phase(  # noqa: SLF001 -- exercising the release lifecycle
            run_id="run-1",
            phase="implementation",
            request=_request(story_id="AG3-100", op_id="op-1"),
            operation_kind=operation_kind,
        )

    #: The op DID commit (the fix does not roll it back) -- but the service
    #: RAISED rather than returning ``committed`` while the release failed. The
    #: fail-OPEN swallow is gone; the release WAS attempted (fail-closed), so the
    #: stuck claim is surfaced to the operator (needs reconcile/admin_abort),
    #: never silently blocking the story behind a ``committed`` response.
    assert repo.committed == ["op-1"]
    assert port.release_attempts == [("tenant-a", "story", "AG3-100", "op-1")]


@dataclass
class _ClosureRepo:
    """Minimal control-plane repo that admits and lets ``complete_closure`` reach
    a SUCCESSFUL commit."""

    committed: list[str] = field(default_factory=list)

    def load_operation(self, op_id: str) -> None:
        del op_id
        return None

    def has_open_repair_for_story(self, project_key: str, story_id: str) -> bool:
        del project_key, story_id
        return False

    def has_committed_story_exit_operation_for_run(
        self, project_key: str, story_id: str, run_id: str
    ) -> bool:
        del project_key, story_id, run_id
        return False

    def has_committed_operation_for_run(
        self, project_key: str, story_id: str, run_id: str
    ) -> bool:
        del project_key, story_id, run_id
        return True

    def load_binding(self, session_id: str) -> None:
        del session_id
        return None

    def load_story_context(self, project_key: str, story_id: str) -> None:
        del project_key, story_id
        return None

    def commit_operation_with_side_effects(
        self,
        record: ControlPlaneOperationRecord,
        *,
        binding_to_save: object,
        binding_to_delete: object,
        locks: object,
        events: object,
    ) -> None:
        del binding_to_save, binding_to_delete, locks, events
        self.committed.append(record.op_id)


def test_closure_release_failure_surfaces_never_returns_committed() -> None:
    repo = _ClosureRepo()
    port = _ReleaseRaisesPort()
    service = ControlPlaneRuntimeService(
        repository=repo,  # type: ignore[arg-type]
        object_claim_repository=ObjectMutationClaimRepository(
            acquire_claim=port.acquire_claim,
            release_claim=port.release_claim,
        ),
    )

    with pytest.raises(RuntimeError, match="release failure"):
        service.complete_closure(
            run_id="run-1",
            request=ClosureCompleteRequest(
                project_key="tenant-a",
                story_id="AG3-100",
                session_id="sess-1",
                op_id="op-1",
            ),
        )

    #: Committed, then the release failed -- the service RAISED instead of
    #: returning ``committed`` with a swallowed held claim (closure leaves no
    #: ``claimed`` op row, so this is exactly the fail-OPEN gap the fix closes).
    assert repo.committed == ["op-1"]
    assert port.release_attempts == [("tenant-a", "story", "AG3-100", "op-1")]
