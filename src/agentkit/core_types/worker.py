"""BlockingCategory, SpawnReason und SpawnRequest — Worker-Lifecycle-Typen.

Source of truth:
- BlockingCategory: FK-26 §26.8.2 Glossar Z. 42-53
  (concept/technical-design/26_implementation_runtime_worker_loop.md).
  Vier upper-case Werte; Pflichtfeld im worker-manifest bei status BLOCKED.
- SpawnReason: ``concept/_meta/bc-cut-decisions.md`` §BC 6 Z. 441-450
  plus FK-26 §26.2 (Worker-Variants). Drei lower-case Wire-Werte gem.
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
    """Klassifikation eines BLOCKED-Worker-Exits pro FK-26 §26.8.2.

    Attributes:
        POLICY_CONFLICT: Unaufloesbarer Widerspruch zwischen Policies.
        ENVIRONMENTAL: Fehlende externe Voraussetzung
            (Tool, Service, Datenquelle).
        FIXABLE_LOCAL: Lokaler Fehler ausserhalb des Worker-Scopes.
        FIXABLE_CODE: Code-Fehler ausserhalb des Worker-Scopes.
    """

    POLICY_CONFLICT = "POLICY_CONFLICT"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    FIXABLE_LOCAL = "FIXABLE_LOCAL"
    FIXABLE_CODE = "FIXABLE_CODE"


class SpawnReason(StrEnum):
    """Grund des Worker-Starts pro FK-26 §26.2 + bc-cut §BC 6.

    Konzept-Drift-Notiz: FK-26 §26.8.2 Glossar listet die Werte in
    UPPER_SNAKE_CASE als Member-Namen; AG3-021 §2.1.1.1 hat die
    Wire-Strings normativ auf lowercase festgelegt (konsistent mit dem
    bestehenden Code in `workers/types.py`). Member-Namen bleiben
    UPPER_SNAKE_CASE.

    Attributes:
        INITIAL: Erstaufruf einer Story-Phase.
        PAUSED_RETRY: Re-Spawn nach PAUSED-Zustand (paused_reason
            faellt mit dem Retry weg).
        REMEDIATION: Re-Spawn nach QA-FAIL fuer Remediation-Runde.
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
