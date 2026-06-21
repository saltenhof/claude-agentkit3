"""ArtifactRepository — Protocol for artifact persistence.

Bounded-context boundary: the ``agentkit.backend.artifacts`` BC defines the
Protocol; concrete implementations live in
``agentkit.backend.state_backend.store.artifact_repository``. The Protocol
itself imports **exclusively** from ``agentkit.backend.artifacts`` and
``agentkit.backend.core_types`` (no backend imports in the contract module).

bc-cut-decisions.md §BC 8 — ArtifactManager contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agentkit.backend.artifacts.envelope import ArtifactEnvelope
    from agentkit.backend.artifacts.reference import ArtifactReference
    from agentkit.backend.core_types import ArtifactClass


@runtime_checkable
class ArtifactRepository(Protocol):
    """Protocol for typed artifact persistence.

    Implementations live in ``agentkit.backend.state_backend.store.artifact_repository``
    (SQLite, Postgres). The Protocol is to be imported exclusively by
    ``ArtifactManager`` and tests — never by producers or consumers
    directly.

    Methods:
        write_envelope: Writes a valid ArtifactEnvelope; returns an
            ArtifactReference.
        read_envelope: Loads an envelope by a Reference; returns
            ``None`` on non-existence.
        find_latest_envelope: Finds the highest ``attempt`` for a
            (story_id, run_id, artifact_class, stage) scope and returns
            the envelope or ``None``.
        exists_envelope: Checks existence without a full read.
    """

    def write_envelope(
        self,
        envelope: ArtifactEnvelope,
    ) -> ArtifactReference:
        """Persist a valid ArtifactEnvelope (fail-closed).

        Args:
            envelope: Fully validated ArtifactEnvelope.

        Returns:
            Opaque reference to the written entry.

        Raises:
            Exception: Implementation-specific error on I/O problems or
                constraint violations.
        """
        ...

    def read_envelope(
        self,
        reference: ArtifactReference,
    ) -> ArtifactEnvelope | None:
        """Load an ArtifactEnvelope by its Reference.

        Args:
            reference: Opaque Reference (return value of ``write_envelope``).

        Returns:
            ArtifactEnvelope if present, otherwise ``None``.
        """
        ...

    def find_latest_envelope(
        self,
        *,
        story_id: str,
        run_id: str | None,
        artifact_class: ArtifactClass,
        stage: str,
    ) -> ArtifactEnvelope | None:
        """Find the envelope with the highest ``attempt`` in the scope.

        Args:
            story_id: Story display id.
            run_id: Run correlation id; ``None`` matches across all runs.
            artifact_class: Producer-class filter.
            stage: Stage filter (e.g. ``qa-policy-decision``).

        Returns:
            Latest ``ArtifactEnvelope`` or ``None``.
        """
        ...

    def exists_envelope(
        self,
        reference: ArtifactReference,
    ) -> bool:
        """Check whether an artifact with this Reference exists.

        Args:
            reference: Opaque Reference.

        Returns:
            True if present, False otherwise.
        """
        ...


__all__ = ["ArtifactRepository"]
