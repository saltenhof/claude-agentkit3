"""StateBackendIntegrityGateStateAdapter — IntegrityGateStatePort implementation.

Implements ``agentkit.governance.repository.IntegrityGateStatePort`` using
the canonical ``state_backend.store.facade`` functions.  This keeps
``agentkit.governance.integrity_gate`` decoupled from the state backend
(Architecture Conformance Fix E9, AG3-031 Pass-4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.state_backend.store import facade

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.state_backend.scope import RuntimeStateScope


class StateBackendIntegrityGateStateAdapter:
    """Adapter from ``state_backend.store.facade`` to ``IntegrityGateStatePort``.

    All methods delegate directly to the facade; no business logic lives here.

    This class intentionally does not inherit from the Protocol class — it
    satisfies the structural (duck-typed) Protocol without formal inheritance,
    which avoids an import of ``agentkit.governance.repository`` from this
    module (direction: state_backend -> governance would be a layering
    violation).

    Args:
        No constructor arguments required; the facade resolves the active
        backend via ``load_state_backend_config()``.
    """

    def has_completed_snapshot(self, story_dir: Path, phase: str) -> bool:
        """Delegate to ``facade.backend_has_completed_snapshot``.

        Args:
            story_dir: Story base directory.
            phase: Phase name.

        Returns:
            True when a completed snapshot exists.
        """
        return facade.backend_has_completed_snapshot(story_dir, phase)

    def has_structural_artifact(self, story_dir: Path) -> bool:
        """Delegate to ``facade.backend_has_structural_artifact``.

        Args:
            story_dir: Story base directory.

        Returns:
            True when the structural artifact record is present.
        """
        return facade.backend_has_structural_artifact(story_dir)

    def has_structural_artifact_for_scope(
        self, scope: RuntimeStateScope
    ) -> bool:
        """Delegate to ``facade.backend_has_structural_artifact_for_scope``.

        Args:
            scope: Runtime state scope.

        Returns:
            True when the structural artifact record is present for the scope.
        """
        return facade.backend_has_structural_artifact_for_scope(scope)

    def has_valid_context(self, story_dir: Path) -> bool:
        """Delegate to ``facade.backend_has_valid_context``.

        Args:
            story_dir: Story base directory.

        Returns:
            True when a valid story context exists.
        """
        return facade.backend_has_valid_context(story_dir)

    def has_valid_phase_state(self, story_dir: Path) -> bool:
        """Delegate to ``facade.backend_has_valid_phase_state``.

        Args:
            story_dir: Story base directory.

        Returns:
            True when a valid phase state exists.
        """
        return facade.backend_has_valid_phase_state(story_dir)

    def load_latest_verify_decision(
        self,
        story_dir: Path,
    ) -> dict[str, object] | None:
        """Delegate to ``facade.load_latest_verify_decision``.

        Args:
            story_dir: Story base directory.

        Returns:
            Raw JSON payload dict or None.
        """
        return facade.load_latest_verify_decision(story_dir)

    def load_latest_verify_decision_for_scope(
        self,
        scope: RuntimeStateScope,
    ) -> dict[str, object] | None:
        """Delegate to ``facade.load_latest_verify_decision_for_scope``.

        Args:
            scope: Runtime state scope.

        Returns:
            Raw JSON payload dict or None.
        """
        return facade.load_latest_verify_decision_for_scope(scope)

    def read_phase_state_record(
        self,
        story_dir: Path,
    ) -> object | None:
        """Delegate to ``facade.read_phase_state_record``.

        Args:
            story_dir: Story base directory.

        Returns:
            The phase state object or None.
        """
        return facade.read_phase_state_record(story_dir)

    def resolve_runtime_scope(self, story_dir: Path) -> RuntimeStateScope:
        """Delegate to ``facade.resolve_runtime_scope``.

        Args:
            story_dir: Story base directory.

        Returns:
            A ``RuntimeStateScope``.

        Raises:
            CorruptStateError: When scope cannot be resolved.
        """
        return facade.resolve_runtime_scope(story_dir)


__all__ = ["StateBackendIntegrityGateStateAdapter"]
