"""Guard runner -- evaluates all registered guards for an operation.

Orchestration only (ARCH-12). Business logic lives in individual guards.
The runner is fail-closed: if any guard blocks, the operation is blocked.
All guards run even if earlier ones block, so that complete violation
information is collected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentkit.governance.protocols import GovernanceGuard, GuardVerdict


class GuardRunner:
    """Runs all registered guards for an operation.

    Fail-closed semantics: if **any** guard blocks, the operation is
    blocked.  All guards are evaluated even when earlier ones already
    blocked, so that complete violation information is available.

    An empty runner (no guards registered) allows everything -- there
    are no rules to violate.
    """

    def __init__(
        self, guards: list[GovernanceGuard] | None = None,
    ) -> None:
        self._guards: list[GovernanceGuard] = list(guards) if guards else []

    def register(self, guard: GovernanceGuard) -> None:
        """Add a guard to the evaluation pipeline.

        Args:
            guard: A ``GovernanceGuard`` implementation to register.
        """
        self._guards.append(guard)

    def evaluate(
        self, operation: str, context: dict[str, object],
    ) -> list[GuardVerdict]:
        """Evaluate all guards. Returns list of all verdicts.

        Even if the first guard blocks, all remaining guards still run
        (to collect complete violation information).

        Args:
            operation: The operation type being attempted.
            context: Operation-specific context dict.

        Returns:
            List of ``GuardVerdict`` instances, one per registered guard.
        """
        return [g.evaluate(operation, context) for g in self._guards]

    def is_allowed(
        self, operation: str, context: dict[str, object],
    ) -> tuple[bool, list[GuardVerdict]]:
        """Check if an operation is allowed.

        Convenience wrapper around :meth:`evaluate` that also returns a
        boolean summary.

        Args:
            operation: The operation type being attempted.
            context: Operation-specific context dict.

        Returns:
            A ``(allowed, verdicts)`` tuple where ``allowed`` is ``True``
            only if every guard returned ``ALLOW``.
        """
        verdicts = self.evaluate(operation, context)
        allowed = all(v.allowed for v in verdicts)
        return allowed, verdicts
