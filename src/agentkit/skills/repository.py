"""SkillBindingRepository protocol and InMemory implementation (AG3-027).

Productive SQLite/Postgres persistence is deferred to AG3-048.  This module
provides:

* ``SkillBindingRepository`` — the storage-port Protocol used by the
  ``Skills`` top-surface.
* ``InMemorySkillBindingRepository`` — a testable in-memory implementation
  suitable for unit- and contract-tests.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.skills.binding import SkillBinding


@runtime_checkable
class SkillBindingRepository(Protocol):
    """Storage port for ``SkillBinding`` records.

    Implementations must satisfy this protocol for use with ``Skills``.
    The full production implementation (Postgres + SQLite) is delivered in
    AG3-048.
    """

    def save(self, binding: SkillBinding) -> None:
        """Persist or update a ``SkillBinding`` record.

        Args:
            binding: The binding to save. If a binding with the same
                ``(project_key, skill_name)`` pair already exists it is
                replaced.
        """
        ...

    def load(self, project_key: str, skill_name: str) -> SkillBinding | None:
        """Load a single binding by its natural key.

        Args:
            project_key: Target project key.
            skill_name: Logical skill name.

        Returns:
            The matching ``SkillBinding`` or ``None`` if not found.
        """
        ...

    def list_for_project(self, project_key: str) -> list[SkillBinding]:
        """Return all bindings for a given project, sorted deterministically.

        Args:
            project_key: Target project key.

        Returns:
            List of ``SkillBinding`` objects sorted by ``skill_name``.
        """
        ...


class InMemorySkillBindingRepository:
    """In-memory implementation of ``SkillBindingRepository``.

    Intended for unit- and contract-tests only. Not thread-safe.
    """

    def __init__(self) -> None:
        # Keyed by (project_key, skill_name) for O(1) lookup.
        self._store: dict[tuple[str, str], SkillBinding] = {}

    def save(self, binding: SkillBinding) -> None:
        """Persist or replace a ``SkillBinding``.

        Args:
            binding: The binding to store.
        """
        self._store[(binding.project_key, binding.skill_name)] = binding

    def load(self, project_key: str, skill_name: str) -> SkillBinding | None:
        """Load a single binding by natural key.

        Args:
            project_key: Target project key.
            skill_name: Logical skill name.

        Returns:
            The matching ``SkillBinding`` or ``None``.
        """
        return self._store.get((project_key, skill_name))

    def list_for_project(self, project_key: str) -> list[SkillBinding]:
        """Return all bindings for a project, sorted by ``skill_name``.

        Args:
            project_key: Target project key.

        Returns:
            Sorted list of ``SkillBinding`` objects.
        """
        return sorted(
            (b for b in self._store.values() if b.project_key == project_key),
            key=lambda b: b.skill_name,
        )
