"""Installer execution modes (FK-50 §50.2).

The installer is transport-agnostic and runs the same checkpoint flow in one
of three typed modes. ``register`` covers BOTH the first registration and the
idempotent re-run (FK-50 §50.2: a re-run is the same mode whose handlers
converge to ``SKIPPED``/``PASS`` when already satisfied and to ``UPDATED`` on a
digest delta). ``dry_run`` and ``verify`` are read-only modes that MUST NOT
mutate the filesystem, the state backend or any binding (FK-50 §50.2).

The mode is a typed enum rather than a string flag (typed-not-strings guardrail,
story §5): a handler branches on :meth:`ExecutionMode.mutations_allowed` instead
of comparing free strings.
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionMode(StrEnum):
    """Typed installer execution mode (FK-50 §50.2).

    Attributes:
        REGISTER: First registration AND idempotent re-run. The checkpoint
            sequence runs in full; handlers converge idempotently (already
            satisfied -> ``SKIPPED``/``PASS``, digest delta -> ``UPDATED``,
            absent -> ``CREATED``). The only mutating mode.
        DRY_RUN: Plan-only. Every handler reports the status the real
            ``REGISTER`` run WOULD produce but performs NO mutation
            (FK-50 §50.2). A planned ``CREATED``/``UPDATED`` carries the stable
            plan reason token ``planned_no_mutation`` plus a plan marker in
            ``detail`` so a consumer can tell "planned, not executed" from a
            real mutation result.
        VERIFY: Read-only verification of all checkpoints (FK-50 §50.2,
            CP 12-equivalent over the whole flow). Returns ``CheckpointResults``
            and never mutates.
    """

    REGISTER = "register"
    DRY_RUN = "dry_run"
    VERIFY = "verify"

    @property
    def mutations_allowed(self) -> bool:
        """Return whether handlers in this mode may perform mutations.

        Only :attr:`REGISTER` may mutate. :attr:`DRY_RUN` and :attr:`VERIFY`
        are guaranteed side-effect-free (FK-50 §50.2; story §2.1.3/§2.1.4).
        """
        return self is ExecutionMode.REGISTER


__all__ = ["ExecutionMode"]
