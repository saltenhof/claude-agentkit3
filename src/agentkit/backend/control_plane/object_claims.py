"""Object-mutation-claim declaration, lock-set ordering, cross-scope fairness
and the K4 wait-decision (AG3-141).

Blood-type A: pure, DB-free, unit-testable via the injected
:class:`ObjectClaimStorePort`. Concept anchors: FK-91 §91.1a Rule 13
(declaration duty; default serialization object ``(project_key, story_id)``;
lock-set with global acquisition order project -> stories lexicographic;
queue-fairness; "reads never take locks"); FK-10 §10.5.4 (durable
object-mutation-claim row acquired before dispatch, because engine writes and
control-plane finalize run in separate DB transactions; transaction-bound
locks stay reserved for single-transaction mutations); FK-17 §17.5
(object-serialization governs WHEN, single-writer governs WHO);
``formal.state-storage.invariants``
(``pending_project_claims_are_not_overtaken_by_younger_story_claims``,
``object_mutation_claims_are_instance_bound_and_never_expire_by_wall_clock``).

The atomic acquire/release row mechanics (the cross-scope conflict check plus
queue-position bookkeeping, conflict-free under concurrent load) live in
``state_backend.postgres_store`` (blood-type AT, K5 Postgres-only); this
module owns the declaration model, the canonical global acquisition order and
the K4 wait-decision only -- it never touches a database.

K4 (Pflicht-Auflage, IMPL-016, ratified): the wait-semantics for a busy object
is a deterministic ``409 + Retry-After``, NEVER a thread-blocking wait. The
server is thread-per-request (``ThreadingHTTPSServer``,
``control_plane_http/app.py``) and the frontend aborts every request after
12s (``AbortController``, ``frontend/app/api.ts``); holding a request thread
on a contested claim is the exact anti-pattern this rules out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

__all__ = (
    "ERROR_CODE_OBJECT_CLAIM_CONFLICT",
    "OBJECT_CLAIM_RETRY_AFTER_SECONDS",
    "PROJECT_SCOPE",
    "STORY_SCOPE",
    "LockSet",
    "LockSetOrderError",
    "ObjectClaimConflict",
    "ObjectClaimKey",
    "ObjectClaimStorePort",
    "acquire_lock_set",
    "build_lock_set",
    "format_declared_scope",
    "parse_declared_scope",
    "project_claim_key",
    "release_lock_set",
    "single_story_lock_set",
    "story_claim_key",
)

#: ``serialization_scope`` column discriminator values (FK-91 §91.1a Rule 13).
PROJECT_SCOPE = "project"
STORY_SCOPE = "story"

#: K4: a client retry hint only (never an actual server-side wait), pinned
#: well under the 12s frontend ``AbortController`` timeout (``api.ts``).
OBJECT_CLAIM_RETRY_AFTER_SECONDS = 2

#: Reuses the frontend's already-known generic concurrency-conflict error
#: code (``formal.frontend-contracts.commands`` Fehler-Vertrag: ``conflict``,
#: 409) so no frontend change is required (AG3-153 out of scope) -- the
#: existing generic 409 handling already covers this response shape.
ERROR_CODE_OBJECT_CLAIM_CONFLICT = "conflict"


@dataclass(frozen=True)
class ObjectClaimKey:
    """Identity of one claimable object (``state-storage.entity.object-mutation-claim``).

    Mirrors the ``object_mutation_claims`` primary key
    ``(project_key, serialization_scope, scope_key)`` (AG3-137). Bound to the
    OBJECT, never the caller/principal -- which client/session/principal
    drives the mutation is irrelevant to serialization.

    Raises:
        ValueError: On an unknown ``serialization_scope`` or an empty
            ``project_key`` / ``scope_key``.
    """

    project_key: str
    serialization_scope: str
    scope_key: str

    def __post_init__(self) -> None:
        if self.serialization_scope not in (PROJECT_SCOPE, STORY_SCOPE):
            raise ValueError(
                "serialization_scope must be 'project' or 'story' (FK-91 "
                f"§91.1a Rule 13), got {self.serialization_scope!r}",
            )
        if not self.project_key.strip():
            raise ValueError("project_key must not be empty")
        if not self.scope_key.strip():
            raise ValueError("scope_key must not be empty")


def project_claim_key(project_key: str) -> ObjectClaimKey:
    """The project-wide claim key (Rule 13: projektweite Mutationen)."""
    return ObjectClaimKey(
        project_key=project_key,
        serialization_scope=PROJECT_SCOPE,
        scope_key=project_key,
    )


def story_claim_key(project_key: str, story_id: str) -> ObjectClaimKey:
    """The default per-story claim key (Rule 13 default ``(project_key, story_id)``)."""
    return ObjectClaimKey(
        project_key=project_key,
        serialization_scope=STORY_SCOPE,
        scope_key=story_id,
    )


class LockSetOrderError(ValueError):
    """Fail-closed (SOLL-049): a lock-set violated the global acquisition order.

    The global order is: the project claim FIRST (if declared), then story
    claims in strictly lexicographic ``story_id`` order. "Story claim held,
    then project claim requested" is not expressible via :func:`build_lock_set`
    and raises this even when a caller hand-builds a :class:`LockSet` directly
    (the constructor validates unconditionally -- there is no bypass).
    """


@dataclass(frozen=True)
class LockSet:
    """An object-claim lock-set, ALWAYS in the mandatory global acquisition order.

    SOLL-049: the canonical order is validated at construction, so even a
    directly hand-built ``LockSet`` with claims out of order fails closed
    (:class:`LockSetOrderError`) rather than silently accepting an illegal
    acquisition order. :func:`build_lock_set` is the sanctioned builder that
    always derives the correct order regardless of input order -- there is no
    constructor path that lets a caller express a custom (illegal) order.

    Raises:
        LockSetOrderError: On an empty claim set, a claim outside this
            set's project, a project claim not first, or story claims that are
            not strictly lexicographically increasing.
    """

    project_key: str
    claims: tuple[ObjectClaimKey, ...]

    def __post_init__(self) -> None:
        if not self.project_key.strip():
            raise ValueError("project_key must not be empty")
        _validate_canonical_order(self.project_key, self.claims)

    @property
    def project_claim(self) -> ObjectClaimKey | None:
        """The project-scope claim in this set, if declared."""
        if self.claims and self.claims[0].serialization_scope == PROJECT_SCOPE:
            return self.claims[0]
        return None

    @property
    def story_claims(self) -> tuple[ObjectClaimKey, ...]:
        """The story-scope claims in this set, in acquisition order."""
        return tuple(c for c in self.claims if c.serialization_scope == STORY_SCOPE)


def _validate_canonical_order(
    project_key: str, claims: tuple[ObjectClaimKey, ...]
) -> None:
    if not claims:
        raise LockSetOrderError(
            "a lock-set must declare at least one claim (SOLL-048: every "
            "mutation declares its serialization object)",
        )
    seen_story = False
    previous_story_id: str | None = None
    for index, claim in enumerate(claims):
        if claim.project_key != project_key:
            raise LockSetOrderError(
                f"claim {claim!r} does not belong to lock-set project "
                f"{project_key!r} (a lock-set is scoped to ONE project)",
            )
        if claim.serialization_scope == PROJECT_SCOPE:
            if index != 0 or seen_story:
                raise LockSetOrderError(
                    "the project claim must be acquired FIRST (SOLL-049: "
                    "global order project -> stories); a lock-set with a "
                    "story claim ahead of (or a second) project claim is "
                    "not a legal acquisition order",
                )
        else:
            seen_story = True
            if previous_story_id is not None and claim.scope_key <= previous_story_id:
                raise LockSetOrderError(
                    "story claims must be acquired in STRICT lexicographic "
                    f"story_id order with no duplicates (SOLL-049); "
                    f"{claim.scope_key!r} does not sort after "
                    f"{previous_story_id!r}",
                )
            previous_story_id = claim.scope_key


def build_lock_set(
    project_key: str,
    *,
    story_ids: Iterable[str] = (),
    include_project_claim: bool = False,
) -> LockSet:
    """Build a lock-set in the MANDATORY global acquisition order (SOLL-049).

    The sanctioned constructor: regardless of the order ``story_ids`` are
    supplied in, the returned lock-set is always canonical (the project claim
    first when requested, then story claims in strictly lexicographic order,
    duplicates collapsed). "Story before project" cannot be expressed through
    this API.
    """
    claims: list[ObjectClaimKey] = []
    if include_project_claim:
        claims.append(project_claim_key(project_key))
    for story_id in sorted(set(story_ids)):
        claims.append(story_claim_key(project_key, story_id))
    return LockSet(project_key=project_key, claims=tuple(claims))


def single_story_lock_set(project_key: str, story_id: str) -> LockSet:
    """The default declaration for lifecycle/implementation mutations (Rule 13)."""
    return build_lock_set(project_key, story_ids=(story_id,))


def format_declared_scope(key: ObjectClaimKey) -> str:
    """The ``declared_serialization_scope`` string persisted on the
    inflight-operation-record.

    Pinned format (AG3-138, existing contract tests): ``f"{project_key}:
    {story_id}"`` for a story claim; a bare ``project_key`` for a project
    claim.
    """
    if key.serialization_scope == PROJECT_SCOPE:
        return key.project_key
    return f"{key.project_key}:{key.scope_key}"


def parse_declared_scope(
    project_key: str, declared: str | None
) -> ObjectClaimKey | None:
    """Recover the :class:`ObjectClaimKey` from a persisted ``declared_serialization_scope``.

    Used by startup reconciliation / admin-abort (Scope item 7) to release the
    object claim of an operation identified only by its persisted
    ``ControlPlaneOperationRecord``. Returns ``None`` for a legacy/absent
    declaration (nothing to release).
    """
    if not declared:
        return None
    if declared == project_key:
        return project_claim_key(project_key)
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
    """Persistence seam for atomic object-claim acquire/release (blood-type AT).

    Satisfied structurally by
    :class:`agentkit.backend.control_plane.repository.ObjectMutationClaimRepository`
    in production; unit tests inject a DB-free fake honoring the SAME
    cross-scope fairness contract (a project claim conflicts with any held
    story claim of the same project and vice versa) to exercise the pure
    lock-set orchestration below without a database.
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


