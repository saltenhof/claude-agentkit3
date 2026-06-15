"""Narrow standard -> integration_stabilization reclassification boundary.

FK-05 §5.7/§5.13 / AG3-069 AC10. AG3-072 §2.2 assigns the NARROW reclassification
(standard -> integration_stabilization) explicitly to AG3-069 (the general story
split stays AG3-072). This module is the REAL, in-story production boundary for
that reclassification.

Invariant (``reclassification_may_not_legalize_pre_manifest_cross_scope_delta``):
reclassifying a standard story into integration_stabilization does NOT retro-
actively legalize pre-existing productive cross-scope mutations. The reclassified
contract begins only at the approved manifest snapshot. The boundary therefore:

1. rewrites the persisted ``StoryContext.implementation_contract`` to
   integration_stabilization (the persisted contract axis is the single source
   of truth, FK-05 §5.2);
2. creates a fresh ``evidence_epoch`` at the snapshot boundary and PERSISTS the
   pre-snapshot cross-scope deltas as quarantine state (NOT legalized);
3. the quarantine state is later READ (declared_surfaces_only / closure) so a
   pre-snapshot delta stays quarantined.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from agentkit.integration_stabilization.state import (
    apply_reclassification_no_retroactive_legalization,
    read_quarantine_state,
)
from agentkit.story_context_manager.types import ImplementationContract

if TYPE_CHECKING:
    from pathlib import Path

    from agentkit.story_context_manager.models import StoryContext

__all__ = [
    "ReclassificationResult",
    "StoryContextWriter",
    "reclassify_standard_to_integration_stabilization",
]


class StoryContextWriter(Protocol):
    """Injected story-context persistence seam (ARCH AC003 mutation surface).

    Story-context mutation may only be imported from the state-backend /
    pipeline-phase surfaces (architecture-conformance ``story_context_write_surface``).
    The integration_stabilization module therefore does NOT import
    ``save_story_context`` directly; the caller (an allowed pipeline-phase
    surface) injects the writer. The composition root / phase handler binds the
    state-backend ``save_story_context``.
    """

    def __call__(self, story_dir: Path, ctx: StoryContext) -> None:
        """Persist the reclassified story context."""
        ...


@dataclass(frozen=True)
class ReclassificationResult:
    """Outcome of a standard -> integration_stabilization reclassification.

    Attributes:
        reclassified_context: The persisted IS-contract ``StoryContext``.
        evidence_epoch: The fresh evidence epoch at the snapshot boundary.
        quarantined_deltas: Pre-snapshot cross-scope deltas that stay quarantined.
        legalization_blocked: True iff no retroactive legalization occurred.
    """

    reclassified_context: StoryContext
    evidence_epoch: str
    quarantined_deltas: tuple[str, ...]
    legalization_blocked: bool


def reclassify_standard_to_integration_stabilization(
    story_dir: Path,
    ctx: StoryContext,
    *,
    pre_snapshot_deltas: tuple[str, ...],
    context_writer: StoryContextWriter,
) -> ReclassificationResult:
    """Reclassify a standard story to integration_stabilization (FK-05 §5.7/§5.13).

    The REAL in-story reclassification boundary (AG3-069 AC10, AG3-072 §2.2).
    Rewrites + persists the IS contract on the story context (via the injected
    ``context_writer`` mutation surface, ARCH AC003), creates the fresh evidence
    epoch and PERSISTS the pre-snapshot cross-scope deltas as quarantine state
    (no retroactive legalization). The quarantine state is read back here (and by
    the structural check / closure) so a pre-snapshot delta stays quarantined.

    Args:
        story_dir: The story working directory (persistence target).
        ctx: The current (standard-contract) story context.
        pre_snapshot_deltas: Identifiers of productive cross-scope mutations that
            existed BEFORE the approved manifest snapshot boundary.
        context_writer: Injected story-context persistence seam (the allowed
            mutation surface binds the state-backend ``save_story_context``).

    Returns:
        A :class:`ReclassificationResult`.

    Raises:
        ValueError: When ``ctx`` is already integration_stabilization (the narrow
            reclassification only applies standard -> integration_stabilization).
    """
    if (
        ctx.implementation_contract
        is ImplementationContract.INTEGRATION_STABILIZATION
    ):
        raise ValueError(
            "story is already integration_stabilization; the narrow "
            "reclassification only applies standard -> integration_stabilization "
            "(FK-05 §5.7, AG3-069 AC10)."
        )

    # 1) Persist the reclassified contract through the injected mutation surface
    #    (the persistent contract axis is the single source of truth, FK-05 §5.2).
    reclassified = ctx.model_copy(
        update={
            "implementation_contract": (
                ImplementationContract.INTEGRATION_STABILIZATION
            )
        }
    )
    context_writer(story_dir, reclassified)

    # 2) Fresh evidence_epoch + quarantine persistence (no retroactive legalize).
    result = apply_reclassification_no_retroactive_legalization(
        story_dir,
        pre_snapshot_deltas=pre_snapshot_deltas,
    )

    # 3) Read the persisted quarantine back (the same state downstream checks read).
    quarantined = read_quarantine_state(story_dir)

    return ReclassificationResult(
        reclassified_context=reclassified,
        evidence_epoch=result.evidence_epoch,
        quarantined_deltas=quarantined,
        legalization_blocked=result.legalization_blocked,
    )
