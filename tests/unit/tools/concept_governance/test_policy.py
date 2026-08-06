"""AC1-3 deterministic W2 policy and discovery tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from concept_governance.chunks import load_chunks
from concept_governance.evaluator import LlmAuthorityProseEvaluator
from concept_governance.models import PROMPT_VERSION, ChunkClassification, NormativeAssertion
from concept_governance.policy import evaluate_policy
from concept_governance.prompt import render_prompt
from concept_governance.runner import run_authority_check
from concept_governance.source_spans import build_source_span_map, extract_source_spans
from tests.unit.tools.concept_governance.helpers import (
    ScriptedEvaluator,
    ScriptedLlmClient,
    source_reference_fields,
    write_doc,
    write_empty_baseline,
)

BACKSLASH = chr(92)
#: A Windows path copied VERBATIM out of a markdown chunk. Inside a JSON
#: string ``\n`` is a RECOGNISED escape, so this is valid JSON that decodes
#: to ``C:`` + newline + ``ew`` — the quote is corrupted with no syntax
#: error anywhere for a parser to catch.
WINDOWS_PATH = "C:" + BACKSLASH + "new"

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest
    from concept_governance.models import AuthorityRunResult
    from concept_ingester.discovery import ConceptChunk


def _classification(
    chunk: ConceptChunk,
    scope: str,
    evidence: str = "The system must retain locks.",
    model: str = "fixed/v1",
) -> ChunkClassification:
    return ChunkClassification(
        has_normative_statements=True,
        assertions=(
            NormativeAssertion(
                **source_reference_fields(chunk.chunk_id, chunk.content, evidence),
                scopes=(scope,),
            ),
        ),
        prompt_version=PROMPT_VERSION,
        prompt_sha256="a" * 64,
        model=model,
    )


def test_unauthorized_scope_and_scope_qualified_defers_to_counter_probe(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    # An UNQUALIFIED deferral (no scope) in the FK-13 §13.9.6 entry form: it names
    # a target but authorizes no scope, so the assertion stays unauthorized.
    write_doc(concept, "consumer.md", "CONSUMER", "[]", "[{target: OWNER}]")
    write_empty_baseline(baseline)
    evaluator = ScriptedEvaluator(lambda chunk: _classification(chunk, "lock.lifecycle"))

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
        ScriptedEvaluator(lambda chunk: _classification(chunk, "invented.scope")),
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
    evaluator = ScriptedEvaluator(lambda chunk: _classification(chunk, "lock.lifecycle"))

    first = run_authority_check(concept, baseline, evaluator)
    second = run_authority_check(concept, baseline, evaluator)

    assert [item.chunk_id for item in first_chunks] == [item.chunk_id for item in second_chunks]
    assert first.findings == second.findings


def _corpus_with_content(content: str, tmp_path: Path) -> tuple[Path, Path]:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]", content=content)
    write_empty_baseline(baseline)
    return concept, baseline


def _response(*references: dict[str, object]) -> str:
    return json.dumps(
        {"has_normative_statements": True, "assertions": references},
        ensure_ascii=False,
    )


def _valid_reference(chunk: ConceptChunk, evidence: str) -> dict[str, object]:
    return {
        **source_reference_fields(chunk.chunk_id, chunk.content, evidence),
        "scopes": ["lock.lifecycle"],
    }


def _run_invalid_reference(
    tmp_path: Path,
    content: str,
    build_references: Callable[[ConceptChunk], tuple[dict[str, object], ...]],
) -> AuthorityRunResult:
    concept, baseline = _corpus_with_content(content, tmp_path)
    chunk = load_chunks(concept)[0]
    client = ScriptedLlmClient([_response(*build_references(chunk))])
    return run_authority_check(concept, baseline, LlmAuthorityProseEvaluator(client, "fixed/v1"))


def test_source_span_extraction_preserves_the_measured_hard_line_break(tmp_path: Path) -> None:
    """AG3-219 regression: the gate, not the model, owns the exact newline."""
    content = (
        "Das **AK3 Backend** ist der **deterministische Orchestrierungs- und\n"
        "Business-Kern** von AK3"
    )
    concept = tmp_path / "concept"
    write_doc(concept, "consumer.md", "CONSUMER", content=content)
    chunk = load_chunks(concept)[0]
    classification = _classification(chunk, "lock.lifecycle", content)

    findings = evaluate_policy(chunk, classification, frozenset({"lock.lifecycle"}))

    assert findings[0].assertion == content
    assert "und\nBusiness-Kern" in findings[0].assertion
    assert findings[0].assertion in chunk.content


def test_source_span_extraction_preserves_crlf_without_normalization() -> None:
    content = "Orchestrierungs- und\r\nBusiness-Kern"
    source = build_source_span_map("chunk-1", content)
    reference = NormativeAssertion(
        source_id="chunk-1",
        start_id="s000000",
        end_id="s000001",
        scopes=("lock.lifecycle",),
    )

    extracted = extract_source_spans((reference,), (source,))

    assert extracted[0].text == content
    assert "und\r\nBusiness-Kern" in extracted[0].text


def test_w2_prompt_labels_the_measured_lines_without_sending_a_quote_field(
    tmp_path: Path,
) -> None:
    content = "Orchestrierungs- und\nBusiness-Kern"
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "OWNER", content=content)
    chunk = load_chunks(concept)[0]

    prompt, _ = render_prompt(chunk, ("lock.lifecycle",))
    payload = json.loads(prompt.split("## Evaluation input\n", maxsplit=1)[1])

    assert set(payload["source"]) == {"source_id", "annotated_content"}
    assert payload["source"]["source_id"] == chunk.chunk_id
    assert "Orchestrierungs- und\n<s" in payload["source"]["annotated_content"]
    assert "content" not in payload


def test_out_of_bounds_source_span_is_invalid_evaluation_response(tmp_path: Path) -> None:
    def references(chunk: ConceptChunk) -> tuple[dict[str, object], ...]:
        reference = _valid_reference(chunk, "The system must retain locks.")
        reference["end_id"] = "s999999"
        return (reference,)

    result = _run_invalid_reference(tmp_path, "The system must retain locks.", references)

    assert [item.code for item in result.findings] == ["INVALID_EVALUATION_RESPONSE"]
    assert "span" in result.findings[0].message


def test_empty_source_span_is_invalid_evaluation_response(tmp_path: Path) -> None:
    def references(chunk: ConceptChunk) -> tuple[dict[str, object], ...]:
        from concept_governance.source_spans import build_source_span_map

        reference = _valid_reference(chunk, "The system must retain locks.")
        span_map = build_source_span_map(chunk.chunk_id, chunk.content)
        blank = next(
            span
            for span in span_map.spans
            if not chunk.content[span.start : span.end].strip()
        )
        reference["start_id"] = blank.span_id
        reference["end_id"] = blank.span_id
        return (reference,)

    result = _run_invalid_reference(tmp_path, "The system must retain locks.", references)

    assert [item.code for item in result.findings] == ["INVALID_EVALUATION_RESPONSE"]
    assert "empty" in result.findings[0].message


def test_reversed_source_span_is_invalid_evaluation_response(tmp_path: Path) -> None:
    def references(chunk: ConceptChunk) -> tuple[dict[str, object], ...]:
        reference = _valid_reference(chunk, "The system must retain\nlocks.")
        reference["start_id"], reference["end_id"] = reference["end_id"], reference["start_id"]
        return (reference,)

    result = _run_invalid_reference(tmp_path, "The system must retain\nlocks.", references)

    assert [item.code for item in result.findings] == ["INVALID_EVALUATION_RESPONSE"]
    assert "reversed" in result.findings[0].message


def test_overlapping_source_spans_are_invalid_evaluation_response(tmp_path: Path) -> None:
    first_line = "The system must retain locks today.\n"
    content = first_line + "Another rule applies."

    def references(chunk: ConceptChunk) -> tuple[dict[str, object], ...]:
        return (
            _valid_reference(chunk, content),
            _valid_reference(chunk, first_line),
        )

    result = _run_invalid_reference(tmp_path, content, references)

    assert [item.code for item in result.findings] == ["INVALID_EVALUATION_RESPONSE"]
    assert "overlap" in result.findings[0].message


def test_implausibly_large_source_span_is_invalid_evaluation_response(tmp_path: Path) -> None:
    content = "x" * 2_001
    result = _run_invalid_reference(
        tmp_path,
        content,
        lambda chunk: (_valid_reference(chunk, content),),
    )

    assert [item.code for item in result.findings] == ["INVALID_EVALUATION_RESPONSE"]
    assert "exceeds maximum 2000" in result.findings[0].message


def test_ag3_179_copied_c_new_quote_remains_a_fail_closed_error(tmp_path: Path) -> None:
    r"""The retired v1 copied-text shape cannot re-enter through valid ``\n`` JSON."""
    concept, baseline = _corpus_with_content(f"The lock file lives at {WINDOWS_PATH}.", tmp_path)
    legacy_response = (
        '{"has_normative_statements":true,"assertions":'
        '[{"assertion":"' + WINDOWS_PATH + '","scopes":["lock.lifecycle"]}]}'
    )
    client = ScriptedLlmClient([legacy_response, legacy_response])

    result = run_authority_check(concept, baseline, LlmAuthorityProseEvaluator(client, "fixed/v1"))

    assert [item.code for item in result.findings] == ["EVALUATION_PARSE_FAILURE"]
    assert not result.ok
