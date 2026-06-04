"""ProjectRegistrationRepository Protocol (FK-50 §50.3 CP 7).

The installer (BC 12) depends only on this Protocol — never on a concrete
state-backend adapter. The productive SQLite/Postgres implementation lives in
``agentkit.state_backend.store.project_registration_repository`` and is wired in
the composition root, keeping the BC boundary intact (story §2.1.9, AC9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from agentkit.installer.registration import ProjectRegistration


@runtime_checkable
class ProjectRegistrationRepository(Protocol):
    """Persistence port for :class:`ProjectRegistration` records (CP 7).

    The five-method surface from story §2.1.3. ``get``/``list_all`` are the
    read path; ``save`` is the initial registration; ``update_verified`` and
    ``update_upgraded`` are the in-place lifecycle mutations (verify / upgrade).
    """

    def get(self, project_key: str) -> ProjectRegistration | None:
        """Return the registration for ``project_key``, or ``None`` if absent."""
        ...

    def save(self, registration: ProjectRegistration) -> None:
        """Insert a new registration (initial CP 7 registration)."""
        ...

    def update_verified(self, project_key: str, verified_at: datetime) -> None:
        """Set ``last_verified_at`` for an existing registration."""
        ...

    def update_upgraded(
        self, project_key: str, upgraded_at: datetime, new_digest: str
    ) -> None:
        """Set ``last_upgraded_at`` and the new ``config_digest`` (upgrade path)."""
        ...

    def list_all(self) -> list[ProjectRegistration]:
        """Return all registrations (deterministically ordered)."""
        ...


__all__ = ["ProjectRegistrationRepository"]
