"""Bounded parse and transport retry tests for the productive evaluator."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest
from concept_governance.chunks import load_chunks
from concept_governance.evaluator import LlmAuthorityProseEvaluator
from concept_governance.runner import run_authority_check
from tests.unit.tools.concept_governance.helpers import ScriptedLlmClient, write_doc, write_empty_baseline

from agentkit.backend.verify_system.llm_evaluator.llm_client import LlmClientError

if TYPE_CHECKING:
    from pathlib import Path


def test_parse_retries_once_with_schema_hint(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    client = ScriptedLlmClient(["not-json", '{"has_normative_statements":false,"assertions":[]}'])

    result = LlmAuthorityProseEvaluator(client, "fixed/v1").evaluate(
        load_chunks(concept)[0], ("lock.lifecycle",)
    )

    assert client.prompts[0] != client.prompts[1]
    assert result.prompt_sha256 == hashlib.sha256(client.prompts[1].encode()).hexdigest()


def test_transient_transport_failure_retries_same_pinned_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    client = ScriptedLlmClient(
        [LlmClientError("connection reset"), '{"has_normative_statements":false,"assertions":[]}']
    )
    delays: list[float] = []
    monkeypatch.setattr("concept_governance.evaluator.time.sleep", delays.append)

    result = LlmAuthorityProseEvaluator(client, "fixed/v1").evaluate(
        load_chunks(concept)[0], ("lock.lifecycle",)
    )

    assert result.has_normative_statements is False
    assert client.prompts[0] == client.prompts[1]
    assert delays == [5.0]


def test_persistent_transport_failure_propagates_after_two_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    concept = tmp_path / "concept"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    client = ScriptedLlmClient([LlmClientError("reset one"), LlmClientError("reset two")])
    monkeypatch.setattr("concept_governance.evaluator.time.sleep", lambda _: None)

    with pytest.raises(LlmClientError, match="reset two"):
        LlmAuthorityProseEvaluator(client, "fixed/v1").evaluate(
            load_chunks(concept)[0], ("lock.lifecycle",)
        )

    assert client.calls == 2


def test_parse_failure_after_retry_is_named_without_baseline_mutation(tmp_path: Path) -> None:
    concept = tmp_path / "concept"
    baseline = concept / "_meta/baseline.yaml"
    write_doc(concept, "owner.md", "OWNER", "[{scope: lock.lifecycle}]")
    write_empty_baseline(baseline)
    before = baseline.read_bytes()
    client = ScriptedLlmClient(["invalid", "still invalid"])

    result = run_authority_check(concept, baseline, LlmAuthorityProseEvaluator(client, "fixed/v1"))

    assert [item.code for item in result.findings] == ["EVALUATION_PARSE_FAILURE"]
    assert client.calls == 2
    assert baseline.read_bytes() == before
