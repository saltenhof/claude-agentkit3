"""BlockingCategory, SpawnReason and SpawnRequest — worker-lifecycle types.

Source of truth:
- BlockingCategory: FK-26 §26.8.2 glossary lines 42-53
  (concept/technical-design/26_implementation_runtime_worker_loop.md).
  Four upper-case values; required field in the worker-manifest at status BLOCKED.
- SpawnReason: ``concept/_meta/bc-cut-decisions.md`` §BC 6 lines 441-450
  plus FK-26 §26.2 (worker variants). Three lower-case wire values per
  AG3-021 §2.1.1.1.
- SpawnRequest: FK-20 §20.5.1 / FK-45 §45.3 — the typed engine-control
  record carried in ``PhaseState.agents_to_spawn`` so the orchestrator
  spawns the next worker (remediation / adversarial) on phase re-entry
  without a second untyped truth (CLAUDE.md SINGLE SOURCE OF TRUTH).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class BlockingCategory(StrEnum):
    """Classification of a BLOCKED worker exit per FK-26 §26.8.2.

    Attributes:
        POLICY_CONFLICT: Unresolvable contradiction between policies.
        ENVIRONMENTAL: Missing external precondition
            (tool, service, data source).
        FIXABLE_LOCAL: Local error outside the worker scope.
        FIXABLE_CODE: Code error outside the worker scope.
    """

    POLICY_CONFLICT = "POLICY_CONFLICT"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    FIXABLE_LOCAL = "FIXABLE_LOCAL"
    FIXABLE_CODE = "FIXABLE_CODE"


class SpawnReason(StrEnum):
    """Reason for the worker start per FK-26 §26.2 + bc-cut §BC 6.

    Concept-drift note: FK-26 §26.8.2 glossary lists the values in
    UPPER_SNAKE_CASE as member names; AG3-021 §2.1.1.1 normatively fixed
    the wire strings to lowercase (consistent with the existing code in
    `workers/types.py`). Member names remain UPPER_SNAKE_CASE.

    Attributes:
        INITIAL: First invocation of a story phase.
        PAUSED_RETRY: Re-spawn after a PAUSED state (paused_reason is
            dropped with the retry).
        REMEDIATION: Re-spawn after a QA FAIL for a remediation round.
    """

    INITIAL = "initial"
    PAUSED_RETRY = "paused_retry"
    REMEDIATION = "remediation"


class SpawnKind(StrEnum):
    """Worker variant the engine must spawn on re-entry (FK-45 §45.3).

    Attributes:
        WORKER: A code-producing worker (initial or remediation, the
            concrete prompt variant follows ``SpawnRequest.spawn_reason``).
        ADVERSARIAL: A Layer-3 adversarial-testing worker (FK-48 §48.2)
            scoped to the adversarial sandbox.
    """

    WORKER = "worker"
    ADVERSARIAL = "adversarial"


class SpawnRequest(BaseModel):
    """A single typed engine-control spawn order (FK-20 §20.5.1 / FK-45 §45.3).

    Written into ``PhaseState.agents_to_spawn`` by a phase handler / the
    adversarial spawner. The orchestrator reacts to it on phase re-entry and
    spawns exactly the requested worker variant; it is never an untyped second
    truth alongside the phase state (CLAUDE.md FIX THE MODEL).

    Attributes:
        kind: Worker variant to spawn (``WORKER`` / ``ADVERSARIAL``).
        spawn_reason: Why the worker is spawned (drives the prompt variant,
            e.g. ``REMEDIATION`` for the subflow-internal feedback loop).
        target_id: Optional correlation id (e.g. the adversarial finding id /
            sandbox epoch) so the spawned worker can be bound to its order.
        sandbox_path: Optional POSIX-relative sandbox path the spawned worker
            must write into (``_temp/adversarial/{story_id}/{epoch}/`` for
            adversarial spawns, FK-48 §48.1; ``None`` for in-worktree workers).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: SpawnKind
    spawn_reason: SpawnReason
    target_id: str | None = None
    sandbox_path: str | None = None