def acquire_lock_set(
    port: ObjectClaimStorePort,
    lock_set: LockSet,
    *,
    op_id: str,
    backend_instance_id: str,
    instance_incarnation: int,
    now: datetime,
) -> ObjectClaimConflict | None:
    """Acquire every claim in *lock_set*, STRICTLY in its canonical order.

    Returns ``None`` on full success (every claim held). On a conflict, ALL
    claims already acquired by THIS attempt are released again (no partial
    lock-set survives) and the busy claim's :class:`ObjectClaimConflict` is
    returned -- the caller surfaces the deterministic 409 + Retry-After (K4)
    and stores no operation (a retry re-evaluates from scratch, never a
    stored terminal result for a busy attempt).
    """
    acquired: list[ObjectClaimKey] = []
    for claim in lock_set.claims:
        won = port.acquire_claim(
            project_key=claim.project_key,
            serialization_scope=claim.serialization_scope,
            scope_key=claim.scope_key,
            op_id=op_id,
            backend_instance_id=backend_instance_id,
            instance_incarnation=instance_incarnation,
            acquired_at=now,
        )
        if not won:
            for held in reversed(acquired):
                port.release_claim(
                    held.project_key,
                    held.serialization_scope,
                    held.scope_key,
                    op_id,
                )
            return ObjectClaimConflict(key=claim)
        acquired.append(claim)
    return None


def release_lock_set(port: ObjectClaimStorePort, lock_set: LockSet, *, op_id: str) -> None:
    """Release every claim in *lock_set*, in REVERSE acquisition order.

    Idempotent / best-effort per claim: ``release_claim`` is a no-op when the
    row is already gone or held by a different ``op_id`` (a concurrent
    admin-abort / startup reconciliation already released it).
    """
    for claim in reversed(lock_set.claims):
        port.release_claim(
            claim.project_key, claim.serialization_scope, claim.scope_key, op_id
        )
