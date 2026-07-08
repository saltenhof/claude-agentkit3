"""Control-plane session ownership and ambient ownership-fence facade operations."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.backend.exceptions import CorruptStateError
from agentkit.backend.state_backend.config import (
    StateBackendKind,
    load_state_backend_config,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    delete_session_run_binding_global as delete_session_run_binding_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    insert_run_ownership_record_global as insert_run_ownership_record_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_active_run_ownership_record_global as load_active_run_ownership_record_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_run_ownership_record_global as load_run_ownership_record_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    load_session_run_binding_global as load_session_run_binding_global,
)
from agentkit.backend.state_backend.story_lifecycle_store import (
    save_session_run_binding_global as save_session_run_binding_global,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

def resolve_ownership_fence_snapshot(
    project_key: str,
    story_id: str,
) -> tuple[str, int] | None:
    """Resolve the caller's early ownership-lease snapshot (AG3-144, FK-91 §91.1a Rule 15).

    Business-logic write paths (the implementation/closure phase handlers)
    call this ONCE, as early as feasible in their own execution, to capture
    the active ``run_ownership_records`` row's ``(owner_session_id,
    ownership_epoch)`` -- mirroring the control-plane's own admission
    snapshot (AG3-142). The snapshot is threaded into the later
    ``record_layer_artifacts`` / ``record_verify_decision`` /
    ``record_closure_report`` calls, which re-verify it AT COMMIT TIME, in
    the SAME transaction, under ``SELECT ... FOR UPDATE`` (no TOCTOU).

    K5 Postgres-only (Querschnitts-Auflagen): on a non-Postgres backend (the
    narrow SQLite unit-test path) this returns ``None`` -- explicit, not a
    silent skip -- so the caller falls back to inert placeholder values that
    the ``sqlite_store`` driver functions explicitly ignore. There is no
    fence mirroring on SQLite.

    Returns:
        ``(owner_session_id, ownership_epoch)`` on Postgres, or ``None`` on a
        non-Postgres backend.

    Raises:
        CorruptStateError: On Postgres, when no active ``run_ownership_records``
            row exists for ``(project_key, story_id)`` -- an in-flight phase
            execution without an active lease is a state-integrity fault, not
            a scenario to silently tolerate.
    """
    if load_state_backend_config().backend is not StateBackendKind.POSTGRES:
        return None
    active = load_active_run_ownership_record_global(project_key, story_id)
    if active is None:
        raise CorruptStateError(
            "No active run-ownership record found for an in-flight phase "
            "execution (AG3-142/AG3-144 no-lease-no-write precondition)",
            detail={"project_key": project_key, "story_id": story_id},
        )
    return (active.owner_session_id, active.ownership_epoch)


@dataclass(frozen=True)
class OwnershipFenceScope:
    """The caller's early-captured ownership-lease snapshot for ONE phase attempt.

    AG3-144 (Codex round-2, FK-91 §91.1a Rule 15): ``artifact_envelopes`` and
    ``qa_check_outcomes`` are written from many BCs (verify-system's QA-subflow
    layers, prompt-runtime materialization, the adversarial orchestrator,
    exploration drafting/review, the ARE-gate audit) through call graphs many
    frames deep. Threading ``owner_session_id`` / ``expected_ownership_epoch``
    as an explicit parameter through every one of those signatures
    (``ArtifactManager.write``, ``PromptRuntime.materialize_prompt``, the
    ``QALayer`` protocol, the exploration ``ChangeFrameSink`` /
    ``ReviewResultSink`` ports, ...) would multiply a single fence mechanism
    into dozens of unrelated public contracts -- the OPPOSITE of FIX THE MODEL.

    Instead, the phase handler that owns the admission-time snapshot
    (``resolve_ownership_fence_snapshot``, called ONCE, as early as feasible)
    binds it for the duration of its own mutating call via
    :func:`bind_ownership_fence_scope`; every ``state_backend`` Postgres write
    reachable from that call -- regardless of how many BC-internal layers
    separate it from the phase handler -- reads the SAME bound snapshot via
    :func:`require_ownership_fence_scope` and re-verifies it AT COMMIT TIME via
    the AG3-142 ``_enforce_ownership_fence_row`` (never a second fence
    predicate). This mirrors the existing per-attempt ``ContextVar`` precedent
    already used in this codebase
    (``verify_system.llm_evaluator.structured_evaluator._EVAL_DEADLINE_CV``).

    Attributes:
        project_key: Project key (fence scope).
        story_id: Story display id the scope is bound to; a write for a
            DIFFERENT story_id is rejected fail-closed (no cross-story reuse).
        run_id: The run correlation id THIS phase attempt is executing under
            (the fence's ``run_id`` predicate input) -- deliberately NOT
            necessarily the individual envelope's own ``run_id`` field, so a
            project-scoped audit artifact (e.g. the ARE-gate ``are_gate.json``)
            can keep its own domain identity while still being fenced against
            the REAL active run.
        owner_session_id: The caller's early-captured
            ``run_ownership_records.owner_session_id`` snapshot.
        expected_ownership_epoch: The caller's early-captured
            ``ownership_epoch`` snapshot.
    """

    project_key: str
    story_id: str
    run_id: str
    owner_session_id: str
    expected_ownership_epoch: int


_OWNERSHIP_FENCE_SCOPE_CV: ContextVar[OwnershipFenceScope | None] = ContextVar(
    "agentkit_ownership_fence_scope",
    default=None,
)


@contextmanager
def bind_ownership_fence_scope(
    *,
    project_key: str,
    story_id: str,
    run_id: str,
    owner_session_id: str,
    expected_ownership_epoch: int,
) -> Iterator[None]:
    """Bind the caller's early-captured lease snapshot for this call's duration.

    The phase handler that captured the admission-time snapshot (e.g.
    ``ImplementationPhaseHandler.on_enter``, ``ExplorationPhaseHandler.on_enter``)
    wraps its ENTIRE mutating execution (the QA-subflow, prompt materialization,
    the ARE-gate check, drafting/review persistence, ...) in this context
    manager, ONCE, using the SAME ``(owner_session_id, expected_ownership_epoch)``
    values it resolved via :func:`resolve_ownership_fence_snapshot` at admission
    time. Never nested in practice (a nested bind would indicate two
    overlapping phase-attempt scopes on one call stack, a modelling error);
    ``ContextVar.reset`` restores the outer value regardless, so a defensive
    nested bind still unwinds correctly.

    Args:
        project_key: Project key (fence scope).
        story_id: Story display id this call is executing for.
        run_id: The run correlation id this call is executing under.
        owner_session_id: The early-captured
            ``run_ownership_records.owner_session_id`` snapshot.
        expected_ownership_epoch: The early-captured ``ownership_epoch``
            snapshot.

    Yields:
        None.
    """
    scope = OwnershipFenceScope(
        project_key=project_key,
        story_id=story_id,
        run_id=run_id,
        owner_session_id=owner_session_id,
        expected_ownership_epoch=expected_ownership_epoch,
    )
    token = _OWNERSHIP_FENCE_SCOPE_CV.set(scope)
    try:
        yield
    finally:
        _OWNERSHIP_FENCE_SCOPE_CV.reset(token)


def require_ownership_fence_scope(*, story_id: str) -> OwnershipFenceScope:
    """Return the bound :class:`OwnershipFenceScope` (fail-closed).

    The state_backend Postgres write boundary (``StateBackendArtifactRepository``
    / ``FacadeQACheckOutcomesRepository``) calls this INSTEAD of accepting an
    ``owner_session_id`` / ``expected_ownership_epoch`` parameter directly -- a
    caller that reaches the write boundary with no bound scope is a hard
    runtime error, never a silent skip (AG3-144 Codex round-2, Rule 15).

    Args:
        story_id: The envelope's/record's own ``story_id`` -- cross-checked
            against the bound scope so a write can never be fenced against a
            DIFFERENT story's lease.

    Returns:
        The bound :class:`OwnershipFenceScope`.

    Raises:
        CorruptStateError: When no scope is bound, or the bound scope's
            ``story_id`` does not match ``story_id`` (fail-closed).
    """
    scope = _OWNERSHIP_FENCE_SCOPE_CV.get()
    if scope is None:
        raise CorruptStateError(
            "No OwnershipFenceScope is bound (AG3-144 Rule 15, no-lease-no-write): "
            "a mutating artifact_envelopes/qa_check_outcomes write was attempted "
            "outside bind_ownership_fence_scope. Every phase handler that writes "
            "a story projection must bind its early-captured "
            "resolve_ownership_fence_snapshot() result for the duration of its "
            "mutating call (fail-closed, no unfenced write path).",
            detail={"story_id": story_id},
        )
    if scope.story_id != story_id:
        raise CorruptStateError(
            "OwnershipFenceScope story_id mismatch: the bound scope belongs to "
            "a different story than the write being attempted (fail-closed, no "
            "cross-story fence reuse).",
            detail={"bound_story_id": scope.story_id, "write_story_id": story_id},
        )
    return scope


__all__ = [
    "save_session_run_binding_global",
    "load_session_run_binding_global",
    "delete_session_run_binding_global",
    "insert_run_ownership_record_global",
    "load_run_ownership_record_global",
    "load_active_run_ownership_record_global",
    "resolve_ownership_fence_snapshot",
    "OwnershipFenceScope",
    "bind_ownership_fence_scope",
    "require_ownership_fence_scope",
]
