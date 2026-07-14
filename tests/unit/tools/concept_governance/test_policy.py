"""AC1-3 deterministic W2 policy and discovery tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from concept_governance.chunks import load_chunks
from concept_governance.models import PROMPT_VERSION, ChunkClassification, NormativeAssertion
from concept_governance.runner import run_authority_check
from tests.unit.tools.concept_governance.helpers import ScriptedEvaluator, write_doc, write_empty_baseline

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _classification(scope: str, model: str = "fixed/v1") -> ChunkClassification:
    return ChunkClassification(
        has_normative_statements=True,
        assertions=(NormativeAssertion(assertion="The system must retain locks.", scopes=(scope,)),),
        prompt_version=PROMPT_VERSION,
        prompt_sha256="a" * 64,
        model=model,
    )


def test_unauthorized_scope_and_scope_qualified_defers_to_counter_probe(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_doc(concept, "consumer.md", "CONSUMER", "[]", "[OWNER]")
    write_empty_baseline(baseline)
    evaluator = ScriptedEvaluator(lambda chunk: _classification("lock.lifecycle"))

    first = run_authority_check(concept, baseline, evaluator)

    assert [item.code for item in first.findings] == ["UNAUTHORIZED_SCOPE_ASSERTION"]
    assert first.findings[0].doc == "domain-design/consumer.md"
    assert first.findings[0].anchor == "rule-000"
    assert first.findings[0].assertion == "The system must retain locks."

    write_doc(
        concept,
        "consumer.md",
        "CONSUMER",
        "[]",
        "[{target: OWNER, scope: lock.lifecycle, reason: delegated contract}]",
    )
    second = run_authority_check(concept, baseline, evaluator, parallelism=2)
    assert second.ok
    assert second.findings == ()


def test_unknown_scope_is_named_fail_closed_finding(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)

    result = run_authority_check(
        concept,
        baseline,
        ScriptedEvaluator(lambda chunk: _classification("invented.scope")),
    )

    assert not result.ok
    assert [item.code for item in result.findings] == ["UNKNOWN_SCOPE_MENTION"]


def test_chunk_source_and_findings_are_deterministic_without_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_doc(concept, "consumer.md", "CONSUMER")
    write_empty_baseline(baseline)
    monkeypatch.setenv("AK3_WEAVIATE_HOST", "unreachable.invalid")
    first_chunks = load_chunks(concept)
    second_chunks = load_chunks(concept)
    evaluator = ScriptedEvaluator(lambda chunk: _classification("lock.lifecycle"))

    first = run_authority_check(concept, baseline, evaluator)
    second = run_authority_check(concept, baseline, evaluator)

    assert [item.chunk_id for item in first_chunks] == [item.chunk_id for item in second_chunks]
    assert first.findings == second.findings
