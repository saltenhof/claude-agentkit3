"""ReviewBundle -- the immutable LLM-evaluation input (FK-27 §27.5 / FK-37).

A :class:`ReviewBundle` is the typed context that the three Layer-2 reviewers
(qa_review, semantic_review, doc_fidelity) receive. It bundles the story
brief, acceptance criteria, the diff summary/content, concept anchors and --
in the remediation round -- the previous round's findings (FK-34 §34.9 /
DK-04 §4.6).

Quelle:
  - FK-37 §37.1 -- six semantic ContextBundle fields.
  - FK-37 §37.3 -- section-aware packing and truncation protocol.
  - FK-34 §34.9 / DK-04 §4.6 -- Remediation-Modus (previous_findings)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from agentkit.verify_system.evidence.bundle_manifest import BundleManifest
from agentkit.verify_system.llm_evaluator.packing import (
    BUNDLE_TOKEN_LIMIT,
    PackingResult,
    pack_code,
    pack_markdown,
)
from agentkit.verify_system.protocols import Finding

if TYPE_CHECKING:
    from agentkit.verify_system.llm_evaluator.inputs import Layer2ReviewInput

class ReviewBundle(BaseModel):
    """Immutable LLM-evaluation input bundle (FK-27 §27.5 / FK-11 §11.4.5).

    Attributes:
        story_id: Story display-ID (e.g. ``AG3-043``).
        story_brief_excerpt: Story specification text or excerpt.
        acceptance_criteria: The story's acceptance-criteria lines.
        diff_summary: Human-readable diff summary (``git diff --stat`` form).
        diff_content: Worker handover/diff body after section-aware packing.
        concept_refs: FK-/DK- concept anchors relevant to the change.
        arch_references: Architecture references loaded by the sufficiency pre-step.
        evidence_manifest: Evidence-assembly manifest for the review bundle.
        packing_protocol: Deterministic per-field truncation protocol.
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
    concept_excerpt: str = ""
    concept_refs: list[str]
    arch_references: str = ""
    evidence_manifest: BundleManifest | dict[str, object] | str | None = None
    packing_protocol: dict[str, tuple[str, ...]] = Field(default_factory=dict)
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
            "concept_excerpt": self.concept_excerpt,
            "concept_refs": self.concept_refs,
            "arch_references": self.arch_references,
            "evidence_manifest": _serialize_evidence_manifest(self.evidence_manifest),
            "packing_protocol": self.packing_protocol,
            "previous_findings": previous,
            "qa_cycle_round": self.qa_cycle_round,
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def build_review_bundle(
    review_input: Layer2ReviewInput,
    *,
    story_id: str,
    qa_cycle_round: int,
    acceptance_criteria: list[str] | None = None,
    concept_refs: list[str] | None = None,
    arch_references: str = "",
    evidence_manifest: BundleManifest | dict[str, object] | str | None = None,
    bundle_token_limit: int = BUNDLE_TOKEN_LIMIT,
    previous_findings: list[Finding] | None = None,
) -> ReviewBundle:
    """Build a packed :class:`ReviewBundle` from a ``Layer2ReviewInput``.

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
        arch_references: Architecture references from ContextSufficiencyBuilder.
        evidence_manifest: Evidence manifest from AG3-061.
        bundle_token_limit: Per-field section-aware packing limit.
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

    packed, protocol = _pack_and_convert(
        review_input,
        arch_references=arch_references,
        bundle_token_limit=bundle_token_limit,
    )

    return ReviewBundle(
        story_id=story_id,
        story_brief_excerpt=packed["story_spec"],
        acceptance_criteria=list(acceptance_criteria or []),
        diff_summary=packed["diff_summary"],
        diff_content=packed["handover"],
        concept_excerpt=packed["concept_excerpt"],
        concept_refs=resolved_concept_refs,
        arch_references=packed["arch_references"],
        evidence_manifest=evidence_manifest,
        packing_protocol=protocol,
        previous_findings=previous_findings,
        qa_cycle_round=qa_cycle_round,
    )


def _pack_and_convert(
    review_input: Layer2ReviewInput,
    *,
    arch_references: str,
    bundle_token_limit: int,
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    """Pack the six semantic fields exactly once before runner invocation."""
    values = {
        "story_spec": review_input.story_spec,
        "diff_summary": review_input.diff_summary,
        "concept_excerpt": review_input.concept_excerpt,
        "handover": review_input.handover,
        "arch_references": arch_references,
    }
    packed: dict[str, str] = {}
    protocol: dict[str, tuple[str, ...]] = {}
    for field_name, value in values.items():
        result = _pack_field(field_name, value, bundle_token_limit)
        packed[field_name] = result.content
        if result.truncated:
            protocol[field_name] = result.protocol or (
                f"{field_name}: packed from {result.original_chars} to {result.packed_chars} chars",
            )
    return packed, protocol


def _pack_field(field_name: str, value: str, limit: int) -> PackingResult:
    if field_name in ("story_spec", "concept_excerpt", "arch_references"):
        return pack_markdown(
            value,
            limit=limit,
            priority_headings=_priorities_for(field_name),
        )
    if field_name == "diff_summary":
        return pack_code(value, changed_symbols=_extract_symbols(value), limit=limit)
    return pack_markdown(value, limit=limit, priority_headings=())


def _priorities_for(field_name: str) -> tuple[str, ...]:
    return {
        "story_spec": ("Acceptance", "Akzeptanz", "Scope", "Context"),
        "concept_excerpt": ("Invariant", "Guardrail", "Scope", "Design"),
        "arch_references": ("Guardrail", "Architecture", "Bounded Context"),
    }.get(field_name, ())


def _extract_symbols(value: str) -> tuple[str, ...]:
    symbols: list[str] = []
    for line in value.splitlines():
        stripped = line.strip()
        if stripped.startswith(("def ", "class ")):
            symbols.append(stripped.split("(", 1)[0].split(":", 1)[0])
        elif stripped.startswith("@@") and "@@" in stripped[2:]:
            tail = stripped.rsplit("@@", 1)[-1].strip()
            if tail:
                symbols.append(tail)
    return tuple(symbols)


def _serialize_evidence_manifest(
    manifest: BundleManifest | dict[str, object] | str | None,
) -> object:
    if isinstance(manifest, BundleManifest):
        return manifest.model_dump(mode="json")
    return manifest


__all__ = [
    "BUNDLE_TOKEN_LIMIT",
    "ReviewBundle",
    "_pack_and_convert",
    "build_review_bundle",
]
