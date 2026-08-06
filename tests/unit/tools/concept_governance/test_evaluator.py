"""Transport-only retry tests for the productive W2 evaluator."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from concept_governance.chunks import load_chunks
from concept_governance.evaluator import EvaluationParseError, LlmAuthorityProseEvaluator
from concept_governance.evaluator_pool import RoutedAuthorityProseEvaluator
from concept_governance.runner import run_authority_check
from concept_governance.transport_retry import EvaluationTransportExhaustedError
from tests.unit.tools.concept_governance.helpers import ScriptedLlmClient, write_doc, write_empty_baseline

from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError

if TYPE_CHECKING:
    from pathlib import Path


def test_unparseable_response_is_final_and_never_retried(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    client = ScriptedLlmClient(
        ["not-json", '{"has_normative_statements":false,"assertions":[]}']
    )

    with pytest.raises(EvaluationParseError):
        LlmAuthorityProseEvaluator(client, "fixed/v1").evaluate(
            load_chunks(concept)[0], ("lock.lifecycle",)
        )

    assert client.calls == 1


def test_programming_defect_propagates_unchanged_without_retry(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    defect = AssertionError("programming defect")
    client = ScriptedLlmClient([defect])

    with pytest.raises(AssertionError) as raised:
        LlmAuthorityProseEvaluator(client, "fixed/v1").evaluate(
            load_chunks(concept)[0], ("lock.lifecycle",)
        )

    assert raised.value is defect
    assert client.calls == 1


def test_transient_transport_failures_retry_same_pinned_prompt_with_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    client = ScriptedLlmClient(
        [
            LlmClientError("connection reset"),
            TimeoutError("response lost"),
            LlmClientError("backend not ready"),
            '{"has_normative_statements":false,"assertions":[]}',
        ]
    )
    delays: list[float] = []
    monkeypatch.setattr("concept_governance.transport_retry.time.sleep", delays.append)

    result = LlmAuthorityProseEvaluator(client, "fixed/v1").evaluate(
        load_chunks(concept)[0], ("lock.lifecycle",)
    )

    assert result.has_normative_statements is False
    assert len(set(client.prompts)) == 1
    assert delays == [5.0, 10.0, 20.0]


def test_exhausted_transport_retry_names_backend_chunk_cause_and_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    chunk = load_chunks(concept)[0]
    client = ScriptedLlmClient([LlmClientError(f"reset {index}") for index in range(1, 5)])
    monkeypatch.setattr("concept_governance.transport_retry.time.sleep", lambda _: None)

    with pytest.raises(EvaluationTransportExhaustedError) as raised:
        LlmAuthorityProseEvaluator(client, "fixed/v1").evaluate(
            chunk, ("lock.lifecycle",)
        )

    assert client.calls == 4
    assert raised.value.backend == "fixed/v1"
    assert raised.value.item_id == chunk.chunk_id
    assert raised.value.attempts == 4
    assert "cause=LlmClientError: reset 4" in str(raised.value)


def test_exhausted_transport_retry_is_named_in_gate_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)
    chunk = load_chunks(concept)[0]
    client = ScriptedLlmClient([LlmClientError("adapter stuck")] * 4)
    monkeypatch.setattr("concept_governance.transport_retry.time.sleep", lambda _: None)

    result = run_authority_check(
        concept,
        baseline,
        LlmAuthorityProseEvaluator(client, "qwen"),
    )

    assert [item.code for item in result.findings] == ["EVALUATION_TRANSPORT_FAILURE"]
    finding = result.findings[0]
    assert finding.model == "qwen"
    assert finding.doc == "domain-design/owner.md"
    assert finding.anchor == chunk.section_anchor
    assert f"chunk='{chunk.chunk_id}'" in finding.message
    assert "backend='qwen'" in finding.message
    assert "attempts=4" in finding.message
    assert "cause=LlmClientError: adapter stuck" in finding.message


def test_invalid_policy_finding_is_final_and_not_retried(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)
    before = baseline.read_bytes()
    chunk = load_chunks(concept)[0]
    invalid = json.dumps(
        {
            "has_normative_statements": True,
            "assertions": [
                {
                    "source_id": "foreign-source",
                    "start_id": "s000000",
                    "end_id": "s000000",
                    "scopes": ["lock.lifecycle"],
                }
            ],
        }
    )
    client = ScriptedLlmClient(
        [invalid, '{"has_normative_statements":false,"assertions":[]}']
    )

    result = run_authority_check(concept, baseline, LlmAuthorityProseEvaluator(client, "fixed/v1"))

    assert chunk.chunk_id != "foreign-source"
    assert [item.code for item in result.findings] == ["INVALID_EVALUATION_RESPONSE"]
    assert client.calls == 1
    assert baseline.read_bytes() == before


def test_incomplete_regex_reference_is_invalid_response_without_retry(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)
    raw = (
        'has_normative_statements: true; "source_id": "chunk-1", '
        '"start_id": "s000001", "end_id": "s000004", '
        '"scopes": ["lock.lifecycle"]; "source_id": "chunk-2", '
        '"start_id": "s000005"'
    )
    client = ScriptedLlmClient(
        [raw, '{"has_normative_statements":false,"assertions":[]}']
    )
    routed = RoutedAuthorityProseEvaluator(
        {"fixed/v1": (LlmAuthorityProseEvaluator(client, "fixed/v1"),)},
        ("fixed/v1",),
    )

    result = run_authority_check(
        concept,
        baseline,
        routed,
    )

    assert [item.code for item in result.findings] == ["INVALID_EVALUATION_RESPONSE"]
    assert "incomplete source reference" in result.findings[0].message
    assert client.calls == 1
