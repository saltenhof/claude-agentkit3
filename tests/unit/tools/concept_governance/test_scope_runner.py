"""AC3-6 bounded-call, baseline, no-index, and incomplete-sweep proofs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from concept_governance.baseline import BaselineDocument, BaselineEntry
from concept_governance.baseline_policy import apply_scope_baseline
from concept_governance.finding_types import FindingLocus, FormalizationCheck
from concept_governance.scope_contracts import (
    ContradictionGroup,
    QuotedAssertion,
    ScopeConsistencyResponse,
    ScopeEvaluation,
)
from concept_governance.scope_models import (
    SCOPE_PROMPT_VERSION,
    ScopeConsistencyFinding,
)
from concept_governance.scope_parser import ScopeResponseParseError
from concept_governance.scope_runner import run_scope_consistency
from concept_governance.transport_retry import EvaluationTransportExhaustedError
from pydantic import ValidationError
from tests.unit.tools.concept_governance.helpers import (
    ScriptedScopeEvaluator,
    source_reference_fields,
    write_doc,
    write_empty_baseline,
)

from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError
from agentkit.integration_clients.multi_llm_hub.errors import HubUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

    from concept_governance.scope_models import ScopePartition


def test_disjoint_scope_partitions_are_evaluated_but_mark_sweep_incomplete(
    tmp_path: Path,
) -> None:
    concept, baseline = _two_scope_corpus(tmp_path)
    evaluator = ScriptedScopeEvaluator(_empty_evaluation)

    result = run_scope_consistency(concept, baseline, evaluator, partition_max_chunks=2)

    assert not result.ok
    assert result.scope_sets == 2
    assert result.partitions == 4
    assert result.completed_partitions == 4
    assert len(evaluator.calls) == result.partitions
    assert len(evaluator.calls) != 15  # six chunks would produce 15 pairwise calls
    assert [item.code for item in result.findings] == ["INCOMPLETE_SWEEP"] * 2
    assert {item.scope for item in result.findings} == {
        "lock.lifecycle",
        "queue.lifecycle",
    }
    assert all("partitions=2" in item.message for item in result.findings)
    assert all(
        "cross-partition contradictions remain unchecked" in item.message
        for item in result.findings
    )
    for partition in evaluator.calls:
        expected_prefix = "lock-" if partition.scope == "lock.lifecycle" else "queue-"
        assert all(expected_prefix in item.doc for item in partition.assertions)


def test_no_external_index_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    concept, baseline = _two_scope_corpus(tmp_path)
    monkeypatch.setenv("AK3_WEAVIATE_HOST", "unreachable.invalid")
    monkeypatch.setenv("CONCEPT_MCP_URL", "http://unreachable.invalid")

    result = run_scope_consistency(concept, baseline, ScriptedScopeEvaluator(_empty_evaluation))

    assert result.ok
    assert result.completed_partitions == result.partitions


def test_live_scope_without_discovery_chunks_fails_instead_of_being_omitted(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    meta = concept / "_meta/meta-owner.md"
    meta.parent.mkdir(parents=True, exist_ok=True)
    # A VALID document (FK-13 §13.9.6 mandatory fields present) that owns a live
    # scope but has an EMPTY body, so discovery yields no chunk for it. The scope
    # must therefore be reported as an incomplete sweep instead of being omitted.
    # (Previously this state was produced by INVALID frontmatter, which the
    # ingester adapter now refuses outright -- AG3-174 R06.)
    meta.write_text(
        "---\nconcept_id: META\ntitle: Meta\nmodule: meta\nstatus: active\n"
        "doc_kind: core\nauthority_over: [{scope: meta.governance}]\ndefers_to: []\n---\n",
        encoding="utf-8",
    )
    write_empty_baseline(baseline)
    evaluator = ScriptedScopeEvaluator(_empty_evaluation)

    result = run_scope_consistency(concept, baseline, evaluator)

    assert [item.code for item in result.findings] == ["INCOMPLETE_SWEEP"]
    assert "meta.governance" in result.findings[0].message
    assert evaluator.calls == []


def test_failed_partition_discards_partial_results_and_names_incomplete_sweep(tmp_path: Path) -> None:
    concept, baseline = _two_scope_corpus(tmp_path)
    before = baseline.read_bytes()
    evaluator = ScriptedScopeEvaluator(
        _contradiction_evaluation,
        fail_at=2,
        error=ScopeResponseParseError("invalid JSON"),
    )

    result = run_scope_consistency(concept, baseline, evaluator, partition_max_chunks=2)

    assert not result.ok
    assert {item.code for item in result.findings} == {"UNPARSEABLE_RESPONSE", "INCOMPLETE_SWEEP"}
    assert [item.code for item in result.findings].count("INCOMPLETE_SWEEP") == 3
    assert {
        item.scope
        for item in result.findings
        if "cross-partition contradictions remain unchecked" in item.message
    } == {"lock.lifecycle", "queue.lifecycle"}
    assert all(
        "partitions=2" in item.message
        for item in result.findings
        if "cross-partition contradictions remain unchecked" in item.message
    )
    assert all(item.code != "SCOPE_CONTRADICTION" for item in result.findings)
    assert result.completed_partitions == 1
    assert baseline.read_bytes() == before


def test_late_partition_discovery_failure_keeps_prior_scope_coverage(
    tmp_path: Path,
) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    for index in range(3):
        write_doc(
            concept,
            f"a-{index}.md",
            f"A-{index}",
            "[{scope: a.scope}]",
            content=f"Rule A-{index} must hold.",
        )
    write_doc(
        concept,
        "z-oversized.md",
        "Z-OVERSIZED",
        "[{scope: z.scope}]",
        content="Oversized rule must hold. " * 400,
    )
    write_empty_baseline(baseline)
    evaluator = ScriptedScopeEvaluator(_empty_evaluation)

    result = run_scope_consistency(
        concept,
        baseline,
        evaluator,
        partition_max_chunks=2,
        partition_max_chars=6_000,
    )

    assert [item.code for item in result.findings] == [
        "DISCOVERY_FAILURE",
        "INCOMPLETE_SWEEP",
    ]
    assert result.scope_sets == 2
    assert result.partitions == 2
    assert result.completed_partitions == 0
    assert result.findings[1].scope == "a.scope"
    assert "partitions=2" in result.findings[1].message
    assert "cross-partition contradictions remain unchecked" in result.findings[1].message
    assert evaluator.calls == []


def test_invalid_w3_source_span_is_named_and_sweep_is_incomplete(tmp_path: Path) -> None:
    concept, baseline = _two_scope_corpus(tmp_path)

    def invalid_evaluation(partition: ScopePartition) -> ScopeEvaluation:
        first = partition.assertions[0]
        valid = QuotedAssertion(
            **source_reference_fields(first.chunk_id, first.text, first.text)
        )
        response = ScopeConsistencyResponse(
            contradictions=(
                ContradictionGroup(
                    loci=(
                        valid,
                        QuotedAssertion(
                            source_id="foreign",
                            start_id="s000000",
                            end_id="s000000",
                        ),
                    ),
                    explanation="Invalid foreign evidence.",
                ),
            )
        )
        return ScopeEvaluation(
            response=response,
            prompt_version=SCOPE_PROMPT_VERSION,
            prompt_sha256="a" * 64,
            model="fixed/v1",
        )

    result = run_scope_consistency(
        concept,
        baseline,
        ScriptedScopeEvaluator(invalid_evaluation),
        scope_filters=("lock.lifecycle",),
    )

    assert [item.code for item in result.findings] == [
        "INVALID_EVALUATION_RESPONSE",
        "INCOMPLETE_SWEEP",
    ]
    assert result.completed_partitions == 0


def test_hub_unreachable_is_named_and_never_returns_empty_pass(tmp_path: Path) -> None:
    concept, baseline = _two_scope_corpus(tmp_path)
    evaluator = ScriptedScopeEvaluator(
        _empty_evaluation,
        fail_at=1,
        error=HubUnavailableError("hub unavailable"),
    )

    result = run_scope_consistency(concept, baseline, evaluator)

    assert not result.ok
    assert [item.code for item in result.findings] == ["HUB_UNREACHABLE", "INCOMPLETE_SWEEP"]
    assert result.completed_partitions == 0


def test_exhausted_w3_transport_names_routed_backend_in_gate_findings(
    tmp_path: Path,
) -> None:
    concept, baseline = _two_scope_corpus(tmp_path)
    evaluator = ScriptedScopeEvaluator(
        _empty_evaluation,
        fail_at=1,
        error=EvaluationTransportExhaustedError(
            backend="grok",
            item_kind="partition",
            item_id="failed-partition",
            attempts=4,
            cause=LlmClientError("adapter stuck"),
        ),
        model="governance-pool/v1",
    )

    result = run_scope_consistency(
        concept,
        baseline,
        evaluator,
    )

    assert [item.code for item in result.findings] == ["HUB_UNREACHABLE", "INCOMPLETE_SWEEP"]
    assert [item.model for item in result.findings] == ["grok", "grok"]
    assert "backend='grok'" in result.findings[0].message
    assert "attempts=4" in result.findings[0].message


def test_prompt_io_failure_is_named_with_incomplete_sweep(tmp_path: Path) -> None:
    concept, baseline = _two_scope_corpus(tmp_path)
    evaluator = ScriptedScopeEvaluator(
        _empty_evaluation,
        fail_at=1,
        error=FileNotFoundError("scope prompt missing"),
    )

    result = run_scope_consistency(concept, baseline, evaluator)

    assert [item.code for item in result.findings] == ["DISCOVERY_FAILURE", "INCOMPLETE_SWEEP"]
    assert result.completed_partitions == 0


def test_w3_baseline_requires_related_locus_and_p4_decision() -> None:
    fields = {
        "code": "SCOPE_CONTRADICTION",
        "doc": "manual.md",
        "anchor": "rule-000",
        "assertion": "Manual rebinding is required.",
        "scope": "lock.lifecycle",
        "prompt_version": SCOPE_PROMPT_VERSION,
        "model": "fixed/v1",
        "reason": "Triaged legacy contradiction.",
    }
    with pytest.raises(ValidationError, match="related_loci"):
        BaselineEntry.model_validate(fields)
    fields["related_loci"] = [
        FindingLocus(doc="ttl.md", anchor="rule-000", assertion="TTL releases the lock.")
    ]
    with pytest.raises(ValidationError, match="formalization_check"):
        BaselineEntry.model_validate(fields)
    fields["formalization_check"] = FormalizationCheck(
        formalization_candidate=True,
        reason="Lifecycle transitions should move to the formal layer.",
    )
    assert BaselineEntry.model_validate(fields).formalization_check is not None


def test_w3_keyed_suppression_keeps_p4_visible_and_stale_is_error() -> None:
    related = (
        FindingLocus(doc="ttl.md", anchor="rule-000", assertion="TTL releases the lock."),
    )
    finding = ScopeConsistencyFinding(
        code="SCOPE_CONTRADICTION",
        doc="manual.md",
        anchor="rule-000",
        assertion="Manual rebinding is required.",
        related_loci=related,
        scope="lock.lifecycle",
        prompt_version=SCOPE_PROMPT_VERSION,
        model="fixed/v1",
        message="contradiction",
        formalization_check=None,
    )
    p4 = FormalizationCheck(
        formalization_candidate=True,
        reason="Lifecycle transitions should move to the formal layer.",
    )
    entry = BaselineEntry(
        code=finding.code,
        doc=finding.doc,
        anchor=finding.anchor,
        assertion=finding.assertion,
        related_loci=related,
        scope=finding.scope,
        prompt_version=finding.prompt_version,
        model=finding.model,
        reason="Accepted temporarily while the formal model is designed.",
        formalization_check=p4,
    )
    baseline = BaselineDocument(version=1, entries=(entry,))

    suppressed = apply_scope_baseline(
        (finding,), baseline, "concept/_meta/authority-prose-baseline.yaml", frozenset({finding.scope})
    )
    stale = apply_scope_baseline(
        (), baseline, "concept/_meta/authority-prose-baseline.yaml", frozenset({finding.scope})
    )

    assert suppressed[0].severity == "REPORT"
    assert suppressed[0].formalization_check == p4
    assert stale[0].code == "STALE_BASELINE"
    assert stale[0].severity == "ERROR"


def test_w3_v1_baseline_entry_is_stale_under_the_v2_response_contract() -> None:
    related = (
        FindingLocus(doc="ttl.md", anchor="rule-000", assertion="TTL releases the lock."),
    )
    current = ScopeConsistencyFinding(
        code="SCOPE_CONTRADICTION",
        doc="manual.md",
        anchor="rule-000",
        assertion="Manual rebinding is required.",
        related_loci=related,
        scope="lock.lifecycle",
        prompt_version=SCOPE_PROMPT_VERSION,
        model="fixed/v1",
        message="contradiction",
        formalization_check=None,
    )
    p4 = FormalizationCheck(
        formalization_candidate=True,
        reason="Lifecycle transitions should move to the formal layer.",
    )
    old = BaselineEntry(
        code=current.code,
        doc=current.doc,
        anchor=current.anchor,
        assertion=current.assertion,
        related_loci=related,
        scope=current.scope,
        prompt_version="scope-consistency/v1",
        model=current.model,
        reason="Old response contract entry.",
        formalization_check=p4,
    )

    result = apply_scope_baseline(
        (current,),
        BaselineDocument(version=1, entries=(old,)),
        "baseline.yaml",
        frozenset({current.scope}),
    )

    assert [item.code for item in result] == ["SCOPE_CONTRADICTION", "STALE_BASELINE"]
    assert all(item.severity == "ERROR" for item in result)


def _empty_evaluation(partition: ScopePartition) -> ScopeEvaluation:
    del partition
    return ScopeEvaluation(
        response=ScopeConsistencyResponse(contradictions=()),
        prompt_version=SCOPE_PROMPT_VERSION,
        prompt_sha256="a" * 64,
        model="fixed/v1",
    )


def _contradiction_evaluation(partition: ScopePartition) -> ScopeEvaluation:
    loci = tuple(
        QuotedAssertion(**source_reference_fields(item.chunk_id, item.text, item.text))
        for item in partition.assertions[:2]
    )
    return ScopeEvaluation(
        response=ScopeConsistencyResponse(
            contradictions=(
                ContradictionGroup(
                    loci=loci,
                    explanation="The first two rules contradict each other.",
                ),
            )
        ),
        prompt_version=SCOPE_PROMPT_VERSION,
        prompt_sha256="a" * 64,
        model="fixed/v1",
    )


def _two_scope_corpus(tmp_path: Path) -> tuple[Path, Path]:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    for prefix, scope in (("lock", "lock.lifecycle"), ("queue", "queue.lifecycle")):
        for index in range(3):
            write_doc(
                concept,
                f"{prefix}-{index}.md",
                f"{prefix.upper()}-{index}",
                f"[{{scope: {scope}}}]",
                content=f"The {prefix} rule number {index} must hold.",
            )
    write_empty_baseline(baseline)
    return concept, baseline
