"""Deterministic W3 contradiction policy; the LLM never decides."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.finding_types import FindingLocus
from concept_governance.scope_models import ScopeConsistencyFinding, ScopePartition

if TYPE_CHECKING:
    from collections.abc import Mapping

    from concept_governance.scope_contracts import QuotedAssertion, ScopeEvaluation
    from concept_governance.scope_models import ScopeAssertionChunk


class ScopeEvaluationContractError(ValueError):
    """Raised when an LLM report does not refer exactly to its input."""


def evaluate_scope_policy(
    partition: ScopePartition,
    evaluation: ScopeEvaluation,
) -> tuple[ScopeConsistencyFinding, ...]:
    """Validate reported evidence and turn each contradiction into ERROR."""
    candidates = {item.chunk_id: item for item in partition.assertions}
    findings: dict[tuple[str, ...], ScopeConsistencyFinding] = {}
    for group in evaluation.response.contradictions:
        loci = tuple(sorted((_validate_locus(item, candidates) for item in group.loci), key=_locus_key))
        primary, *related = loci
        finding = ScopeConsistencyFinding(
            code="SCOPE_CONTRADICTION",
            doc=primary.doc,
            anchor=primary.anchor,
            assertion=primary.assertion,
            related_loci=tuple(related),
            scope=partition.scope,
            prompt_version=evaluation.prompt_version,
            prompt_sha256=evaluation.prompt_sha256,
            model=evaluation.model,
            message=group.explanation,
            formalization_check=None,
        )
        findings[finding.key] = finding
    return tuple(findings[key] for key in sorted(findings))


def _validate_locus(
    locus: QuotedAssertion,
    candidates: Mapping[str, ScopeAssertionChunk],
) -> FindingLocus:
    candidate = candidates.get(locus.chunk_id)
    if candidate is None:
        raise ScopeEvaluationContractError(f"reported foreign chunk {locus.chunk_id!r}")
    if (locus.doc, locus.anchor) != (candidate.doc, candidate.anchor):
        raise ScopeEvaluationContractError(f"reported locus metadata mismatches {locus.chunk_id!r}")
    if locus.assertion not in candidate.text:
        raise ScopeEvaluationContractError(f"reported quote is absent from {locus.chunk_id!r}")
    return FindingLocus(doc=locus.doc, anchor=locus.anchor, assertion=locus.assertion)


def _locus_key(locus: FindingLocus) -> tuple[str, str, str]:
    return (locus.doc, locus.anchor, locus.assertion)
