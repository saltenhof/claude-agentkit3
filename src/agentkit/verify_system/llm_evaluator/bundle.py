"""ReviewBundle -- the immutable LLM-evaluation input (FK-27 §27.5 / FK-11 §11.4.5).

A :class:`ReviewBundle` is the typed context that the three Layer-2 reviewers
(qa_review, semantic_review, doc_fidelity) receive. It bundles the story
brief, acceptance criteria, the diff summary/content, concept anchors and --
in the remediation round -- the previous round's findings (FK-34 §34.9 /
DK-04 §4.6).

Scope note (story.md §2.1.5 / §2.2): the full section-aware bundle-packing
mechanism (FK-37 §37.3), the EvidenceAssembler and the
ContextSufficiencyBuilder are explicitly out of scope for this first wave.
This module therefore implements only a simple, deterministic truncation:
``diff_content`` is capped first, then the total serialized size is bounded.
Truncation is recorded in-band (an explicit marker line) so the LLM is never
silently handed a cut payload (FK-11 §11.4.5: "dokumentiertes
Kuerzungsprotokoll").

Quelle:
  - FK-27 §27.5.2 -- Kontext-Bundles (story_spec, diff_summary, concept_excerpt, handover)
  - FK-11 §11.4.5 -- Kontext-Bundles + Kuerzungsprotokoll
  - FK-34 §34.9 / DK-04 §4.6 -- Remediation-Modus (previous_findings)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from agentkit.verify_system.protocols import Finding

if TYPE_CHECKING:
    from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput

#: Hard cap on the embedded ``diff_content`` (story.md §2.1.5: "max 100KB").
MAX_DIFF_CONTENT_BYTES: int = 100 * 1024
#: Hard cap on the total serialized bundle (story.md §2.1.5: "max 200KB total").
MAX_BUNDLE_TOTAL_BYTES: int = 200 * 1024
#: In-band marker appended to a truncated text field (FK-11 §11.4.5).
_TRUNCATION_MARKER: str = "\n[...TRUNCATED by build_review_bundle (FK-11 §11.4.5)...]"


class ReviewBundle(BaseModel):
    """Immutable LLM-evaluation input bundle (FK-27 §27.5 / FK-11 §11.4.5).

    Attributes:
        story_id: Story display-ID (e.g. ``AG3-043``).
        story_brief_excerpt: Story specification text or excerpt.
        acceptance_criteria: The story's acceptance-criteria lines.
        diff_summary: Human-readable diff summary (``git diff --stat`` form).
        diff_content: The full diff content, capped at 100KB.
        concept_refs: FK-/DK- concept anchors relevant to the change.
        previous_findings: Prior-round findings carried in remediation mode
            (FK-34 §34.9 / DK-04 §4.6); ``None`` in the initial round.
        qa_cycle_round: 1-based QA-cycle round. ``> 1`` activates the
            finding-resolution prompt section (DK-04 §4.6).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    story_id: str
    story_brief_excerpt: str
    acceptance_criteria: list[str]
    diff_summary: str
    diff_content: str
    concept_refs: list[str]
    previous_findings: list[Finding] | None
    qa_cycle_round: int

    def to_prompt_json(self) -> str:
        """Serialize the bundle to a deterministic JSON string for the prompt.

        ``Finding`` is a frozen dataclass (not a Pydantic model), so the
        previous findings are projected to a stable, JSON-serializable shape
        here rather than relying on Pydantic's model serialization. Keys are
        sorted so the same bundle always yields byte-identical output
        (determinism, no dict-order leakage).

        Returns:
            A ``sort_keys=True`` JSON object string of the bundle's fields.
        """
        previous: list[dict[str, object]] | None
        if self.previous_findings is None:
            previous = None
        else:
            previous = [
                {
                    "layer": f.layer,
                    "check": f.check,
                    "severity": str(f.severity),
                    "message": f.message,
                }
                for f in self.previous_findings
            ]
        payload: dict[str, object] = {
            "story_id": self.story_id,
            "story_brief_excerpt": self.story_brief_excerpt,
            "acceptance_criteria": self.acceptance_criteria,
            "diff_summary": self.diff_summary,
            "diff_content": self.diff_content,
            "concept_refs": self.concept_refs,
            "previous_findings": previous,
            "qa_cycle_round": self.qa_cycle_round,
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _truncate_text(text: str, max_bytes: int) -> str:
    """Truncate ``text`` to at most ``max_bytes`` UTF-8 bytes (in-band marker).

    Args:
        text: The text to bound.
        max_bytes: The UTF-8 byte ceiling (must be larger than the marker).

    Returns:
        ``text`` unchanged when it already fits, else a prefix plus the
        documented truncation marker.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    marker_len = len(_TRUNCATION_MARKER.encode("utf-8"))
    budget = max(0, max_bytes - marker_len)
    # Decode the byte prefix, dropping any partial trailing multibyte char.
    prefix = encoded[:budget].decode("utf-8", errors="ignore")
    return prefix + _TRUNCATION_MARKER


def build_review_bundle(
    review_input: Layer2ReviewInput,
    *,
    story_id: str,
    qa_cycle_round: int,
    acceptance_criteria: list[str] | None = None,
    concept_refs: list[str] | None = None,
    previous_findings: list[Finding] | None = None,
) -> ReviewBundle:
    """Build a size-bounded :class:`ReviewBundle` from a ``Layer2ReviewInput``.

    The bundle is derived from the already-assembled
    :class:`~agentkit.verify_system.llm_evaluator.inputs.Layer2ReviewInput`
    (the SSOT for the four FK-27 §27.5.2 text inputs) -- this story does NOT
    introduce a second git-diff reader (EvidenceAssembler is OOS, story.md
    §2.2). Truncation is two-stage and deterministic: ``diff_content`` is
    capped at 100KB first, then the whole serialized bundle is bounded at
    200KB (story.md §2.1.5).

    Args:
        review_input: The four FK-27 §27.5.2 text inputs. ``story_spec`` maps
            to ``story_brief_excerpt``; ``diff_summary``/``handover`` map to
            ``diff_summary``/``diff_content``; ``concept_excerpt`` seeds
            ``concept_refs`` when none are supplied.
        story_id: Story display-ID.
        qa_cycle_round: 1-based QA-cycle round (``> 1`` => remediation mode).
        acceptance_criteria: Optional explicit AC lines; defaults to ``[]``.
        concept_refs: Optional explicit concept anchors; defaults to a
            single-element list with ``concept_excerpt`` when that is
            non-empty, else ``[]``.
        previous_findings: Prior-round findings for the remediation prompt
            section (DK-04 §4.6). ``None`` in the initial round.

    Returns:
        A frozen, size-bounded :class:`ReviewBundle`.

    Raises:
        ValueError: If ``qa_cycle_round`` is < 1 (fail-closed: a round number
            is always 1-based, FK-27 §27.2.1).
    """
    if qa_cycle_round < 1:
        msg = (
            "qa_cycle_round must be >= 1 (FK-27 §27.2.1, 1-based); "
            f"got {qa_cycle_round!r}"
        )
        raise ValueError(msg)

    resolved_concept_refs: list[str]
    if concept_refs is not None:
        resolved_concept_refs = list(concept_refs)
    elif review_input.concept_excerpt:
        resolved_concept_refs = [review_input.concept_excerpt]
    else:
        resolved_concept_refs = []

    bundle = ReviewBundle(
        story_id=story_id,
        story_brief_excerpt=review_input.story_spec,
        acceptance_criteria=list(acceptance_criteria or []),
        diff_summary=review_input.diff_summary,
        diff_content=_truncate_text(review_input.handover, MAX_DIFF_CONTENT_BYTES),
        concept_refs=resolved_concept_refs,
        previous_findings=previous_findings,
        qa_cycle_round=qa_cycle_round,
    )

    return _bound_total_size(bundle)


def _bound_total_size(bundle: ReviewBundle) -> ReviewBundle:
    """Shrink ``diff_content`` until the serialized bundle fits 200KB.

    Deterministic, bounded fixed-point: each pass subtracts the measured
    overshoot (plus a small margin to absorb JSON-escaping/marker overhead)
    from the diff-content cap until the whole payload fits or diff_content is
    empty (fail-soft on size only -- FK-11 §11.4.5).

    Args:
        bundle: The candidate bundle (diff_content already <= 100KB).

    Returns:
        A bundle whose ``to_prompt_json()`` is at most 200KB.
    """
    margin = len(_TRUNCATION_MARKER.encode("utf-8")) + 16
    current = bundle
    for _ in range(8):
        total = len(current.to_prompt_json().encode("utf-8"))
        if total <= MAX_BUNDLE_TOTAL_BYTES:
            return current
        diff_bytes = len(current.diff_content.encode("utf-8"))
        if diff_bytes == 0:
            return current
        overshoot = total - MAX_BUNDLE_TOTAL_BYTES
        new_cap = max(0, diff_bytes - overshoot - margin)
        current = current.model_copy(
            update={"diff_content": _truncate_text(current.diff_content, new_cap)},
        )
    return current


__all__ = [
    "MAX_BUNDLE_TOTAL_BYTES",
    "MAX_DIFF_CONTENT_BYTES",
    "ReviewBundle",
    "build_review_bundle",
]
