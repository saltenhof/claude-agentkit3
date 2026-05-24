"""Repository protocols for the governance BC.

This module defines the repository Protocol interfaces so that governance
BC modules can depend on abstractions rather than importing directly from
``state_backend.store`` (Architecture Conformance AK8).

Protocols defined here:
- ``HookRegistrationRepository``: hook-definition registration (pre-existing).
- ``IntegrityGateStatePort``: read-only state access for IntegrityGate (Fix E9).
- ``SetupContextRepository``: story-context write access for SetupPhaseHandler (Fix E9).
- ``WorktreeRepository``: worktree path resolution for Governance.deactivate_locks (Fix E4).

Concrete implementations live in ``state_backend.store.*_repository``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.governance.hook_registration import HookDefinition, RegistrationResult
    from agentkit.state_backend.scope import RuntimeStateScope
    from agentkit.story_context_manager.models import StoryContext


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

        UPSERT semantics (Fix E3, AG3-031 Pass-3 FK-30 §30.3.1):
        - Identical ``(project_key, hook_event_name, matcher, command)`` tuples
          are reported as ``skipped`` (no DB write).
        - Changed ``command`` or new ``matcher`` → INSERT OR REPLACE / ON CONFLICT
          DO UPDATE; reported as ``registered``.

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


@runtime_checkable
class IntegrityGateStatePort(Protocol):
    """Read-only state access protocol for ``IntegrityGate`` (Fix E9).

    Abstracts all ``state_backend.store`` predicate calls used by
    ``IntegrityGate.evaluate``.  Implementations live in
    ``state_backend.store.integrity_gate_repository``.

    The protocol keeps ``agentkit.governance.integrity_gate`` decoupled
    from the state-backend infrastructure (Architecture Conformance).
    """

    def has_completed_snapshot(self, story_dir: Path, phase: str) -> bool:
        """Return True when the given phase has a completed canonical snapshot.

        Args:
            story_dir: Story base directory.
            phase: Phase name (e.g. ``"setup"``, ``"implementation"``).

        Returns:
            True when a completed snapshot exists; False otherwise.

        Raises:
            CorruptStateError: When the backend record is unreadable.
        """
        ...

    def has_structural_artifact(self, story_dir: Path) -> bool:
        """Return True when a structural QA artifact record exists.

        Args:
            story_dir: Story base directory.

        Returns:
            True when the record is present; False otherwise.

        Raises:
            CorruptStateError: When the backend record is unreadable.
        """
        ...

    def has_structural_artifact_for_scope(self, scope: RuntimeStateScope) -> bool:
        """Scope-narrowed variant of ``has_structural_artifact``.

        Args:
            scope: Runtime state scope narrowing the read to a specific run_id.

        Returns:
            True when the record is present for the given scope.

        Raises:
            CorruptStateError: When the backend record is unreadable.
        """
        ...

    def has_valid_context(self, story_dir: Path) -> bool:
        """Return True when a valid story context record exists.

        Args:
            story_dir: Story base directory.

        Returns:
            True when a valid story context is found.

        Raises:
            CorruptStateError: When the backend record is unreadable.
        """
        ...

    def has_valid_phase_state(self, story_dir: Path) -> bool:
        """Return True when a valid phase state record exists.

        Args:
            story_dir: Story base directory.

        Returns:
            True when a valid phase state is found.

        Raises:
            CorruptStateError: When the backend record is unreadable.
        """
        ...

    def load_latest_verify_decision(
        self,
        story_dir: Path,
    ) -> dict[str, object] | None:
        """Load the latest verify decision payload for a story directory.

        Args:
            story_dir: Story base directory.

        Returns:
            Raw JSON payload dict or None when absent.

        Raises:
            CorruptStateError: When the backend record is unreadable.
        """
        ...

    def load_latest_verify_decision_for_scope(
        self,
        scope: RuntimeStateScope,
    ) -> dict[str, object] | None:
        """Scope-narrowed variant of ``load_latest_verify_decision``.

        Args:
            scope: Runtime state scope narrowing the read to a specific run_id.

        Returns:
            Raw JSON payload dict or None when absent.

        Raises:
            CorruptStateError: When the backend record is unreadable.
        """
        ...

    def read_phase_state_record(
        self,
        story_dir: Path,
    ) -> object | None:
        """Read the raw phase state record for a story directory.

        Args:
            story_dir: Story base directory.

        Returns:
            The phase state object (``PhaseState``) or None when absent.

        Raises:
            CorruptStateError: When the backend record is unreadable.
        """
        ...

    def resolve_runtime_scope(self, story_dir: Path) -> RuntimeStateScope:
        """Resolve the current runtime scope for a story directory.

        Args:
            story_dir: Story base directory.

        Returns:
            A ``RuntimeStateScope`` with project_key, story_id, run_id etc.

        Raises:
            CorruptStateError: When neither FlowExecution nor StoryContext
                can be resolved.
        """
        ...


@runtime_checkable
class SetupContextRepository(Protocol):
    """Story-context write protocol for ``SetupPhaseHandler`` (Fix E9).

    Abstracts the ``save_story_context`` call used by
    ``setup_preflight_gate.phase``.  Implementations live in
    ``state_backend.store.setup_context_repository``.

    The protocol keeps ``agentkit.governance.setup_preflight_gate``
    decoupled from the state-backend infrastructure.
    """

    def save(self, story_dir: Path, ctx: StoryContext) -> None:
        """Persist ``ctx`` to the canonical state backend for ``story_dir``.

        Args:
            story_dir: Story base directory (scopes the write).
            ctx: The ``StoryContext`` to persist.

        Raises:
            Exception: On unrecoverable backend failures.
        """
        ...


@runtime_checkable
class WorktreeRepository(Protocol):
    """Worktree-path resolution protocol for ``Governance.deactivate_locks`` (Fix E4).

    ``Governance._restore_ai_augmented_mode`` must iterate over all
    worktree paths associated with a story so it can clear
    ``.agent-guard/lock.json`` and write the ``ai_augmented`` mode marker
    in each worktree (FK-30 §30.6.0 + FK-22 §22.7).

    Implementations may source worktree paths from the ``StoryContext``
    stored in the state backend (``worktree_map`` field), the
    ``story_execution_locks`` table (``worktree_roots_json``), or any
    equivalent authoritative source.
    """

    def list_worktree_paths(
        self,
        story_id: str,
    ) -> list[Path]:
        """Return all filesystem paths of active worktrees for ``story_id``.

        Args:
            story_id: Canonical story identifier.

        Returns:
            List of ``Path`` objects pointing to worktree root directories.
            Empty list when the story has no worktrees (e.g. CONCEPT type).
        """
        ...


__all__ = [
    "HookRegistrationRepository",
    "IntegrityGateStatePort",
    "SetupContextRepository",
    "WorktreeRepository",
]
