"""ArtifactManager — top-surface for artifact read/write coordination.

The only authorized write entrypoint for artifact persistence in the
artifact BC. All producer BCs write exclusively through this class;
direct access to ``ArtifactRepository`` implementations is only allowed
within the ``state_backend`` BC.

Fail-closed semantics:
- ``write`` validates the envelope before persistence; partial writes
  are not possible.
- ``read`` raises ``ArtifactNotFoundError`` on non-existence (no silent
  None return).
- ``exists`` is the only reading path without an error guarantee.

bc-cut-decisions.md §BC 8, FK-71 §71.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.artifacts.errors import ArtifactNotFoundError

if TYPE_CHECKING:
    from agentkit.artifacts.envelope import ArtifactEnvelope
    from agentkit.artifacts.reference import ArtifactReference
    from agentkit.artifacts.repository import ArtifactRepository
    from agentkit.artifacts.validator import EnvelopeValidator
    from agentkit.core_types import ArtifactClass


class ArtifactManager:
    """Top-surface for typed artifact persistence.

    Coordinates validation (``EnvelopeValidator``) and persistence
    (``ArtifactRepository``). No producer BC should use the repository
    adapter directly; instead it receives an ArtifactManager via
    dependency injection.

    Args:
        repository: Persistence backend (SQLite or Postgres).
        validator: Envelope validator (five check steps, AG3-022).

    Performance note: ``write`` does no additional ``read`` roundtrip
    after writing (no double hit).
    """

    def __init__(
        self,
        repository: ArtifactRepository,
        validator: EnvelopeValidator,
    ) -> None:
        self._repository = repository
        self._validator = validator

    def write(self, envelope: ArtifactEnvelope) -> ArtifactReference:
        """Validate and persist an ArtifactEnvelope.

        Step 1: ``EnvelopeValidator.validate`` — fails closed on any
            validation violation (no partial write).
        Step 2: ``ArtifactRepository.write_envelope`` — atomic
            persistence.

        Args:
            envelope: ArtifactEnvelope to persist, with all required
                fields.

        Returns:
            ``ArtifactReference`` — opaque reference to the entry.

        Raises:
            ProducerNotRegisteredError: When the producer is unknown.
            ProducerTypeMismatchError: When the producer type is wrong.
            EnvelopeFieldError: When a required field is invalid.
            Exception: Backend error from the repository implementation.
        """
        # Step 1: validation — fail-closed, raises a specific exception.
        self._validator.validate(envelope)
        # Step 2: atomic persistence — no read roundtrip afterwards.
        return self._repository.write_envelope(envelope)

    def read(self, reference: ArtifactReference) -> ArtifactEnvelope:
        """Load an ArtifactEnvelope by its Reference.

        Args:
            reference: Opaque Reference (return value of ``write``).

        Returns:
            Stored ArtifactEnvelope.

        Raises:
            ArtifactNotFoundError: When no artifact with this Reference
                exists (fail-closed; no silent None).
        """
        result = self._repository.read_envelope(reference)
        if result is None:
            msg = (
                f"No artifact found for reference: "
                f"artifact_class={reference.artifact_class!r}, "
                f"story_id={reference.story_id!r}, "
                f"run_id={reference.run_id!r}, "
                f"record_key={reference.record_key!r}"
            )
            raise ArtifactNotFoundError(msg)
        return result

    def read_latest(
        self,
        *,
        story_id: str,
        run_id: str | None,
        artifact_class: ArtifactClass,
        stage: str,
    ) -> ArtifactEnvelope:
        """Load the highest-attempt envelope in the (story, run, class, stage) scope.

        Args:
            story_id: Story display id.
            run_id: Run correlation id; ``None`` matches across all runs.
            artifact_class: Producer-class filter.
            stage: Stage filter.

        Returns:
            ``ArtifactEnvelope`` with the highest ``attempt`` in the scope.

        Raises:
            ArtifactNotFoundError: When no envelope exists in the scope
                (fail-closed; no silent None).
        """
        result = self._repository.find_latest_envelope(
            story_id=story_id,
            run_id=run_id,
            artifact_class=artifact_class,
            stage=stage,
        )
        if result is None:
            msg = (
                "No artifact in scope: "
                f"story_id={story_id!r}, run_id={run_id!r}, "
                f"artifact_class={artifact_class!r}, stage={stage!r}"
            )
            raise ArtifactNotFoundError(msg)
        return result

    def exists(self, reference: ArtifactReference) -> bool:
        """Check whether an artifact with this Reference exists.

        Read-only path without an error guarantee (backend errors
        propagate directly from the repository implementation).

        Args:
            reference: Opaque Reference.

        Returns:
            True if present, False otherwise.
        """
        return self._repository.exists_envelope(reference)


__all__ = ["ArtifactManager"]
