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
from tests.unit.tools.concept_governance.helpers import write_doc

if TYPE_CHECKING:
    from pathlib import Path

    from concept_governance.scope_models import ScopePartition


def test_same_scope_contradiction_becomes_error_with_both_loci(tmp_path: Path) -> None:
    partition = _contradictory_partition(tmp_path)
    first, second = partition.assertions
    response = ScopeConsistencyResponse(
        contradictions=(
            ContradictionGroup(
                loci=(
                    QuotedAssertion(
                        chunk_id=first.chunk_id,
                        doc=first.doc,
                        anchor=first.anchor,
                        assertion="A human must explicitly bind again.",
                    ),
                    QuotedAssertion(
                        chunk_id=second.chunk_id,
                        doc=second.doc,
                        anchor=second.anchor,
                        assertion="The lock is released automatically after TTL.",
                    ),
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
    assert finding.formalization_check is None


def test_policy_rejects_a_foreign_cross_scope_locus(tmp_path: Path) -> None:
    partition = _contradictory_partition(tmp_path)
    first = partition.assertions[0]
    response = ScopeConsistencyResponse(
        contradictions=(
            ContradictionGroup(
                loci=(
                    QuotedAssertion(
                        chunk_id=first.chunk_id, doc=first.doc, anchor=first.anchor,
                        assertion="A human must explicitly bind again.",
                    ),
                    QuotedAssertion(
                        chunk_id="foreign", doc="queue.md", anchor="rule-000",
                        assertion="A queue drains automatically.",
                    ),
                ),
                explanation="Reported cross-scope pair.",
            ),
        )
    )

    with pytest.raises(ScopeEvaluationContractError, match="foreign chunk"):
        evaluate_scope_policy(partition, _evaluation(response))


def _contradictory_partition(tmp_path: Path) -> ScopePartition:
    concept = tmp_path / "concept"
    write_doc(
        concept, "manual.md", "LOCK", "[{scope: lock.lifecycle}]",
        content="A human must explicitly bind again.",
    )
    write_doc(
        concept, "ttl.md", "TTL", "[{scope: lock.lifecycle}]",
        content="The lock is released automatically after TTL.",
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
