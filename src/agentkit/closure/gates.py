"""Closure gates -- the Finding-Resolution-Gate (FK-29 §29.2, BC 7 ``ClosureGates``).

This module is a thin orchestration helper: it READS the three Layer-2 QA
artefacts (``qa_review.json`` / ``semantic_review.json`` / ``doc_fidelity.json``,
producer AG3-043) through the injected :class:`~agentkit.artifacts.ArtifactManager`
and evaluates whether every previous-round finding has been *fully* resolved.

FK-29 §29.2.1 / §29.2.4 is the SINGLE SOURCE OF TRUTH for the rule: closure is
blocked fail-closed when at least one finding carries the resolution status
``partially_resolved`` or ``not_resolved``. The resolution status is produced by
the Layer-2 evaluator (AG3-041) and serialised into the Layer-2 envelope metadata
under :data:`~agentkit.verify_system.remediation.finding_resolution.LLM_RESOLUTION_METADATA_KEY`;
this gate only consumes it (no second resolution truth).

Fail-closed semantics (FK-29 §29.2.4):

* a missing Layer-2 artefact for an impl/bugfix story (after a remediation round)
  is a hard block;
* a malformed resolution map is a hard block (it surfaces as an internal
  pipeline-corruption error from the decode helper, never silently skipped);
* the first round (no remediation, no ``resolution`` fields) yields a PASS — the
  gate is dormant until a remediation round populates the resolution map.

The gate does NOT apply to concept/research stories (FK-29 §29.2 "Ausnahme") —
the caller skips it via the typed story-type switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentkit.artifacts.errors import ArtifactNotFoundError
from agentkit.core_types import ArtifactClass
from agentkit.core_types.qa_artifact_names import (
    DOC_FIDELITY_STAGE,
    QA_REVIEW_STAGE,
    SEMANTIC_REVIEW_STAGE,
)
from agentkit.verify_system.implementation_evidence_gate import (
    ImplementationEvidenceVerdict,
    evaluate_implementation_evidence_gate,
)
from agentkit.verify_system.remediation.finding_resolution import (
    resolution_map_from_metadata,
    resolution_map_has_open_findings,
)

if TYPE_CHECKING:
    from agentkit.artifacts import ArtifactManager

#: The three Layer-2 QA artefact stages the Finding-Resolution-Gate reads, in
#: deterministic order (FK-27 §27.5.5 / FK-29 §29.2.4). SINGLE source of the
#: stage ids is ``core_types.qa_artifact_names`` (no second naming truth).
_LAYER2_STAGES: tuple[str, ...] = (
    QA_REVIEW_STAGE,
    SEMANTIC_REVIEW_STAGE,
    DOC_FIDELITY_STAGE,
)


@dataclass(frozen=True)
class FindingResolutionVerdict:
    """Outcome of the Finding-Resolution-Gate (FK-29 §29.2).

    Attributes:
        passed: ``True`` only when every previous-round finding is fully
            resolved across all three Layer-2 artefacts. ``False`` is a hard
            closure blocker (ESCALATED).
        blocking_reason: A human-facing reason when ``passed`` is ``False``,
            else ``None``.
    """

    passed: bool
    blocking_reason: str | None = None


def evaluate_finding_resolution_gate(
    manager: ArtifactManager,
    *,
    story_id: str,
    run_id: str | None,
) -> FindingResolutionVerdict:
    """Evaluate the Finding-Resolution-Gate against the three Layer-2 artefacts.

    Reads the latest ``qa_review`` / ``semantic_review`` / ``doc_fidelity``
    envelope for the run and inspects each one's serialised finding-resolution
    map (FK-29 §29.2.4). The gate blocks fail-closed when any finding is
    ``partially_resolved`` / ``not_resolved`` (an open finding) or when a
    required Layer-2 artefact is missing for a story that ran a remediation
    round (a missing artefact is treated as an unverifiable resolution =>
    block, never a silent pass).

    Args:
        manager: The injected :class:`ArtifactManager` (the only Layer-2 read
            seam; closure never touches the repository directly).
        story_id: Story display id (e.g. ``AG3-053``).
        run_id: Run correlation id; ``None`` matches across runs (the latest
            envelope wins).

    Returns:
        A :class:`FindingResolutionVerdict`.
    """
    for stage in _LAYER2_STAGES:
        try:
            envelope = manager.read_latest(
                story_id=story_id,
                run_id=run_id,
                artifact_class=ArtifactClass.QA,
                stage=stage,
            )
        except ArtifactNotFoundError:
            # An absent Layer-2 artefact cannot prove the findings are resolved.
            # First-round stories (no remediation) DO still produce all three
            # Layer-2 envelopes (run_qa_subflow always writes them), so an
            # absent one here is a real gap -> fail-closed (FK-29 §29.2.4).
            reason = "".join(
                (
                    "Finding-Resolution-Gate: Layer-2 artefact for stage ",
                    repr(stage),
                    " is missing (cannot verify finding resolution).",
                )
            )
            return FindingResolutionVerdict(
                passed=False,
                blocking_reason=reason,
            )
        metadata = (envelope.payload or {}).get("metadata")
        resolution_map = resolution_map_from_metadata(
            metadata if isinstance(metadata, dict) else None
        )
        if resolution_map_has_open_findings(resolution_map):
            open_keys = sorted(
                f"{layer}:{check}" for (layer, check), _status in resolution_map.items()
            )
            reason = "".join(
                (
                    f"Finding-Resolution-Gate: stage {stage!r} has unresolved ",
                    "findings (partially_resolved/not_resolved): ",
                    f"{open_keys}.",
                )
            )
            return FindingResolutionVerdict(
                passed=False,
                blocking_reason=reason,
            )
    return FindingResolutionVerdict(passed=True)


__all__ = [
    "FindingResolutionVerdict",
    "ImplementationEvidenceVerdict",
    "evaluate_finding_resolution_gate",
    "evaluate_implementation_evidence_gate",
]
