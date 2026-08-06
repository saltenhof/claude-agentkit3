"""AC2 deterministic contradiction policy and evidence-contract tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from concept_governance.chunks import load_chunks
from concept_governance.scope_contracts import (
    ContradictionGroup,
    QuotedAssertion,
    ScopeConsistencyResponse,
    ScopeEvaluation,
)
from concept_governance.scope_models import SCOPE_PROMPT_VERSION
from concept_governance.scope_policy import ScopeEvaluationContractError, evaluate_scope_policy
from concept_governance.scope_sets import build_scope_sets, partition_scope_sets
from concept_governance.vocabulary import load_scope_vocabulary
from tests.unit.tools.concept_governance.helpers import source_reference_fields, write_doc

if TYPE_CHECKING:
    from pathlib import Path

    from concept_governance.scope_models import ScopeAssertionChunk, ScopePartition


def _reference(candidate: ScopeAssertionChunk, evidence: str) -> QuotedAssertion:
    return QuotedAssertion(
        **source_reference_fields(candidate.chunk_id, candidate.text, evidence)
    )


def test_same_scope_contradiction_extracts_exact_source_text_with_line_break(
    tmp_path: Path,
) -> None:
    partition = _contradictory_partition(tmp_path)
    first, second = partition.assertions[:2]
    ttl_assertion = "The lock is released automatically\nafter TTL."
    response = ScopeConsistencyResponse(
        contradictions=(
            ContradictionGroup(
                loci=(
                    _reference(first, "A human must explicitly bind again."),
                    _reference(second, ttl_assertion),
                ),
                explanation="Manual rebinding and automatic TTL release cannot both govern the lock.",
            ),
        )
    )

    findings = evaluate_scope_policy(partition, _evaluation(response))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.code == "SCOPE_CONTRADICTION"
    assert finding.severity == "ERROR"
    assert finding.scope == "lock.lifecycle"
    assert finding.doc == first.doc
    assert finding.related_loci[0].doc == second.doc
    assert finding.related_loci[0].assertion == ttl_assertion
    assert finding.formalization_check is None


def test_policy_rejects_a_foreign_cross_scope_source(tmp_path: Path) -> None:
    partition = _contradictory_partition(tmp_path)
    first = partition.assertions[0]
    response = ScopeConsistencyResponse(
        contradictions=(
            ContradictionGroup(
                loci=(
                    _reference(first, "A human must explicitly bind again."),
                    QuotedAssertion(
                        source_id="foreign",
                        start_id="b000000",
                        end_id="b000001",
                    ),
                ),
                explanation="Reported cross-scope pair.",
            ),
        )
    )

    with pytest.raises(ScopeEvaluationContractError, match="foreign source"):
        evaluate_scope_policy(partition, _evaluation(response))


def test_policy_rejects_overlapping_w3_source_spans(tmp_path: Path) -> None:
    partition = _contradictory_partition(tmp_path)
    first = partition.assertions[0]
    response = ScopeConsistencyResponse(
        contradictions=(
            ContradictionGroup(
                loci=(
                    _reference(first, first.text),
                    _reference(first, "A human must explicitly bind again."),
                ),
                explanation="Duplicated overlapping evidence.",
            ),
        )
    )

    with pytest.raises(ScopeEvaluationContractError, match="overlap"):
        evaluate_scope_policy(partition, _evaluation(response))


def test_w3_evidence_can_be_reused_across_distinct_contradiction_groups(
    tmp_path: Path,
) -> None:
    partition = _contradictory_partition(tmp_path)
    first, second, third = partition.assertions
    first_reference = _reference(first, "A human must explicitly bind again.")
    response = ScopeConsistencyResponse(
        contradictions=(
            ContradictionGroup(
                loci=(
                    first_reference,
                    _reference(second, "The lock is released automatically\nafter TTL."),
                ),
                explanation="A conflicts with B.",
            ),
            ContradictionGroup(
                loci=(
                    first_reference,
                    _reference(third, "The lock is reassigned without a human."),
                ),
                explanation="A conflicts with C.",
            ),
        )
    )

    findings = evaluate_scope_policy(partition, _evaluation(response))

    assert len(findings) == 2
    assert {item.related_loci[0].doc for item in findings} == {second.doc, third.doc}


def _contradictory_partition(tmp_path: Path) -> ScopePartition:
    concept = tmp_path / "concept"
    write_doc(
        concept,
        "manual.md",
        "LOCK",
        "[{scope: lock.lifecycle}]",
        content="A human must explicitly bind again.",
    )
    write_doc(
        concept,
        "ttl.md",
        "TTL",
        "[{scope: lock.lifecycle}]",
        content="The lock is released automatically\nafter TTL.",
    )
    write_doc(
        concept,
        "z-other.md",
        "OTHER",
        "[{scope: lock.lifecycle}]",
        content="The lock is reassigned without a human.",
    )
    sets = build_scope_sets(load_chunks(concept), load_scope_vocabulary(concept))
    return partition_scope_sets(sets)[0]


def _evaluation(response: ScopeConsistencyResponse) -> ScopeEvaluation:
    return ScopeEvaluation(
        response=response,
        prompt_version=SCOPE_PROMPT_VERSION,
        prompt_sha256="a" * 64,
        model="fixed/v1",
    )
