"""Repository protocols for the governance BC.

This module defines the ``HookRegistrationRepository`` Protocol so that
``Governance`` (runner.py) can depend on the abstraction rather than
importing directly from ``state_backend.store`` (Architecture Conformance AK8).

Concrete implementations live in ``state_backend.store.governance_hook_repository``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.governance.hook_registration import HookDefinition, RegistrationResult


@runtime_checkable
class HookRegistrationRepository(Protocol):
    """Persistence protocol for hook-definition registration.

    Implementations must be SQLite/Postgres-backed; the protocol keeps
    the governance BC decoupled from the state-backend infrastructure.

    All methods are idempotent: repeated calls with identical inputs
    produce the same outcome.
    """

    def register(
        self,
        project_key: str,
        hook_definitions: list[HookDefinition],
    ) -> RegistrationResult:
        """Persist ``hook_definitions`` for ``project_key``.

        Uses INSERT OR IGNORE / ON CONFLICT DO NOTHING semantics.
        Unchanged rows are reported as ``skipped``; new rows as ``registered``.

        Args:
            project_key: Owning project key.
            hook_definitions: Hook definitions to persist.

        Returns:
            ``RegistrationResult`` with registered/skipped/errors lists.

        Raises:
            Exception: On unrecoverable backend failures.
        """
        ...

    def list_for_project(
        self,
        project_key: str,
    ) -> list[HookDefinition]:
        """Return all registered hook definitions for ``project_key``.

        Args:
            project_key: Owning project key.

        Returns:
            List of ``HookDefinition`` objects, possibly empty.
        """
        ...

    def clear_for_project(self, project_key: str) -> None:
        """Delete all hook registrations for ``project_key`` (test helper).

        Args:
            project_key: Owning project key.
        """
        ...


__all__ = ["HookRegistrationRepository"]
