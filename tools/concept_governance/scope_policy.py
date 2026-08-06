"""Deterministic W3 contradiction policy; the LLM never decides."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.finding_types import FindingLocus
from concept_governance.scope_models import ScopeConsistencyFinding, ScopePartition
from concept_governance.source_spans import (
    ExtractedSourceSpan,
    SourceSpanContractError,
    build_source_span_map,
    extract_source_spans,
)

if TYPE_CHECKING:
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
    sources = tuple(build_source_span_map(item.chunk_id, item.text) for item in partition.assertions)
    findings: dict[tuple[str, ...], ScopeConsistencyFinding] = {}
    for group in evaluation.response.contradictions:
        try:
            extracted = extract_source_spans(group.loci, sources)
        except SourceSpanContractError as exc:
            raise ScopeEvaluationContractError(str(exc)) from exc
        loci = tuple(
            sorted(
                (
                    _validate_locus(item, candidates[item.source_id], evidence)
                    for item, evidence in zip(group.loci, extracted, strict=True)
                ),
                key=_locus_key,
            )
        )
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
    candidate: ScopeAssertionChunk,
    extracted: ExtractedSourceSpan,
) -> FindingLocus:
    if locus.source_id != extracted.source_id:
        raise ScopeEvaluationContractError("extracted evidence order mismatches response")
    return FindingLocus(doc=candidate.doc, anchor=candidate.anchor, assertion=extracted.text)


def _locus_key(locus: FindingLocus) -> tuple[str, str, str]:
    return (locus.doc, locus.anchor, locus.assertion)
