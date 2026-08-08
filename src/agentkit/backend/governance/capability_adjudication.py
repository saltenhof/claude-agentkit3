"""Core-side capability adjudication behind ``/v1`` (AG3-239, FK-55 §55.10.3).

This is the service the hook process reaches instead of constructing the
capability components itself. It performs FK-55 §55.10.3 steps 1-5 as **one**
business transaction (AG3-239 AC 3): resolve the principal, classify the path,
classify the operation, consult the matrix, apply the conflict-freeze overlay.

**The freeze split.** The invariant
``principal-capabilities.invariant.freeze_has_backend_record_and_local_export``
requires an active freeze to exist as canonical backend record AND as local,
hook-readable export carrying the same ``freeze_version``. Those two live on two
machines. ``FreezeRepository`` is canonical state and stays here; the local
export is a file only the edge can read, so the edge reports what it says and
this service compares. Any disagreement -- one-sided record, mismatched story,
version drift, unreadable export -- is a fail-closed freeze, exactly as the
in-process overlay decided it before.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentkit_wire.governance_adjudication import (
    AdjudicationOutcome,
    CapabilityAdjudicationResponse,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Protocol

    from agentkit_wire.governance_adjudication import (
        CapabilityAdjudicationRequest,
        LocalFreezeState,
    )

logger = logging.getLogger(__name__)


if TYPE_CHECKING:

    class _FreezeReader(Protocol):
        """The one canonical-freeze read this service needs."""

        def read_freeze(self, story_id: str) -> object | None:
            """Return the canonical freeze record, or ``None`` when not frozen."""


class CapabilityAdjudicationService:
    """Adjudicates one principal operation against canonical capability state."""

    def __init__(self, *, project_root: Path | None = None) -> None:
        """Build the service.

        Args:
            project_root: Root used for path classification. Tests pass
                ``tmp_path``; production wiring passes the served project root.
        """
        self._project_root = project_root

    def adjudicate(
        self, request: CapabilityAdjudicationRequest
    ) -> CapabilityAdjudicationResponse:
        """Return the adjudication outcome for ``request``.

        Never raises for a capability-layer fault: FK-55 §55.10.5 / FK-31
        §31.2.7 require a deterministic BLOCK rather than an escaping runtime
        error, so a fault becomes ``AdjudicationOutcome.FAULT`` with the fault
        class in ``detail``.

        Args:
            request: The edge's adjudication request.

        Returns:
            The outcome plus the verdict fields the hook needs to block.
        """
        from pathlib import Path

        from agentkit.backend.governance.principal_capabilities import (
            CapabilityEnforcement,
            CapabilityMatrix,
            ConflictFreezeOverlay,
            EnforcementOutcome,
            OperationClassifier,
            PathClassifier,
            PrincipalResolver,
        )
        from agentkit.backend.state_backend.store.freeze_repository import FreezeRepository

        project_root = self._project_root or Path(request.cwd or ".")
        try:
            freeze_store = FreezeRepository(project_root)
            disagreement = self._freeze_disagrees(
                freeze_store, request.story_id, request.local_freeze
            )
            if disagreement is not None:
                return disagreement
            enforcement = CapabilityEnforcement(
                principal_resolver=PrincipalResolver(),
                path_classifier=PathClassifier(),
                op_classifier=OperationClassifier(),
                matrix=CapabilityMatrix(),
                # The overlay consults the canonical record only: the local half
                # of the invariant was already compared above, against what the
                # EDGE reported. Handing it a core-side "local export" would
                # compare the core against itself and prove nothing.
                freeze=ConflictFreezeOverlay(freeze_store),
            )
            result = enforcement.evaluate(
                request,
                project_root=project_root,
                story_id=request.story_id,
                story_scope_roots=request.story_scope_roots,
                binding_revocation_reason=request.binding_revocation_reason,
                new_owner_ref=request.new_owner_ref,
            )
        except Exception as exc:  # noqa: BLE001 -- fail-closed, never escape
            logger.warning("Capability adjudication faulted: %s", exc, exc_info=True)
            return CapabilityAdjudicationResponse(
                outcome=AdjudicationOutcome.FAULT,
                allowed=False,
                message="capability evaluation fault",
                detail=type(exc).__name__,
            )

        permitting = {
            EnforcementOutcome.ALLOW,
            EnforcementOutcome.ALLOW_VIA_OFFICIAL_SERVICE_PATH,
        }
        if result.outcome in permitting:
            return CapabilityAdjudicationResponse(
                outcome=AdjudicationOutcome.PERMIT, allowed=True
            )
        blocking = {
            EnforcementOutcome.DENY: AdjudicationOutcome.DENY,
            EnforcementOutcome.UNCLASSIFIED_MUTATION: (
                AdjudicationOutcome.UNCLASSIFIED_MUTATION
            ),
            EnforcementOutcome.UNKNOWN_PERMISSION: (
                AdjudicationOutcome.UNKNOWN_PERMISSION
            ),
            EnforcementOutcome.UNRESOLVED: AdjudicationOutcome.UNRESOLVED,
        }
        return CapabilityAdjudicationResponse(
            outcome=blocking[result.outcome],
            allowed=False,
            guard_name="principal_capability",
            # ``CapabilityVerdict.reason`` -- NOT ``.message``. The capability
            # verdict is not a GuardVerdict; reading the wrong attribute would
            # silently ship the generic default and erase the concrete reason the
            # operator needs (e.g. "ownership_transferred").
            message=str(getattr(result.verdict, "reason", "")),
            violation_type=_violation_value(result.verdict),
            rule_id=_rule_id(result.verdict),
        )

    def _freeze_disagrees(
        self,
        freeze_store: _FreezeReader,
        story_id: str | None,
        local: LocalFreezeState,
    ) -> CapabilityAdjudicationResponse | None:
        """Compare the canonical freeze record against the edge's local export.

        Returns a fail-closed freeze response when the two disagree, else
        ``None``. Mirrors the in-process overlay rule: any one-sided record, any
        version drift and any unreadable export is treated as an ACTIVE freeze,
        because a stale or broken export must never read as "not frozen".
        """
        if story_id is None:
            return None
        record = freeze_store.read_freeze(story_id)
        canonical_version = (
            getattr(record, "freeze_version", None) if record is not None else None
        )
        canonical_active = record is not None

        if local.unreadable:
            return self._frozen("local freeze export is unreadable")
        if canonical_active != local.present:
            return self._frozen(
                "freeze record and local export disagree on whether a freeze is active"
            )
        if not canonical_active:
            return None
        if local.story_id is not None and local.story_id != story_id:
            return self._frozen("local freeze export names a different story")
        if canonical_version != local.freeze_version:
            return self._frozen(
                "freeze_version mismatch between record and local export"
            )
        # Both agree there IS an active freeze at the same version. That is a
        # real freeze, not a disagreement -- the overlay below decides it.
        return None

    @staticmethod
    def _frozen(reason: str) -> CapabilityAdjudicationResponse:
        """Build the fail-closed freeze response for a dual-materialization defect."""
        return CapabilityAdjudicationResponse(
            outcome=AdjudicationOutcome.DENY,
            allowed=False,
            guard_name="principal_capability",
            message=f"conflict freeze active: {reason}",
            violation_type="conflict_freeze",
            rule_id="FK-55-55.10.5",
            freeze_disagreement=True,
        )


def _rule_id(verdict: object) -> str | None:
    """Return the concept rule id the core decided by, when it names one."""
    rule = getattr(verdict, "rule_id", None)
    return str(rule) if rule is not None else None


def _violation_value(verdict: object) -> str | None:
    """Return the violation type of a verdict as a plain wire string."""
    violation = getattr(verdict, "violation_type", None)
    if violation is None:
        return None
    return str(getattr(violation, "value", violation))


__all__ = ["CapabilityAdjudicationService"]
