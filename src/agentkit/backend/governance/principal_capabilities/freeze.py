"""Conflict-freeze overlay with dual materialization (FK-55 §55.8/§55.10.5, FK-31 §31.2.7).

When a story is in ``conflict_freeze`` (HARD-STOP after ``normative_conflict`` /
``authoritative_snapshot_divergence``), the overlay further restricts the base
capability verdict regardless of the matrix default (FK-55 §55.8.1):

- ``orchestrator`` loses ALL story-scoped mutation rights (write / git_mutation
  / curate / admin_transition) — FK-55 §55.10.6 / invariant
  ``freeze_removes_orchestrator_mutation_rights``.
- ``worker`` / ``qa_reader`` / ``adversarial_writer`` may not create new
  productive progress while frozen (write / execute / git_mutation / curate /
  admin_transition are blocked) — FK-55 §55.8.1.
- only ``human_cli`` / ``pipeline_deterministic`` / ``admin_service`` may
  continue via official paths — invariant
  ``only_official_service_or_human_cli_may_mutate_during_freeze``.

Dual materialization (FK-55 §55.10.5 / FK-31 §31.2.7 / invariant
``freeze_has_backend_record_and_local_export``): the freeze is the canonical
backend record (truth, via the injected :class:`FreezeStore`) AND a local
hook-readable export ``.agentkit/governance/freeze.json`` with a matching
``freeze_version`` (via the injected :class:`LocalFreezeExport`). Activation
writes the backend record first, then the export (atomic ordering, §55.10.5).

BOTH materializations are consulted on every read (:meth:`is_frozen`). A
stale / missing / mismatched local export versus the backend record is NOT a
silent pass: per §55.10.5 "a call with a stale or missing freeze context is
blocked" the overlay treats any disagreement as *frozen* (fail-closed —
block mutations).

AK10 (AG3-032): this package imports only ``core_types`` and
``guard_evaluation`` (+ same-package). The freeze.json byte-level read/write
therefore lives behind the injected :class:`LocalFreezeExport` boundary (its
production implementation is wired in from ``state_backend`` /
``freeze_repository``), NOT via a direct ``agentkit.backend.utils.io`` import here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from agentkit.backend.core_types.plane_artifact_names import GOVERNANCE_FREEZE_EXPORT_PARTS
from agentkit.backend.governance.principal_capabilities.matrix import (
    CapabilityDecision,
    CapabilityVerdict,
)
from agentkit.backend.governance.principal_capabilities.operations import OperationClass
from agentkit.backend.governance.principal_capabilities.principals import Principal

#: Local freeze export, relative to the project root (FK-31 §31.2.7 / AG3-023).
#: Sourced from ``core_types.plane_artifact_names`` — the single source of truth
#: for the governance-plane freeze path. No path literal lives in this protected
#: governance module (CLAUDE.md SINGLE SOURCE OF TRUTH / Truth-Boundary).
FREEZE_EXPORT_RELPATH = Path(*GOVERNANCE_FREEZE_EXPORT_PARTS)

#: Mutating operation classes that a freeze blocks (FK-55 §55.10.6 / §55.8.1).
_MUTATING_OPS: frozenset[OperationClass] = frozenset(
    {
        OperationClass.WRITE,
        OperationClass.EXECUTE,
        OperationClass.GIT_MUTATION,
        OperationClass.CURATE,
        OperationClass.ADMIN_TRANSITION,
    }
)

#: Principals whose mutations are blocked while a freeze is active. The official
#: service / human principals are exempt (they continue via official paths).
_FROZEN_PRINCIPALS: frozenset[Principal] = frozenset(
    {
        Principal.ORCHESTRATOR,
        Principal.WORKER,
        Principal.QA_READER,
        Principal.ADVERSARIAL_WRITER,
        Principal.INTERACTIVE_AGENT,
        Principal.LLM_EVALUATOR,
    }
)

_FREEZE_RULE_ID = "FK-55-55.10.6"
_FREEZE_REASON = "conflict_freeze active: mutation blocked for non-official principal"


@runtime_checkable
class FreezeStore(Protocol):
    """Canonical freeze persistence contract (implemented by FreezeRepository).

    Injected so the capability package does not import ``state_backend`` directly
    (AG3-032 AK10 — the package imports only ``core_types`` and
    ``guard_evaluation``).
    """

    def set_freeze(
        self,
        story_id: str,
        *,
        frozen_at: str,
        freeze_reason: str,
        freeze_version: int,
    ) -> object:
        """Persist the canonical freeze record."""
        ...

    def read_freeze(self, story_id: str) -> object | None:
        """Return the canonical freeze record, or ``None``."""
        ...

    def clear_freeze(self, story_id: str) -> int:
        """Delete the canonical freeze record; return rows removed."""
        ...


@runtime_checkable
class ConflictFreezeProofStore(Protocol):
    """Canonical conflict-freeze proof persistence contract."""

    def save(self, record: object) -> None:
        """Persist the canonical conflict-freeze proof record."""
        ...


@runtime_checkable
class LocalFreezeExport(Protocol):
    """Local hook-readable freeze-export boundary (FK-55 §55.10.5 / FK-31 §31.2.7).

    Encapsulates the byte-level read/write of ``.agentkit/governance/freeze.json``
    so the capability package itself does not import a filesystem-IO helper
    (AG3-032 AK10). The production implementation is wired in from the
    ``state_backend`` side (see ``freeze_repository.LocalFreezeJsonExport``).
    """

    def write(
        self,
        story_id: str,
        *,
        frozen_at: str,
        freeze_reason: str,
        freeze_version: int,
    ) -> None:
        """Atomically write the local freeze export."""
        ...

    def read(self) -> dict[str, object] | None:
        """Return the local export payload, or ``None`` when absent.

        Raises:
            Exception: When the export exists but cannot be parsed (a corrupt
                export is a fault, not a soft fallback — FAIL-CLOSED).
        """
        ...

    def remove(self) -> None:
        """Remove the local freeze export if present."""
        ...


def _frozen_at_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


class ConflictFreezeOverlay:
    """Applies the story-scoped conflict-freeze on top of a base verdict.

    Args:
        store: Canonical freeze persistence (the truth side of the dual
            materialization). When ``None``, the overlay operates export-only
            (the local export is the sole record); production wiring always
            supplies the backend store.
        local_export: The local freeze-export boundary. When ``None`` the
            overlay degrades to backend-only consultation; production wiring
            always supplies the export so BOTH materializations are consulted
            (FK-55 §55.10.5 / invariant ``freeze_has_backend_record_and_local_export``).
    """

    def __init__(
        self,
        store: FreezeStore | None = None,
        *,
        local_export: LocalFreezeExport | None = None,
        proof_store: ConflictFreezeProofStore | None = None,
        project_key: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self._store = store
        self._local_export = local_export
        self._proof_store = proof_store
        self._project_key = project_key
        self._run_id = run_id

    # -- activation / release ------------------------------------------------

    def freeze(
        self,
        story_id: str,
        *,
        reason: str,
        freeze_version: int,
        blocked_principal: str | None = None,
        resolution_service_path: str | None = None,
    ) -> None:
        """Activate a conflict-freeze for ``story_id`` with dual materialization.

        FK-55 §55.10.5 atomic ordering: persist the canonical backend record
        FIRST, then write the local export with the same ``freeze_version``.

        Args:
            story_id: Canonical story identifier.
            reason: HARD-STOP signal (e.g. ``"normative_conflict"``).
            freeze_version: Monotonic freeze version for the local export.
            blocked_principal: Principal blocked by the freeze proof.
            resolution_service_path: Official path used for resolution.
        """
        frozen_at = _frozen_at_now()
        if self._store is not None:
            self._store.set_freeze(
                story_id,
                frozen_at=frozen_at,
                freeze_reason=reason,
                freeze_version=freeze_version,
            )
        if self._local_export is not None:
            self._local_export.write(
                story_id,
                frozen_at=frozen_at,
                freeze_reason=reason,
                freeze_version=freeze_version,
            )
        self._write_proof(
            story_id,
            activated_at=frozen_at,
            blocked_principal=blocked_principal,
            resolution_service_path=resolution_service_path,
        )

    def release(self, story_id: str) -> None:
        """Release a freeze: clear the backend record and remove the export."""
        if self._store is not None:
            self._store.clear_freeze(story_id)
        if self._local_export is not None:
            self._local_export.remove()

    # -- queries -------------------------------------------------------------

    def is_frozen(self, story_id: str) -> bool:
        """Return whether ``story_id`` is frozen, consulting BOTH materializations.

        FK-55 §55.10.5 / FK-31 §31.2.7 / invariant
        ``freeze_has_backend_record_and_local_export``: an active freeze must
        exist BOTH as a canonical backend record AND as a local export with a
        matching ``freeze_version``. Consultation is fail-closed:

        - both agree there is NO freeze  → ``False`` (not frozen).
        - both agree there IS a freeze AND the freeze_versions match → ``True``.
        - any disagreement (one says frozen and the other is missing / for a
          different story / a mismatched freeze_version) → ``True`` (a stale or
          incomplete freeze context blocks — §55.10.5 "stale or missing
          → blocked").

        When the overlay is wired with only one side (no backend store, or no
        local export — test/degraded wiring) that single side is authoritative.
        """
        backend = self._backend_state(story_id)
        local = self._local_state(story_id)
        if self._store is not None and self._local_export is not None:
            # Frozen unless BOTH materializations agree there is no freeze. A
            # one-sided record (missing the other) and a freeze_version mismatch
            # are both stale/incoherent contexts → fail-closed (block).
            return not (backend is None and local is None)
        # Degraded single-side wiring: the present side is authoritative.
        if self._store is not None:
            return backend is not None
        if self._local_export is not None:
            return local is not None
        return False

    # -- overlay -------------------------------------------------------------

    def apply(
        self,
        base_verdict: CapabilityVerdict,
        principal: Principal,
        story_id: str,
        op_class: OperationClass,
    ) -> CapabilityVerdict:
        """Overlay the freeze on top of ``base_verdict`` (FK-55 §55.10.6).

        A freeze can only *tighten*: it never turns a base ``DENY`` into
        ``ALLOW``. If the story is frozen, the principal is a frozen (non-
        official) principal, and the operation is mutating, the result is
        ``DENY`` regardless of the base verdict.

        Args:
            base_verdict: The hard-matrix verdict to overlay.
            principal: The resolved principal.
            story_id: The active story identifier.
            op_class: The normalized operation class.

        Returns:
            ``base_verdict`` unchanged when the freeze does not apply, otherwise
            a freeze ``DENY``.
        """
        if base_verdict.decision is CapabilityDecision.DENY:
            return base_verdict
        if principal not in _FROZEN_PRINCIPALS:
            return base_verdict
        if op_class not in _MUTATING_OPS:
            return base_verdict
        if not self.is_frozen(story_id):
            return base_verdict
        return CapabilityVerdict.deny(_FREEZE_REASON, rule_id=_FREEZE_RULE_ID)

    # -- internal state reads ------------------------------------------------

    def _backend_state(self, story_id: str) -> int | None:
        """Backend freeze_version for ``story_id``, or ``None`` when not frozen."""
        if self._store is None:
            return None
        record = self._store.read_freeze(story_id)
        if record is None:
            return None
        return _record_freeze_version(record)

    def _local_state(self, story_id: str) -> int | None:
        """Local-export freeze_version for ``story_id``, or ``None``.

        Returns ``None`` when the export is absent or is for a different story.
        Raises (via the boundary) when the export exists but is corrupt — a
        corrupt freeze export is a fault, not a soft fallback (FAIL-CLOSED).
        """
        if self._local_export is None:
            return None
        from agentkit.backend.governance.principal_capabilities.errors import (
            FreezePersistenceError,
        )

        try:
            payload = self._local_export.read()
        except Exception as exc:  # corrupt/unreadable export → hard fault.
            raise FreezePersistenceError(
                f"corrupt local freeze export: {exc}"
            ) from exc
        if payload is None or payload.get("story_id") != story_id:
            return None
        version = payload.get("freeze_version")
        return version if isinstance(version, int) else None

    def _write_proof(
        self,
        story_id: str,
        *,
        activated_at: str,
        blocked_principal: str | None,
        resolution_service_path: str | None,
    ) -> None:
        """Persist a proof when all proof dependencies are wired."""
        if (
            self._proof_store is None
            or self._project_key is None
            or self._run_id is None
            or blocked_principal is None
            or resolution_service_path is None
        ):
            return
        from datetime import datetime
        from uuid import uuid4

        from agentkit.backend.governance.guard_system.records import (
            ConflictFreezeProofRecord,
        )

        self._proof_store.save(
            ConflictFreezeProofRecord(
                project_key=self._project_key,
                story_id=story_id,
                run_id=self._run_id,
                proof_id=str(uuid4()),
                activated_at=datetime.fromisoformat(activated_at),
                blocked_principal=blocked_principal,
                resolution_service_path=resolution_service_path,
            )
        )


def _record_freeze_version(record: object) -> int | None:
    """Extract ``freeze_version`` from a backend record (duck-typed / mapping)."""
    version = getattr(record, "freeze_version", None)
    if version is None and isinstance(record, dict):
        version = record.get("freeze_version")
    return version if isinstance(version, int) else None


__all__ = [
    "FREEZE_EXPORT_RELPATH",
    "ConflictFreezeOverlay",
    "ConflictFreezeProofStore",
    "FreezeStore",
    "LocalFreezeExport",
]
