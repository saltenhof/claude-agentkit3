"""Boundary port for the exploration worker execution (BC 5, bloodgroup A).

``agentkit.backend.exploration.drafting`` is a bloodgroup-A domain core
(``architecture-conformance.group.exploration_drafting``). Per ARCH-22 / ARCH-31
it MUST NOT spawn a worker, call an LLM, materialize a prompt nor touch the
filesystem directly. The seven-step FK-23 §23.3.2 drafting is WORKER behaviour
(NOT engine-side, NOT rule-based): the worker runs inside the harness, executes
the seven steps and emits a seven-part change-frame payload.

This is the sanctioned MOCKS-exception seam (CLAUDE.md "MOCKS/STUBS NUR IM ENGEN
AUSNAHMEFALL"): the LLM / worker boundary. The PRODUCTIVE adapter materializes
``worker-exploration.md`` (prompt-runtime, FK-44), spawns the exploration worker
over the EXISTING AG3-044 worker-spawn path (``SpawnKind.WORKER``) and returns
the worker's raw seven-part change-frame payload. Tests inject a RECORD-REPLAY
adapter that replays a recorded real worker/LLM result fixture (no live LLM
call). The bloodgroup-A :class:`~agentkit.backend.exploration.drafting.drafting.ExplorationDrafting`
orchestrates through this port; the concrete spawn / FS / LLM I/O lives in the
adapter, wired at the composition-root.

Fail-closed semantics (FK-23 §23.3 / ZERO DEBT): the runner returns the raw
worker payload (a mapping) for the requested (story, run) scope. An EMPTY result
(no draft produced) is signalled by ``payload is None`` -- the drafting core then
rejects fail-closed (no artifact written). A non-empty payload that does not
validate against :meth:`ChangeFrame.from_payload` is rejected by the core, never
patched (the worker, not the engine, owns the content).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.backend.story_context_manager.models import StoryContext


@dataclass(frozen=True)
class ExplorationWorkerResult:
    """The raw outcome of one exploration-worker run (the LLM/worker boundary).

    The worker (the non-deterministic harness actor, FK-23 §23.3) executes the
    seven FK-23 §23.3.2 steps and emits a seven-part change-frame payload. This
    carrier transports that RAW payload across the boundary port into the
    bloodgroup-A drafting core, which validates it into a typed
    :class:`~agentkit.backend.exploration.change_frame.ChangeFrame`.

    Attributes:
        payload: The worker's raw change-frame JSON payload (a mapping with the
            seven FK-23 §23.4.1 wire keys plus the identity fields), or ``None``
            when the worker produced NO draft (empty result -> fail-closed
            rejection in the drafting core; never a fabricated draft).
        prompt_path: The POSIX path of the materialized ``worker-exploration.md``
            prompt instance the worker consumed (FK-44; for traceability /
            audit). Empty when the runner did not materialize a prompt (e.g. an
            empty-result run that never reached spawn).
    """

    payload: dict[str, object] | None
    prompt_path: str = ""


@runtime_checkable
class ExplorationWorkerRunner(Protocol):
    """Run the exploration worker for a (story, run) and return its raw output.

    The single boundary the bloodgroup-A drafting core uses to obtain the
    worker-produced change-frame payload. The productive adapter materializes the
    ``worker-exploration.md`` prompt and spawns the exploration worker over the
    AG3-044 worker-spawn path; the record-replay test adapter replays a recorded
    real worker result. No parallel spawn path: the productive adapter reuses the
    WORKER spawn path with the exploration prompt template (there is no
    EXPLORATION ``SpawnKind``).
    """

    def run_exploration_worker(
        self, ctx: StoryContext, *, run_id: str, invocation_id: str
    ) -> ExplorationWorkerResult:
        """Execute the exploration worker and return its raw change-frame payload.

        Args:
            ctx: The authoritative story context for the run (drives the prompt
                materialization + worker spawn context).
            run_id: The bound run correlation id (FK-02 §2.3.1 UUID).
            invocation_id: The spawn/invocation id (prompt-audit correlation).

        Returns:
            An :class:`ExplorationWorkerResult` carrying the worker's raw
            seven-part change-frame payload (or ``None`` when no draft was
            produced -> fail-closed in the drafting core).

        Raises:
            Exception: When the worker could not be spawned / its prompt bundle
                is missing-or-unbound (fail-closed; never a silent empty result).
        """
        ...


__all__ = [
    "ExplorationWorkerResult",
    "ExplorationWorkerRunner",
]
