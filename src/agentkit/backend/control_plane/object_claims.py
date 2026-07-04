"""Per-Story object-mutation-claim declaration and the K4 wait-decision (AG3-141).

Blood-type A: pure, DB-free, unit-testable via the injected
:class:`ObjectClaimStorePort`. Concept anchors: FK-91 §91.1a Rule 13
(declaration duty; the serialization object for lifecycle/implementation
mutations is the Story, default ``(project_key, story_id)``; "reads never take
locks"); FK-10 §10.5.4 (durable object-mutation-claim row acquired before
dispatch, because engine writes and control-plane finalize run in separate DB
transactions; transaction-bound locks stay reserved for single-transaction
mutations); FK-17 §17.5 (object-serialization governs WHEN, single-writer
governs WHO).

Serialization is PER MUTATED OBJECT = the Story: two mutations of the SAME
Story collide on the ``object_mutation_claims`` primary key
``(project_key, serialization_scope, scope_key)`` -- exactly one acquires, the
other is busy. The project-scope / multi-object lock-set / cross-scope
fairness / ``queue_position`` apparatus was REMOVED as speculative (PO
decision, two independent reviews): it had no genuine requirement.
Project-wide mutations (mode-lock, story-number) are single-transaction and
stay xact-locked (FK-10 §10.5.4).

K4 (mandatory requirement, IMPL-016, ratified): the wait-semantics for a busy
object is a deterministic ``409 + Retry-After``, NEVER a thread-blocking wait.
The server is thread-per-request (``ThreadingHTTPSServer``,
``control_plane_http/app.py``) and the frontend aborts every request after
12s (``AbortController``, ``frontend/app/api.ts``); holding a request thread
on a contested claim is the exact anti-pattern this rules out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime

__all__ = (
    "ERROR_CODE_OBJECT_CLAIM_CONFLICT",
    "OBJECT_CLAIM_RETRY_AFTER_SECONDS",
    "STORY_SCOPE",
    "ObjectClaimConflict",
    "ObjectClaimKey",
    "ObjectClaimStorePort",
    "acquire_story_claim",
    "format_declared_scope",
    "parse_declared_scope",
    "release_story_claim",
    "story_claim_key",
)

#: The ``serialization_scope`` column value for a per-Story object claim -- the
#: ONLY object-claim scope (FK-91 §91.1a Rule 13 default ``(project_key,
#: story_id)``). Project-scope claims were removed as speculative.
STORY_SCOPE = "story"

#: K4: a client retry hint only (never an actual server-side wait), pinned
#: well under the 12s frontend ``AbortController`` timeout (``api.ts``).
OBJECT_CLAIM_RETRY_AFTER_SECONDS = 2

#: Reuses the frontend's already-known generic concurrency-conflict error
#: code (``formal.frontend-contracts.commands`` error contract: ``conflict``,
#: 409) so no frontend change is required (AG3-153 out of scope) -- the
#: existing generic 409 handling already covers this response shape.
ERROR_CODE_OBJECT_CLAIM_CONFLICT = "conflict"


@dataclass(frozen=True)
class ObjectClaimKey:
    """Identity of one claimable object = a Story.

    Mirrors the ``object_mutation_claims`` primary key
    ``(project_key, serialization_scope, scope_key)`` (AG3-137). Bound to the
    OBJECT (the Story), never the caller/principal -- which client/session/
    principal drives the mutation is irrelevant to serialization.

    Raises:
        ValueError: On a ``serialization_scope`` other than ``'story'`` (the
            only object-claim scope; project-scope was removed as speculative),
            or an empty ``project_key`` / ``scope_key``.
    """

    project_key: str
    serialization_scope: str
    scope_key: str

    def __post_init__(self) -> None:
        if self.serialization_scope != STORY_SCOPE:
            raise ValueError(
                "serialization_scope must be 'story' -- the only object-claim "
                "scope (FK-91 §91.1a Rule 13; project-scope claims were removed "
                f"as speculative), got {self.serialization_scope!r}",
            )
        if not self.project_key.strip():
            raise ValueError("project_key must not be empty")
        if not self.scope_key.strip():
            raise ValueError("scope_key must not be empty")


def story_claim_key(project_key: str, story_id: str) -> ObjectClaimKey:
    """The per-Story claim key (Rule 13 default ``(project_key, story_id)``)."""
    return ObjectClaimKey(
        project_key=project_key,
        serialization_scope=STORY_SCOPE,
        scope_key=story_id,
    )


def format_declared_scope(key: ObjectClaimKey) -> str:
    """The ``declared_serialization_scope`` string persisted on the
    inflight-operation-record.

    Pinned format (AG3-138, existing contract tests): ``f"{project_key}:
    {story_id}"``.
    """
    return f"{key.project_key}:{key.scope_key}"


def parse_declared_scope(
    project_key: str, declared: str | None
) -> ObjectClaimKey | None:
    """Recover the :class:`ObjectClaimKey` from a persisted ``declared_serialization_scope``.

    Used by startup reconciliation / admin-abort to release the object claim of
    an operation identified only by its persisted ``ControlPlaneOperationRecord``.
    Returns ``None`` for a legacy/absent declaration or one that does not match
    ``project_key`` (defense in depth) -- nothing to release.
    """
    if not declared:
        return None
    prefix = f"{project_key}:"
    if declared.startswith(prefix):
        story_id = declared[len(prefix) :]
        if story_id:
            return story_claim_key(project_key, story_id)
    return None


@dataclass(frozen=True)
class ObjectClaimConflict:
    """K4 wait-decision (IMPL-016, ratified): a busy object -- deterministic
    ``409 + Retry-After``, NEVER a thread-blocking wait.

    The response form is part of the error contract (FK-91 §91.1a Rule 8):
    a stable ``error_code`` plus a structured, pinned ``retry_after_seconds``
    budget.
    """

    key: ObjectClaimKey
    retry_after_seconds: int = OBJECT_CLAIM_RETRY_AFTER_SECONDS
    error_code: str = ERROR_CODE_OBJECT_CLAIM_CONFLICT


class ObjectClaimStorePort(Protocol):
    """Persistence seam for the atomic per-Story object-claim acquire/release.

    Satisfied structurally by
    :class:`agentkit.backend.control_plane.repository.ObjectMutationClaimRepository`
    in production; unit tests inject a DB-free fake with the SAME semantics
    (acquire wins iff the Story object is free; ownership-scoped release) to
    exercise the pure decision logic below without a database.
    """

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
    ) -> bool: ...

    def release_claim(
        self,
        project_key: str,
        serialization_scope: str,
        scope_key: str,
        op_id: str,
    ) -> bool: ...


def acquire_story_claim(
    port: ObjectClaimStorePort,
    key: ObjectClaimKey,
    *,
    op_id: str,
    backend_instance_id: str,
    instance_incarnation: int,
    now: datetime,
) -> ObjectClaimConflict | None:
    """Acquire the durable per-Story object-mutation claim BEFORE dispatch.

    Returns ``None`` on success (the claim is held). On a busy object (another
    in-flight mutation already holds the SAME Story's claim) returns the
    :class:`ObjectClaimConflict` so the caller surfaces the deterministic
    409 + Retry-After (K4) and stores NO operation for this attempt (a retry
    re-evaluates from scratch once the object is free), never a blocking wait.
    """
    won = port.acquire_claim(
        project_key=key.project_key,
        serialization_scope=key.serialization_scope,
        scope_key=key.scope_key,
        op_id=op_id,
        backend_instance_id=backend_instance_id,
        instance_incarnation=instance_incarnation,
        acquired_at=now,
    )
    if won:
        return None
    return ObjectClaimConflict(key=key)


def release_story_claim(
    port: ObjectClaimStorePort, key: ObjectClaimKey, *, op_id: str
) -> None:
    """Release the per-Story object claim (ownership-scoped, op_id-CAS).

    Idempotent / best-effort per claim: ``release_claim`` is a no-op when the
    row is already gone or held by a different ``op_id`` (a concurrent
    admin-abort / startup reconciliation already released it).
    """
    port.release_claim(key.project_key, key.serialization_scope, key.scope_key, op_id)
