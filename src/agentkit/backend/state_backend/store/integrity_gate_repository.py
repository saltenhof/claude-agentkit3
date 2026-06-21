"""StateBackendIntegrityGateStateAdapter — IntegrityGateStatePort implementation.

Implements ``agentkit.backend.governance.repository.IntegrityGateStatePort`` using
the canonical ``state_backend.store.facade`` functions.  This keeps
``agentkit.backend.governance.integrity_gate`` decoupled from the state backend
(Architecture Conformance Fix E9, AG3-031 Pass-4).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentkit.backend.state_backend.store import facade

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from agentkit.backend.artifacts.envelope import ArtifactEnvelope
    from agentkit.backend.state_backend.scope import RuntimeStateScope


class StateBackendIntegrityGateStateAdapter:
    """Adapter from ``state_backend.store.facade`` to ``IntegrityGateStatePort``.

    All methods delegate directly to the facade; no business logic lives here.

    This class intentionally does not inherit from the Protocol class — it
    satisfies the structural (duck-typed) Protocol without formal inheritance,
    which avoids an import of ``agentkit.backend.governance.repository`` from this
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

    def validate_context_record(
        self,
        story_dir: Path,
        scope: RuntimeStateScope | None,
    ) -> str | None:
        """Validate the context record fields (FK-35 §35.2.4 Dim 2, Z. 268).

        FK-35 §35.2.4 Dim 2 (Z. 268) requires the ``ArtifactRecord(context)`` to
        be present, carry ``status == PASS``, a non-empty ``story_id`` AND a
        resolvable ``run_id``.  In AK3 the canonical context artifact is the
        ``StoryContext`` record in ``story_contexts`` (FK-35 §35.2.3 mandatory
        table; FK-22 §22.4: built and persisted by the Setup phase) — NOT a QA
        ``ArtifactEnvelope``, so the FK-71 §71.2 ``EnvelopeValidator`` does not
        apply.  The record itself carries no ``status`` column; its authoritative
        ``status == PASS`` is the **Setup phase snapshot completion** — the Setup
        phase is the producer that finalises the context (FK-22 §22.4), and its
        ``PhaseSnapshot.status == COMPLETED`` is the already-persisted, canonical
        PASS status (no second truth invented).  All four §35.2.4 Z. 268
        conditions are verified here with full depth (R3-F):

        * present (``StoryContext`` loadable),
        * ``status == PASS`` (Setup snapshot COMPLETED),
        * non-empty ``story_id``,
        * resolvable ``run_id`` (scope or ``facade.resolve_runtime_scope``).

        Any missing/invalid condition (incl. ``status != PASS``) returns a
        violation detail string -> Dim 2 fails closed ``CONTEXT_INVALID``;
        ``None`` only when the context record is fully valid.

        Args:
            story_dir: Story base directory.
            scope: Resolved runtime scope (provides ``run_id`` when present).

        Returns:
            A violation detail string, or ``None`` when the context is valid.
        """
        from agentkit.backend.exceptions import CorruptStateError

        ctx = facade.load_story_context(story_dir)
        if ctx is None:
            return "context record absent for field validation"
        if not ctx.story_id:
            return "context record carries no story_id (FK-35 §35.2.4 Dim 2)"
        # FK-35 §35.2.4 Dim 2 Z. 268 status == PASS: the context's authoritative
        # PASS status is the Setup phase having COMPLETED (the producer of the
        # context, FK-22 §22.4).  An absent/non-completed Setup snapshot means the
        # context was never finalised PASS -> fail-closed (R3-F).
        if not facade.backend_has_completed_snapshot(story_dir, "setup"):
            return (
                "context record status != PASS: Setup phase snapshot is absent or "
                "not COMPLETED (FK-35 §35.2.4 Dim 2 Z. 268)"
            )
        run_id = scope.run_id if scope is not None else None
        if run_id is None:
            try:
                run_id = facade.resolve_runtime_scope(story_dir).run_id
            except CorruptStateError:
                run_id = None
        if not run_id:
            return "context record has no resolvable run_id (FK-35 §35.2.4 Dim 2)"
        return None

    def load_context_finished_at(
        self,
        story_dir: Path,
        scope: RuntimeStateScope | None,
    ) -> datetime | None:
        """Return the ``story_contexts`` record completion timestamp (FK-35 Dim 8).

        Reads the canonical context record via ``facade.load_story_context`` and
        returns its authoritative completion timestamp (``created_at``).  The
        ``scope`` is accepted for protocol symmetry; the context is keyed by
        ``story_dir`` (one canonical record per story).

        Args:
            story_dir: Story base directory.
            scope: Resolved runtime scope (unused; context is story-keyed).

        Returns:
            The context record's ``created_at``, or ``None`` when absent.
        """
        del scope  # Context is the single canonical story-keyed record.
        ctx = facade.load_story_context(story_dir)
        if ctx is None:
            return None
        return ctx.created_at

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

    def find_latest_qa_envelope(
        self,
        story_dir: Path,
        scope: RuntimeStateScope | None,
        stage: str,
    ) -> ArtifactEnvelope | None:
        """Delegate to ``facade.find_latest_qa_envelope``.

        Args:
            story_dir: Story base directory.
            scope: Resolved runtime scope (or None).
            stage: QA layer stage id.

        Returns:
            The latest QA ``ArtifactEnvelope`` for the stage, or None.
        """
        from agentkit.backend.artifacts.envelope import ArtifactEnvelope as _Envelope

        envelope = facade.find_latest_qa_envelope(story_dir, scope, stage)
        if envelope is None:
            return None
        if not isinstance(envelope, _Envelope):  # pragma: no cover - defensive
            return None
        return envelope

    def has_active_conflict_freeze(
        self,
        story_dir: Path,
        scope: RuntimeStateScope | None,
    ) -> bool:
        """Return whether the story currently has an active conflict-freeze."""
        del scope
        ctx = facade.load_story_context(story_dir)
        if ctx is None:
            return False
        from agentkit.backend.state_backend.store.freeze_repository import FreezeRepository

        return FreezeRepository(story_dir).read_freeze(ctx.story_id) is not None

    def has_conflict_freeze_proof(
        self,
        story_dir: Path,
        scope: RuntimeStateScope | None,
    ) -> bool:
        """Return whether the active run has a persisted conflict-freeze proof."""
        resolved = scope
        if resolved is None:
            try:
                resolved = facade.resolve_runtime_scope(story_dir)
            except Exception:  # noqa: BLE001 -- unresolvable scope has no proof
                return False
        from agentkit.backend.state_backend.store.conflict_freeze_proof_repository import (
            ConflictFreezeProofRepository,
        )

        if resolved.run_id is None:
            return False
        proof = ConflictFreezeProofRepository(story_dir).latest_for_run(
            resolved.project_key,
            resolved.story_id,
            resolved.run_id,
        )
        return proof is not None


__all__ = ["StateBackendIntegrityGateStateAdapter"]
